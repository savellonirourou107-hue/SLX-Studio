from __future__ import annotations

import http.client
import json
import time
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import pytest

from slxdiff import parser
from slxdiff.model_edit import build_single_edit
from slxdiff.parser import parse_slx, parse_slx_bytes


def _write_slx(path: Path, xml: str, *, extra_xml: str | None = None) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("simulink/systems/system_root.xml", xml)
        if extra_xml is not None:
            archive.writestr("metadata/extra.xml", extra_xml)


def _simple_xml() -> str:
    return """<?xml version='1.0' encoding='UTF-8'?>
<System>
  <Block BlockType='Inport' Name='输入' SID='1'><P Name='Position'>[20 100 50 130]</P></Block>
  <Block BlockType='Gain' Name='控制器' SID='2'><P Name='Gain'>2</P><P Name='Position'>[100 100 140 130]</P></Block>
  <Block BlockType='Outport' Name='输出' SID='3'><P Name='Position'>[200 100 230 130]</P></Block>
  <Line><P Name='Src'>1#out:1</P><P Name='Dst'>2#in:1</P></Line>
  <Line><P Name='Src'>2#out:1</P><P Name='Dst'>3#in:1</P></Line>
</System>"""


def _post(url: str, path: str, token: str, payload: object) -> tuple[int, dict[str, str], dict]:
    parsed = urlparse(url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    connection.request(
        "POST",
        path,
        body=data,
        headers={"Content-Type": "application/json", "X-SLX-Studio-Token": token},
    )
    response = connection.getresponse()
    raw = response.read()
    headers = {key.lower(): value for key, value in response.getheaders()}
    connection.close()
    return response.status, headers, json.loads(raw.decode("utf-8"))


def test_parser_rejects_delayed_and_nested_entities_and_scans_all_members() -> None:
    delayed = b"<System>" + (b" " * 5000) + b"<!DOCTYPE x [<!ENTITY boom 'x'>]></System>"
    payload = Path("delayed.slx")
    try:
        import io

        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("simulink/systems/system_root.xml", delayed)
        with pytest.raises(ValueError, match=r"DTD/entity declaration: simulink/systems/system_root.xml"):
            parse_slx_bytes(stream.getvalue(), name=str(payload))

        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("simulink/systems/system_root.xml", _simple_xml())
            archive.writestr("metadata/extra.xml", b"<x>&nested;</x>")
        with pytest.raises(ValueError, match=r"DTD/entity declaration: metadata/extra.xml"):
            parse_slx_bytes(stream.getvalue(), name="nested.slx")

        stream = io.BytesIO()
        nested_reference = b"<System><Block BlockType='Gain' Name='&boom;' SID='1'/></System>"
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("simulink/systems/system_root.xml", nested_reference)
        # Only the five XML predefined entities are accepted; a user entity
        # reference cannot reach ElementTree even when no declaration is present.
        with pytest.raises(ValueError, match=r"DTD/entity declaration: simulink/systems/system_root.xml"):
            parse_slx_bytes(stream.getvalue(), name="reference.slx")
    finally:
        payload.unlink(missing_ok=True)


def test_parser_accepts_unicode_and_nested_subsystem_xml(tmp_path: Path) -> None:
    model_path = tmp_path / "nested.slx"
    _write_slx(
        model_path,
        """<System><Block BlockType='SubSystem' Name='内层' SID='1'><System>
        <Block BlockType='Gain' Name='增益' SID='2'><P Name='Gain'>3</P></Block>
        </System></Block></System>""",
    )
    model = parse_slx(model_path)
    assert any(block.name == "增益" for block in model.blocks.values())


def test_parser_surfaces_unsupported_features_without_dropping_blocks(tmp_path: Path) -> None:
    model_path = tmp_path / "unsupported.slx"
    _write_slx(
        model_path,
        """<System><Block BlockType='MATLABSystem' Name='Controller' SID='1'>
        <Mask><P Name='MaskType'>custom</P></Mask><P Name='VariantControl'>A</P>
        </Block></System>""",
    )
    model = parse_slx(model_path)
    assert model.blocks
    assert model.metadata["unsupported_features"] == ["mask", "specialized_toolbox_block", "variant"]
    from slxdiff.studio import render_studio_html

    html = render_studio_html(model)
    assert "unsupported_features" in html and "unsupportedNotice" in html


def test_parser_preserves_archive_entry_and_member_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_path = tmp_path / "large.slx"
    monkeypatch.setattr(parser, "_MAX_XML_MEMBER_BYTES", 8)
    _write_slx(model_path, _simple_xml())
    with pytest.raises(ValueError, match="too large.*system_root.xml"):
        parse_slx(model_path)

    monkeypatch.setattr(parser, "_MAX_XML_MEMBER_BYTES", 32 * 1024 * 1024)
    monkeypatch.setattr(parser, "_MAX_ARCHIVE_ENTRIES", 1)
    _write_slx(model_path, _simple_xml(), extra_xml="<metadata />")
    with pytest.raises(ValueError, match="too many archive entries"):
        parse_slx(model_path)


def test_studio_api_rejects_tool_argument_types_as_json_400(tmp_path: Path) -> None:
    from slxdiff.server import serve_studio

    model_path = tmp_path / "controller.slx"
    _write_slx(model_path, _simple_xml())
    server, url = serve_studio(model_path, open_browser=False, token="hardening-token")
    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for arguments in ([], "not-an-object", None):
            status, headers, body = _post(
                url, "/api/v1/tools/call", server.token, {"name": "get_capabilities", "arguments": arguments}
            )
            assert status == 400
            assert body["ok"] is False and "error" in body
            assert headers["content-type"].startswith("application/json")
            assert int(headers["content-length"]) > 0
        status, _, body = _post(url, "/api/v1/blueprints/validate", server.token, {"blueprint": []})
        assert status == 400 and body["ok"] is False
        status, _, body = _post(url, "/api/v1/agent/chat", server.token, {"provider": [], "prompt": "x"})
        assert status == 400 and body["ok"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_studio_api_rejects_patch_and_stop_time_types(tmp_path: Path) -> None:
    from slxdiff.server import serve_studio

    model_path = tmp_path / "controller.slx"
    _write_slx(model_path, _simple_xml())
    server, url = serve_studio(model_path, open_browser=False, token="patch-token")
    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, body = _post(url, "/api/validate", server.token, {"patch": []})
        assert status == 400 and body["ok"] is False
        status, _, body = _post(url, "/api/simulate", server.token, {"patch": {}, "stop_time": []})
        assert status == 400 and body["ok"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_workbench_api_rejects_start_line_sweep_and_edit_types(tmp_path: Path) -> None:
    from slxdiff.workbench_server import serve_workbench

    server, url = serve_workbench(tmp_path, open_browser=False, token="workbench-hardening")
    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        (tmp_path / "controller.m").write_text("a = 1;\n", encoding="utf-8")
        for path, payload in (
            ("/api/v1/workspace/run/start", {"path": "controller.m", "start_line": "1"}),
            (
                "/api/v1/workspace/sweep/start",
                {"path": "model.slx", "block_path": "Gain", "parameter": "Gain", "values": {}},
            ),
            ("/api/v1/workspace/model-edit", {"path": "model.slx", "edit": []}),
        ):
            status, headers, body = _post(url, path, server.token, payload)
            assert status == 400, (path, body)
            assert body["ok"] is False and "error" in body
            assert headers["content-type"].startswith("application/json")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_structured_edit_rejects_invalid_connections_before_matlab(tmp_path: Path) -> None:
    model_path = tmp_path / "controller.slx"
    _write_slx(model_path, _simple_xml())
    model = parse_slx(model_path)
    with pytest.raises(ValueError, match="duplicate connection"):
        build_single_edit(
            model,
            model_path,
            {
                "op": "add_line",
                "system_path": "",
                "src_path": "控制器",
                "src_port": 1,
                "dst_path": "输出",
                "dst_port": 1,
            },
        )
    with pytest.raises(ValueError, match="self-connections"):
        build_single_edit(
            model,
            model_path,
            {
                "op": "add_line",
                "system_path": "",
                "src_path": "控制器",
                "src_port": 1,
                "dst_path": "控制器",
                "dst_port": 1,
            },
        )
    with pytest.raises(ValueError, match="delete"):
        build_single_edit(
            model,
            model_path,
            {
                "op": "delete_line",
                "system_path": "",
                "src_path": "输入",
                "src_port": 1,
                "dst_path": "输出",
                "dst_port": 1,
            },
        )


@pytest.mark.parametrize(
    "module_name, manager_name",
    [("slxdiff.mrunner", "MatlabRunManager"), ("slxdiff.sweep", "SweepRunManager")],
)
def test_completed_job_retention_does_not_remove_running_jobs(module_name: str, manager_name: str) -> None:
    module = __import__(module_name, fromlist=[manager_name])
    manager = getattr(module, manager_name)(matlab="fake")
    now = time.time()
    manager._jobs = {
        "old": {"id": "old", "state": "finished", "finished_at": now - 7200},
        "running": {"id": "running", "state": "running", "started_at": now},
    }
    with pytest.raises(ValueError, match="unknown"):
        manager.status("old")
    assert "running" in manager._jobs


def test_cli_doctor_reports_ready_json_without_matlab(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from slxdiff import cli
    from slxdiff.matlab_bridge import MatlabStatus

    monkeypatch.setattr(
        cli, "find_matlab", lambda _explicit=None: MatlabStatus(False, None, "MATLAB not configured")
    )
    assert cli.main(["doctor", str(tmp_path), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["status"] == "ready"
    assert {item["name"] for item in payload["checks"]} == {"python", "slx_studio", "workspace", "matlab"}
    assert next(item for item in payload["checks"] if item["name"] == "matlab")["required"] is False


def test_cli_doctor_parses_slx_and_surfaces_warnings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from slxdiff import cli
    from slxdiff.matlab_bridge import MatlabStatus

    model_path = tmp_path / "controller.slx"
    _write_slx(model_path, _simple_xml())
    monkeypatch.setattr(
        cli, "find_matlab", lambda _explicit=None: MatlabStatus(True, "matlab", "MATLAB executable found")
    )
    assert cli.main(["doctor", str(model_path)]) == 0
    output = capsys.readouterr().out
    assert "SLX parsed: 3 blocks, 2 lines" in output
    assert "Result: READY" in output


def test_cli_doctor_returns_action_required_for_missing_path(monkeypatch, capsys, tmp_path: Path) -> None:
    from slxdiff import cli
    from slxdiff.matlab_bridge import MatlabStatus

    monkeypatch.setattr(
        cli, "find_matlab", lambda _explicit=None: MatlabStatus(False, None, "MATLAB not configured")
    )
    assert cli.main(["doctor", str(tmp_path / "missing")]) == 1
    assert "ACTION REQUIRED" in capsys.readouterr().out
