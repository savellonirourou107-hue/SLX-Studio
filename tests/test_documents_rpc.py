"""Real filesystem/protocol tests, deliberately without MATLAB or Electron."""

import hashlib
import io
import json
import os
import stat
import subprocess
import sys

import pytest

from slxdiff import documents, rpc


def message(method, params=None, identifier=1):
    return {"jsonrpc": "2.0", "id": identifier, "method": method, "params": params or {}}


def test_document_roundtrip_and_conflicts(tmp_path):
    file = tmp_path / "控制.m"
    original = b"\xef\xbb\xbf" + "%% 控制\r\nKp = 2;".encode()
    file.write_bytes(original)
    base = documents.read_document(tmp_path, file.name)
    assert base["content"] == "%% 控制\r\nKp = 2;"
    assert base["bom"] and base["eol"] == "CRLF"
    saved = documents.save_document(
        tmp_path, file.name, base["content"].replace("2", "3"), base["sha256"], True
    )
    assert file.read_bytes() == original.replace(b"2", b"3")
    assert saved["sha256"] == hashlib.sha256(file.read_bytes()).hexdigest()
    file.write_text("external = 1;", encoding="utf8")
    with pytest.raises(documents.DocumentConflict):
        documents.save_document(tmp_path, file.name, "editor", saved["sha256"])
    assert file.read_text() == "external = 1;"


@pytest.mark.parametrize(
    "relative",
    [
        "../escape.m",
        "/absolute.m",
        "C:/absolute.m",
        "file.m:stream",
        "./file.m",
        "folder/../file.m",
        "file.m\x00",
    ],
)
def test_document_path_rejects_escapes(tmp_path, relative):
    with pytest.raises(ValueError):
        documents.read_document(tmp_path, relative)


def test_save_failure_keeps_source_and_cleans_temp(tmp_path, monkeypatch):
    file = tmp_path / "file.m"
    file.write_text("original", encoding="utf8")
    base = documents.read_document(tmp_path, file.name)

    def fail(*args):
        raise OSError("simulated disk write failure")

    monkeypatch.setattr(documents.os, "replace", fail)
    with pytest.raises(OSError):
        documents.save_document(tmp_path, file.name, "changed", base["sha256"])
    assert file.read_text() == "original"
    assert sorted(item.name for item in tmp_path.iterdir()) == ["file.m"]


def test_save_retries_transient_windows_permission_error(tmp_path, monkeypatch):
    file = tmp_path / "file.m"
    file.write_text("original", encoding="utf8")
    base = documents.read_document(tmp_path, file.name)
    replace = documents.os.replace
    attempts = 0

    def transient(source, target):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError(5, "temporary sharing violation")
        return replace(source, target)

    monkeypatch.setattr(documents.os, "replace", transient)
    saved = documents.save_document(tmp_path, file.name, "changed", base["sha256"])
    assert attempts == 3
    assert saved["content"] == "changed"
    assert file.read_text() == "changed"


def test_save_retry_rechecks_external_changes(tmp_path, monkeypatch):
    file = tmp_path / "file.m"
    file.write_text("original", encoding="utf8")
    base = documents.read_document(tmp_path, file.name)

    def concurrent_writer(*args):
        file.write_text("external", encoding="utf8")
        raise PermissionError(5, "temporary sharing violation")

    monkeypatch.setattr(documents.os, "replace", concurrent_writer)
    with pytest.raises(documents.DocumentConflict, match="save retry"):
        documents.save_document(tmp_path, file.name, "editor", base["sha256"])
    assert file.read_text() == "external"


def test_permission_retry_exhaustion_preserves_source(tmp_path, monkeypatch):
    file = tmp_path / "file.m"
    file.write_text("original", encoding="utf8")
    base = documents.read_document(tmp_path, file.name)
    attempts = 0

    def locked(*args):
        nonlocal attempts
        attempts += 1
        raise PermissionError(5, "locked")

    monkeypatch.setattr(documents.os, "replace", locked)
    with pytest.raises(PermissionError):
        documents.save_document(tmp_path, file.name, "editor", base["sha256"])
    assert attempts == 4
    assert file.read_text() == "original"
    assert sorted(item.name for item in tmp_path.iterdir()) == ["file.m"]


@pytest.mark.parametrize("content", ["a\r\nb\n", "a\rb"])
def test_mixed_and_legacy_newlines_are_flagged(tmp_path, content):
    file = tmp_path / "mixed.m"
    file.write_bytes(content.encode())
    assert documents.read_document(tmp_path, file.name)["mixed_eol"]


def test_readonly_deleted_and_oversize_documents(tmp_path):
    file = tmp_path / "file.m"
    file.write_text("x=1;", encoding="utf8")
    base = documents.read_document(tmp_path, file.name)
    file.chmod(stat.S_IRUSR)
    try:
        with pytest.raises(PermissionError):
            documents.save_document(tmp_path, file.name, "x=2;", base["sha256"])
    finally:
        file.chmod(stat.S_IWUSR | stat.S_IRUSR)
    file.unlink()
    with pytest.raises(FileNotFoundError):
        documents.save_document(tmp_path, file.name, "x=2;", base["sha256"])
    file.write_bytes(b"x" * (documents._MAX_TEXT_BYTES + 1))
    with pytest.raises(ValueError, match="size limit"):
        documents.read_document(tmp_path, file.name)


def test_parent_link_or_windows_junction_rejected(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.m").write_text("secret", encoding="utf8")
    link = root / "linked"
    if os.name == "nt":
        subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-Command",
                "New-Item -ItemType Junction -Path $env:SLX_TEST_LINK -Target $env:SLX_TEST_TARGET -ErrorAction Stop | Out-Null",
            ],
            env={**os.environ, "SLX_TEST_LINK": str(link), "SLX_TEST_TARGET": str(outside)},
            check=True,
            capture_output=True,
            timeout=10,
        )
    else:
        link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="links and reparse"):
        documents.read_document(root, "linked/secret.m")
    assert documents.list_directory(root)["items"] == []


def test_directory_is_lazy_and_paginated(tmp_path):
    for index in range(520):
        (tmp_path / f"file{index}.m").touch()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "child").mkdir()
    (tmp_path / "child" / "nested.m").touch()
    found = []
    cursor = 0
    while True:
        page = documents.list_directory(tmp_path, cursor=cursor)
        found.extend(page["items"])
        if page["next_cursor"] is None:
            break
        cursor = page["next_cursor"]
    assert len(found) == 521
    assert "child/nested.m" not in {item["path"] for item in found}
    assert "node_modules" not in {item["path"] for item in found}


def test_rpc_framing_and_notifications(tmp_path):
    source = io.BytesIO()
    rpc.write_frame(source, message("initialize"))
    rpc.write_frame(source, {"jsonrpc": "2.0", "method": "initialize"})
    rpc.write_frame(source, message("unknown", identifier=3))
    rpc.write_frame(
        source, [message("initialize", identifier="four"), {"jsonrpc": "2.0", "method": "initialize"}]
    )
    target = io.BytesIO()
    source.seek(0)
    rpc.serve(rpc.Backend(str(tmp_path)), source, target)
    target.seek(0)
    assert json.loads(rpc.read_frame(target))["result"]["matlab_started"] is False
    assert json.loads(rpc.read_frame(target))["error"]["code"] == -32601
    assert json.loads(rpc.read_frame(target))[0]["id"] == "four"
    assert rpc.read_frame(target) is None


@pytest.mark.parametrize(
    "payload",
    [
        b"{}",
        b"Content-Length: 999999999\r\n\r\n",
        b"Content-Length: 2\r\nContent-Length: 2\r\n\r\n{}",
        b"Content-Length: 5\r\n\r\n{}",
    ],
)
def test_bad_frames_are_bounded(payload):
    with pytest.raises(rpc.FrameError):
        rpc.read_frame(io.BytesIO(payload))


def test_invalid_requests_and_conflict_errors(tmp_path):
    backend = rpc.Backend(str(tmp_path))
    assert backend.dispatch(5)["error"]["code"] == -32600
    assert backend.dispatch(message("document/read", {"relative": "../outside.m"}))["error"]["code"] == -32602
    assert backend.dispatch(message("document/read", {"relative": 5}))["error"]["code"] == -32602
    assert backend.dispatch(message("initialize", {"surprise": True}))["error"]["code"] == -32602
    assert backend.dispatch({"jsonrpc": "2.0", "method": "initialize", "id": True})["error"]["code"] == -32600


def test_real_python_stdio_process(tmp_path):
    source = io.BytesIO()
    rpc.write_frame(source, message("initialize"))
    rpc.write_frame(source, message("workspace/listDirectory"))
    result = subprocess.run(
        [sys.executable, "-u", "-m", "slxdiff.rpc", "--workspace", str(tmp_path)],
        input=source.getvalue(),
        capture_output=True,
        check=True,
        timeout=10,
    )
    output = io.BytesIO(result.stdout)
    assert json.loads(rpc.read_frame(output))["result"]["protocol_version"] == 1
    assert json.loads(rpc.read_frame(output))["result"]["items"] == []
    assert result.stderr == b""
