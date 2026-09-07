"""Fast protocol tests use a Python worker double, never claim MATLAB semantics."""

import concurrent.futures
import http.client
import json
import threading

import pytest

from slxdiff.persistent import PersistentMatlabSession
from slxdiff.workbench_server import serve_workbench

FAKE_WORKER = r"""#!/usr/bin/env python3
import json, os, re, sys, time
from pathlib import Path
root = Path(re.search(r"slxstudio_worker\('((?:[^']|'')*)'", sys.argv[-1])[1].replace("''", "'"))
(root / 'ready.json').write_text('{}')
count = 0
while True:
    request_path = root / 'request.json'
    if not request_path.exists():
        time.sleep(.005)
        continue
    request = json.loads(request_path.read_text())
    request_path.unlink()
    command = request['command']
    count += 1
    if command == 'crash':
        with open('effects.txt', 'a') as f: f.write('once\n')
        sys.exit(1)
    if command == 'slow':
        sys.stdout.write('started')
        sys.stdout.flush()
        time.sleep(10)
    elif command == 'flood':
        sys.stdout.write('x' * (2 * 1024 * 1024))
    else:
        sys.stdout.write('hello ' + str(count))
    sys.stdout.write(request['marker']); sys.stdout.flush()
    sys.stderr.write(request['marker']); sys.stderr.flush()
    result = {'ok': command != 'error', 'error': {'message': 'expected'} if command == 'error' else {},
              'variables': [{'name':'count', 'class':'double', 'size':'1x1', 'preview': str(count)}], 'figures': []}
    dest = Path(request['result'])
    staging = dest.with_suffix('.tmp')
    staging.write_text(json.dumps(result))
    os.replace(staging, dest)
"""


@pytest.fixture
def fake(tmp_path):
    worker = tmp_path / "fake-worker.py"
    worker.write_text(FAKE_WORKER, encoding="utf-8")
    worker.chmod(0o755)
    return worker


@pytest.fixture
def session(tmp_path, fake):
    backend = PersistentMatlabSession(
        work_dir=tmp_path,
        workspace_file=tmp_path / "workspace.mat",
        matlab=fake,
        temp_parent=tmp_path,
        timeout=5,
    )
    yield backend
    backend.close()
    assert not list(tmp_path.glob("slx-worker-*"))


def test_reuses_worker_serializes_jobs_and_keeps_error_recoverable(session):
    processes = []
    first = session.execute("hello", on_process=processes.append)
    assert first["ok"], first
    assert not session.execute("error")["ok"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: session.execute("hello", on_process=processes.append), range(4)))
    assert all(r["ok"] and r["session_id"] == first["session_id"] for r in results)
    assert len({p.pid for p in processes}) == 1
    assert sorted(int(r["variables"][0]["preview"]) for r in results) == [3, 4, 5, 6]
    assert all("SLXSTUDIO_END_" not in r["stdout"] for r in results)


def test_crash_is_not_replayed_and_restart_is_explicit(session, tmp_path):
    crashed = session.execute("crash")
    assert not crashed["ok"] and crashed["state_lost"]
    assert (tmp_path / "effects.txt").read_text().splitlines() == ["once"]
    restarted = session.execute("hello")
    assert restarted["ok"] and restarted["session_reset"]
    assert restarted["session_id"] != crashed["session_id"]


def test_timeout_and_close_reap_the_owned_process(session):
    processes = []
    assert session.execute("hello", on_process=processes.append)["ok"]
    session.timeout = 0.15
    result = session.execute("slow")
    assert not result["ok"] and result["state_lost"]
    assert processes[0].poll() is not None
    session.close()
    session.close()
    with pytest.raises(RuntimeError, match="closed"):
        session.execute("hello")


def test_close_interrupts_active_job_and_output_streams_without_newline(session):
    seen = threading.Event()
    processes = []
    results = []
    worker = threading.Thread(
        target=lambda: results.append(
            session.execute("slow", on_process=processes.append, on_output=lambda *_: seen.set())
        )
    )
    worker.start()
    try:
        assert seen.wait(3)
        session.close()
    finally:
        worker.join(8)
    assert not worker.is_alive()
    assert processes[0].poll() is not None
    assert results[0]["cancelled"] and results[0]["state_lost"]


def test_precancelled_queued_job_does_not_discard_live_worker(session):
    first = session.execute("hello")
    result = session.execute("slow", cancelled=lambda: True)
    assert result["cancelled"] and not result["state_lost"]
    assert session.execute("hello")["session_id"] == first["session_id"]


def test_worker_output_is_bounded_even_when_streaming(session):
    output = []
    result = session.execute("flood", on_output=lambda kind, text: output.append(text))
    assert result["ok"] and result["output_truncated"], result
    assert len(result["stdout"]) == 1024 * 1024
    assert len("".join(output)) == 1024 * 1024


def test_persistent_http_mode_auth_and_run_routing(tmp_path, fake, monkeypatch):
    monkeypatch.setenv("SLX_STUDIO_STATE_DIR", str(tmp_path / "state"))
    (tmp_path / "test.m").write_text("a = 1;", encoding="utf-8")
    server, _ = serve_workbench(
        tmp_path, matlab=str(fake), matlab_session="persistent", open_browser=False, token="test-token"
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    conn = http.client.HTTPConnection(*server.server_address)
    headers = {"X-SLX-Studio-Token": "test-token", "Content-Type": "application/json"}
    try:
        conn.request("GET", "/api/v1/workspace/session")
        response = conn.getresponse()
        assert response.status == 403
        response.read()
        conn.request("GET", "/api/v1/workspace/session", headers=headers)
        response = conn.getresponse()
        assert json.loads(response.read())["state"] == "stopped"  # lazy startup
        conn.request("POST", "/api/v1/workspace/run-m", json.dumps({"path": "test.m"}), headers)
        response = conn.getresponse()
        run = json.loads(response.read())["run"]
        assert run["ok"] and run["backend"] == "persistent", run
        assert server.run_manager.run_executor is not None
        assert server.command_session.execute("hello")["session_id"] == run["session_id"]
    finally:
        conn.close()
        server.shutdown()
        server.server_close()
        thread.join(3)


def test_invalid_mode_and_section_arguments_do_not_start_matlab(tmp_path, session):
    with pytest.raises(ValueError, match="matlab_session"):
        serve_workbench(tmp_path, matlab_session="invalid", open_browser=False)
    (tmp_path / "test.m").touch()
    with pytest.raises(ValueError, match="start_line"):
        session.run_file(tmp_path / "test.m", code="1", start_line=-1)
    assert session.status()["state"] == "stopped"
