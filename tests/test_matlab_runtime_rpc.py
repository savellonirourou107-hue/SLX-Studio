from __future__ import annotations

import time
from pathlib import Path

from slxdiff import rpc

FAKE_WORKER = r"""#!/usr/bin/env python3
import json, re, sys, time
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
    count += 1
    command = request['command']
    print('runtime-' + str(count), end='', flush=True)
    result = {'ok': command != 'error', 'error': {'message': 'expected'} if command == 'error' else {},
              'variables': [{'name':'count', 'class':'double', 'size':'1x1', 'bytes':8, 'preview': str(count)}], 'figures': []}
    print(request['marker'], end='', flush=True)
    sys.stderr.write(request['marker']); sys.stderr.flush()
    destination = Path(request['result'])
    destination.write_text(json.dumps(result))
"""


def message(method: str, params: dict | None = None, identifier: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": identifier, "method": method, "params": params or {}}


def wait_job(backend: rpc.Backend, kind: str, job_id: str) -> dict:
    method = f"matlab/{kind}/status"
    stdout_offset = stderr_offset = 0
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = backend.dispatch(
            message(
                method, {"job_id": job_id, "stdout_offset": stdout_offset, "stderr_offset": stderr_offset}
            )
        )
        assert "result" in result, result
        status = result["result"]
        stdout_offset, stderr_offset = status["stdout_offset"], status["stderr_offset"]
        if status["state"] != "running":
            return status
        time.sleep(0.02)
    raise AssertionError("MATLAB runtime job did not finish")


def test_desktop_runtime_is_lazy_shared_and_streamable(tmp_path: Path, monkeypatch) -> None:
    fake = tmp_path / "fake-matlab.py"
    fake.write_text(FAKE_WORKER, encoding="utf-8")
    monkeypatch.setenv("SLX_STUDIO_MATLAB", str(fake))
    (tmp_path / "controller.m").write_text("value = 1;", encoding="utf-8")
    backend = rpc.Backend(str(tmp_path))
    try:
        initialized = backend.dispatch(message("initialize"))["result"]
        assert initialized["matlab_started"] is False
        idle = backend.dispatch(message("matlab/status"))["result"]
        assert idle["state"] == "stopped" and idle["available"] is True
        started = backend.dispatch(message("matlab/command/start", {"command": "value = 5;"}))
        assert started["result"]["state"] == "running"
        command = wait_job(backend, "command", started["result"]["id"])
        assert command["state"] == "finished" and command["result"]["variables"][0]["preview"] == "1"
        run = backend.dispatch(message("matlab/run/start", {"relative": "controller.m"}))
        assert run["result"]["state"] == "running"
        completed = wait_job(backend, "run", run["result"]["id"])
        assert completed["state"] == "finished" and completed["result"]["path"].endswith("controller.m")
        assert completed["result"]["session_id"] == command["result"]["session_id"]
        assert (
            backend.dispatch(message("matlab/run/start", {"relative": "../outside.m"}))["error"]["code"]
            == -32602
        )
    finally:
        backend.close()
