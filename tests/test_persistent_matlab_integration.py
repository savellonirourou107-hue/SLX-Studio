"""Opt-in transport acceptance against a real installed MATLAB, not a mock."""

import http.client
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from slxdiff.msession import MatlabCommandManager
from slxdiff.persistent import PersistentMatlabSession
from slxdiff.workbench_server import serve_workbench

pytestmark = pytest.mark.matlab_integration


@pytest.fixture
def session(tmp_path):
    matlab = os.environ.get("SLX_STUDIO_MATLAB") or os.environ.get("SLX_DIFF_MATLAB")
    if not matlab:
        pytest.skip("configure SLX_STUDIO_MATLAB for real worker acceptance")
    backend = PersistentMatlabSession(
        work_dir=tmp_path,
        workspace_file=tmp_path / "workspace.mat",
        matlab=matlab,
        temp_parent=tmp_path,
        timeout=120,
    )
    try:
        yield backend
    finally:
        backend.close()
    assert backend.status()["state"] == "closed"
    assert not list(tmp_path.glob("slx-worker-*"))
    if os.name == "nt":
        # The launcher's return code alone does not prove that MATLAB exited.
        completed = subprocess.run(
            [
                shutil.which("pwsh") or "powershell",
                "-NoProfile",
                "-Command",
                (
                    "@(Get-CimInstance Win32_Process -Filter \"Name = 'MATLAB.exe'\" | "
                    "Select-Object ProcessId,CommandLine) | ConvertTo-Json -Compress"
                ),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        rows = json.loads(completed.stdout or "[]")
        rows = rows if isinstance(rows, list) else [rows]
        assert not [
            row for row in rows if str(tmp_path).casefold() in str(row.get("CommandLine", "")).casefold()
        ], rows


def test_live_workspace_survives_commands_files_errors_and_clear(session, tmp_path):
    processes = []
    first = session.execute("Kp = 2; disp(version('-release'));", on_process=processes.append)
    assert first["ok"], first
    assert "2026a" in first["stdout"], first
    # Function persistent variables cannot be carried by the batch MAT checkpoint.
    (tmp_path / "slx_counter.m").write_text(
        "function value = slx_counter()\npersistent count;\n"
        "if isempty(count), count = 0; end\ncount = count + 1;\nvalue = count;\nend\n",
        encoding="utf-8",
    )
    setup = session.execute("counter = slx_counter(); load_system('simulink');")
    assert setup["ok"], setup
    script = tmp_path / "controller.m"
    script.write_text("Kp = Kp + 1;\nfile_counter = slx_counter();\n", encoding="utf-8")
    result = session.run_file(script, on_process=processes.append)
    assert result["ok"], result
    assert any(v["name"] == "file_counter" and v["preview"] == "2" for v in result["variables"])
    script.write_text("saved_version = 17;\nfile_counter = slx_counter();\n", encoding="utf-8")
    updated = session.run_file(script)
    assert updated["ok"] and any(
        v["name"] == "saved_version" and v["preview"] == "17" for v in updated["variables"]
    ), updated
    assert any(v["name"] == "file_counter" and v["preview"] == "3" for v in updated["variables"])
    (tmp_path / "section_helper.m").write_text(
        "function x = section_helper(x)\nx = x * 2;\nend\n", encoding="utf-8"
    )
    section = session.run_file(
        script, code="section_value = section_helper(Kp); section_counter = slx_counter();", start_line=8
    )
    assert section["ok"], section
    assert any(v["name"] == "section_counter" and v["preview"] == "4" for v in section["variables"])
    bad = session.run_file(script, code="error('slxstudio:Expected', 'test failure');", start_line=8)
    assert not bad["ok"] and not bad["state_lost"], bad
    assert bad["error"]["line"] == 8 and Path(bad["error"]["file"]) == script, bad
    last = session.execute(
        "assert(bdIsLoaded('simulink')); assert(section_value == 6); fprintf('你好');",
        on_process=processes.append,
    )
    assert last["ok"], last
    assert last["session_id"] == first["session_id"]
    assert len({p.pid for p in processes}) == 1
    assert not (tmp_path / "workspace.mat").exists()
    assert "你好" in last["stdout"], last
    cleared = session.execute("clearvars; fresh = 9;")
    assert cleared["ok"], cleared
    assert [v["name"] for v in cleared["variables"]] == ["fresh"]
    print(f"cold={first['elapsed_seconds']:.3f}s warm={last['elapsed_seconds']:.3f}s pid={processes[0].pid}")


def test_stream_without_newline_cancel_restart_and_no_replay(session, tmp_path):
    assert session.execute("sentinel = 42;")["ok"]
    old_id = session.status()["session_id"]
    seen = threading.Event()
    cancelled = threading.Event()
    results = []

    def output(kind, text):
        if "ready-to-stop" in text:
            seen.set()

    worker = threading.Thread(
        target=lambda: results.append(
            session.execute(
                "fprintf('ready-to-stop'); pause(30);", on_output=output, cancelled=cancelled.is_set
            )
        )
    )
    worker.start()
    try:
        assert seen.wait(20), "expected output before command completion, without newline"
    finally:
        cancelled.set()
        worker.join(15)
    assert not worker.is_alive()
    assert results[0]["cancelled"] and results[0]["state_lost"], results
    restarted = session.execute("assert(~exist('sentinel', 'var')); fresh = 1;")
    assert restarted["ok"] and restarted["session_reset"], restarted
    assert restarted["session_id"] != old_id
    crashed = session.execute("exit;")
    assert not crashed["ok"] and crashed["state_lost"], crashed
    assert session.execute("after_exit = 2;")["ok"]


def test_tracepoints_and_timeout_discard_worker(session, tmp_path):
    script = tmp_path / "trace.m"
    script.write_text("a = 1;\na = a + 1;\ndisp(a);\n", encoding="utf-8")
    result = session.run_file(script, tracepoints=[2, 3])
    assert result["ok"], result
    assert [e["line"] for e in result["debug_events"]] == [2, 3], result
    session.timeout = 0.3
    result = session.execute("pause(5);")
    assert not result["ok"] and result["state_lost"], result
    assert "timed out" in result["error"]["message"]
    assert session.status()["state"] == "stopped"


def test_manager_stop_and_server_close_own_their_worker(session):
    processes = []
    assert session.execute("initial = 1;", on_process=processes.append)["ok"]
    manager = MatlabCommandManager(session)
    job = manager.start("pause(30);")
    time.sleep(0.2)
    manager.stop(job["id"])
    deadline = time.monotonic() + 15
    while manager.status(job["id"])["state"] == "running" and time.monotonic() < deadline:
        time.sleep(0.05)
    result = manager.status(job["id"])
    assert result["state"] == "cancelled", result
    assert processes[0].poll() is not None


def test_real_workbench_command_variable_and_async_file_share_session(tmp_path, monkeypatch):
    matlab = os.environ.get("SLX_STUDIO_MATLAB") or os.environ.get("SLX_DIFF_MATLAB")
    if not matlab:
        pytest.skip("configure SLX_STUDIO_MATLAB for real HTTP acceptance")
    monkeypatch.setenv("SLX_STUDIO_STATE_DIR", str(tmp_path / "state"))
    (tmp_path / "controller.m").write_text("file_value = Kp * 2;", encoding="utf-8")
    server, _ = serve_workbench(
        tmp_path, matlab=matlab, matlab_session="persistent", open_browser=False, token="real-test"
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection(*server.server_address, timeout=120)
    headers = {"Content-Type": "application/json", "X-SLX-Studio-Token": "real-test"}

    def post(endpoint, body):
        connection.request("POST", "/api/v1/workspace/" + endpoint, json.dumps(body), headers)
        response = connection.getresponse()
        data = json.loads(response.read())
        assert response.status in (200, 202), data
        return data

    def finish(kind, job):
        deadline = time.monotonic() + 120
        while job["state"] == "running" and time.monotonic() < deadline:
            time.sleep(0.05)
            job = post(kind + "/status", {"job_id": job["id"]})["job"]
        assert job["state"] == "finished", job
        assert job["result"]["ok"], job
        return job["result"]

    try:
        command = finish("command", post("command/start", {"code": "Kp = 2;"})["job"])
        edited = post("variables/set", {"name": "Kp", "expression": "Kp + 1"})["run"]
        run = finish("run", post("run/start", {"path": "controller.m"})["job"])
        assert command["session_id"] == edited["session_id"] == run["session_id"]
        assert any(v["name"] == "file_value" and v["preview"] == "6" for v in run["variables"]), run
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(3)
    assert server.command_session.status()["state"] == "closed"
