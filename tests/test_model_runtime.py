"""Pure transaction tests use a fake MATLAB edit, never claim simulation coverage."""

import threading
import time

import pytest
from test_slxdiff import make_slx

from slxdiff.model_edit import build_single_edit
from slxdiff.model_runtime import ModelRuntime
from slxdiff.parser import parse_slx
from slxdiff.patching import sha256_file


def edit(path):
    model = parse_slx(path)
    gain = next(block for block in model.blocks.values() if block.name == "Gain")
    return build_single_edit(
        model,
        path,
        {
            "op": "set_param",
            "block_path": gain.path,
            "sid": gain.sid,
            "parameter": "Gain",
            "before": gain.parameters["Gain"],
            "after": "3",
        },
    ).to_dict()


def finish(runtime, job):
    deadline = time.monotonic() + 5
    while job["state"] == "running" and time.monotonic() < deadline:
        time.sleep(0.01)
        job = runtime.status(job["id"])
    assert job["state"] != "running", job
    return job


def test_edit_is_async_staged_hash_guarded_and_history_is_reversible(tmp_path, monkeypatch):
    path = tmp_path / "model.slx"
    make_slx(path)
    original = path.read_bytes()
    ready, release = threading.Event(), threading.Event()

    def matlab(source, document, *, output_path, **kwargs):
        assert source != path and output_path != path
        assert source.read_bytes() == original
        ready.set()
        assert release.wait(5)
        make_slx(output_path, gain="3")
        return {"ok": True}

    monkeypatch.setattr("slxdiff.model_runtime.apply_model_edit_with_matlab", matlab)
    runtime = ModelRuntime(tmp_path)
    try:
        job = runtime.start_edit("model.slx", edit(path))
        assert ready.wait(2) and job["state"] == "running"
        assert path.read_bytes() == original
        with pytest.raises(RuntimeError, match="another"):
            runtime.start_edit("model.slx", edit(path))
        release.set()
        job = finish(runtime, job)
        assert job["state"] == "finished", job
        changed = path.read_bytes()
        assert changed != original
        assert runtime.history_action("model.slx", "undo")["can_redo"]
        assert path.read_bytes() == original
        assert runtime.history_action("model.slx", "redo")["can_undo"]
        assert path.read_bytes() == changed
        make_slx(path, gain="5")
        with pytest.raises(ValueError, match="outside"):
            runtime.history_action("model.slx", "undo")
    finally:
        release.set()
        runtime.close()


@pytest.mark.parametrize("failure", ["cancel", "external", "matlab", "history"])
def test_failed_or_cancelled_transaction_preserves_original_or_external_edit(tmp_path, monkeypatch, failure):
    path = tmp_path / "model.slx"
    make_slx(path)
    original = path.read_bytes()
    ready, release = threading.Event(), threading.Event()

    def matlab(source, document, *, output_path, **kwargs):
        ready.set()
        assert release.wait(5)
        make_slx(output_path, gain="3")
        if failure == "matlab":
            raise RuntimeError("expected MATLAB failure")
        return {"ok": True}

    monkeypatch.setattr("slxdiff.model_runtime.apply_model_edit_with_matlab", matlab)
    runtime = ModelRuntime(tmp_path)
    try:
        if failure == "history":
            monkeypatch.setattr(
                runtime.history, "record", lambda *args: (_ for _ in ()).throw(OSError("disk full"))
            )
        job = runtime.start_edit("model.slx", edit(path))
        assert ready.wait(2)
        if failure == "cancel":
            runtime.stop(job["id"])
        if failure == "external":
            make_slx(path, gain="9")
            original = path.read_bytes()
        release.set()
        status = finish(runtime, job)
        assert status["state"] == ("cancelled" if failure == "cancel" else "failed"), status
        assert path.read_bytes() == original
        assert not runtime.history_action("model.slx")["can_undo"]
        assert not list(tmp_path.glob("*.tmp"))
    finally:
        release.set()
        runtime.close()


def test_simulation_is_read_only_and_retains_input_provenance(tmp_path, monkeypatch):
    path = tmp_path / "model.slx"
    make_slx(path)
    original = path.read_bytes()
    version = sha256_file(path)

    def simulate(source, patch, *, output_path, simulate, stop_time, **kwargs):
        assert source != path and output_path != path and simulate
        assert not patch.operations and patch.source_sha256 == version
        make_slx(output_path, gain="99")
        return {"ok": True, "simulation": {"ran": True, "stop_time": stop_time, "series": []}}

    monkeypatch.setattr("slxdiff.model_runtime.apply_patch_with_matlab", simulate)
    runtime = ModelRuntime(tmp_path)
    try:
        result = finish(runtime, runtime.start_simulation("model.slx", version, "2"))
        assert result["state"] == "finished", result
        assert result["source_sha256"] == version and result["backend"] == "matlab_batch"
        assert result["result"]["simulation"]["stop_time"] == "2"
        assert path.read_bytes() == original
        with pytest.raises(ValueError):
            runtime.start_simulation("model.slx", "0" * 64)
        with pytest.raises(ValueError):
            runtime.start_simulation("../model.slx", version)
    finally:
        runtime.close()
