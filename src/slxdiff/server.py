from __future__ import annotations

import json
import secrets
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .agent import ToolRuntime, provider_catalog_payload, provider_from_dict, run_agent
from .blueprint import blueprint_from_dict, blueprint_to_model, catalog_payload
from .matlab_bridge import apply_patch_with_matlab, build_blueprint_with_matlab, find_matlab
from .model import Model
from .parser import parse_slx
from .patching import patch_from_dict, validate_patch_for_model
from .studio import model_payload, render_studio_html

_MAX_BODY = 4 * 1024 * 1024


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class StudioServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address,
        handler,
        *,
        model_path: Path | None,
        output_path: Path,
        generated_dir: Path,
        matlab: str | None,
        token: str,
    ):
        super().__init__(address, handler)
        self.model_path = model_path
        self.output_path = output_path
        self.generated_dir = generated_dir
        self.matlab = matlab
        self.token = token
        # Serialize MATLAB/Simulink execution across concurrent HTTP requests.
        self.execution_lock = threading.RLock()

    def current_model(self) -> Model:
        with self.execution_lock:
            if self.model_path is None:
                model = Model(name="untitled")
                model.metadata.update({"source": "blank", "sha256": ""})
                return model
            return parse_slx(self.model_path)


class StudioHandler(BaseHTTPRequestHandler):
    server: StudioServer

    def log_message(self, fmt: str, *args) -> None:  # pragma: no cover - standard server logging
        print(f"SLX Studio: {fmt % args}")

    def _send(self, status: int, data: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'",
        )
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        self._send(status, _json_bytes(payload), "application/json; charset=utf-8")

    def _authorized(self) -> bool:
        return secrets.compare_digest(self.headers.get("X-SLX-Studio-Token", ""), self.server.token)

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if length <= 0 or length > _MAX_BODY:
            raise ValueError("request body is empty or too large")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("request body must be valid UTF-8 JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("request JSON must be an object")
        return value

    def _require_model_path(self) -> Path:
        if self.server.model_path is None:
            raise ValueError("this Studio session is blank and has no source SLX model")
        return self.server.model_path

    def _status_payload(self) -> dict[str, Any]:
        status = find_matlab(self.server.matlab)
        return {
            "ok": True,
            "matlab": {"available": status.available, "detail": status.detail},
            "model_loaded": self.server.model_path is not None,
            "output_model": str(self.server.output_path),
            "generated_dir": str(self.server.generated_dir),
            "api_version": "v1",
        }

    def do_GET(self) -> None:
        if self.path == "/":
            model = self.server.current_model()
            html = render_studio_html(
                model,
                bridge={
                    "enabled": True,
                    "token": self.server.token,
                    "output_model": str(self.server.output_path),
                    "api_version": "v1",
                    "blank": self.server.model_path is None,
                },
            )
            self._send(HTTPStatus.OK, html.encode("utf-8"), "text/html; charset=utf-8")
            return

        if self.path in {"/api/status", "/api/v1/status"}:
            if not self._authorized():
                self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "forbidden"})
                return
            self._send_json(HTTPStatus.OK, self._status_payload())
            return

        if self.path == "/api/v1/capabilities":
            if not self._authorized():
                self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "forbidden"})
                return
            runtime = ToolRuntime(
                self.server.model_path,
                matlab=self.server.matlab,
                build_output=self.server.generated_dir,
                allow_build=True,
                execution_lock=self.server.execution_lock,
            )
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "api_version": "v1",
                    "providers": provider_catalog_payload(),
                    "block_catalog": catalog_payload(),
                    "tools": runtime.definitions(),
                    "security": {
                        "loopback_only": True,
                        "api_key_persisted": False,
                        "arbitrary_matlab_execution": False,
                        "writes_require_validated_blueprint_or_patch": True,
                    },
                },
            )
            return

        if self.path == "/api/v1/providers":
            if not self._authorized():
                self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "forbidden"})
                return
            self._send_json(HTTPStatus.OK, {"ok": True, "providers": provider_catalog_payload()})
            return

        if self.path == "/api/v1/model":
            if not self._authorized():
                self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "forbidden"})
                return
            self._send_json(HTTPStatus.OK, {"ok": True, "model": model_payload(self.server.current_model())})
            return

        if self.path == "/api/v1/tools":
            if not self._authorized():
                self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "forbidden"})
                return
            runtime = ToolRuntime(self.server.model_path, matlab=self.server.matlab, allow_build=False, execution_lock=self.server.execution_lock)
            self._send_json(HTTPStatus.OK, {"ok": True, "tools": runtime.definitions()})
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        known = {
            "/api/validate",
            "/api/apply",
            "/api/simulate",
            "/api/v1/blueprints/validate",
            "/api/v1/blueprints/build",
            "/api/v1/tools/call",
            "/api/v1/agent/chat",
        }
        if self.path not in known:
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            return
        if not self._authorized():
            self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "forbidden"})
            return

        try:
            body = self._read_json()

            if self.path in {"/api/validate", "/api/apply", "/api/simulate"}:
                model_path = self._require_model_path()
                patch = patch_from_dict(body.get("patch", body))
                model = parse_slx(model_path)
                validate_patch_for_model(patch, model, source_path=model_path)
                if self.path == "/api/validate":
                    self._send_json(HTTPStatus.OK, {"ok": True, "operations": len(patch.operations)})
                    return
                stop_time = str(body.get("stop_time", "10")).strip() or "10"
                if len(stop_time) > 128 or "\n" in stop_time or "\r" in stop_time:
                    raise ValueError("invalid simulation stop time")
                with self.server.execution_lock:
                    result = apply_patch_with_matlab(
                        model_path,
                        patch,
                        output_path=self.server.output_path,
                        matlab=self.server.matlab,
                        simulate=self.path == "/api/simulate",
                        stop_time=stop_time,
                    )
                self._send_json(HTTPStatus.OK, result)
                return

            if self.path == "/api/v1/blueprints/validate":
                blueprint = blueprint_from_dict(body.get("blueprint", body))
                preview = model_payload(blueprint_to_model(blueprint))
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "valid": True,
                        "blueprint": blueprint.to_dict(),
                        "preview": preview,
                        "summary": {"blocks": len(blueprint.blocks), "connections": len(blueprint.connections)},
                    },
                )
                return

            if self.path == "/api/v1/blueprints/build":
                blueprint = blueprint_from_dict(body.get("blueprint", body))
                output = self.server.generated_dir / f"{blueprint.model_name}.slx"
                with self.server.execution_lock:
                    result = build_blueprint_with_matlab(
                        blueprint,
                        output_path=output,
                        matlab=self.server.matlab,
                        overwrite=bool(body.get("overwrite", False)),
                    )
                result["preview"] = model_payload(blueprint_to_model(blueprint))
                self._send_json(HTTPStatus.OK, result)
                return

            if self.path == "/api/v1/tools/call":
                name = str(body.get("name", ""))
                arguments = body.get("arguments", {})
                runtime = ToolRuntime(self.server.model_path, matlab=self.server.matlab, allow_build=False, execution_lock=self.server.execution_lock)
                result = runtime.call(name, arguments)
                payload: dict[str, Any] = {"ok": True, "result": result}
                patch = runtime.patch_document()
                if patch is not None:
                    payload["patch"] = patch.to_dict()
                if runtime.blueprint is not None:
                    payload["blueprint"] = runtime.blueprint.to_dict()
                    payload["preview"] = model_payload(blueprint_to_model(runtime.blueprint))
                self._send_json(HTTPStatus.OK, payload)
                return

            if self.path == "/api/v1/agent/chat":
                provider = provider_from_dict(body.get("provider", {}))
                prompt = str(body.get("prompt", ""))
                language = str(body.get("language", "en"))
                allow_build = bool(body.get("auto_build", False))
                run = run_agent(
                    provider,
                    prompt,
                    model_path=self.server.model_path,
                    matlab=self.server.matlab,
                    build_output=self.server.generated_dir,
                    allow_build=allow_build,
                    language=language,
                    execution_lock=self.server.execution_lock,
                )
                payload = run.to_dict()
                if run.blueprint is not None:
                    payload["preview"] = model_payload(blueprint_to_model(run.blueprint))
                self._send_json(HTTPStatus.OK, payload)
                return

        except (ValueError, RuntimeError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})


def serve_studio(
    model_path: str | Path | None = None,
    *,
    output_path: str | Path | None = None,
    generated_dir: str | Path | None = None,
    matlab: str | None = None,
    host: str = "127.0.0.1",
    port: int = 0,
    open_browser: bool = True,
    token: str | None = None,
) -> tuple[StudioServer, str]:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("the SLX Studio local API is loopback-only; use 127.0.0.1, localhost, or ::1")
    if port < 0 or port > 65535:
        raise ValueError("port must be between 0 and 65535")

    model: Path | None = Path(model_path).resolve() if model_path is not None else None
    if model is not None:
        if not model.exists():
            raise FileNotFoundError(model)
        parse_slx(model)  # fail before binding a local server
        root = model.parent
        output = Path(output_path).resolve() if output_path else model.with_name(f"{model.stem}_edited.slx")
    else:
        root = Path.cwd()
        output = Path(output_path).resolve() if output_path else root / "slx_studio_edited.slx"

    build_root = Path(generated_dir).resolve() if generated_dir else root
    build_root.mkdir(parents=True, exist_ok=True)
    session_token = token or secrets.token_urlsafe(24)
    if not session_token or len(session_token) > 512 or "\r" in session_token or "\n" in session_token:
        raise ValueError("invalid API token")

    server = StudioServer(
        (host, port),
        StudioHandler,
        model_path=model,
        output_path=output,
        generated_dir=build_root,
        matlab=matlab,
        token=session_token,
    )
    actual_host, actual_port = server.server_address[:2]
    display_host = f"[{actual_host}]" if ":" in actual_host else actual_host
    url = f"http://{display_host}:{actual_port}/"
    if open_browser:
        threading.Timer(0.15, lambda: webbrowser.open(url)).start()
    return server, url


def run_studio_server(**kwargs) -> str:
    server, url = serve_studio(**kwargs)
    print(f"SLX Studio: {url}")
    print(f"Local API: {url.rstrip('/')}/api/v1")
    print(f"API token: {server.token}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return url
