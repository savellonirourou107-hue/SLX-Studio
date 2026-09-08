"""Desktop-facing MATLAB runtime built on the existing persistent worker.

The RPC layer deliberately exposes only explicit start/status/stop operations.
Inspecting or opening an SLX never creates this object, so static model viewing
remains safe and fast.  Command and script jobs share one worker and execution
lock, which keeps variables, figures and diagnostics in the same session.
"""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path
from typing import Any

from .documents import document_path
from .matlab_bridge import find_matlab
from .mrunner import MatlabRunManager
from .msession import MatlabCommandManager
from .persistent import PersistentMatlabSession

_MAX_TRACEPOINTS = 256


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
            return commands.start(command)

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
            return self._runs.start(path, code=code, start_line=start_line, tracepoints=points)

    def status_job(
        self, kind: str, job_id: str, *, stdout_offset: int = 0, stderr_offset: int = 0
    ) -> dict[str, Any]:
        if kind not in {"command", "run"}:
            raise ValueError("job kind must be command or run")
        with self._lock:
            manager = self._commands if kind == "command" else self._runs
            if manager is None:
                raise ValueError("unknown MATLAB job")
            return manager.status(job_id, stdout_offset=stdout_offset, stderr_offset=stderr_offset)

    def stop(self, kind: str, job_id: str) -> dict[str, Any]:
        if kind not in {"command", "run"}:
            raise ValueError("job kind must be command or run")
        with self._lock:
            manager = self._commands if kind == "command" else self._runs
            if manager is None:
                raise ValueError("unknown MATLAB job")
            return manager.stop(job_id)

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
