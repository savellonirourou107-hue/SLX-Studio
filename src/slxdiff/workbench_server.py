from __future__ import annotations

import os
import secrets
import shutil
import tempfile
import threading
import webbrowser
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .history import ModelHistory
from .matlab_bridge import (
    apply_model_edit_with_matlab,
    apply_patch_with_matlab,
    create_empty_model_with_matlab,
)
from .model_edit import edit_document_from_dict
from .mrunner import MatlabRunManager, run_m_file
from .msession import MatlabCommandSession
from .parser import parse_slx
from .patching import patch_from_dict
from .server import StudioHandler, StudioServer
from .simrunner import SimulationRunManager
from .state import StudioState
from .studio import model_payload, render_studio_html
from .sweep import SweepRunManager
from .workbench import render_workbench_html
from .workspace import (
    copy_workspace_file,
    create_m_file,
    list_workspace,
    read_text_file,
    resolve_workspace_path,
    search_workspace,
    workspace_root,
    write_text_file,
)


def _restore_model_snapshot(snapshot: Path, target: Path) -> None:
    """Restore an SLX snapshot through an atomic sibling replace.

    The sibling is only a byte-copy staging file; MATLAB never loads or saves it,
    so its filename does not need to satisfy Simulink model-name rules.
    """

    staging = target.with_name(f".{target.name}.restore-{secrets.token_hex(8)}.tmp")
    try:
        shutil.copy2(snapshot, staging)
        os.replace(staging, target)
    finally:
        staging.unlink(missing_ok=True)


class WorkbenchServer(StudioServer):
    def __init__(self, address, handler, *, root: Path, initial_file: str | None, matlab: str | None, token: str):
        initial_model = None
        if initial_file and initial_file.lower().endswith(".slx"):
            initial_model = resolve_workspace_path(root, initial_file)
        output = initial_model if initial_model is not None else root / "untitled_model.slx"
        super().__init__(
            address,
            handler,
            model_path=initial_model,
            output_path=output,
            generated_dir=root,
            matlab=matlab,
            token=token,
        )
        self.workspace_root = root
        self.initial_file = initial_file
        self.model_history = ModelHistory(max_records_per_file=25)
        self.session_temp = tempfile.TemporaryDirectory(prefix="slx-studio-session-")
        self.session_root = Path(self.session_temp.name)
        self.workspace_checkpoint = self.session_root / "workspace.mat"
        self.run_manager = MatlabRunManager(matlab=matlab, workspace_file=self.workspace_checkpoint, execution_lock=self.execution_lock)
        self.command_session = MatlabCommandSession(work_dir=root, workspace_file=self.workspace_checkpoint, matlab=matlab, execution_lock=self.execution_lock)
        self.sweep_manager = SweepRunManager(matlab=matlab, execution_lock=self.execution_lock)
        self.simulation_manager = SimulationRunManager(matlab=matlab, history=self.model_history, execution_lock=self.execution_lock)
        self.state = StudioState()
        self.state.mark_recent(root)

    def server_close(self) -> None:
        try:
            self.run_manager.stop_all()
            self.sweep_manager.stop_all()
            self.simulation_manager.stop_all()
            self.model_history.close()
            self.session_temp.cleanup()
        finally:
            super().server_close()


class WorkbenchHandler(StudioHandler):
    server: WorkbenchServer

    def _relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.server.workspace_root).as_posix()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            html = render_workbench_html(
                {
                    "token": self.server.token,
                    "root": str(self.server.workspace_root),
                    "initial_file": self.server.initial_file,
                    "api_version": "v1",
                }
            )
            self._send(HTTPStatus.OK, html.encode("utf-8"), "text/html; charset=utf-8")
            return

        if parsed.path == "/slx":
            relative = (parse_qs(parsed.query).get("path") or [""])[0]
            try:
                path = resolve_workspace_path(self.server.workspace_root, relative)
                if path.suffix.lower() != ".slx":
                    raise ValueError("graphical editor only opens .slx files")
                with self.server.execution_lock:
                    model = parse_slx(path)
                self.server.model_path = path
                self.server.output_path = path
                html = render_studio_html(
                    model,
                    bridge={
                        "enabled": True,
                        "token": self.server.token,
                        "output_model": str(path),
                        "api_version": "v1",
                        "blank": False,
                        "workbench": True,
                        "workspace_path": relative,
                    },
                )
                self._send(HTTPStatus.OK, html.encode("utf-8"), "text/html; charset=utf-8")
            except (FileNotFoundError, ValueError) as exc:
                self._send(HTTPStatus.BAD_REQUEST, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
            return

        if parsed.path == "/api/v1/workspace":
            if not self._authorized():
                self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "forbidden"})
                return
            payload = list_workspace(self.server.workspace_root)
            payload["ok"] = True
            self._send_json(HTTPStatus.OK, payload)
            return

        if parsed.path == "/api/v1/state/recent":
            if not self._authorized():
                self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "forbidden"})
                return
            self._send_json(HTTPStatus.OK, {"ok": True, "recent_projects": self.server.state.recent_projects()})
            return

        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        workspace_routes = {
            "/api/v1/workspace/read",
            "/api/v1/workspace/save",
            "/api/v1/workspace/save-as",
            "/api/v1/workspace/search",
            "/api/v1/workspace/new-m",
            "/api/v1/workspace/new-slx",
            "/api/v1/workspace/run-m",
            "/api/v1/workspace/run/start",
            "/api/v1/workspace/run/status",
            "/api/v1/workspace/run/stop",
            "/api/v1/workspace/command",
            "/api/v1/workspace/variables/set",
            "/api/v1/workspace/recovery/save",
            "/api/v1/workspace/recovery/clear",
            "/api/v1/workspace/sweep/start",
            "/api/v1/workspace/sweep/status",
            "/api/v1/workspace/sweep/stop",
            "/api/v1/workspace/sim/start",
            "/api/v1/workspace/sim/status",
            "/api/v1/workspace/sim/stop",
            "/api/v1/workspace/model-edit",
            "/api/v1/workspace/apply-patch",
            "/api/v1/workspace/history",
            "/api/v1/workspace/undo",
            "/api/v1/workspace/redo",
        }
        if parsed.path not in workspace_routes:
            super().do_POST()
            return
        if not self._authorized():
            self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "forbidden"})
            return
        try:
            body = self._read_json()
            relative = str(body.get("path", ""))

            if parsed.path == "/api/v1/workspace/read":
                path = resolve_workspace_path(self.server.workspace_root, relative)
                content = read_text_file(self.server.workspace_root, relative)
                recovery = self.server.state.get_recovery(self.server.workspace_root, self._relative(path)) if path.suffix.lower() == ".m" else None
                if recovery is not None:
                    recovery = dict(recovery)
                    saved_mtime = int(recovery.get("disk_mtime_ns") or 0)
                    current_mtime = int(path.stat().st_mtime_ns)
                    recovery["disk_conflict"] = bool(saved_mtime and saved_mtime != current_mtime)
                    recovery["current_disk_mtime_ns"] = current_mtime
                self._send_json(
                    HTTPStatus.OK,
                    {"ok": True, "path": str(path), "relative_path": self._relative(path), "content": content, "recovery": recovery},
                )
                return

            if parsed.path == "/api/v1/workspace/save":
                content = body.get("content")
                if not isinstance(content, str):
                    raise ValueError("content must be a string")
                path = write_text_file(self.server.workspace_root, relative, content)
                self.server.state.clear_recovery(self.server.workspace_root, self._relative(path))
                self._send_json(
                    HTTPStatus.OK,
                    {"ok": True, "path": str(path), "relative_path": self._relative(path), "bytes": len(content.encode("utf-8"))},
                )
                return

            if parsed.path == "/api/v1/workspace/save-as":
                destination = str(body.get("destination", ""))
                if not destination:
                    raise ValueError("destination is required")
                source = resolve_workspace_path(self.server.workspace_root, relative)
                if source.suffix.lower() == ".m" and isinstance(body.get("content"), str):
                    target = resolve_workspace_path(self.server.workspace_root, destination, must_exist=False)
                    if target.exists():
                        raise ValueError(f"destination already exists: {destination}")
                    if target.suffix.lower() != ".m":
                        raise ValueError("Save As must preserve the .m extension")
                    path = write_text_file(self.server.workspace_root, destination, body["content"])
                else:
                    path = copy_workspace_file(self.server.workspace_root, relative, destination)
                self._send_json(HTTPStatus.OK, {"ok": True, "path": str(path), "relative_path": self._relative(path)})
                return

            if parsed.path == "/api/v1/workspace/search":
                query = str(body.get("query", ""))
                payload = search_workspace(self.server.workspace_root, query)
                self._send_json(HTTPStatus.OK, {"ok": True, **payload})
                return

            if parsed.path == "/api/v1/workspace/new-m":
                path = create_m_file(self.server.workspace_root, relative)
                self._send_json(HTTPStatus.OK, {"ok": True, "path": str(path), "relative_path": self._relative(path)})
                return

            if parsed.path == "/api/v1/workspace/new-slx":
                path = resolve_workspace_path(self.server.workspace_root, relative, must_exist=False)
                with self.server.execution_lock:
                    result = create_empty_model_with_matlab(path, matlab=self.server.matlab)
                result.update({"relative_path": self._relative(path)})
                self._send_json(HTTPStatus.OK, result)
                return

            if parsed.path == "/api/v1/workspace/run-m":
                path = resolve_workspace_path(self.server.workspace_root, relative)
                with self.server.execution_lock:
                    result = run_m_file(path, matlab=self.server.matlab, workspace_file=self.server.workspace_checkpoint)
                self._send_json(HTTPStatus.OK, {"ok": True, "run": result})
                return

            if parsed.path == "/api/v1/workspace/run/start":
                path = resolve_workspace_path(self.server.workspace_root, relative)
                code = body.get("code")
                if code is not None and not isinstance(code, str):
                    raise ValueError("code must be a string")
                start_line = int(body.get("start_line") or 1)
                job = self.server.run_manager.start(path, code=code, start_line=start_line)
                self._send_json(HTTPStatus.ACCEPTED, {"ok": True, "job": job})
                return

            if parsed.path == "/api/v1/workspace/run/status":
                job = self.server.run_manager.status(str(body.get("job_id", "")))
                self._send_json(HTTPStatus.OK, {"ok": True, "job": job})
                return

            if parsed.path == "/api/v1/workspace/run/stop":
                job = self.server.run_manager.stop(str(body.get("job_id", "")))
                self._send_json(HTTPStatus.OK, {"ok": True, "job": job})
                return

            if parsed.path == "/api/v1/workspace/command":
                result = self.server.command_session.execute(str(body.get("code", "")))
                self._send_json(HTTPStatus.OK, {"ok": True, "run": result})
                return

            if parsed.path == "/api/v1/workspace/variables/set":
                result = self.server.command_session.set_variable(str(body.get("name", "")), str(body.get("expression", "")))
                self._send_json(HTTPStatus.OK, {"ok": True, "run": result})
                return

            if parsed.path == "/api/v1/workspace/recovery/save":
                path = resolve_workspace_path(self.server.workspace_root, relative)
                if path.suffix.lower() != ".m":
                    raise ValueError("recovery drafts are supported for .m files")
                content = body.get("content")
                if not isinstance(content, str):
                    raise ValueError("content must be a string")
                entry = self.server.state.save_recovery(self.server.workspace_root, self._relative(path), content, disk_mtime_ns=path.stat().st_mtime_ns)
                self._send_json(HTTPStatus.OK, {"ok": True, "recovery": entry})
                return

            if parsed.path == "/api/v1/workspace/recovery/clear":
                path = resolve_workspace_path(self.server.workspace_root, relative)
                cleared = self.server.state.clear_recovery(self.server.workspace_root, self._relative(path))
                self._send_json(HTTPStatus.OK, {"ok": True, "cleared": cleared})
                return

            if parsed.path == "/api/v1/workspace/sweep/start":
                path = resolve_workspace_path(self.server.workspace_root, relative)
                if path.suffix.lower() != ".slx":
                    raise ValueError("parameter sweeps require a .slx model")
                job = self.server.sweep_manager.start(path, block_path=str(body.get("block_path", "")), parameter=str(body.get("parameter", "")), values=body.get("values", ""), stop_time=str(body.get("stop_time", "10")))
                self._send_json(HTTPStatus.ACCEPTED, {"ok": True, "job": job})
                return

            if parsed.path == "/api/v1/workspace/sweep/status":
                job = self.server.sweep_manager.status(str(body.get("job_id", "")))
                self._send_json(HTTPStatus.OK, {"ok": True, "job": job})
                return

            if parsed.path == "/api/v1/workspace/sweep/stop":
                job = self.server.sweep_manager.stop(str(body.get("job_id", "")))
                self._send_json(HTTPStatus.OK, {"ok": True, "job": job})
                return

            if parsed.path == "/api/v1/workspace/sim/start":
                path = resolve_workspace_path(self.server.workspace_root, relative)
                if path.suffix.lower() != ".slx":
                    raise ValueError("simulation requires a .slx model")
                job = self.server.simulation_manager.start(path, patch=body.get("patch", {}), stop_time=str(body.get("stop_time", "10")))
                self._send_json(HTTPStatus.ACCEPTED, {"ok": True, "job": job})
                return

            if parsed.path == "/api/v1/workspace/sim/status":
                job = self.server.simulation_manager.status(str(body.get("job_id", "")))
                self._send_json(HTTPStatus.OK, {"ok": True, "job": job})
                return

            if parsed.path == "/api/v1/workspace/sim/stop":
                job = self.server.simulation_manager.stop(str(body.get("job_id", "")))
                self._send_json(HTTPStatus.OK, {"ok": True, "job": job})
                return


            if parsed.path == "/api/v1/workspace/history":
                path = resolve_workspace_path(self.server.workspace_root, relative)
                if path.suffix.lower() != ".slx":
                    raise ValueError("model history requires a .slx file")
                self._send_json(HTTPStatus.OK, {"ok": True, "relative_path": self._relative(path), **self.server.model_history.status(path)})
                return

            if parsed.path in {"/api/v1/workspace/undo", "/api/v1/workspace/redo"}:
                path = resolve_workspace_path(self.server.workspace_root, relative)
                if path.suffix.lower() != ".slx":
                    raise ValueError("model history requires a .slx file")
                with self.server.execution_lock:
                    if parsed.path.endswith("/undo"):
                        history = self.server.model_history.undo(path)
                        action = "undo"
                    else:
                        history = self.server.model_history.redo(path)
                        action = "redo"
                    refreshed = parse_slx(path)
                self.server.model_path = path
                self.server.output_path = path
                self._send_json(
                    HTTPStatus.OK,
                    {"ok": True, "action": action, "relative_path": self._relative(path), "model": model_payload(refreshed), **history},
                )
                return

            if parsed.path == "/api/v1/workspace/apply-patch":
                path = resolve_workspace_path(self.server.workspace_root, relative)
                if path.suffix.lower() != ".slx":
                    raise ValueError("model patches require a .slx file")
                patch = patch_from_dict(body.get("patch", {}))
                simulate = bool(body.get("simulate", False))
                stop_time = str(body.get("stop_time", "10")).strip() or "10"
                if len(stop_time) > 128 or "\n" in stop_time or "\r" in stop_time:
                    raise ValueError("invalid simulation stop time")
                before_snapshot = None
                try:
                    with self.server.execution_lock:
                        # Always keep a rollback copy because save_system may touch the
                        # original even when a later simulation step fails.  Saving to a
                        # made-up .slx filename is unsafe: Simulink model filenames are
                        # constrained by model naming rules.
                        before_snapshot = self.server.model_history.capture(path, label="before")
                        result = apply_patch_with_matlab(
                            path,
                            patch,
                            output_path=path,
                            matlab=self.server.matlab,
                            simulate=simulate,
                            stop_time=stop_time,
                        )
                        result["output_model"] = str(path)
                        if patch.operations:
                            history = self.server.model_history.record(path, before_snapshot)
                            before_snapshot = None
                        else:
                            # A simulation-only request must not create a model edit just
                            # because MATLAB rewrote the file while saving it.
                            _restore_model_snapshot(before_snapshot, path)
                            self.server.model_history.discard_capture(before_snapshot)
                            before_snapshot = None
                            history = self.server.model_history.status(path)
                        refreshed = parse_slx(path)
                except Exception:
                    if before_snapshot is not None:
                        _restore_model_snapshot(before_snapshot, path)
                        self.server.model_history.discard_capture(before_snapshot)
                    raise
                self.server.model_path = path
                self.server.output_path = path
                result.update({"relative_path": self._relative(path), "model": model_payload(refreshed), "history": history})
                self._send_json(HTTPStatus.OK, result)
                return

            if parsed.path == "/api/v1/workspace/model-edit":
                path = resolve_workspace_path(self.server.workspace_root, relative)
                if path.suffix.lower() != ".slx":
                    raise ValueError("model edits require a .slx file")
                document = edit_document_from_dict(body.get("edit", {}))
                before_snapshot = None
                try:
                    with self.server.execution_lock:
                        before_snapshot = self.server.model_history.capture(path, label="before")
                        result = apply_model_edit_with_matlab(path, document, output_path=path, matlab=self.server.matlab)
                        result["output_model"] = str(path)
                        history = self.server.model_history.record(path, before_snapshot)
                        before_snapshot = None
                        refreshed = parse_slx(path)
                except Exception:
                    if before_snapshot is not None:
                        _restore_model_snapshot(before_snapshot, path)
                        self.server.model_history.discard_capture(before_snapshot)
                    raise
                self.server.model_path = path
                self.server.output_path = path
                result.update({"relative_path": self._relative(path), "model": model_payload(refreshed), "history": history})
                self._send_json(HTTPStatus.OK, result)
                return

        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})


def serve_workbench(
    path: str | Path | None = None,
    *,
    matlab: str | None = None,
    host: str = "127.0.0.1",
    port: int = 0,
    open_browser: bool = True,
    token: str | None = None,
) -> tuple[WorkbenchServer, str]:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("SLX Studio desktop API is loopback-only")
    root, initial = workspace_root(path)
    session_token = token or secrets.token_urlsafe(24)
    server = WorkbenchServer((host, port), WorkbenchHandler, root=root, initial_file=initial, matlab=matlab, token=session_token)
    actual_host, actual_port = server.server_address[:2]
    display_host = f"[{actual_host}]" if ":" in actual_host else actual_host
    url = f"http://{display_host}:{actual_port}/"
    if open_browser:
        threading.Timer(0.15, lambda: webbrowser.open(url)).start()
    return server, url


def run_workbench_server(**kwargs: Any) -> str:
    server, url = serve_workbench(**kwargs)
    print(f"SLX Studio Workbench: {url}")
    print(f"Workspace: {server.workspace_root}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return url
