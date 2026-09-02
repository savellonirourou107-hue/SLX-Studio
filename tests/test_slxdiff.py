from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import pytest

from slxdiff.diff import compare_models
from slxdiff.gitdiff import compare_git_refs
from slxdiff.parser import parse_slx, parse_slx_bytes
from slxdiff.render import render_git_markdown, render_markdown


def make_slx(path: Path, *, gain: str = "2", add_sink: bool = False, x_pos: int = 100) -> None:
    sink = (
        '<Block BlockType="Outport" Name="Scope" SID="3">'
        '<P Name="Position">[400 100 430 130]</P></Block>'
        if add_sink
        else ""
    )
    line2 = '<Line><P Name="Src">2#out:1</P><P Name="Dst">3#in:1</P></Line>' if add_sink else ""
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<System>
  <Block BlockType="Inport" Name="Input" SID="1"><P Name="Position">[20 100 50 130]</P></Block>
  <Block BlockType="Gain" Name="Gain" SID="2">
    <P Name="Gain">{gain}</P><P Name="Position">[{x_pos} 100 {x_pos+40} 130]</P>
  </Block>
  {sink}
  <Line><P Name="Src">1#out:1</P><P Name="Dst">2#in:1</P></Line>
  {line2}
</System>'''
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("simulink/systems/system_root.xml", xml)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_parameter_and_connection_changes(tmp_path: Path) -> None:
    old = tmp_path / "old.slx"
    new = tmp_path / "new.slx"
    make_slx(old, gain="2")
    make_slx(new, gain="3", add_sink=True)

    diff = compare_models(parse_slx(old), parse_slx(new))

    assert diff.changed
    assert len(diff.changed_blocks) == 1
    assert diff.changed_blocks[0].parameter_changes[0].name == "Gain"
    assert len(diff.added_blocks) == 1
    assert len(diff.added_lines) == 1
    markdown = render_markdown(diff)
    assert "Gain" in markdown
    assert "Added blocks" in markdown


def test_layout_noise_is_ignored_by_default(tmp_path: Path) -> None:
    old = tmp_path / "old.slx"
    new = tmp_path / "new.slx"
    make_slx(old, x_pos=100)
    make_slx(new, x_pos=180)

    assert not compare_models(parse_slx(old), parse_slx(new)).changed
    assert compare_models(parse_slx(old), parse_slx(new), include_layout=True).changed


def test_parse_slx_bytes(tmp_path: Path) -> None:
    model_path = tmp_path / "controller.slx"
    make_slx(model_path, gain="7")
    model = parse_slx_bytes(model_path.read_bytes(), name="controller.slx")
    gain = next(block for block in model.blocks.values() if block.name == "Gain")
    assert gain.parameters["Gain"] == "7"


def test_rejects_dtd_entity_xml() -> None:
    from io import BytesIO

    payload = BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr(
            "simulink/systems/system_root.xml",
            b'<!DOCTYPE x [<!ENTITY boom "boom">]><System><Block SID="1" Name="&boom;" /></System>',
        )
    with pytest.raises(ValueError, match="DTD/entity"):
        parse_slx_bytes(payload.getvalue(), name="hostile.slx")


def test_git_diff_discovers_changed_slx(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "tests@example.com")
    git(repo, "config", "user.name", "slx-diff tests")

    model = repo / "controller.slx"
    make_slx(model, gain="2")
    git(repo, "add", "controller.slx")
    git(repo, "commit", "-m", "before")
    base = git(repo, "rev-parse", "HEAD")

    make_slx(model, gain="3", add_sink=True)
    git(repo, "add", "controller.slx")
    git(repo, "commit", "-m", "after")
    head = git(repo, "rev-parse", "HEAD")

    diffs = compare_git_refs(base, head, cwd=repo)
    assert len(diffs) == 1
    assert diffs[0].status == "M"
    assert diffs[0].result.change_count == 3
    report = render_git_markdown(diffs)
    assert "1 model inspected" in report
    assert "3 semantic changes" in report
    assert "controller.slx" in report


def test_git_diff_handles_rename(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "tests@example.com")
    git(repo, "config", "user.name", "slx-diff tests")

    old_path = repo / "old_controller.slx"
    make_slx(old_path, gain="2")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")

    new_path = repo / "renamed_controller.slx"
    old_path.rename(new_path)
    make_slx(new_path, gain="3")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "rename")
    head = git(repo, "rev-parse", "HEAD")

    diffs = compare_git_refs(base, head, cwd=repo)
    assert len(diffs) == 1
    assert diffs[0].status == "R"
    assert diffs[0].old_path == "old_controller.slx"
    assert diffs[0].new_path == "renamed_controller.slx"
    assert diffs[0].result.changed


def test_git_diff_handles_added_model(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "tests@example.com")
    git(repo, "config", "user.name", "slx-diff tests")

    (repo / "README.md").write_text("base\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")

    make_slx(repo / "added.slx", gain="5")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "add model")
    head = git(repo, "rev-parse", "HEAD")

    diffs = compare_git_refs(base, head, cwd=repo)
    assert len(diffs) == 1
    assert diffs[0].status == "A"
    assert diffs[0].result.changed
    assert len(diffs[0].result.added_blocks) == 2


def test_studio_html_renders_model_and_diff(tmp_path: Path) -> None:
    from slxdiff.studio import write_studio_html

    old = tmp_path / "old.slx"
    new = tmp_path / "new.slx"
    single_html = tmp_path / "single.html"
    diff_html = tmp_path / "diff.html"
    make_slx(old, gain="2")
    make_slx(new, gain="3", add_sink=True)

    write_studio_html(old, output=single_html)
    write_studio_html(old, new, output=diff_html)

    single = single_html.read_text(encoding="utf-8")
    visual = diff_html.read_text(encoding="utf-8")
    assert "SLX Studio" in single
    assert '"mode":"model"' in single
    assert '"Position":"[100 100 140 130]"' in single
    assert '"mode":"diff"' in visual
    assert '"status":"changed"' in visual
    assert '"status":"added"' in visual
    assert '"change_count":3' in visual


def test_studio_escapes_script_terminator(tmp_path: Path) -> None:
    import zipfile

    from slxdiff.studio import write_studio_html

    model = tmp_path / "unsafe.slx"
    xml = '''<?xml version="1.0"?><System>
    <Block BlockType="Gain" Name="Unsafe" SID="1"><P Name="Gain">&lt;/script&gt;&lt;script&gt;alert(1)&lt;/script&gt;</P></Block>
    </System>'''
    with zipfile.ZipFile(model, "w") as archive:
        archive.writestr("simulink/systems/system_root.xml", xml)
    output = tmp_path / "unsafe.html"
    write_studio_html(model, output=output)
    html = output.read_text(encoding="utf-8")
    assert "<\\/script>" in html
    assert "</script><script>alert(1)</script>" not in html


def test_patch_is_hash_bound_and_conflict_detecting(tmp_path: Path) -> None:
    from slxdiff.patching import PatchDocument, PatchOperation, sha256_file, validate_patch_for_model

    model_path = tmp_path / "controller.slx"
    make_slx(model_path, gain="2")
    model = parse_slx(model_path)
    patch = PatchDocument(
        schema_version="0.1",
        model_name="controller",
        source_sha256=sha256_file(model_path),
        operations=(
            PatchOperation(
                op="set_param",
                block_path="Gain",
                parameter="Gain",
                before="2",
                after="3",
                sid="2",
                system_id="system_root",
            ),
        ),
    )
    validate_patch_for_model(patch, model, source_path=model_path)

    stale = PatchDocument(
        schema_version="0.1",
        model_name="controller",
        source_sha256=patch.source_sha256,
        operations=(
            PatchOperation(
                op="set_param",
                block_path="Gain",
                parameter="Gain",
                before="99",
                after="3",
                sid="2",
                system_id="system_root",
            ),
        ),
    )
    with pytest.raises(ValueError, match="patch conflict"):
        validate_patch_for_model(stale, model, source_path=model_path)


def test_studio_contains_editable_patch_metadata(tmp_path: Path) -> None:
    from slxdiff.studio import write_studio_html

    model_path = tmp_path / "controller.slx"
    output = tmp_path / "studio.html"
    make_slx(model_path, gain="2")
    write_studio_html(model_path, output=output)
    html = output.read_text(encoding="utf-8")
    model = parse_slx(model_path)
    assert 'Download Patch' in html
    assert 'Apply in MATLAB' in html
    assert '"patch_schema_version":"0.1"' in html
    assert model.metadata["sha256"] in html


def test_live_server_status_requires_token(tmp_path: Path) -> None:
    import http.client
    import threading
    from urllib.parse import urlparse

    from slxdiff.server import serve_studio

    model_path = tmp_path / "controller.slx"
    make_slx(model_path)
    server, url = serve_studio(model_path, open_browser=False)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        parsed = urlparse(url)
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
        conn.request("GET", "/api/status")
        assert conn.getresponse().status == 403
        conn.close()

        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
        conn.request("GET", "/api/status", headers={"X-SLX-Studio-Token": server.token})
        response = conn.getresponse()
        body = response.read().decode("utf-8")
        assert response.status == 200
        assert '"ok": true' in body
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_matlab_bridge_protocol_with_fake_executable(tmp_path: Path) -> None:
    import os

    from slxdiff.matlab_bridge import apply_patch_with_matlab
    from slxdiff.patching import PatchDocument, PatchOperation, sha256_file

    model_path = tmp_path / "controller.slx"
    output_path = tmp_path / "controller_edited.slx"
    make_slx(model_path, gain="2")
    patch = PatchDocument(
        schema_version="0.1",
        model_name="controller",
        source_sha256=sha256_file(model_path),
        operations=(PatchOperation("set_param", "Gain", "Gain", "2", "3", "2", "system_root"),),
    )

    fake = tmp_path / "fake-matlab"
    fake.write_text(
        """#!/usr/bin/env python3
import json, pathlib, re, shutil, sys
expr = sys.argv[2]
runner = pathlib.Path(re.search(r\"run\\('(.+)'\\)\", expr).group(1).replace(\"''\", \"'\"))
text = runner.read_text()
request = pathlib.Path(re.search(r\"requestPath = '(.+)';\", text).group(1).replace(\"''\", \"'\"))
result = pathlib.Path(re.search(r\"resultPath = '(.+)';\", text).group(1).replace(\"''\", \"'\"))
req = json.loads(request.read_text())
shutil.copyfile(req['input_model'], req['output_model'])
payload = {'ok': True, 'message': 'fake matlab ok', 'output_model': req['output_model'], 'simulation': {'ran': bool(req['simulate']['enabled']), 'stop_time': req['simulate']['stop_time'], 'elapsed_seconds': 0.01}}
result.write_text(json.dumps(payload))
""",
        encoding="utf-8",
    )
    os.chmod(fake, 0o755)
    result = apply_patch_with_matlab(
        model_path,
        patch,
        output_path=output_path,
        matlab=fake,
        simulate=True,
        stop_time="5",
    )
    assert result["ok"] is True
    assert result["simulation"]["ran"] is True
    assert output_path.exists()


def test_live_server_applies_patch_through_bridge(tmp_path: Path) -> None:
    import http.client
    import json
    import os
    import threading
    from urllib.parse import urlparse

    from slxdiff.patching import PatchDocument, PatchOperation, sha256_file
    from slxdiff.server import serve_studio

    model_path = tmp_path / "controller.slx"
    output_path = tmp_path / "controller_edited.slx"
    make_slx(model_path, gain="2")
    patch = PatchDocument(
        schema_version="0.1",
        model_name="controller",
        source_sha256=sha256_file(model_path),
        operations=(PatchOperation("set_param", "Gain", "Gain", "2", "3", "2", "system_root"),),
    )

    fake = tmp_path / "fake-matlab-server"
    fake.write_text(
        """#!/usr/bin/env python3
import json, pathlib, re, shutil, sys
runner = pathlib.Path(re.search(r"run\\('(.+)'\\)", sys.argv[2]).group(1).replace("''", "'"))
text = runner.read_text()
request = pathlib.Path(re.search(r"requestPath = '(.+)';", text).group(1).replace("''", "'"))
result = pathlib.Path(re.search(r"resultPath = '(.+)';", text).group(1).replace("''", "'"))
req = json.loads(request.read_text())
shutil.copyfile(req['input_model'], req['output_model'])
result.write_text(json.dumps({'ok': True, 'message': 'ok', 'output_model': req['output_model'], 'simulation': {'ran': False}}))
""",
        encoding="utf-8",
    )
    os.chmod(fake, 0o755)

    server, url = serve_studio(
        model_path,
        output_path=output_path,
        matlab=str(fake),
        open_browser=False,
    )
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        parsed = urlparse(url)
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
        body = json.dumps({"patch": patch.to_dict(), "stop_time": "10"})
        conn.request(
            "POST",
            "/api/apply",
            body=body,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body.encode("utf-8"))),
                "X-SLX-Studio-Token": server.token,
            },
        )
        response = conn.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        assert response.status == 200
        assert payload["ok"] is True
        assert output_path.exists()
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_review_intelligence_tracks_downstream_outport(tmp_path: Path) -> None:
    from slxdiff.review import build_review_report

    old = tmp_path / "before.slx"
    new = tmp_path / "after.slx"
    make_slx(old, gain="2")
    make_slx(new, gain="6", add_sink=True)

    report = build_review_report(parse_slx(old), parse_slx(new))
    gain = next(item for item in report.items if item.block_path == "Gain")
    assert gain.priority in {"medium", "high"}
    assert "Scope" in gain.downstream_blocks
    assert "Scope" in gain.affected_outports
    assert any(reason.code == "gain_changed" for reason in gain.reasons)
    assert any(reason.code == "reaches_outport" for reason in gain.reasons)


def test_review_intelligence_prioritizes_sample_time_changes(tmp_path: Path) -> None:
    from slxdiff.review import build_review_report

    def make_sample_model(path: Path, sample_time: str) -> None:
        xml = f'''<?xml version="1.0"?>
<System>
  <Block BlockType="Inport" Name="Input" SID="1" />
  <Block BlockType="Gain" Name="Controller" SID="2">
    <P Name="Gain">2</P><P Name="SampleTime">{sample_time}</P>
  </Block>
  <Block BlockType="Outport" Name="Output" SID="3" />
  <Line><P Name="Src">1#out:1</P><P Name="Dst">2#in:1</P></Line>
  <Line><P Name="Src">2#out:1</P><P Name="Dst">3#in:1</P></Line>
</System>'''
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("simulink/systems/system_root.xml", xml)

    old = tmp_path / "before.slx"
    new = tmp_path / "after.slx"
    make_sample_model(old, "0.01")
    make_sample_model(new, "0.1")
    report = build_review_report(parse_slx(old), parse_slx(new))
    controller = next(item for item in report.items if item.block_path == "Controller")
    assert controller.priority == "high"
    assert any(reason.code == "sample_time_changed" for reason in controller.reasons)
    assert controller.affected_outports == ["Output"]


def test_agent_context_is_compact_and_review_aware(tmp_path: Path) -> None:
    from slxdiff.context import build_agent_context

    old = tmp_path / "before.slx"
    new = tmp_path / "after.slx"
    make_slx(old, gain="2")
    make_slx(new, gain="3", add_sink=True)
    context = build_agent_context(parse_slx(old), parse_slx(new))

    assert context["kind"] == "slx-agent-review-context"
    assert context["summary"]["change_count"] == 3
    assert context["review_hotspots"]
    assert context["interpretation"]["does_not_compile_or_execute_model"] is True
    assert context["semantic_changes"]["changed_blocks"][0]["path"] == "Gain"


def test_studio_contains_bilingual_review_lens_and_agent_context(tmp_path: Path) -> None:
    from slxdiff.studio import write_studio_html

    old = tmp_path / "before.slx"
    new = tmp_path / "after.slx"
    output = tmp_path / "review.html"
    make_slx(old, gain="2")
    make_slx(new, gain="3", add_sink=True)
    write_studio_html(old, new, output=output)
    html = output.read_text(encoding="utf-8")

    assert "Review Lens" in html
    assert "审查透镜" in html
    assert "AI 上下文" in html
    assert '"kind":"slx-review-intelligence"' in html
    assert '"kind":"slx-agent-review-context"' in html
    assert 'id="languageSelect"' in html


def test_review_blast_radius_keeps_removed_signal_path(tmp_path: Path) -> None:
    from slxdiff.review import build_review_report

    def make_path_model(path: Path, *, connected_to_output: bool) -> None:
        final_line = (
            '<Line><P Name="Src">2#out:1</P><P Name="Dst">3#in:1</P></Line>'
            if connected_to_output
            else ""
        )
        xml = f'''<?xml version="1.0"?>
<System>
  <Block BlockType="Inport" Name="Input" SID="1" />
  <Block BlockType="Gain" Name="Controller" SID="2"><P Name="Gain">2</P></Block>
  <Block BlockType="Outport" Name="Output" SID="3" />
  <Line><P Name="Src">1#out:1</P><P Name="Dst">2#in:1</P></Line>
  {final_line}
</System>'''
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("simulink/systems/system_root.xml", xml)

    old = tmp_path / "before.slx"
    new = tmp_path / "after.slx"
    make_path_model(old, connected_to_output=True)
    make_path_model(new, connected_to_output=False)

    report = build_review_report(parse_slx(old), parse_slx(new))
    controller = next(item for item in report.items if item.block_path == "Controller")
    assert controller.status == "rewired"
    assert "Output" in controller.downstream_blocks
    assert "Output" in controller.affected_outports
    assert any(reason.code == "connection_changed" for reason in controller.reasons)


def sample_blueprint() -> dict:
    return {
        "schema_version": "0.1",
        "model_name": "ai_demo",
        "description": "Step through a gain to an output.",
        "blocks": [
            {"id": "ref", "type": "step", "name": "Reference", "position": [20, 100, 70, 130], "parameters": {"Time": "0", "Before": "0", "After": "1"}},
            {"id": "kp", "type": "gain", "name": "Kp", "position": [150, 100, 200, 130], "parameters": {"Gain": "2"}},
            {"id": "out", "type": "outport", "name": "Output", "position": [300, 100, 330, 130], "parameters": {}},
        ],
        "connections": [
            {"src": "ref", "dst": "kp", "src_port": 1, "dst_port": 1},
            {"src": "kp", "dst": "out", "src_port": 1, "dst_port": 1},
        ],
        "model_parameters": {"StopTime": "10"},
    }


def test_blueprint_is_validated_and_previewable() -> None:
    from slxdiff.blueprint import blueprint_from_dict, blueprint_to_model

    blueprint = blueprint_from_dict(sample_blueprint())
    preview = blueprint_to_model(blueprint)
    assert blueprint.model_name == "ai_demo"
    assert len(preview.blocks) == 3
    assert len(preview.lines) == 2
    assert next(block for block in preview.blocks.values() if block.name == "Kp").parameters["Gain"] == "2"


def test_blueprint_rejects_unknown_blocks_and_parameters() -> None:
    from slxdiff.blueprint import blueprint_from_dict

    bad = sample_blueprint()
    bad["blocks"][1]["type"] = "arbitrary_script"
    with pytest.raises(ValueError, match="unsupported blueprint block type"):
        blueprint_from_dict(bad)

    bad = sample_blueprint()
    bad["blocks"][1]["parameters"]["OpenFcn"] = "system('bad')"
    with pytest.raises(ValueError, match="not allowed"):
        blueprint_from_dict(bad)


def test_blueprint_matlab_bridge_with_fake_executable(tmp_path: Path) -> None:
    import os

    from slxdiff.blueprint import blueprint_from_dict
    from slxdiff.matlab_bridge import build_blueprint_with_matlab

    fake = tmp_path / "fake-matlab-blueprint"
    fake.write_text(
        '''#!/usr/bin/env python3
import json, pathlib, re, sys
runner = pathlib.Path(re.search(r"run\\('(.+)'\\)", sys.argv[2]).group(1).replace("''", "'"))
text = runner.read_text()
request = pathlib.Path(re.search(r"requestPath = '(.+)';", text).group(1).replace("''", "'"))
result = pathlib.Path(re.search(r"resultPath = '(.+)';", text).group(1).replace("''", "'"))
req = json.loads(request.read_text())
out = pathlib.Path(req['output_model'])
out.write_bytes(b'fake-slx')
result.write_text(json.dumps({'ok': True, 'message': 'built', 'output_model': str(out), 'model_name': req['model_name'], 'block_count': len(req['blocks']), 'connection_count': len(req['connections'])}))
''',
        encoding="utf-8",
    )
    os.chmod(fake, 0o755)
    output = tmp_path / "ai_demo.slx"
    result = build_blueprint_with_matlab(
        blueprint_from_dict(sample_blueprint()), output_path=output, matlab=fake
    )
    assert result["ok"] is True
    assert result["block_count"] == 3
    assert output.exists()


def test_v1_api_supports_blank_workspace_and_blueprint_preview(tmp_path: Path) -> None:
    import http.client
    import json
    import threading
    from urllib.parse import urlparse

    from slxdiff.server import serve_studio

    server, url = serve_studio(None, generated_dir=tmp_path, open_browser=False, token="test-token")
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        parsed = urlparse(url)
        headers = {"X-SLX-Studio-Token": "test-token"}
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
        conn.request("GET", "/api/v1/capabilities", headers=headers)
        response = conn.getresponse()
        capabilities = json.loads(response.read())
        assert response.status == 200
        assert capabilities["security"]["arbitrary_matlab_execution"] is False
        assert "gain" in capabilities["block_catalog"]
        conn.close()

        body = json.dumps({"blueprint": sample_blueprint()})
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
        conn.request(
            "POST",
            "/api/v1/blueprints/validate",
            body=body,
            headers={**headers, "Content-Type": "application/json", "Content-Length": str(len(body.encode()))},
        )
        response = conn.getresponse()
        payload = json.loads(response.read())
        assert response.status == 200
        assert payload["valid"] is True
        assert len(payload["preview"]["blocks"]) == 3
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_agent_chat_openai_compatible_tool_loop(tmp_path: Path) -> None:
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from slxdiff.agent import provider_from_dict, run_agent

    blueprint = sample_blueprint()
    requests: list[dict] = []

    class ProviderHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length))
            requests.append(body)
            if len(requests) == 1:
                payload = {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [{
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "submit_blueprint", "arguments": json.dumps(blueprint)},
                            }],
                        }
                    }]
                }
            else:
                payload = {"choices": [{"message": {"role": "assistant", "content": "Blueprint ready for review."}}]}
            raw = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    provider_server = ThreadingHTTPServer(("127.0.0.1", 0), ProviderHandler)
    thread = threading.Thread(target=provider_server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = provider_server.server_address
        provider = provider_from_dict({
            "kind": "openai_compatible_chat",
            "base_url": f"http://{host}:{port}/v1",
            "model": "fake-model",
            "api_key": "secret-not-persisted",
        })
        result = run_agent(provider, "Build a tiny model", model_path=None, allow_build=False)
        assert result.text == "Blueprint ready for review."
        assert result.blueprint is not None
        assert result.blueprint.model_name == "ai_demo"
        assert result.trace[0]["tool"] == "submit_blueprint"
    finally:
        provider_server.shutdown()
        provider_server.server_close()
        thread.join(timeout=2)


def test_cn_provider_presets_and_environment_key(monkeypatch) -> None:
    from slxdiff.agent import provider_catalog_payload, provider_from_dict

    providers = {item["id"]: item for item in provider_catalog_payload()}
    assert {"deepseek", "kimi", "minimax", "glm", "qwen"}.issubset(providers)
    assert providers["deepseek"]["default_base_url"] == "https://api.deepseek.com"
    assert providers["deepseek"]["default_model"] == "deepseek-v4-flash"
    assert providers["kimi"]["default_base_url"] == "https://api.moonshot.cn/v1"
    assert providers["kimi"]["default_model"] == "kimi-k3"
    assert providers["minimax"]["default_base_url"] == "https://api.minimaxi.com/v1"
    assert providers["glm"]["default_base_url"] == "https://open.bigmodel.cn/api/paas/v4"
    assert providers["qwen"]["default_base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"

    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-secret")
    config = provider_from_dict({"provider_id": "deepseek"})
    assert config.kind == "openai_compatible_chat"
    assert config.model == "deepseek-v4-flash"
    assert config.api_key == "env-secret"
    assert config.provider_id == "deepseek"

    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.setenv("MOONSHOT_API_KEY", "moonshot-official-env")
    kimi = provider_from_dict({"provider_id": "kimi"})
    assert kimi.api_key == "moonshot-official-env"
    assert "MOONSHOT_API_KEY" in providers["kimi"]["api_key_env_aliases"]
    assert "MiniMax-M3" not in providers["minimax"]["models"]
    assert "qwen3.7-flash" in providers["qwen"]["models"]


def test_v1_providers_endpoint_lists_cn_presets(tmp_path: Path) -> None:
    import http.client
    import json
    import threading
    from urllib.parse import urlparse

    from slxdiff.server import serve_studio

    server, url = serve_studio(None, generated_dir=tmp_path, open_browser=False, token="provider-token")
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        parsed = urlparse(url)
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
        conn.request("GET", "/api/v1/providers", headers={"X-SLX-Studio-Token": "provider-token"})
        response = conn.getresponse()
        payload = json.loads(response.read())
        conn.close()
        assert response.status == 200
        ids = {item["id"] for item in payload["providers"]}
        assert {"deepseek", "kimi", "minimax", "glm", "qwen"}.issubset(ids)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_agent_static_structure_analysis(tmp_path: Path) -> None:
    from slxdiff.agent import ToolRuntime

    model_path = tmp_path / "structure.slx"
    make_slx(model_path, add_sink=True)
    runtime = ToolRuntime(model_path)
    result = runtime.call("analyze_model_structure", {})
    assert result["analysis_kind"] == "static_signal_graph"
    assert result["source_blocks"] == ["Input"]
    assert result["sink_blocks"] == ["Scope"]
    assert result["outports"] == ["Scope"]
    assert result["feedback_components"] == []
    assert "stability" in result["disclaimer"]


def test_workspace_edits_matlab_scripts_and_blocks_traversal(tmp_path: Path) -> None:
    from slxdiff.workspace import create_m_file, list_workspace, read_text_file, write_text_file

    script = create_m_file(tmp_path, "scripts/demo.m")
    assert script.exists()
    write_text_file(tmp_path, "scripts/demo.m", "x = 42;\ndisp(x);\n")
    assert read_text_file(tmp_path, "scripts/demo.m") == "x = 42;\ndisp(x);\n"
    tree = list_workspace(tmp_path)
    assert tree["items"][0]["type"] == "directory"
    assert tree["items"][0]["children"][0]["kind"] == "matlab"
    with pytest.raises(ValueError, match="escapes"):
        read_text_file(tmp_path, "../outside.m")


def test_matlab_m_runner_with_fake_executable(tmp_path: Path) -> None:
    import os

    from slxdiff.mrunner import run_m_file

    script = tmp_path / "hello.m"
    script.write_text("disp('hello')\n", encoding="utf-8")
    fake = tmp_path / "fake-matlab-m"
    fake.write_text("#!/usr/bin/env python3\nprint('hello from fake MATLAB')\n", encoding="utf-8")
    os.chmod(fake, 0o755)
    result = run_m_file(script, matlab=fake)
    assert result["ok"] is True
    assert "hello from fake MATLAB" in result["stdout"]


def test_structural_model_edit_validation_and_bridge(tmp_path: Path) -> None:
    import os

    from slxdiff.matlab_bridge import apply_model_edit_with_matlab
    from slxdiff.model_edit import build_single_edit
    from slxdiff.parser import parse_slx

    model_path = tmp_path / "controller.slx"
    make_slx(model_path, gain="2")
    model = parse_slx(model_path)
    document = build_single_edit(
        model,
        model_path,
        {"op": "add_block", "block_type": "scope", "name": "Monitor", "parent": "", "position": [300, 180, 350, 220], "parameters": {}},
    )

    fake = tmp_path / "fake-matlab-edit"
    fake.write_text(
        '''#!/usr/bin/env python3
import json, pathlib, re, sys
runner = pathlib.Path(re.search(r"run\\('(.+)'\\)", sys.argv[2]).group(1).replace("''", "'"))
text = runner.read_text()
request = pathlib.Path(re.search(r"requestPath = '(.+)';", text).group(1).replace("''", "'"))
result = pathlib.Path(re.search(r"resultPath = '(.+)';", text).group(1).replace("''", "'"))
req = json.loads(request.read_text())
assert req['edit']['operations'][0]['library'] == 'simulink/Sinks/Scope'
result.write_text(json.dumps({'ok': True, 'message': 'edited', 'output_model': req['output_model']}))
''',
        encoding="utf-8",
    )
    os.chmod(fake, 0o755)
    result = apply_model_edit_with_matlab(model_path, document, output_path=model_path, matlab=fake)
    assert result["ok"] is True


def test_workbench_api_reads_saves_and_serves_slx(tmp_path: Path) -> None:
    import http.client
    import json
    import threading
    from urllib.parse import quote, urlparse

    from slxdiff.workbench_server import serve_workbench

    script = tmp_path / "demo.m"
    script.write_text("x = 1;\n", encoding="utf-8")
    model = tmp_path / "controller.slx"
    make_slx(model)
    server, url = serve_workbench(tmp_path, open_browser=False, token="workbench-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        parsed = urlparse(url)
        headers = {"X-SLX-Studio-Token": "workbench-token"}
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
        conn.request("GET", "/api/v1/workspace", headers=headers)
        response = conn.getresponse()
        payload = json.loads(response.read())
        assert response.status == 200
        flat = str(payload)
        assert "demo.m" in flat and "controller.slx" in flat
        conn.close()

        body = json.dumps({"path": "demo.m", "content": "x = 7;\n"})
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
        conn.request("POST", "/api/v1/workspace/save", body=body, headers={**headers, "Content-Type": "application/json", "Content-Length": str(len(body.encode()))})
        response = conn.getresponse()
        assert response.status == 200
        response.read(); conn.close()
        assert script.read_text(encoding="utf-8") == "x = 7;\n"

        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
        conn.request("GET", "/slx?path=" + quote("controller.slx"))
        response = conn.getresponse()
        html = response.read().decode("utf-8")
        assert response.status == 200
        assert "SLX Studio" in html
        assert '"workbench":true' in html
        assert "+ Block" in html
        conn.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_workbench_html_is_bilingual_and_has_m_editor() -> None:
    from slxdiff.workbench import render_workbench_html

    html = render_workbench_html({"token": "x", "root": "/tmp/demo", "initial_file": None})
    assert "New .m" in html
    assert "新建 .m" in html
    assert 'id="code"' in html
    assert 'id="slxFrame"' in html
    assert 'id="consoleOutput"' in html


def test_create_empty_slx_with_fake_matlab(tmp_path: Path) -> None:
    import os

    from slxdiff.matlab_bridge import create_empty_model_with_matlab

    fake = tmp_path / "fake-matlab-create"
    fake.write_text(
        '''#!/usr/bin/env python3
import pathlib, re, sys
expr = sys.argv[2]
match = re.search(r"save_system\\('[^']+','([^']+)'\\)", expr)
if not match:
    raise SystemExit(3)
path = pathlib.Path(match.group(1).replace("''", "'"))
path.parent.mkdir(parents=True, exist_ok=True)
path.write_bytes(b'fake slx')
''',
        encoding="utf-8",
    )
    os.chmod(fake, 0o755)
    output = tmp_path / "new_model.slx"
    result = create_empty_model_with_matlab(output, matlab=fake)
    assert result["ok"] is True
    assert output.exists()


def test_model_edit_supports_conflict_checked_block_move(tmp_path: Path) -> None:
    from slxdiff.model_edit import build_single_edit
    from slxdiff.parser import parse_slx

    model_path = tmp_path / "move.slx"
    make_slx(model_path, x_pos=100)
    model = parse_slx(model_path)
    gain = next(block for block in model.blocks.values() if block.name == "Gain")
    document = build_single_edit(
        model,
        model_path,
        {
            "op": "move_block",
            "block_path": gain.path,
            "sid": gain.sid,
            "before_position": [100, 100, 140, 130],
            "position": [180, 160, 220, 190],
        },
    )
    assert document.operations[0]["op"] == "move_block"
    assert document.operations[0]["position"] == [180, 160, 220, 190]

    with pytest.raises(ValueError, match="position conflict"):
        build_single_edit(
            model,
            model_path,
            {
                "op": "move_block",
                "block_path": gain.path,
                "sid": gain.sid,
                "before_position": [101, 100, 141, 130],
                "position": [180, 160, 220, 190],
            },
        )


def test_model_history_undo_redo_and_external_conflict(tmp_path: Path) -> None:
    from slxdiff.history import ModelHistory

    model = tmp_path / "controller.slx"
    model.write_bytes(b"before")
    history = ModelHistory(max_records_per_file=4)
    try:
        before = history.capture(model, label="before")
        model.write_bytes(b"after")
        status = history.record(model, before)
        assert status["can_undo"] is True
        history.undo(model)
        assert model.read_bytes() == b"before"
        assert history.status(model)["can_redo"] is True
        history.redo(model)
        assert model.read_bytes() == b"after"

        model.write_bytes(b"external")
        with pytest.raises(ValueError, match="outside SLX Studio"):
            history.undo(model)
    finally:
        history.close()


def test_m_runner_accepts_workspace_metadata_from_matlab_wrapper(tmp_path: Path) -> None:
    import os

    from slxdiff.mrunner import run_m_file

    script = tmp_path / "variables.m"
    script.write_text("x = 42;\nname = 'demo';\n", encoding="utf-8")
    fake = tmp_path / "fake-matlab-vars"
    fake.write_text(
        '''#!/usr/bin/env python3
import json, pathlib, re, sys
runner = pathlib.Path(re.search(r"run\\('(.+)'\\)", sys.argv[2]).group(1).replace("''", "'"))
text = runner.read_text()
result = pathlib.Path(re.search(r"resultPath = '(.+)';", text).group(1).replace("''", "'"))
result.write_text(json.dumps({
  'ok': True,
  'variables': [
    {'name': 'x', 'class': 'double', 'size': '1x1', 'bytes': 8, 'preview': '42'},
    {'name': 'name', 'class': 'char', 'size': '1x4', 'bytes': 8, 'preview': 'demo'}
  ],
  'error': {}
}))
print('fake execution complete')
''',
        encoding="utf-8",
    )
    os.chmod(fake, 0o755)
    result = run_m_file(script, matlab=fake)
    assert result["ok"] is True
    assert [item["name"] for item in result["variables"]] == ["x", "name"]
    assert result["variables"][0]["preview"] == "42"
    assert result["error"] is None


def test_v08_workbench_contains_tabs_highlighting_variables_and_history_controls() -> None:
    from slxdiff.workbench import render_workbench_html

    html = render_workbench_html({"token": "x", "root": "/tmp/demo", "initial_file": None})
    assert 'id="tabs"' in html
    assert 'id="highlight"' in html
    assert 'id="variablesBody"' in html
    assert 'id="undo"' in html and 'id="redo"' in html
    assert "syntaxHighlight" in html
    assert "Ctrl+S" in html
    assert "Workspace" in html and "变量" in html


def test_v08_studio_contains_drag_connect_and_block_palette(tmp_path: Path) -> None:
    from slxdiff.studio import render_studio_html

    model_path = tmp_path / "controller.slx"
    make_slx(model_path, gain="2")
    model = parse_slx(model_path)
    html = render_studio_html(
        model,
        bridge={"enabled": True, "token": "x", "workbench": True, "workspace_path": "controller.slx"},
    )
    assert 'id="connectPreview"' in html
    assert "move_block" in html
    assert "startConnection" in html
    assert "blockCatalogSearch" in html
    assert "slx-studio-save" in html
    assert "/api/v1/workspace/apply-patch" in html
    assert "拖动模块可移动" in html


def test_v09_section_runner_preserves_source_line_offset(tmp_path: Path) -> None:
    import os

    from slxdiff.mrunner import run_m_code

    script = tmp_path / "sections.m"
    script.write_text("%% one\na = 1;\n%% two\nb = missing_name;\n", encoding="utf-8")
    fake = tmp_path / "fake-matlab-section"
    fake.write_text(
        '''#!/usr/bin/env python3
import json, pathlib, re, sys
runner = pathlib.Path(re.search(r"run\\('(.+)'\\)", sys.argv[2]).group(1).replace("''", "'"))
text = runner.read_text()
assert "lineOffset = 2;" in text
source = pathlib.Path(re.search(r"sourcePath = '(.+)';", text).group(1).replace("''", "'"))
assert source.name == 'sections.m'
section = pathlib.Path(re.search(r"scriptPath = '(.+)';", text).group(1).replace("''", "'"))
assert 'b = missing_name;' in section.read_text()
result = pathlib.Path(re.search(r"resultPath = '(.+)';", text).group(1).replace("''", "'"))
result.write_text(json.dumps({'ok': True, 'variables': [], 'figures': [], 'error': {}}))
''',
        encoding="utf-8",
    )
    os.chmod(fake, 0o755)
    result = run_m_code(script, "%% two\nb = missing_name;\n", start_line=3, matlab=fake)
    assert result["ok"] is True


def test_v09_runner_captures_matlab_figure_payload(tmp_path: Path) -> None:
    import base64
    import os

    from slxdiff.mrunner import run_m_file

    script = tmp_path / "plot_demo.m"
    script.write_text("plot(1:3)\n", encoding="utf-8")
    fake = tmp_path / "fake-matlab-figure"
    fake.write_text(
        '''#!/usr/bin/env python3
import json, pathlib, re, sys
runner = pathlib.Path(re.search(r"run\\('(.+)'\\)", sys.argv[2]).group(1).replace("''", "'"))
text = runner.read_text()
result = pathlib.Path(re.search(r"resultPath = '(.+)';", text).group(1).replace("''", "'"))
figure_dir = pathlib.Path(re.search(r"figureDir = '(.+)';", text).group(1).replace("''", "'"))
figure_dir.mkdir(parents=True, exist_ok=True)
png = figure_dir / 'figure-01.png'
png.write_bytes(b'fake-png-data')
result.write_text(json.dumps({'ok': True, 'variables': [], 'figures': [{'name':'Response','path':str(png)}], 'error': {}}))
''',
        encoding="utf-8",
    )
    os.chmod(fake, 0o755)
    result = run_m_file(script, matlab=fake)
    assert result["ok"] is True
    assert result["figures"][0]["name"] == "Response"
    assert base64.b64decode(result["figures"][0]["data_base64"]) == b"fake-png-data"


def test_v09_matlab_run_manager_can_stop_job(tmp_path: Path) -> None:
    import os
    import time

    from slxdiff.mrunner import MatlabRunManager

    script = tmp_path / "slow.m"
    script.write_text("pause(10)\n", encoding="utf-8")
    fake = tmp_path / "fake-matlab-slow"
    fake.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(30)\n", encoding="utf-8")
    os.chmod(fake, 0o755)
    manager = MatlabRunManager(matlab=fake, timeout=60)
    job = manager.start(script)
    assert job["state"] == "running"
    manager.stop(job["id"])
    deadline = time.time() + 3
    status = manager.status(job["id"])
    while status["state"] == "running" and time.time() < deadline:
        time.sleep(0.05)
        status = manager.status(job["id"])
    assert status["state"] == "cancelled"
    assert status["result"]["cancelled"] is True


def test_v09_workspace_search_finds_m_text_and_slx_blocks(tmp_path: Path) -> None:
    from slxdiff.workspace import search_workspace

    script = tmp_path / "controller.m"
    script.write_text("Kp = 4.2;\ndisp(Kp);\n", encoding="utf-8")
    model = tmp_path / "plant.slx"
    make_slx(model, gain="2")
    m_results = search_workspace(tmp_path, "Kp")["results"]
    assert any(item["path"] == "controller.m" and item["line"] == 1 for item in m_results)
    slx_results = search_workspace(tmp_path, "Gain")["results"]
    assert any(item["path"] == "plant.slx" and item["type"] == "block" for item in slx_results)


def test_v09_workspace_save_as_preserves_extension(tmp_path: Path) -> None:
    from slxdiff.workspace import copy_workspace_file

    source = tmp_path / "model.slx"
    source.write_bytes(b"slx")
    copied = copy_workspace_file(tmp_path, "model.slx", "model_copy.slx")
    assert copied.read_bytes() == b"slx"
    with pytest.raises(ValueError, match="preserve"):
        copy_workspace_file(tmp_path, "model.slx", "model_copy.m")


def test_v09_workbench_has_run_section_stop_search_plots_and_save_as() -> None:
    from slxdiff.workbench import render_workbench_html

    html = render_workbench_html({"token": "x", "root": "/tmp/demo", "initial_file": None})
    for marker in ['id="runSection"', 'id="stop"', 'id="saveAs"', 'id="paletteBackdrop"', 'id="plotsBody"']:
        assert marker in html
    assert "Ctrl+Enter" in html or "startMRun(true)" in html
    assert "/api/v1/workspace/run/start" in html
    assert "/api/v1/workspace/search" in html


def test_v09_matlab_bridge_collects_simulation_series() -> None:
    from slxdiff.matlab_bridge import _runner_source

    source = _runner_source(Path("request.json"), Path("result.json"))
    assert "slxstudio_collect_sim_series" in source
    assert "Simulink.SimulationData.Dataset" in source
    assert "timeseries" in source


def test_v09_studio_renders_explicit_multiports_and_subsystem_navigation():
    html = (Path(__file__).parents[1] / "src" / "slxdiff" / "studio.html").read_text(encoding="utf-8")
    assert "function buildPortCounts" in html
    assert "srcPort=1" in html
    assert "src_port:Number(state.srcPort)||1" in html
    assert "for(let i=1;i<=pc.in;i++)" in html
    assert "for(let i=1;i<=pc.out;i++)" in html
    assert "openSubsystem(b)" in html


def test_v10_state_tracks_recent_projects_and_recovery(tmp_path: Path) -> None:
    from slxdiff.state import StudioState

    project = tmp_path / "project"
    project.mkdir()
    script = project / "controller.m"
    script.write_text("Kp = 2;\n", encoding="utf-8")
    state = StudioState(tmp_path / "state")
    recent = state.mark_recent(project)
    assert recent[0]["path"] == str(project.resolve())
    listed = state.recent_projects()
    assert listed[0]["exists"] is True
    state.save_recovery(project, "controller.m", "Kp = 3;\n", disk_mtime_ns=script.stat().st_mtime_ns)
    recovery = state.get_recovery(project, "controller.m")
    assert recovery is not None and recovery["content"] == "Kp = 3;\n"
    assert state.clear_recovery(project, "controller.m") is True
    assert state.get_recovery(project, "controller.m") is None


def test_v10_m_runner_workspace_checkpoint_is_loaded_and_saved(tmp_path: Path) -> None:
    from slxdiff.mrunner import _runner_source

    source = _runner_source(
        tmp_path / "script.m",
        tmp_path / "result.json",
        tmp_path / "figures",
        source_path=tmp_path / "script.m",
        line_offset=0,
        workspace_file=tmp_path / "workspace.mat",
    )
    assert "state = load(workspaceFile)" in source
    assert "assignin('base', name, state.(name))" in source
    assert "evalin('base', runExpression)" in source
    assert "save(workspaceFile, '-struct', 'state')" in source


def test_v10_command_session_uses_shared_checkpoint_and_returns_variables(tmp_path: Path) -> None:
    import os

    from slxdiff.msession import MatlabCommandSession

    fake = tmp_path / "fake-matlab-command"
    fake.write_text(
        '''#!/usr/bin/env python3
import json, pathlib, re, sys
runner = pathlib.Path(re.search(r"run\\('(.+)'\\)", sys.argv[2]).group(1).replace("''", "'"))
text = runner.read_text()
workspace = pathlib.Path(re.search(r"workspaceFile = '(.+)';", text).group(1).replace("''", "'"))
workspace.parent.mkdir(parents=True, exist_ok=True)
workspace.write_bytes(b'checkpoint')
result = pathlib.Path(re.search(r"resultPath = '(.+)';", text).group(1).replace("''", "'"))
result.write_text(json.dumps({'ok': True, 'stdout': 'Kp = 3\\n', 'variables': [{'name':'Kp','class':'double','size':'1x1','bytes':8,'preview':'3'}], 'figures': [], 'error': {}}))
''',
        encoding="utf-8",
    )
    os.chmod(fake, 0o755)
    checkpoint = tmp_path / "session" / "workspace.mat"
    session = MatlabCommandSession(work_dir=tmp_path, workspace_file=checkpoint, matlab=fake)
    result = session.execute("Kp = 3")
    assert result["ok"] is True
    assert result["variables"][0]["name"] == "Kp"
    assert checkpoint.exists()


def test_v10_sweep_value_parser_and_validation(tmp_path: Path) -> None:
    from slxdiff.sweep import parse_sweep_values, validate_sweep

    assert parse_sweep_values("1:0.5:2") == ["1", "1.5", "2"]
    assert parse_sweep_values("3:1") == ["3", "2", "1"]
    with pytest.raises(ValueError, match="at most"):
        parse_sweep_values("0:1:30")
    with pytest.raises(ValueError, match="numeric"):
        parse_sweep_values("1,system('calc'),3")
    with pytest.raises(ValueError, match="numeric"):
        parse_sweep_values("1,nan,3")
    model = tmp_path / "controller.slx"
    make_slx(model, gain="2")
    info = validate_sweep(model, "Gain", "Gain", ["1", "2", "3"])
    assert info["before"] == "2"
    assert info["parameter"] == "Gain"


def test_v10_parameter_sweep_returns_series_and_metrics(tmp_path: Path) -> None:
    import os

    from slxdiff.sweep import run_parameter_sweep_with_matlab

    model = tmp_path / "controller.slx"
    make_slx(model, gain="2")
    fake = tmp_path / "fake-matlab-sweep"
    fake.write_text(
        '''#!/usr/bin/env python3
import json, pathlib, re, sys
runner = pathlib.Path(re.search(r"run\\('(.+)'\\)", sys.argv[2]).group(1).replace("''", "'"))
text = runner.read_text()
result = pathlib.Path(re.search(r"resultPath = '(.+)';", text).group(1).replace("''", "'"))
result.write_text(json.dumps({'ok': True, 'message':'done', 'elapsed_seconds':0.1, 'runs':[{'value':'1','elapsed_seconds':0.01,'series':[{'name':'y','time':[0,1,2],'data':[0,0.8,1]}]},{'value':'2','elapsed_seconds':0.01,'series':[{'name':'y','time':[0,1,2],'data':[0,1.1,1]}]}]}))
''',
        encoding="utf-8",
    )
    os.chmod(fake, 0o755)
    result = run_parameter_sweep_with_matlab(model, block_path="Gain", parameter="Gain", values="1,2", matlab=fake)
    assert result["ok"] is True
    assert len(result["runs"]) == 2
    assert result["runs"][0]["series"][0]["metrics"]["final"] == 1.0
    assert "verification" in result["metric_disclaimer"].lower()


def test_v10_workbench_has_command_window_sweep_recovery_and_command_palette() -> None:
    from slxdiff.workbench import render_workbench_html

    html = render_workbench_html({"token": "x", "root": "/tmp/demo", "initial_file": None})
    for marker in ['id="commandInput"', 'id="sweep"', 'id="sweepBackdrop"', 'id="recoveryBanner"', 'id="commandPalette"']:
        assert marker in html
    assert "/api/v1/workspace/command" in html
    assert "/api/v1/workspace/variables/set" in html
    assert "/api/v1/workspace/sweep/start" in html
    assert "/api/v1/workspace/sim/stop" in html
    assert "Ctrl+Shift+P" in html


def test_v10_studio_routes_workbench_simulation_through_parent_job_manager(tmp_path: Path) -> None:
    from slxdiff.studio import render_studio_html

    model_path = tmp_path / "controller.slx"
    make_slx(model_path, gain="2")
    html = render_studio_html(
        parse_slx(model_path),
        bridge={"enabled": True, "token": "x", "workbench": True, "workspace_path": "controller.slx"},
    )
    assert "slx-simulation-request" in html
    assert "slx-simulation-finished" in html
    assert "slx-block-selected" in html


def test_beta2_parser_escapes_slashes_in_block_names(tmp_path: Path) -> None:
    path = tmp_path / "slash-name.slx"
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<System>
  <Block BlockType="Gain" Name="A/B" SID="1"><P Name="Gain">2</P></Block>
  <Block BlockType="Outport" Name="Out" SID="2" />
  <Line><P Name="Src">1#out:1</P><P Name="Dst">2#in:1</P></Line>
</System>'''
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("simulink/systems/system_root.xml", xml)
    model = parse_slx(path)
    block = next(item for item in model.blocks.values() if item.name == "A/B")
    assert block.path == "A//B"
    line = next(iter(model.lines))
    assert line.src == "A//B:out1"


def test_beta2_blueprint_rejects_matlab_function_calls_but_allows_arithmetic() -> None:
    from slxdiff.blueprint import blueprint_from_dict

    good = sample_blueprint()
    good["blocks"][1]["parameters"]["Gain"] = "Kp*2 + 0.5"
    assert blueprint_from_dict(good).blocks[1].parameters["Gain"] == "Kp*2 + 0.5"

    for payload in ["system('calc')", "eval('1+1')", "sin(1)", "obj.method"]:
        bad = sample_blueprint()
        bad["blocks"][1]["parameters"]["Gain"] = payload
        with pytest.raises(ValueError):
            blueprint_from_dict(bad)


def test_beta2_recovery_detects_external_disk_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import http.client
    import json
    import os
    import threading
    from urllib.parse import urlparse

    from slxdiff.workbench_server import serve_workbench

    project = tmp_path / "project"
    project.mkdir()
    script = project / "controller.m"
    script.write_text("Kp = 2;\n", encoding="utf-8")
    monkeypatch.setenv("SLX_STUDIO_STATE_DIR", str(tmp_path / "state"))
    server, url = serve_workbench(project, open_browser=False, token="beta2-token")
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        original_mtime = script.stat().st_mtime_ns
        server.state.save_recovery(project, "controller.m", "Kp = 3;\n", disk_mtime_ns=original_mtime)
        script.write_text("Kp = 9;\n", encoding="utf-8")
        os.utime(script, ns=(script.stat().st_atime_ns, original_mtime + 1_000_000_000))

        parsed = urlparse(url)
        body = json.dumps({"path": "controller.m"})
        headers = {"X-SLX-Studio-Token": "beta2-token", "Content-Type": "application/json", "Content-Length": str(len(body.encode()))}
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
        conn.request("POST", "/api/v1/workspace/read", body=body, headers=headers)
        response = conn.getresponse()
        payload = json.loads(response.read())
        conn.close()
        assert response.status == 200
        assert payload["content"] == "Kp = 9;\n"
        assert payload["recovery"]["content"] == "Kp = 3;\n"
        assert payload["recovery"]["disk_conflict"] is True
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_beta2_simulation_reports_disk_change_even_when_simulation_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    from slxdiff.history import ModelHistory
    from slxdiff.patching import PatchDocument, PatchOperation, sha256_file
    from slxdiff.simrunner import SimulationRunManager

    model = tmp_path / "controller.slx"
    make_slx(model, gain="2")
    history = ModelHistory()

    def fake_apply(path, patch, **_kwargs):
        make_slx(Path(path), gain="3")
        raise RuntimeError("simulation failed after model save")

    monkeypatch.setattr("slxdiff.simrunner.apply_patch_with_matlab", fake_apply)
    patch = PatchDocument(
        schema_version="0.1",
        model_name="controller",
        source_sha256=sha256_file(model),
        operations=(PatchOperation("set_param", "Gain", "Gain", "2", "3", "2", "system_root"),),
    )
    manager = SimulationRunManager(matlab="fake", history=history, timeout=10)
    try:
        job = manager.start(model, patch=patch)
        deadline = time.time() + 3
        status = manager.status(job["id"])
        while status["state"] == "running" and time.time() < deadline:
            time.sleep(0.02)
            status = manager.status(job["id"])
        assert status["state"] == "failed"
        assert status["model_changed"] is True
        assert status["history"]["can_undo"] is True
        history.undo(model)
        assert next(block for block in parse_slx(model).blocks.values() if block.name == "Gain").parameters["Gain"] == "2"
    finally:
        manager.stop_all(); history.close()


def test_beta2_installer_does_not_take_over_default_file_associations() -> None:
    text = (Path(__file__).parents[1] / "installer" / "SLXStudio.iss").read_text(encoding="utf-8")
    assert r"Software\Classes\.m\OpenWithProgids" in text
    assert r"Software\Classes\.slx\OpenWithProgids" in text
    assert 'Subkey: "Software\\Classes\\.m"; ValueType: string; ValueName: ""' not in text
    assert 'Subkey: "Software\\Classes\\.slx"; ValueType: string; ValueName: ""' not in text


def test_beta2_agent_parameter_edit_rejects_callbacks_and_code_values(tmp_path: Path) -> None:
    from slxdiff.agent import ToolRuntime

    path = tmp_path / "agent-safe.slx"
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<System>
  <Block BlockType="Gain" Name="Kp" SID="1">
    <P Name="Gain">2</P><P Name="OpenFcn">disp('opened')</P><P Name="Position">[100 100 140 130]</P>
  </Block>
</System>'''
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("simulink/systems/system_root.xml", xml)
    runtime = ToolRuntime(path)
    good = runtime.call("stage_parameter_edit", {"block_path": "Kp", "parameter": "Gain", "after": "Kp0*2 + 0.5"})
    assert good["staged"] is True
    with pytest.raises(ValueError, match="do not allow parameter"):
        runtime.call("stage_parameter_edit", {"block_path": "Kp", "parameter": "OpenFcn", "after": "disp('owned')"})
    with pytest.raises(ValueError, match="not allowed|may not call MATLAB functions"):
        runtime.call("stage_parameter_edit", {"block_path": "Kp", "parameter": "Gain", "after": "system('calc')"})


def test_beta2_simulink_path_helpers_preserve_escaped_slashes_and_rename(tmp_path: Path) -> None:
    from slxdiff.model_edit import build_single_edit, validate_edit_document
    from slxdiff.slx_path import basename, parent_path, relative_to_system, split_path

    path = tmp_path / "slash-rename.slx"
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<System>
  <Block BlockType="Gain" Name="A/B" SID="1"><P Name="Gain">2</P><P Name="Position">[100 100 140 130]</P></Block>
</System>'''
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("simulink/systems/system_root.xml", xml)
    model = parse_slx(path)
    block = next(iter(model.blocks.values()))
    assert block.path == "A//B"
    assert basename(block.path) == "A/B"
    assert parent_path(block.path) == ""
    assert split_path("Controller/A//B") == ["Controller", "A/B"]
    assert parent_path("Controller/A//B") == "Controller"
    assert relative_to_system("Controller/A//B", "Controller") == "A//B"
    document = build_single_edit(model, path, {"op": "rename_block", "block_path": "A//B", "sid": "1", "new_name": "Renamed"})
    validate_edit_document(document, model, source_path=path)


def test_beta2_workbench_uses_one_matlab_execution_gate(tmp_path: Path) -> None:
    from slxdiff.workbench_server import serve_workbench

    project = tmp_path / "project"
    project.mkdir()
    server, _ = serve_workbench(project, open_browser=False, token="gate-token")
    try:
        gate = server.execution_lock
        assert server.run_manager.execution_lock is gate
        assert server.command_session.execution_lock is gate
        assert server.sweep_manager.execution_lock is gate
        assert server.simulation_manager.execution_lock is gate
    finally:
        server.server_close()


def test_beta2_model_edit_failure_is_transactional(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import http.client
    import json
    import threading
    from urllib.parse import urlparse

    from slxdiff.patching import sha256_file
    from slxdiff.workbench_server import serve_workbench

    project = tmp_path / "project"
    project.mkdir()
    model = project / "controller.slx"
    make_slx(model, gain="2")

    def fake_edit(source, _document, *, output_path, **_kwargs):
        # Simulate a bridge that writes the proposed output and then reports failure.
        make_slx(Path(output_path), gain="9")
        raise RuntimeError("MATLAB bridge failed after writing staging file")

    monkeypatch.setattr("slxdiff.workbench_server.apply_model_edit_with_matlab", fake_edit)
    server, url = serve_workbench(project, open_browser=False, token="tx-token")
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        edit = {
            "schema_version": "0.1",
            "model_name": "controller",
            "source_sha256": sha256_file(model),
            "operations": [{"op": "set_param", "block_path": "Gain", "parameter": "Gain", "before": "2", "after": "9", "sid": "2"}],
        }
        body = json.dumps({"path": "controller.slx", "edit": edit})
        parsed = urlparse(url)
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
        conn.request("POST", "/api/v1/workspace/model-edit", body=body, headers={"X-SLX-Studio-Token": "tx-token", "Content-Type": "application/json", "Content-Length": str(len(body.encode()))})
        response = conn.getresponse(); payload = json.loads(response.read()); conn.close()
        assert response.status == 400
        assert "failed after writing" in payload["error"]
        gain = next(block for block in parse_slx(model).blocks.values() if block.name == "Gain")
        assert gain.parameters["Gain"] == "2"
        assert not list(project.glob(".controller.slxstudio-*.slx"))
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_beta2_parser_preserves_canonical_newline_name_path(tmp_path: Path) -> None:
    path = tmp_path / "newline-name.slx"
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<System><Block BlockType="Gain" Name="A&#10;B" SID="1"><P Name="Gain">2</P></Block></System>'''
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("simulink/systems/system_root.xml", xml)
    block = next(iter(parse_slx(path).blocks.values()))
    assert block.name == "A B"
    assert block.path == "A\nB"


def test_beta2_shared_execution_gate_serializes_jobs_and_cancels_queued_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import threading
    import time
    from types import SimpleNamespace

    from slxdiff.mrunner import MatlabRunManager
    from slxdiff.sweep import SweepRunManager

    script = tmp_path / "hold.m"
    script.write_text("pause(1);\n", encoding="utf-8")
    model = tmp_path / "controller.slx"
    make_slx(model, gain="2")
    gate = threading.RLock()
    entered = threading.Event()
    release = threading.Event()
    sweep_called = threading.Event()

    monkeypatch.setattr("slxdiff.mrunner.find_matlab", lambda _matlab=None: SimpleNamespace(available=True, executable="fake", detail="ok"))

    def fake_run_m(*_args, **_kwargs):
        entered.set()
        assert release.wait(2)
        return {"ok": True, "cancelled": False, "stdout": "", "stderr": "", "variables": [], "figures": []}

    def fake_sweep(*_args, **_kwargs):
        sweep_called.set()
        return {"ok": True, "cancelled": False, "runs": []}

    monkeypatch.setattr("slxdiff.mrunner._run_m", fake_run_m)
    monkeypatch.setattr("slxdiff.sweep.validate_sweep", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("slxdiff.sweep.run_parameter_sweep_with_matlab", fake_sweep)

    runner = MatlabRunManager(matlab="fake", execution_lock=gate)
    sweeper = SweepRunManager(matlab="fake", execution_lock=gate)
    first = runner.start(script)
    assert entered.wait(1)
    second = sweeper.start(model, block_path="Gain", parameter="Gain", values="1,2")
    stopped = sweeper.stop(second["id"])
    assert stopped["state"] == "running"  # queued cancellation is asynchronous
    release.set()
    deadline = time.time() + 3
    while time.time() < deadline:
        a = runner.status(first["id"])
        b = sweeper.status(second["id"])
        if a["state"] != "running" and b["state"] != "running":
            break
        time.sleep(0.02)
    assert runner.status(first["id"])["state"] == "finished"
    assert sweeper.status(second["id"])["state"] == "cancelled"
    assert not sweep_called.is_set()


def test_beta2_matlab_runners_use_base_workspace_without_internal_name_collisions(tmp_path: Path) -> None:
    from slxdiff.mrunner import _runner_source
    from slxdiff.msession import _command_runner_source

    runner = _runner_source(
        tmp_path / "script.m",
        tmp_path / "result.json",
        tmp_path / "figures",
        source_path=tmp_path / "script.m",
        workspace_file=tmp_path / "workspace.mat",
    )
    assert "evalin('base', runExpression)" in runner
    assert "assignin('base', name, state.(name))" in runner
    assert "raw = evalin('base', 'whos')" in runner
    # Loading no longer occurs into the wrapper's own workspace, where user names could overwrite internals.
    assert "if ~isempty(workspaceFile) && exist(workspaceFile, 'file'), load(workspaceFile); end" not in runner

    command = "resultPath = 123;\ncommandText = 'user value';\ndisp('你好')"
    command_runner = _command_runner_source(
        tmp_path / "command-result.json",
        tmp_path / "figures",
        tmp_path / "workspace.mat",
        command=command,
        work_dir=tmp_path,
    )
    assert "evalc('evalin(''base'', commandText)')" in command_runner
    assert "assignin('base', name, state.(name))" in command_runner
    assert "native2unicode(uint8([" in command_runner
    # The raw multi-line command is byte-encoded, not interpolated as MATLAB source in the wrapper.
    assert command not in command_runner


def test_beta2_find_matlab_discovers_standard_desktop_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    from slxdiff.matlab_bridge import find_matlab

    executable = tmp_path / "MATLAB" / "R2026a" / "bin" / ("matlab.exe" if os.name == "nt" else "matlab")
    executable.parent.mkdir(parents=True)
    executable.write_text("fake", encoding="utf-8")
    monkeypatch.delenv("SLX_DIFF_MATLAB", raising=False)
    monkeypatch.setattr("slxdiff.matlab_bridge.shutil.which", lambda _name: None)
    monkeypatch.setattr("slxdiff.matlab_bridge._known_matlab_candidates", lambda: [executable])
    status = find_matlab()
    assert status.available is True
    assert Path(status.executable or "").resolve() == executable.resolve()
    assert "standard install location" in status.detail


def test_beta2_transactional_model_edit_saves_original_name_then_rolls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import http.client
    import json
    import threading
    from urllib.parse import urlparse

    from slxdiff.patching import sha256_file
    from slxdiff.workbench_server import serve_workbench

    project = tmp_path / "project"
    project.mkdir()
    model = project / "controller.slx"
    make_slx(model, gain="2")
    observed: dict[str, Path] = {}

    def fake_edit(source, _document, *, output_path, **_kwargs):
        observed["source"] = Path(source)
        observed["output"] = Path(output_path)
        assert Path(output_path).resolve() == model.resolve()
        make_slx(Path(output_path), gain="9")
        raise RuntimeError("save failed after touching original")

    monkeypatch.setattr("slxdiff.workbench_server.apply_model_edit_with_matlab", fake_edit)
    server, url = serve_workbench(project, open_browser=False, token="tx-original-token")
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        edit = {
            "schema_version": "0.1",
            "model_name": "controller",
            "source_sha256": sha256_file(model),
            "operations": [{"op": "set_param", "block_path": "Gain", "parameter": "Gain", "before": "2", "after": "9", "sid": "2"}],
        }
        body = json.dumps({"path": "controller.slx", "edit": edit})
        parsed = urlparse(url)
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
        conn.request("POST", "/api/v1/workspace/model-edit", body=body, headers={"X-SLX-Studio-Token": "tx-original-token", "Content-Type": "application/json", "Content-Length": str(len(body.encode()))})
        response = conn.getresponse(); payload = json.loads(response.read()); conn.close()
        assert response.status == 400
        assert "save failed" in payload["error"]
        assert observed["output"].resolve() == model.resolve()
        gain = next(block for block in parse_slx(model).blocks.values() if block.name == "Gain")
        assert gain.parameters["Gain"] == "2"
        assert not list(project.glob("*.restore-*.tmp"))
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_beta2_simulation_only_patch_endpoint_does_not_persist_matlab_rewrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import http.client
    import json
    import threading
    from urllib.parse import urlparse

    from slxdiff.patching import PatchDocument, sha256_file
    from slxdiff.workbench_server import serve_workbench

    project = tmp_path / "project"
    project.mkdir()
    model = project / "controller.slx"
    make_slx(model, gain="2")
    source_sha = sha256_file(model)

    def fake_apply(source, patch, *, output_path, **_kwargs):
        assert not patch.operations
        assert Path(output_path).resolve() == model.resolve()
        # Mimic save_system rewriting the file even though no edit was requested.
        make_slx(Path(output_path), gain="999")
        return {"ok": True, "message": "simulated", "output_model": str(output_path), "simulation": {"ran": True}}

    monkeypatch.setattr("slxdiff.workbench_server.apply_patch_with_matlab", fake_apply)
    server, url = serve_workbench(project, open_browser=False, token="sim-only-token")
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        patch = PatchDocument(schema_version="0.1", model_name="controller", source_sha256=source_sha, operations=()).to_dict()
        body = json.dumps({"path": "controller.slx", "patch": patch, "simulate": True, "stop_time": "1"})
        parsed = urlparse(url)
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
        conn.request("POST", "/api/v1/workspace/apply-patch", body=body, headers={"X-SLX-Studio-Token": "sim-only-token", "Content-Type": "application/json", "Content-Length": str(len(body.encode()))})
        response = conn.getresponse(); payload = json.loads(response.read()); conn.close()
        assert response.status == 200
        assert payload["history"]["can_undo"] is False
        assert sha256_file(model) == source_sha
        gain = next(block for block in parse_slx(model).blocks.values() if block.name == "Gain")
        assert gain.parameters["Gain"] == "2"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_beta2_simulation_stop_time_is_numeric_only() -> None:
    from slxdiff.matlab_bridge import validate_simulation_stop_time

    assert validate_simulation_stop_time("10") == "10"
    assert validate_simulation_stop_time("1e-3") == "0.001"
    assert validate_simulation_stop_time("0") == "0"
    for value in ["system('calc')", "Tstop", "nan", "inf", "-1"]:
        with pytest.raises(ValueError, match="stop time"):
            validate_simulation_stop_time(value)
