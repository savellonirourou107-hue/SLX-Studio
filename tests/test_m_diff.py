from __future__ import annotations

import json
from pathlib import Path
from urllib import request

import pytest

from slxdiff.m_diff import apply_m_edit, generate_m_diff_preview, sha256_text
from slxdiff.workbench_server import serve_workbench


def test_m_diff_preview_clean(tmp_path: Path) -> None:
    file_path = tmp_path / "script.m"
    file_path.write_text("x = 1;\ny = 2;\n", encoding="utf-8")
    initial_sha = sha256_text("x = 1;\ny = 2;\n")

    proposed = "x = 1;\ny = 20;\nz = 30;\n"
    preview = generate_m_diff_preview(tmp_path, "script.m", proposed, base_sha256=initial_sha)

    assert preview["ok"] is True
    assert preview["conflict"] is False
    assert preview["identical"] is False
    assert preview["current_sha256"] == initial_sha
    assert "-y = 2;" in preview["diff"]
    assert "+y = 20;" in preview["diff"]
    assert "+z = 30;" in preview["diff"]
    assert preview["stats"]["additions"] == 2
    assert preview["stats"]["deletions"] == 1


def test_m_diff_preview_conflict(tmp_path: Path) -> None:
    file_path = tmp_path / "script.m"
    file_path.write_text("x = 100;\n", encoding="utf-8")

    stale_sha = "0000000000000000000000000000000000000000000000000000000000000000"
    preview = generate_m_diff_preview(tmp_path, "script.m", "x = 200;\n", base_sha256=stale_sha)

    assert preview["ok"] is True
    assert preview["conflict"] is True
    assert preview["current_sha256"] != stale_sha


def test_m_diff_preview_new_file(tmp_path: Path) -> None:
    preview = generate_m_diff_preview(tmp_path, "new_script.m", "a = 1;\n")
    assert preview["ok"] is True
    assert preview["exists"] is False
    assert preview["current_sha256"] == ""
    assert "+a = 1;" in preview["diff"]


def test_m_diff_preview_rejects_non_m(tmp_path: Path) -> None:
    (tmp_path / "data.txt").write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError, match="only .m files support text diff preview"):
        generate_m_diff_preview(tmp_path, "data.txt", "new")


def test_m_diff_preview_rejects_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes the workspace root"):
        generate_m_diff_preview(tmp_path, "../outside.m", "test")


def test_apply_m_edit_success(tmp_path: Path) -> None:
    file_path = tmp_path / "algo.m"
    original = "% Algo\nx = 1;\n"
    file_path.write_text(original, encoding="utf-8")
    orig_sha = sha256_text(original)

    updated = "% Algo\nx = 42;\n"
    result = apply_m_edit(tmp_path, "algo.m", updated, expected_sha256=orig_sha)

    assert result["ok"] is True
    assert result["sha256"] == sha256_text(updated)
    assert file_path.read_text(encoding="utf-8") == updated


def test_apply_m_edit_conflict(tmp_path: Path) -> None:
    file_path = tmp_path / "algo.m"
    file_path.write_text("x = 1;\n", encoding="utf-8")

    wrong_sha = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    with pytest.raises(ValueError, match="stale file conflict"):
        apply_m_edit(tmp_path, "algo.m", "x = 2;\n", expected_sha256=wrong_sha)

    assert file_path.read_text(encoding="utf-8") == "x = 1;\n"


def test_http_m_edit_endpoints(tmp_path: Path) -> None:
    import threading

    script = tmp_path / "test_api.m"
    script.write_text("val = 1;\n", encoding="utf-8")
    orig_sha = sha256_text("val = 1;\n")

    server, url = serve_workbench(
        tmp_path,
        host="127.0.0.1",
        port=0,
        open_browser=False,
        token="secret-token",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    headers = {"X-SLX-Studio-Token": "secret-token", "Content-Type": "application/json"}
    try:
        # 1. Preview request
        preview_body = json.dumps(
            {"path": "test_api.m", "content": "val = 2;\n", "base_sha256": orig_sha}
        ).encode("utf-8")
        req = request.Request(
            f"{url}api/v1/workspace/m-edit/preview",
            data=preview_body,
            headers=headers,
            method="POST",
        )
        with request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True
            assert data["conflict"] is False
            assert "+val = 2;" in data["diff"]

        # 2. Stale apply request (must return HTTP 400)
        stale_body = json.dumps(
            {"path": "test_api.m", "content": "val = 99;\n", "expected_sha256": "bad-hash"}
        ).encode("utf-8")
        stale_req = request.Request(
            f"{url}api/v1/workspace/m-edit/apply",
            data=stale_body,
            headers=headers,
            method="POST",
        )
        try:
            with request.urlopen(stale_req, timeout=5):
                pytest.fail("expected HTTP 400 on stale hash")
        except request.HTTPError as exc:
            assert exc.code == 400
            assert "HTTP Error 400" in str(exc)

        # 3. Clean apply request
        clean_body = json.dumps(
            {"path": "test_api.m", "content": "val = 2;\n", "expected_sha256": orig_sha}
        ).encode("utf-8")
        clean_req = request.Request(
            f"{url}api/v1/workspace/m-edit/apply",
            data=clean_body,
            headers=headers,
            method="POST",
        )
        with request.urlopen(clean_req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True
            assert data["sha256"] == sha256_text("val = 2;\n")

        assert script.read_text(encoding="utf-8") == "val = 2;\n"

    finally:
        server.shutdown()
        server.server_close()
