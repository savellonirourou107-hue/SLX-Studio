"""Optional acceptance checks for a licensed MATLAB R2026a installation.

The suite is skipped unless the caller explicitly sets SLX_STUDIO_MATLAB or
SLX_DIFF_MATLAB.  Fake MATLAB executables are deliberately not accepted here;
the normal Python tests cover that protocol separately.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from slxdiff.matlab_bridge import find_matlab
from slxdiff.mrunner import run_m_file

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
