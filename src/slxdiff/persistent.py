"""Opt-in, process-owned MATLAB worker; no Engine or third-party dependency.

Commands are serialized, never retried, and evaluated in the same base workspace.
Cancellation deliberately discards the worker, not just the current command.
"""

from __future__ import annotations

import codecs
import json
import locale
import os
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .matlab_bridge import _matlab_command, _matlab_quote, find_matlab
from .mrunner import (
    _TRACEPOINT_SOURCE,
    _instrument_tracepoints,
    _normalize_debug_events,
    _normalize_figures,
    _normalize_variables,
)
from .msession import MatlabCommandSession, _command_helpers_source
from .worker_process import WorkerProcess

_OUTPUT_LIMIT = 1024 * 1024  # characters per stream per job, including callback output


def _worker_source() -> str:
    return r"""function slxstudio_worker(root, workDir)
% Worker bookkeeping lives in function scope, outside user clearvars/assignments.
cd(workDir);
slxstudio_write_json(fullfile(root, 'ready.json'), struct('release', version('-release')));
while ~exist(fullfile(root, 'close'), 'file')
    requestPath = fullfile(root, 'request.json');
    if ~exist(requestPath, 'file'), pause(0.05); continue; end
    request = jsondecode(fileread(requestPath));
    delete(requestPath);
    result = slxstudio_execute_command(request.figures, '', '', request.command);
    fprintf(1, '%s', request.marker);
    fprintf(2, '%s', request.marker);
    slxstudio_write_json(request.result, result);
end
end

function slxstudio_write_json(destination, value)
staging = [destination '.tmp'];
fid = fopen(staging, 'w', 'n', 'UTF-8');
if fid == -1, error('slxstudio:WorkerIO', 'Cannot write worker response'); end
closer = onCleanup(@() fclose(fid));
fprintf(fid, '%s', jsonencode(value));
clear closer;
movefile(staging, destination, 'f');
end
""" + _command_helpers_source()


class PersistentMatlabSession(MatlabCommandSession):
    """Lazy private worker with serialized jobs and deterministic disposal.

    The batch checkpoint is intentionally not loaded or saved. Run/file/section
    clients must use this backend too if they need the same live variables.
    """

    def __init__(self, *, temp_parent: str | Path | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.temp_parent = temp_parent
        self._state_lock = threading.RLock()
        self._output_lock = threading.RLock()
        self._closed = False
        self._process: subprocess.Popen | None = None
        self._temporary: tempfile.TemporaryDirectory | None = None
        self._readers: list[threading.Thread] = []
        self._sink: dict[str, Any] | None = None
        self._generation = 0
        self._session_id: str | None = None

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            alive = self._process is not None and self._process.poll() is None
            return {
                "backend": "persistent",
                "state": "closed" if self._closed else ("ready" if alive else "stopped"),
                "session_id": self._session_id,
                "generation": self._generation,
            }

    def _drain(self, stream, kind: str) -> None:
        # Windows MATLAB writes console bytes in the system code page (e.g.
        # CP936), independently of the JSON file transport, which is UTF-8.
        encoding = (
            getattr(locale, "getencoding", lambda: locale.getpreferredencoding(False))()
            if os.name == "nt"
            else "utf-8"
        )
        decoder = codecs.getincrementaldecoder(encoding)(errors="replace")
        pending = ""
        try:
            while raw := os.read(stream.fileno(), 4096):
                text = pending + decoder.decode(raw)
                pending = ""
                with self._output_lock:
                    sink = self._sink
                    if sink is None or sink["ended"][kind].is_set():
                        continue
                    marker = sink["marker"]
                    if marker in text:
                        text = text.split(marker, 1)[0]
                        sink["ended"][kind].set()
                    else:
                        for n in range(min(len(text), len(marker) - 1), 0, -1):
                            if text.endswith(marker[:n]):
                                pending, text = text[-n:], text[:-n]
                                break
                    remaining = _OUTPUT_LIMIT - len(sink[kind])
                    accepted = text[:remaining]
                    sink[kind] += accepted
                    sink["truncated"] |= len(text) > remaining
                    if accepted and sink["callback"]:
                        sink["callback"](kind, accepted)
        except (OSError, ValueError):
            pass  # close() owns the pipe/process lifecycle
        finally:
            stream.close()

    def _dispose(self) -> None:
        """Called under the execution lock, after current work has stopped."""
        with self._state_lock:
            proc = self._process
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            for reader in self._readers:
                reader.join(timeout=2)
            self._readers = []
            self._process = None
            if self._temporary is not None:
                self._temporary.cleanup()
                self._temporary = None

    def close(self) -> None:
        # Do not wait behind a command before signalling it to stop.
        with self._state_lock:
            self._closed = True
            proc = self._process
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                except OSError:
                    pass
        with self.execution_lock:
            self._dispose()

    def execute(self, command: str, *, on_process=None, on_output=None, cancelled=None) -> dict[str, Any]:
        self._validate_command(command)
        started = time.perf_counter()
        with self.execution_lock:
            if self._closed:
                raise RuntimeError("MATLAB session is closed")
            sink = {
                "stdout": "",
                "stderr": "",
                "truncated": False,
                "callback": on_output,
                "marker": "SLXSTUDIO_END_" + uuid.uuid4().hex,
                "ended": {"stdout": threading.Event(), "stderr": threading.Event()},
            }
            with self._output_lock:
                self._sink = sink
            deadline = time.monotonic() + self.timeout
            launched = False
            was_cancelled = False
            metadata: dict[str, Any] = {}
            failure = ""

            def check() -> None:
                nonlocal was_cancelled
                if self._closed or (cancelled and cancelled()):
                    was_cancelled = True
                    raise RuntimeError("MATLAB session stopped; in-memory state was discarded")
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        f"MATLAB session timed out after {self.timeout:g} seconds; state discarded"
                    )
                if self._process is not None and self._process.poll() is not None:
                    raise RuntimeError(
                        "MATLAB worker exited; in-memory state was discarded. Command was not retried"
                    )

            def wait_for(predicate) -> None:
                while not predicate():
                    check()
                    time.sleep(0.02)
                check()

            try:
                if cancelled and cancelled():
                    # A cancelled queued command must not start or destroy a live worker.
                    was_cancelled = True
                    return self._cancelled_before_start(command, started)
                if self._process is None or self._process.poll() is not None:
                    self._dispose()
                    status = find_matlab(self.matlab)
                    if not status.available or not status.executable:
                        raise RuntimeError(status.detail)
                    with self._state_lock:
                        if self._closed:
                            raise RuntimeError("MATLAB session is closed")
                        self._temporary = tempfile.TemporaryDirectory(
                            prefix="slx-worker-", dir=self.temp_parent
                        )
                        root = Path(self._temporary.name)
                        (root / "slxstudio_worker.m").write_text(_worker_source(), encoding="utf-8")
                        batch = (
                            f"addpath('{_matlab_quote(str(root))}'); "
                            f"slxstudio_worker('{_matlab_quote(str(root))}', "
                            f"'{_matlab_quote(str(self.work_dir))}')"
                        )
                        self._process = WorkerProcess(
                            [*_matlab_command(status.executable), "-batch", batch],
                            cwd=self.work_dir,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                        )
                        self._generation += 1
                        self._session_id = uuid.uuid4().hex
                        launched = True
                        self._readers = [
                            threading.Thread(target=self._drain, args=(stream, kind), daemon=True)
                            for stream, kind in [
                                (self._process.stdout, "stdout"),
                                (self._process.stderr, "stderr"),
                            ]
                        ]
                        for reader in self._readers:
                            reader.start()
                if on_process:
                    on_process(self._process)
                root = Path(self._temporary.name)
                wait_for(lambda: (root / "ready.json").is_file())
                with tempfile.TemporaryDirectory(prefix="job-", dir=root) as job_dir:
                    job_root = Path(job_dir)
                    result_path = job_root / "result.json"
                    request = {
                        "command": command,
                        "result": str(result_path),
                        "figures": str(job_root / "figures"),
                        "marker": sink["marker"],
                    }
                    staging = root / "request.tmp"
                    staging.write_text(json.dumps(request, ensure_ascii=True), encoding="utf-8")
                    check()
                    staging.replace(root / "request.json")
                    try:
                        wait_for(
                            lambda: result_path.is_file() and all(e.is_set() for e in sink["ended"].values())
                        )
                        metadata = json.loads(result_path.read_text(encoding="utf-8"))
                        if not isinstance(metadata, dict):
                            raise RuntimeError("Invalid MATLAB worker response")  # noqa: TRY004
                        metadata["figures"] = _normalize_figures(metadata.get("figures"), job_root)
                    except Exception:
                        # Stop MATLAB before Windows attempts to remove open job files.
                        if self._process.poll() is None:
                            self._process.terminate()
                            self._process.wait(timeout=5)
                        raise
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                failure = str(exc)
                self._dispose()
            finally:
                with self._output_lock:
                    self._sink = None
            error = metadata.get("error") or None
            if failure:
                error = {"message": failure, "identifier": "slxstudio:SessionLost", "line": 0, "file": ""}
            return {
                "ok": bool(metadata.get("ok")) and not failure,
                "cancelled": was_cancelled,
                "command": command,
                "elapsed_seconds": time.perf_counter() - started,
                "stdout": sink["stdout"],
                "stderr": sink["stderr"],
                "output_truncated": sink["truncated"],
                "variables": _normalize_variables(metadata.get("variables")),
                "figures": metadata.get("figures", []),
                "error": error,
                "backend": "persistent",
                "session_id": self._session_id,
                "session_generation": self._generation,
                "session_reset": launched and self._generation > 1,
                "state_lost": bool(failure),
            }

    def _cancelled_before_start(self, command: str, started: float) -> dict[str, Any]:
        return {
            "ok": False,
            "cancelled": True,
            "command": command,
            "stdout": "",
            "stderr": "",
            "variables": [],
            "figures": [],
            "error": None,
            "state_lost": False,
            "backend": "persistent",
            "elapsed_seconds": time.perf_counter() - started,
        }

    def run_file(
        self,
        path: str | Path,
        *,
        code: str | None = None,
        start_line: int = 1,
        tracepoints: list[int] | None = None,
        **callbacks: Any,
    ) -> dict[str, Any]:
        script = Path(path).resolve()
        if not script.is_file() or script.suffix.lower() != ".m":
            raise ValueError("MATLAB runner requires an existing .m file")
        if isinstance(start_line, bool) or not isinstance(start_line, int) or start_line < 1:
            raise ValueError("start_line must be a positive integer")
        if code is not None and not isinstance(code, str):
            raise TypeError("code must be a string")
        if code is not None and len(code.encode("utf-8")) > 4 * 1024 * 1024:
            raise ValueError("MATLAB section is too large")
        with (
            self.execution_lock,
            tempfile.TemporaryDirectory(prefix="slx-script-", dir=self.temp_parent) as tmp,
        ):
            root = Path(tmp)
            executable = script
            trace_path = root / "trace.jsonl"
            if code is not None:
                executable = root / "slxstudio_section.m"
                executable.write_text(code, encoding="utf-8")
            elif tracepoints:
                executable = root / "slxstudio_debug.m"
                (root / "slxstudio_tracepoint.m").write_text(_TRACEPOINT_SOURCE, encoding="utf-8")
                executable.write_text(
                    _instrument_tracepoints(
                        script.read_text(encoding="utf-8"), tracepoints, trace_path, script
                    ),
                    encoding="utf-8",
                )
            # The worker never returns to MATLAB's interactive prompt, where
            # edited files would normally be detected. Include the source
            # folder then refresh its function cache before every explicit Run.
            # Do not clear functions/workspace: that would lose user state.
            command = (
                f"addpath('{_matlab_quote(str(script.parent))}'); rehash; "
                f"run('{_matlab_quote(str(executable))}')"
            )
            result = self.execute(command, **callbacks)
            result["path"] = str(script)
            result["returncode"] = 0 if result["ok"] else 1
            result["debug_events"] = []
            if trace_path.exists():
                result["debug_events"] = _normalize_debug_events(
                    [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
                )
            error = result.get("error")
            if error and error.get("file") == str(executable):
                error["file"] = str(script)
                if code is not None:
                    error["line"] = int(error.get("line") or 0) + start_line - 1
                if code is None and tracepoints:
                    line = int(error.get("line") or 0)
                    for point in sorted(set(tracepoints), reverse=True):
                        if line > point:
                            line -= 1
                    error["line"] = line
            return result
