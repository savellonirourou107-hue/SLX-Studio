"""Optional acceptance checks for a licensed MATLAB R2026a installation.

The suite is skipped unless the caller explicitly sets SLX_STUDIO_MATLAB or
SLX_DIFF_MATLAB.  Fake MATLAB executables are deliberately not accepted here;
the normal Python tests cover that protocol separately.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from slxdiff import rpc
from slxdiff.matlab_bridge import find_matlab
from slxdiff.model_edit import build_single_edit
from slxdiff.mrunner import run_m_file
from slxdiff.parser import parse_slx

pytestmark = pytest.mark.matlab_integration


def _configured_matlab() -> str:
    configured = os.environ.get("SLX_STUDIO_MATLAB") or os.environ.get("SLX_DIFF_MATLAB")
    if not configured:
        pytest.skip("set SLX_STUDIO_MATLAB or SLX_DIFF_MATLAB to run MATLAB integration tests")
    status = find_matlab(configured)
    if not status.available or not status.executable:
        pytest.skip(status.detail)
    return status.executable


def test_matlab_r2026a_edit_sim_figure_and_checkpoint(tmp_path: Path) -> None:
    matlab = _configured_matlab()
    script = tmp_path / "r2026a_smoke.m"
    script.write_text(
        """
modelName = 'slxstudio_r2026a_smoke';
release_marker = version('-release');
modelPath = fullfile(pwd, [modelName '.slx']);
if bdIsLoaded(modelName), close_system(modelName, 0); end
new_system(modelName);
set_param(modelName, 'StopTime', '1');
add_block('simulink/Sources/Step', [modelName '/Reference'], 'Position', [30 80 60 110]);
add_block('simulink/Math Operations/Gain', [modelName '/Gain'], 'Gain', '2', 'Position', [110 75 170 115]);
add_block('simulink/Discontinuities/Saturation', [modelName '/Saturation'], 'UpperLimit', '10', 'LowerLimit', '-10', 'Position', [220 75 300 115]);
add_block('simulink/Sinks/Out1', [modelName '/Output'], 'Position', [350 80 380 110]);
add_block('simulink/Sinks/To Workspace', [modelName '/Monitor'], 'VariableName', 'monitor', 'SaveFormat', 'Timeseries', 'Position', [340 170 440 210]);
add_block('simulink/Ports & Subsystems/Subsystem', [modelName '/Nested'], 'Position', [110 180 200 230]);
add_block('simulink/Sources/Constant', [modelName '/Temporary'], 'Value', '0', 'Position', [220 160 270 190]);
delete_block([modelName '/Temporary']);
add_line(modelName, 'Reference/1', 'Gain/1');
add_line(modelName, 'Gain/1', 'Saturation/1');
add_line(modelName, 'Saturation/1', 'Output/1');
add_line(modelName, 'Saturation/1', 'Monitor/1');
delete_line(modelName, 'Gain/1', 'Saturation/1');
add_line(modelName, 'Gain/1', 'Saturation/1');
checkpoint_value = 42;
save_system(modelName, modelPath);
sim(modelName, 'StopTime', '1', 'ReturnWorkspaceOutputs', 'on');
figure('Visible', 'off'); plot([0 1], [0 1]); title('SLX Studio R2026a smoke');
close_system(modelName, 0);
""",
        encoding="utf-8",
    )
    result = run_m_file(script, matlab=matlab, workspace_file=tmp_path / "workspace.mat", timeout=300)
    assert result["ok"], result
    release_items = [item for item in result["variables"] if item["name"] == "release_marker"]
    assert release_items and "2026a" in release_items[0]["preview"].lower(), result
    assert any(item["name"] == "checkpoint_value" for item in result["variables"])
    assert result["figures"], result
    assert (tmp_path / "slxstudio_r2026a_smoke.slx").exists()


def test_matlab_r2026a_command_stream_and_cancel(tmp_path: Path) -> None:
    matlab = _configured_matlab()
    from slxdiff.msession import MatlabCommandManager, MatlabCommandSession

    session = MatlabCommandSession(
        work_dir=tmp_path,
        workspace_file=tmp_path / "workspace.mat",
        matlab=matlab,
        timeout=60,
    )
    manager = MatlabCommandManager(session)
    job = manager.start("fprintf(1, 'stream-one\\n'); pause(0.4); fprintf(1, 'stream-two\\n'); value = 42;")
    output = ""
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        status = manager.status(job["id"], stdout_offset=len(output))
        output += status["stdout_delta"]
        if status["state"] != "running":
            break
        time.sleep(0.05)
    final = manager.status(job["id"], stdout_offset=len(output))
    output += final["stdout_delta"]
    assert final["state"] == "finished", final
    assert final["result"]["ok"] is True, final
    assert "stream-one" in output
    assert "stream-two" in output
    assert any(item["name"] == "value" and item["preview"] == "42" for item in final["result"]["variables"])

    cancel_job = manager.start("pause(30);")
    time.sleep(0.5)
    manager.stop(cancel_job["id"])
    deadline = time.monotonic() + 30
    cancelled = manager.status(cancel_job["id"])
    while cancelled["state"] == "running" and time.monotonic() < deadline:
        time.sleep(0.05)
        cancelled = manager.status(cancel_job["id"])
    assert cancelled["state"] == "cancelled", cancelled
    assert cancelled["result"]["cancelled"] is True, cancelled


def test_matlab_r2026a_debug_tracepoints_capture_line_and_workspace(tmp_path: Path) -> None:
    matlab = _configured_matlab()
    script = tmp_path / "tracepoints.m"
    script.write_text("a = 1;\na = a + 1;\nfprintf(1, 'trace\\n');\n", encoding="utf-8")
    from slxdiff.mrunner import run_m_file

    result = run_m_file(
        script,
        matlab=matlab,
        workspace_file=tmp_path / "workspace.mat",
        tracepoints=[2, 3],
        timeout=60,
    )
    assert result["ok"], result
    assert [event["line"] for event in result["debug_events"]] == [2, 3], result
    assert all("a" in event["variables"] for event in result["debug_events"])


def test_matlab_r2026a_desktop_rpc_applies_validated_model_edit(tmp_path: Path, monkeypatch) -> None:
    matlab = _configured_matlab()
    monkeypatch.setenv("SLX_STUDIO_MATLAB", matlab)
    script = tmp_path / "make_rpc_model.m"
    script.write_text(
        """
modelName = 'rpc_model';
modelPath = fullfile(pwd, [modelName '.slx']);
if bdIsLoaded(modelName), close_system(modelName, 0); end
new_system(modelName);
add_block('simulink/Sources/Constant', [modelName '/Input'], 'Value', '1', 'Position', [30 80 60 110]);
add_block('simulink/Math Operations/Gain', [modelName '/Gain'], 'Gain', '2', 'Position', [110 80 170 110]);
add_block('simulink/Sinks/Out1', [modelName '/Output'], 'Position', [220 80 250 110]);
add_line(modelName, 'Input/1', 'Gain/1'); add_line(modelName, 'Gain/1', 'Output/1');
save_system(modelName, modelPath); close_system(modelName, 0);
""",
        encoding="utf-8",
    )
    created = run_m_file(script, matlab=matlab, timeout=120)
    assert created["ok"], created
    model_path = tmp_path / "rpc_model.slx"
    model = parse_slx(model_path)
    gain = next(block for block in model.blocks.values() if block.name == "Gain")
    edit = build_single_edit(
        model,
        model_path,
        {
            "op": "set_param",
            "block_path": gain.path,
            "parameter": "Gain",
            "before": gain.parameters["Gain"],
            "after": "3",
            "sid": gain.sid,
        },
    )
    backend = rpc.Backend(str(tmp_path))
    try:
        response = backend.dispatch(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "model/applyEdit",
                "params": {"relative": "rpc_model.slx", "edit": edit.to_dict()},
            }
        )
        assert response.get("result", {}).get("ok") is True, response
    finally:
        backend.close()
    changed = parse_slx(model_path)
    assert changed.blocks[(gain.system_id, gain.sid)].parameters["Gain"] == "3"
