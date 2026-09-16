from __future__ import annotations

import io
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, BinaryIO, TextIO

from . import __version__
from .diff import compare_models
from .m_diff import generate_m_diff_preview
from .parser import parse_slx
from .render import render_markdown
from .review import build_review_report, render_review_markdown
from .workspace import read_text_file, resolve_workspace_path, search_workspace

PROTOCOL_VERSION = "2024-11-05"
MAX_REQUEST_BYTES = 1024 * 1024


def _error(code: int, message: str, msg_id: Any = None) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


class McpServer:
    """Standard Model Context Protocol (MCP) server over JSON-RPC 2.0."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root).resolve() if root else Path.cwd()

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "slx_inspect_model",
                "description": (
                    "Parse and inspect a Simulink (.slx) model statically without starting MATLAB. "
                    "Returns block counts, hierarchy, connections, metadata, and unsupported features."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative or absolute path to an .slx file within the workspace root.",
                        }
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "slx_diff_models",
                "description": (
                    "Compute semantic diff between two Simulink (.slx) models without starting MATLAB. "
                    "Reports added, removed, and modified blocks, lines, and parameters."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "left_path": {"type": "string", "description": "Path to the base .slx model."},
                        "right_path": {"type": "string", "description": "Path to the modified .slx model."},
                        "include_layout": {
                            "type": "boolean",
                            "description": "Include visual/layout changes (positions, bounds).",
                            "default": False,
                        },
                    },
                    "required": ["left_path", "right_path"],
                },
            },
            {
                "name": "slx_review_intelligence",
                "description": (
                    "Analyze blast radius, dependency changes, and impact summary between two .slx models."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "left_path": {"type": "string", "description": "Path to base .slx model."},
                        "right_path": {"type": "string", "description": "Path to modified .slx model."},
                    },
                    "required": ["left_path", "right_path"],
                },
            },
            {
                "name": "slx_read_script",
                "description": "Safely read a MATLAB script (.m) within the workspace boundary.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative path to .m file in workspace."}
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "slx_search_workspace",
                "description": "Search workspace file names and MATLAB script text without starting MATLAB.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search keyword or block name."}
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "slx_propose_script_edit",
                "description": (
                    "Generate a unified diff preview and conflict check for a proposed .m edit before writing to disk. "
                    "Requires explicit confirmation before applying."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative path to .m file in workspace."},
                        "content": {"type": "string", "description": "Proposed new content of the script."},
                        "base_sha256": {
                            "type": "string",
                            "description": "Optional SHA-256 of original content for conflict detection.",
                        },
                    },
                    "required": ["path", "content"],
                },
            },
        ]

    def _resolve_slx(self, path_str: str) -> Path:
        p = Path(path_str)
        if p.is_absolute():
            resolved = p.resolve()
        else:
            resolved = resolve_workspace_path(self.root, path_str)
        if not resolved.is_relative_to(self.root):
            raise ValueError("model path escapes the workspace root")
        if not resolved.is_file():
            raise FileNotFoundError(f"model file not found: {path_str}")
        if resolved.suffix.lower() != ".slx":
            raise ValueError(f"file is not an .slx model: {path_str}")
        return resolved

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise TypeError("arguments must be a JSON object")

        if name == "slx_inspect_model":
            path = str(arguments.get("path", "")).strip()
            if not path:
                raise ValueError("path is required")
            model_path = self._resolve_slx(path)
            model = parse_slx(model_path)
            payload = {
                "name": model.name,
                "metadata": model.metadata,
                "block_count": len(model.blocks),
                "connection_count": len(model.lines),
                "blocks": [asdict(b) for _, b in sorted(model.blocks.items())[:100]],
                "blocks_truncated": len(model.blocks) > 100,
            }
            return {
                "content": [{"type": "text", "text": json.dumps(payload, indent=2, ensure_ascii=False)}],
                "isError": False,
            }

        if name == "slx_diff_models":
            left_path = str(arguments.get("left_path", "")).strip()
            right_path = str(arguments.get("right_path", "")).strip()
            if not left_path or not right_path:
                raise ValueError("left_path and right_path are required")
            include_layout = bool(arguments.get("include_layout", False))
            left_model, right_model = self._resolve_slx(left_path), self._resolve_slx(right_path)
            old = parse_slx(left_model)
            new = parse_slx(right_model)
            result = compare_models(old, new, include_layout=include_layout)
            diff_text = render_markdown(result)
            return {
                "content": [{"type": "text", "text": diff_text}],
                "isError": False,
            }

        if name == "slx_review_intelligence":
            left_path = str(arguments.get("left_path", "")).strip()
            right_path = str(arguments.get("right_path", "")).strip()
            if not left_path or not right_path:
                raise ValueError("left_path and right_path are required")
            left_model, right_model = self._resolve_slx(left_path), self._resolve_slx(right_path)
            old = parse_slx(left_model)
            new = parse_slx(right_model)
            report = build_review_report(old, new)
            review_md = render_review_markdown(report)
            return {
                "content": [{"type": "text", "text": review_md}],
                "isError": False,
            }

        if name == "slx_read_script":
            path = str(arguments.get("path", "")).strip()
            if not path:
                raise ValueError("path is required")
            content = read_text_file(self.root, path)
            return {
                "content": [{"type": "text", "text": content}],
                "isError": False,
            }

        if name == "slx_search_workspace":
            query = str(arguments.get("query", "")).strip()
            if not query:
                raise ValueError("query is required")
            results = search_workspace(self.root, query)
            return {
                "content": [{"type": "text", "text": json.dumps(results, indent=2, ensure_ascii=False)}],
                "isError": False,
            }

        if name == "slx_propose_script_edit":
            path = str(arguments.get("path", "")).strip()
            content = str(arguments.get("content", ""))
            base_sha256 = arguments.get("base_sha256")
            base_sha = str(base_sha256).strip() if base_sha256 else None
            preview = generate_m_diff_preview(self.root, path, content, base_sha256=base_sha)
            text_summary = (
                f"Proposed diff for {preview['relative_path']}:\n\n"
                f"{preview['diff']}\n\n"
                f"Stats: +{preview['stats']['additions']} / -{preview['stats']['deletions']} lines.\n"
                f"Current SHA-256: {preview['current_sha256']}\n"
                f"Conflict: {preview['conflict']}\n"
                f"Note: This edit is a preview. Application requires explicit user confirmation."
            )
            return {
                "content": [{"type": "text", "text": text_summary}],
                "preview": preview,
                "isError": False,
            }

        raise ValueError(f"unknown tool: {name}")

    def handle_request(self, request: Any) -> dict[str, Any] | None:
        """Handle a single parsed JSON-RPC 2.0 request or notification."""
        if not isinstance(request, dict):
            return _error(-32600, "Request must be a JSON object")
        msg_id = request.get("id")
        method = request.get("method", "")
        if (
            request.get("jsonrpc") != "2.0"
            or not isinstance(method, str)
            or not method
            or isinstance(msg_id, bool)
            or (msg_id is not None and not isinstance(msg_id, (str, int)))
        ):
            return _error(-32600, "Invalid JSON-RPC 2.0 request")

        # Handle notifications (no id)
        if "id" not in request:
            if method == "notifications/initialized":
                return None
            return None

        params = request.get("params", {})
        if not isinstance(params, dict):
            return _error(-32602, "params must be a JSON object", msg_id)

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {
                        "tools": {"listChanged": False},
                    },
                    "serverInfo": {
                        "name": "slx-studio",
                        "version": __version__,
                    },
                },
            }

        if method == "ping":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": self.get_tool_definitions()},
            }

        if method == "tools/call":
            tool_name = str(params.get("name", ""))
            arguments = params.get("arguments", {})
            try:
                res = self.call_tool(tool_name, arguments)
                return {"jsonrpc": "2.0", "id": msg_id, "result": res}
            except Exception as exc:  # noqa: BLE001 - return tool execution failure in MCP response
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Error: {exc}"}],
                        "isError": True,
                    },
                }

        # Unknown method
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    def process_message(self, raw_line: str) -> str | None:
        """Process a raw JSON-RPC string and return the serialized JSON response string if any."""
        if len(raw_line) > MAX_REQUEST_BYTES or len(raw_line.encode("utf-8")) > MAX_REQUEST_BYTES:
            return json.dumps(_error(-32600, "Request exceeds the 1 MiB limit"))
        stripped = raw_line.strip()
        if not stripped:
            return None
        try:
            payload = json.loads(stripped)
        except (json.JSONDecodeError, RecursionError) as exc:
            return json.dumps(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {exc}"}}
            )
        response = self.handle_request(payload)
        return json.dumps(response, ensure_ascii=False) if response is not None else None


def run_mcp_server(
    root: str | Path | None = None,
    *,
    in_stream: TextIO | BinaryIO | None = None,
    out_stream: TextIO | BinaryIO | None = None,
) -> int:
    """Run the MCP server reading line-delimited JSON-RPC from in_stream and writing to out_stream."""
    server = McpServer(root=root)
    reader = in_stream if in_stream is not None else sys.stdin.buffer
    writer = out_stream if out_stream is not None else sys.stdout.buffer

    while True:
        line = reader.readline(MAX_REQUEST_BYTES + 1)
        if not line:
            break
        newline = b"\n" if isinstance(line, bytes) else "\n"
        if len(line) > MAX_REQUEST_BYTES:
            # Drain only the oversized frame, never buffer it or consume the
            # next request. Text streams get an additional UTF-8 byte check.
            while not line.endswith(newline):
                line = reader.readline(MAX_REQUEST_BYTES + 1)
                if not line:
                    break
            response_str = json.dumps(_error(-32600, "Request exceeds the 1 MiB limit"))
        else:
            try:
                decoded = line.decode("utf-8") if isinstance(line, bytes) else line
                response_str = server.process_message(decoded)
            except UnicodeError:
                response_str = json.dumps(_error(-32700, "Request must be valid UTF-8"))
        if response_str:
            output = response_str + "\n"
            writer.write(
                output.encode("utf-8") if isinstance(writer, (io.BufferedIOBase, io.RawIOBase)) else output
            )
            writer.flush()
    return 0
