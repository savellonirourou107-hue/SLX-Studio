"""Desktop-facing MATLAB runtime built on the existing persistent worker.

The RPC layer deliberately exposes only explicit start/status/stop operations.
Inspecting or opening an SLX never starts a worker, so static model viewing
remains safe and fast.  Command and script jobs share one worker and execution
lock, which keeps variables, figures and diagnostics in the same session.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
from pathlib import Path
from typing import Any

from .documents import document_path
from .matlab_bridge import find_matlab
from .mrunner import MatlabRunManager
from .msession import MatlabCommandManager
from .persistent import PersistentMatlabSession

_MAX_TRACEPOINTS = 256
_RESULT_PAGE_SIZE = 128
_STREAM_PAGE_CHARS = 65_536


class MatlabRuntime:
    """Lazy, project-scoped MATLAB runtime for the Electron backend."""

    def __init__(
        self, root: Path, *, state_dir: str | Path | None = None, matlab: str | Path | None = None
    ) -> None:
        self.root = root.resolve()
        self.matlab = matlab or os.environ.get("SLX_STUDIO_MATLAB") or os.environ.get("SLX_DIFF_MATLAB")
        configured = Path(
            state_dir or os.environ.get("SLX_STUDIO_STATE_DIR") or (self.root / ".slx-studio-state")
        )
        # Avoid sharing a persisted worker checkpoint between projects when the
        # desktop state directory is global.
        project_key = hashlib.sha256(str(self.root).encode("utf-8")).hexdigest()[:20]
        self.state_dir = configured.resolve() / "matlab" / project_key
        self._lock = threading.RLock()
        self._session: PersistentMatlabSession | None = None
        self._commands: MatlabCommandManager | None = None
        self._runs: MatlabRunManager | None = None

    def _ensure(self) -> tuple[PersistentMatlabSession, MatlabCommandManager, MatlabRunManager]:
        with self._lock:
            if self._session is None:
                self.state_dir.mkdir(parents=True, exist_ok=True)
                session = PersistentMatlabSession(
                    work_dir=self.root,
                    workspace_file=self.state_dir / "workspace.mat",
                    matlab=self.matlab,
                    temp_parent=self.state_dir,
                    timeout=300.0,
                )
                self._session = session
                self._commands = MatlabCommandManager(session)
                self._runs = MatlabRunManager(
                    matlab=self.matlab,
                    timeout=300.0,
                    execution_lock=session.execution_lock,
                    run_executor=session.run_file,
                )
            assert self._commands is not None and self._runs is not None
            return self._session, self._commands, self._runs

    def status(self) -> dict[str, Any]:
        # find_matlab is a read-only executable check and does not launch MATLAB.
        available = find_matlab(self.matlab)
        with self._lock:
            session_status = (
                self._session.status()
                if self._session is not None
                else {"backend": "persistent", "state": "stopped", "session_id": None, "generation": 0}
            )
            command = self._commands
            run = self._runs
            command_id = (
                next((item["id"] for item in command._jobs.values() if item.get("state") == "running"), None)
                if command
                else None
            )
            run_id = (
                next((item["id"] for item in run._jobs.values() if item.get("state") == "running"), None)
                if run
                else None
            )
        return {
            **session_status,
            "available": bool(available.available),
            "detail": available.detail,
            "executable": str(available.executable) if available.executable else None,
            "active": {"command": command_id, "run": run_id},
        }

    def _busy(self) -> bool:
        command = self._commands
        run = self._runs
        return bool(
            command and any(item.get("state") == "running" for item in command._jobs.values())
        ) or bool(run and any(item.get("state") == "running" for item in run._jobs.values()))

    def start_command(self, command: str) -> dict[str, Any]:
        session, commands, _ = self._ensure()
        session._validate_command(command)
        with self._lock:
            if self._busy():
                raise RuntimeError("a MATLAB command or script is already active")
            started = commands.start(command)
            return self.status_job("command", started["id"])

    def start_variable(self, name: str, expression: str) -> dict[str, Any]:
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,62}", name):
            raise ValueError("variable name must be a MATLAB identifier")
        if (
            not isinstance(expression, str)
            or not expression.strip()
            or "\n" in expression
            or "\r" in expression
        ):
            raise ValueError("variable editor accepts one non-empty MATLAB expression")
        return self.start_command(f"{name} = {expression};")

    def start_run(
        self,
        relative: str,
        *,
        code: str | None = None,
        start_line: int = 1,
        tracepoints: list[int] | None = None,
    ) -> dict[str, Any]:
        path = document_path(self.root, relative)
        if path.suffix.lower() != ".m":
            raise ValueError("MATLAB runtime can run only .m files")
        if code is not None and not isinstance(code, str):
            raise TypeError("MATLAB section code must be text")
        if (
            isinstance(start_line, bool)
            or not isinstance(start_line, int)
            or start_line < 1
            or start_line > 1_000_000
        ):
            raise ValueError("start_line must be a positive bounded integer")
        if tracepoints is None:
            points: list[int] = []
        elif not isinstance(tracepoints, list) or len(tracepoints) > _MAX_TRACEPOINTS:
            raise ValueError("tracepoints must be a bounded list")
        else:
            points = []
            for point in tracepoints:
                if isinstance(point, bool) or not isinstance(point, int) or point < 1 or point > 1_000_000:
                    raise ValueError("tracepoint must be a positive bounded integer")
                points.append(point)
        self._ensure()
        with self._lock:
            if self._busy():
                raise RuntimeError("a MATLAB command or script is already active")
            assert self._runs is not None
            started = self._runs.start(path, code=code, start_line=start_line, tracepoints=points)
            return self.status_job("run", started["id"])

    def _result_page(
        self,
        result: dict[str, Any],
        *,
        variable_cursor: int = 0,
        figure_cursor: int = 0,
        event_cursor: int = 0,
    ) -> dict[str, Any]:
        for cursor in (variable_cursor, figure_cursor, event_cursor):
            if isinstance(cursor, bool) or not isinstance(cursor, int) or not 0 <= cursor <= 1_000_000:
                raise ValueError("result cursor must be a bounded non-negative integer")
        # Output is delivered only as deltas. Never repeat up to two MiB of
        # console text or six large figures in every job status response.
        page = {
            key: value
            for key, value in result.items()
            if key
            in {
                "ok",
                "cancelled",
                "elapsed_seconds",
                "backend",
                "session_id",
                "session_generation",
                "session_reset",
                "state_lost",
                "output_truncated",
                "returncode",
            }
        }
        for key in ("path", "command"):
            if key in result:
                page[key] = str(result[key])[:262_144]
        if isinstance(result.get("error"), dict):
            error = result["error"]
            filename = str(error.get("file") or "")
            if filename:
                try:
                    filename = Path(filename).resolve().relative_to(self.root).as_posix()
                except ValueError:
                    filename = ""  # external errors are visible, but not an arbitrary file-open capability
            page["error"] = {
                "message": str(error.get("message") or "")[:8192],
                "identifier": str(error.get("identifier") or "")[:256],
                "file": filename,
                "line": error.get("line", 0),
            }
        for name, cursor, size in (
            ("variables", variable_cursor, _RESULT_PAGE_SIZE),
            ("figures", figure_cursor, 1),
            ("debug_events", event_cursor, _RESULT_PAGE_SIZE),
        ):
            items = result.get(name) if isinstance(result.get(name), list) else []
            page[name] = items[cursor : cursor + size]
            page[f"total_{name}"] = len(items)
            page[f"{name}_cursor"] = cursor
            page[f"next_{name}_cursor"] = cursor + size if cursor + size < len(items) else None
        page["variables"] = [
            {
                key: (str(item.get(key, ""))[:512] if key != "bytes" else item.get(key, 0))
                for key in ("name", "class", "size", "bytes", "preview")
            }
            for item in page["variables"]
            if isinstance(item, dict)
        ]
        page["debug_events"] = [
            {
                "file": str(item.get("file") or "")[:4096],
                "line": item.get("line", 0),
                "variables": [str(name)[:128] for name in item.get("variables", [])[:128]],
                "total_variables": len(item.get("variables", [])),
            }
            for item in page["debug_events"]
            if isinstance(item, dict)
        ]
        return page

    def status_job(
        self, kind: str, job_id: str, *, stdout_offset: int = 0, stderr_offset: int = 0
    ) -> dict[str, Any]:
        if kind not in {"command", "run"}:
            raise ValueError("job kind must be command or run")
        with self._lock:
            manager = self._commands if kind == "command" else self._runs
            if manager is None:
                raise ValueError("unknown MATLAB job")
            status = manager.status(job_id, stdout_offset=stdout_offset, stderr_offset=stderr_offset)
            pending_output = False
            for stream, offset in (("stdout", stdout_offset), ("stderr", stderr_offset)):
                delta = status[f"{stream}_delta"]
                total = status[f"{stream}_offset"]
                delivered = delta[:_STREAM_PAGE_CHARS]
                status[f"{stream}_delta"] = delivered
                status[f"{stream}_offset"] = min(offset, total) + len(delivered)
                pending_output |= status[f"{stream}_offset"] < total
            status["output_pending"] = pending_output
            if isinstance(status.get("result"), dict):
                status["result"] = self._result_page(status["result"])
            return status

    def result_page(self, kind: str, job_id: str, **cursors: int) -> dict[str, Any]:
        if kind not in {"command", "run"}:
            raise ValueError("job kind must be command or run")
        with self._lock:
            manager = self._commands if kind == "command" else self._runs
            if manager is None:
                raise ValueError("unknown MATLAB job")
            result = manager.status(job_id).get("result")
            if not isinstance(result, dict):
                raise ValueError("MATLAB job has no result yet")  # noqa: TRY004 - job lifecycle, not input type
            return self._result_page(result, **cursors)

    def stop(self, kind: str, job_id: str) -> dict[str, Any]:
        if kind not in {"command", "run"}:
            raise ValueError("job kind must be command or run")
        with self._lock:
            manager = self._commands if kind == "command" else self._runs
            if manager is None:
                raise ValueError("unknown MATLAB job")
            manager.stop(job_id)
            return self.status_job(kind, job_id)

    def close(self) -> None:
        with self._lock:
            if self._commands is not None:
                self._commands.stop_all()
            if self._runs is not None:
                self._runs.stop_all()
            if self._session is not None:
                self._session.close()
            self._session = None
            self._commands = None
            self._runs = None
