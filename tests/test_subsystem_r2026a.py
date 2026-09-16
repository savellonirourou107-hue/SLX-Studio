"""Opt-in tests of SLX Studio's own bridge, not mocks or an attached MATLAB session."""

import time
from pathlib import Path

import pytest
from test_matlab_r2026a_integration import _configured_matlab, create_rpc_model
from test_subsystem_edit import document, subsystem_ops

from slxdiff.model_runtime import ModelRuntime
from slxdiff.mrunner import run_m_file
from slxdiff.parser import parse_slx
from slxdiff.patching import sha256_file

pytestmark = pytest.mark.matlab_integration


def test_r2026a_library_subsystem_defaults(tmp_path, monkeypatch):
    matlab = _configured_matlab()
    probe = Path(__file__).parents[1] / "scripts" / "probe_subsystem_defaults.m"
    script = tmp_path / probe.name
    script.write_text(probe.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("SLX_ACCEPTANCE_DIR", str(tmp_path))
    result = run_m_file(script, matlab=matlab, timeout=180)
    assert result["ok"], result
    model = parse_slx(tmp_path / "slxstudio_subsystem_defaults.slx")
    children = {b.path for b in model.blocks.values() if b.path.startswith("Probe/")}
    assert children == {"Probe/In1", "Probe/Out1"}
    assert len(model.lines) == 1


def test_r2026a_subsystem_create_reparse_reload_history_and_conflicts(tmp_path):
    matlab = _configured_matlab()
    path = create_rpc_model(tmp_path, matlab)
    baseline = parse_slx(path)
    original = path.read_bytes()
    runtime = ModelRuntime(tmp_path, matlab=matlab)

    def apply(operations):
        model = parse_slx(path)
        edit = document(path, model, operations)
        job = runtime.start_edit(path.name, edit.to_dict())
        deadline = time.monotonic() + 240
        while job["state"] == "running" and time.monotonic() < deadline:
            time.sleep(0.1)
            job = runtime.status(job["id"])
        assert job["state"] == "finished", job.get("error") or job
        assert job["result"]["ok"], job
        return parse_slx(path)

    try:
        model = apply(subsystem_ops())
        blocks = {b.path: b for b in model.blocks.values()}
        assert set(blocks) == {b.path for b in baseline.blocks.values()} | {
            "Controller",
            "Controller/In1",
            "Controller/Gain",
            "Controller/Out1",
        }
        assert blocks["Controller"].block_type == "SubSystem"
        assert blocks["Controller/Gain"].parameters["Gain"] == "2"
        assert blocks["Controller"].system_id != blocks["Controller/Gain"].system_id
        assert len(model.lines) == len(baseline.lines) + 2
        assert baseline.lines.issubset(model.lines)
        created = path.read_bytes()
        assert runtime.history_action(path.name, "undo")["can_redo"]
        assert path.read_bytes() == original
        assert runtime.history_action(path.name, "redo")["can_undo"]
        assert path.read_bytes() == created

        verify = tmp_path / "reload_subsystem.m"
        verify.write_text(
            """
assert(strcmp(version('-release'), '2026a'));
load_system(fullfile(pwd, 'rpc_model.slx'));
assert(strcmp(get_param('rpc_model/Controller', 'BlockType'), 'SubSystem'));
assert(strcmp(get_param('rpc_model/Controller/Gain', 'Gain'), '2'));
assert(strcmp(get_param('rpc_model/Controller/In1', 'Port'), '1'));
assert(strcmp(get_param('rpc_model/Controller/Out1', 'Port'), '1'));
childPaths = find_system('rpc_model/Controller', 'SearchDepth', 1, 'Type', 'Block');
assert(numel(childPaths) == 4);
lines = find_system('rpc_model/Controller', 'FindAll', 'on', 'SearchDepth', 1, 'Type', 'line');
assert(numel(lines) == 2);
close_system('rpc_model', 0);
""",
            encoding="utf-8",
        )
        result = run_m_file(verify, matlab=matlab, timeout=180)
        assert result["ok"], result

        renamed = apply([{"op": "rename_block", "block_path": "Controller", "new_name": "Regulator"}])
        assert {b.path for b in renamed.blocks.values() if b.path.startswith("Regulator/")} == {
            "Regulator/In1",
            "Regulator/Gain",
            "Regulator/Out1",
        }
        renamed_bytes = path.read_bytes()
        removed = apply([{"op": "delete_block", "block_path": "Regulator"}])
        assert {b.path for b in removed.blocks.values()} == {b.path for b in baseline.blocks.values()}
        assert removed.lines == baseline.lines
        runtime.history_action(path.name, "undo")
        assert path.read_bytes() == renamed_bytes
        runtime.history_action(path.name, "redo")
        stale = document(path, parse_slx(path), subsystem_ops())
        path.write_bytes(path.read_bytes() + b"external fixture edit")
        external_sha = sha256_file(path)
        with pytest.raises(ValueError, match="changed on disk"):
            runtime.start_edit(path.name, stale.to_dict())
        with pytest.raises(ValueError, match="outside"):
            runtime.history_action(path.name, "undo")
        assert sha256_file(path) == external_sha
    finally:
        runtime.close()
