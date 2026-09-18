"""Create-only document filesystem/RPC contracts. No MATLAB or GUI required."""

import hashlib
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from slxdiff import documents, rpc


def test_create_unicode_bom_crlf_and_no_final_newline(tmp_path):
    (tmp_path / "实验").mkdir()
    content = "%% 控制\r\nKp = 7;"
    result = documents.create_document(tmp_path, "实验\\控制.M", content, True)
    raw = b"\xef\xbb\xbf" + content.encode("utf-8")
    assert (tmp_path / "实验" / "控制.M").read_bytes() == raw
    assert result["path"] == "实验/控制.M"
    assert result["sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["content"] == content
    assert result["bom"] and result["eol"] == "CRLF"
    assert result["warnings"] == []
    assert len(list((tmp_path / "实验").iterdir())) == 1


def test_create_empty_document_is_readable_and_saveable(tmp_path):
    created = documents.create_document(tmp_path, "new.m")
    assert created["bytes"] == 0
    assert documents.read_document(tmp_path, "new.m")["sha256"] == created["sha256"]
    saved = documents.save_document(tmp_path, "new.m", "x = 1;\n", created["sha256"])
    assert saved["content"] == "x = 1;\n"


@pytest.mark.parametrize("kind", ["file", "directory", "dangling-link"])
def test_create_never_overwrites_any_existing_entry(tmp_path, kind):
    target = tmp_path / "existing.m"
    if kind == "file":
        target.write_bytes(b"external")
    elif kind == "directory":
        target.mkdir()
    else:
        try:
            target.symlink_to(tmp_path / "absent.m")
        except OSError:
            pytest.skip("OS does not permit unprivileged file symlinks")
    before = target.lstat()
    with pytest.raises(documents.DocumentConflict):
        documents.create_document(tmp_path, target.name, "new")
    assert target.lstat().st_ino == before.st_ino
    if kind == "file":
        assert target.read_bytes() == b"external"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["existing.m"]


@pytest.mark.parametrize(
    "relative",
    [
        "", "../outside.m", "/absolute.m", "C:/absolute.m", "\\\\server\\share\\a.m",
        "./a.m", "a//b.m", "folder/../a.m", " a.m", "a.m ", "a.m:stream", "a.m\0",
        "x\n.m", "x?.m", "x*.m", "x|.m", "x<.m", "x>.m", 'x".m', "x\x7f.m",
        ".git/hook.m", ".slx-studio/settings.m", "node_modules/a.m", ".hidden.m",
        "CON.m", "nul.m", "AUX.txt.m", "com1.m", "LPT9.m", "COM¹.m", "LPT².m",
        "CONIN$.m", "CONOUT$.m", "folder./a.m", "nul/a.m", "model.slx", "text.txt",
        "a" * 4097 + ".m", 3, None,
    ],
)
def test_create_rejects_unsafe_or_invisible_paths(tmp_path, relative):
    with pytest.raises((ValueError, TypeError)):
        documents.create_document(tmp_path, relative, "never written")
    assert list(tmp_path.iterdir()) == []


def test_create_requires_an_existing_parent(tmp_path):
    with pytest.raises(FileNotFoundError):
        documents.create_document(tmp_path, "missing/file.m", "x=1;")
    assert not (tmp_path / "missing").exists()
    (tmp_path / "parent.m").write_bytes(b"keep")
    with pytest.raises((NotADirectoryError, ValueError)):
        documents.create_document(tmp_path, "parent.m/file.m", "x=1;")
    assert (tmp_path / "parent.m").read_bytes() == b"keep"


def test_create_rejects_parent_link_or_junction(tmp_path):
    import subprocess

    root, outside = tmp_path / "workspace", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    linked = root / "linked"
    if os.name == "nt":
        subprocess.run(
            ["pwsh", "-NoProfile", "-Command",
             "New-Item -ItemType Junction -Path $env:SLX_TEST_LINK -Target $env:SLX_TEST_TARGET -ErrorAction Stop | Out-Null"],
            env={**os.environ, "SLX_TEST_LINK": str(linked), "SLX_TEST_TARGET": str(outside)},
            check=True, capture_output=True, timeout=10,
        )
    else:
        linked.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="links and reparse"):
        documents.create_document(root, "linked/escape.m", "not outside")
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("content,bom", [(12, False), (None, False), ("x", 1), ("x", "false")])
def test_create_validates_payload_types(tmp_path, content, bom):
    with pytest.raises(TypeError):
        documents.create_document(tmp_path, "new.m", content, bom)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("content", ["null\0", "\ud800", "字" * (documents._MAX_TEXT_BYTES // 3 + 1)])
def test_create_rejects_binary_invalid_unicode_and_oversize_bytes(tmp_path, content):
    with pytest.raises((ValueError, UnicodeError)):
        documents.create_document(tmp_path, "new.m", content)
    assert list(tmp_path.iterdir()) == []


def test_create_byte_limit_includes_bom(tmp_path, monkeypatch):
    monkeypatch.setattr(documents, "_MAX_TEXT_BYTES", 8)
    with pytest.raises(ValueError, match="size limit"):
        documents.create_document(tmp_path, "new.m", "123456", True)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failure_point", ["fsync", "link"])
def test_create_failure_never_leaves_a_partial_destination(tmp_path, monkeypatch, failure_point):
    calls = 0

    def fail(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise OSError("simulated filesystem failure")

    monkeypatch.setattr(documents.os, failure_point, fail)
    with pytest.raises(OSError):
        documents.create_document(tmp_path, "new.m", "complete or absent")
    assert calls == 1, "creation must not automatically replay failed mutations"
    assert list(tmp_path.iterdir()) == []


def test_target_appearing_at_publication_is_never_overwritten(tmp_path, monkeypatch):
    link = documents.os.link

    def race(source, target):
        Path(target).write_bytes(b"external writer")
        return link(source, target)

    monkeypatch.setattr(documents.os, "link", race)
    with pytest.raises(documents.DocumentConflict, match="appeared"):
        documents.create_document(tmp_path, "new.m", "our buffer")
    assert (tmp_path / "new.m").read_bytes() == b"external writer"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["new.m"]


def test_competing_creations_have_exactly_one_winner(tmp_path):
    def create(content):
        try:
            return documents.create_document(tmp_path, "new.m", content)["content"]
        except documents.DocumentConflict:
            return None

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(create, ["a" * 1000, "b" * 1000, "c" * 1000, "d" * 1000]))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert (tmp_path / "new.m").read_text() == winners[0]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["new.m"]


def test_cleanup_failure_reports_published_file_and_warning(tmp_path, monkeypatch):
    unlink = Path.unlink

    def fail_temp(path, **kwargs):
        if path.name.startswith(".slx-create-"):
            raise PermissionError("temporary file locked")
        return unlink(path, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_temp)
    result = documents.create_document(tmp_path, "new.m", "published")
    assert result["content"] == "published"
    assert (tmp_path / "new.m").read_bytes() == b"published"
    assert result["warnings"] and "cleanup failed" in result["warnings"][0]
    for temp in tmp_path.glob(".slx-create-*"):
        unlink(temp)


def test_rpc_create_is_allowlisted_updates_index_and_keeps_runtime_stopped(tmp_path, monkeypatch):
    backend = rpc.Backend(str(tmp_path))
    invalidations = []
    monkeypatch.setattr(backend._index, "invalidate", lambda: invalidations.append(True))
    try:
        assert "document.create" in backend.initialize()["capabilities"]
        reply = backend.dispatch({"jsonrpc": "2.0", "id": 1, "method": "document/create", "params": {"relative": "new.m", "content": "gain=2;"}})
        assert reply["result"]["path"] == "new.m"
        assert invalidations == [True]
        assert backend._matlab.status()["state"] == "stopped"
        duplicate = backend.dispatch({"jsonrpc": "2.0", "id": 2, "method": "document/create", "params": {"relative": "new.m"}})
        assert duplicate["error"]["data"]["kind"] == "conflict"
        assert invalidations == [True]
        bad = backend.dispatch({"jsonrpc": "2.0", "id": 3, "method": "document/create", "params": {"relative": "../outside.m"}})
        assert bad["error"]["code"] == -32602
    finally:
        backend.close()
