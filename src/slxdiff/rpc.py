"""Private, bounded JSON-RPC stdio adapter; no listeners or implicit execution."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, BinaryIO

from .diff import compare_models
from .documents import DocumentConflict, document_path, list_directory, read_document, save_document
from .matlab_bridge import apply_model_edit_with_matlab
from .matlab_runtime import MatlabRuntime
from .model_view import model_viewport
from .parser import parse_slx
from .workspace import workspace_root

MAX_FRAME_BYTES = 16 * 1024 * 1024
MODEL_PAGE_MAX_ITEMS = 512
MODEL_PAGE_MAX_BYTES = 2 * 1024 * 1024


class FrameError(ValueError):
    pass


def _slx_path(root: Path, relative: str) -> Path:
    path = document_path(root, relative)
    if path.suffix.lower() != ".slx":
        raise ValueError("model path must end in .slx")
    return path


def _validate_page(cursor: int, page_size: int) -> None:
    if isinstance(cursor, bool) or not isinstance(cursor, int) or not 0 <= cursor <= 100_000:
        raise ValueError("model page cursor must be a bounded non-negative integer")
    if (
        isinstance(page_size, bool)
        or not isinstance(page_size, int)
        or not 1 <= page_size <= MODEL_PAGE_MAX_ITEMS
    ):
        raise ValueError(f"model page size must be an integer from 1 to {MODEL_PAGE_MAX_ITEMS}")


def _page_records(
    records: list[dict[str, Any]], cursor: int, page_size: int, label: str
) -> tuple[list[dict[str, Any]], int | None]:
    _validate_page(cursor, page_size)
    selected: list[dict[str, Any]] = []
    size = 2
    for record in records[cursor : cursor + page_size]:
        encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
            "utf-8"
        )
        if len(encoded) > MODEL_PAGE_MAX_BYTES:
            raise ValueError(f"{label} item exceeds the model page size limit")
        if selected and size + len(encoded) + 1 > MODEL_PAGE_MAX_BYTES:
            break
        selected.append(record)
        size += len(encoded) + 1
    end = cursor + len(selected)
    return selected, end if end < len(records) else None


def inspect_model(
    root: Path,
    relative: str,
    block_cursor: int = 0,
    line_cursor: int = 0,
    page_size: int = MODEL_PAGE_MAX_ITEMS,
) -> dict[str, Any]:
    model = parse_slx(_slx_path(root, relative))
    blocks = [asdict(block) for _, block in sorted(model.blocks.items())]
    lines = [asdict(line) for line in sorted(model.lines)]
    block_page, next_block_cursor = _page_records(blocks, block_cursor, page_size, "block")
    line_page, next_line_cursor = _page_records(lines, line_cursor, page_size, "line")
    return {
        "schema_version": "0.5",
        "name": model.name,
        "metadata": model.metadata,
        "blocks": block_page,
        "lines": line_page,
        "total_blocks": len(blocks),
        "total_lines": len(lines),
        "block_cursor": block_cursor,
        "line_cursor": line_cursor,
        "page_size": page_size,
        "next_block_cursor": next_block_cursor,
        "next_line_cursor": next_line_cursor,
    }


def diff_models(
    root: Path,
    old: str,
    new: str,
    include_layout: bool = False,
    added_block_cursor: int = 0,
    removed_block_cursor: int = 0,
    changed_block_cursor: int = 0,
    added_line_cursor: int = 0,
    removed_line_cursor: int = 0,
    page_size: int = MODEL_PAGE_MAX_ITEMS,
) -> dict[str, Any]:
    if not isinstance(include_layout, bool):
        raise TypeError("include_layout must be boolean")
    result = compare_models(
        parse_slx(_slx_path(root, old)), parse_slx(_slx_path(root, new)), include_layout=include_layout
    )
    added_blocks = [asdict(block) for block in result.added_blocks]
    removed_blocks = [asdict(block) for block in result.removed_blocks]
    changed_blocks = [
        {
            "before": asdict(change.before),
            "after": asdict(change.after),
            "parameter_changes": [asdict(item) for item in change.parameter_changes],
        }
        for change in result.changed_blocks
    ]
    added_lines = [asdict(line) for line in result.added_lines]
    removed_lines = [asdict(line) for line in result.removed_lines]
    added_block_page, next_added_block_cursor = _page_records(
        added_blocks, added_block_cursor, page_size, "added block"
    )
    removed_block_page, next_removed_block_cursor = _page_records(
        removed_blocks, removed_block_cursor, page_size, "removed block"
    )
    changed_block_page, next_changed_block_cursor = _page_records(
        changed_blocks, changed_block_cursor, page_size, "changed block"
    )
    added_line_page, next_added_line_cursor = _page_records(
        added_lines, added_line_cursor, page_size, "added line"
    )
    removed_line_page, next_removed_line_cursor = _page_records(
        removed_lines, removed_line_cursor, page_size, "removed line"
    )
    return {
        "schema_version": "0.5",
        "old_name": result.old_name,
        "new_name": result.new_name,
        "changed": result.changed,
        "change_count": result.change_count,
        "added_blocks": added_block_page,
        "removed_blocks": removed_block_page,
        "changed_blocks": changed_block_page,
        "added_lines": added_line_page,
        "removed_lines": removed_line_page,
        "total_added_blocks": len(added_blocks),
        "total_removed_blocks": len(removed_blocks),
        "total_changed_blocks": len(changed_blocks),
        "total_added_lines": len(added_lines),
        "total_removed_lines": len(removed_lines),
        "page_size": page_size,
        "next_added_block_cursor": next_added_block_cursor,
        "next_removed_block_cursor": next_removed_block_cursor,
        "next_changed_block_cursor": next_changed_block_cursor,
        "next_added_line_cursor": next_added_line_cursor,
        "next_removed_line_cursor": next_removed_line_cursor,
    }


def apply_model_edit(
    root: Path, relative: str, edit: dict[str, Any], output_relative: str | None = None
) -> dict[str, Any]:
    """Apply a validated edit through MATLAB/Simulink, never by ZIP rewriting."""
    source = _slx_path(root, relative)
    if not isinstance(edit, dict):
        raise TypeError("model edit must be an object")
    output = source
    if output_relative is not None:
        output = _slx_path(root, output_relative)
        if output != source:
            raise ValueError(
                "desktop model edits currently save in place; use Save As from the legacy Workbench"
            )
    result = apply_model_edit_with_matlab(source, edit, output_path=output)
    if not isinstance(result, dict):
        raise TypeError("MATLAB model edit returned an invalid result")
    return {**result, "model_path": relative.replace("\\", "/"), "backend": "matlab_batch"}


def read_frame(stream: BinaryIO) -> bytes | None:
    length = None
    total = 0
    while True:
        line = stream.readline(1025)
        if not line and total == 0:
            return None
        total += len(line)
        if not line or len(line) > 1024 or total > 4096 or not line.endswith(b"\r\n"):
            raise FrameError("invalid or oversized framing header")
        if line == b"\r\n":
            break
        key, separator, value = line[:-2].partition(b":")
        if not separator:
            raise FrameError("invalid framing header")
        if key.lower() == b"content-length":
            if length is not None or not value.strip().isdigit():
                raise FrameError("invalid or duplicate Content-Length")
            length = int(value.strip())
    if length is None or not 0 < length <= MAX_FRAME_BYTES:
        raise FrameError("missing or out-of-range Content-Length")
    chunks = []
    remaining = length
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise FrameError("truncated frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def write_frame(stream: BinaryIO, message: Any) -> None:
    payload = json.dumps(message, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(payload) > MAX_FRAME_BYTES:
        raise FrameError("response exceeds the frame size limit")
    stream.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload)
    stream.flush()


def error(identifier: Any, code: int, message: str, kind: str = "") -> dict:
    return {
        "jsonrpc": "2.0",
        "id": identifier,
        "error": {"code": code, "message": message, "data": {"kind": kind}},
    }


class Backend:
    def __init__(self, root: str) -> None:
        self.root, self.initial_file = workspace_root(root)
        self._matlab = MatlabRuntime(self.root)

    def close(self) -> None:
        self._matlab.close()

    @staticmethod
    def _offset(value: Any, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1_048_576:
            raise ValueError(f"{name} must be a bounded non-negative integer")
        return value

    def dispatch(self, message: Any) -> dict | list | None:
        if isinstance(message, list):
            if not message or len(message) > 32:
                return error(None, -32600, "invalid or oversized batch")
            replies = [
                self.dispatch(item) if isinstance(item, dict) else error(None, -32600, "invalid request")
                for item in message
            ]
            return [reply for reply in replies if reply is not None] or None
        if not isinstance(message, dict):
            return error(None, -32600, "request must be an object")
        identifier = message.get("id")
        if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return error(None, -32600, "invalid JSON-RPC request")
        if isinstance(identifier, bool) or not isinstance(identifier, (str, int, type(None))):
            return error(None, -32600, "invalid request identifier")
        methods = {
            "initialize": self.initialize,
            "workspace/listDirectory": lambda **params: list_directory(self.root, **params),
            "document/read": lambda **params: read_document(self.root, **params),
            "document/save": lambda **params: save_document(self.root, **params),
            "model/inspect": lambda **params: inspect_model(self.root, **params),
            "model/viewport": lambda **params: model_viewport(self.root, **params),
            "model/diff": lambda **params: diff_models(self.root, **params),
            "model/applyEdit": lambda **params: apply_model_edit(self.root, **params),
            "matlab/status": lambda **params: self._matlab.status(),
            "matlab/command/start": lambda **params: self._matlab.start_command(params.get("command")),
            "matlab/command/status": lambda **params: self._matlab.status_job(
                "command",
                params.get("job_id"),
                stdout_offset=self._offset(params.get("stdout_offset", 0), "stdout_offset"),
                stderr_offset=self._offset(params.get("stderr_offset", 0), "stderr_offset"),
            ),
            "matlab/command/stop": lambda **params: self._matlab.stop("command", params.get("job_id")),
            "matlab/run/start": lambda **params: self._matlab.start_run(
                params.get("relative"),
                code=params.get("code"),
                start_line=params.get("start_line", 1),
                tracepoints=params.get("tracepoints"),
            ),
            "matlab/run/status": lambda **params: self._matlab.status_job(
                "run",
                params.get("job_id"),
                stdout_offset=self._offset(params.get("stdout_offset", 0), "stdout_offset"),
                stderr_offset=self._offset(params.get("stderr_offset", 0), "stderr_offset"),
            ),
            "matlab/run/stop": lambda **params: self._matlab.stop("run", params.get("job_id")),
        }
        try:
            method = methods.get(message["method"])
            if method is None:
                reply = error(identifier, -32601, "method not found")
            elif not isinstance(message.get("params", {}), dict):
                reply = error(identifier, -32602, "params must be an object")
            else:
                result = method(**message.get("params", {}))
                reply = {"jsonrpc": "2.0", "id": identifier, "result": result}
        except DocumentConflict as exc:
            reply = error(identifier, -32009, str(exc), "conflict")
        except (TypeError, ValueError, UnicodeError) as exc:
            reply = error(identifier, -32602, str(exc), "invalid_params")
        except OSError as exc:
            reply = error(identifier, -32010, str(exc), "io")
        except RuntimeError as exc:
            reply = error(identifier, -32020, str(exc), "matlab_runtime")
        except Exception:  # noqa: BLE001 - isolate unexpected faults at the RPC boundary.
            reply = error(identifier, -32603, "internal backend error")
        return reply if "id" in message else None

    def initialize(self) -> dict:
        return {
            "protocol_version": 1,
            "root": str(self.root),
            "initial_file": self.initial_file,
            "capabilities": [
                "workspace.listDirectory",
                "document.read",
                "document.save",
                "model/inspect",
                "model/viewport",
                "model/diff",
                "model/applyEdit",
                "matlab/status",
                "matlab/command/start",
                "matlab/command/status",
                "matlab/command/stop",
                "matlab/run/start",
                "matlab/run/status",
                "matlab/run/stop",
            ],
            "matlab_started": self._matlab.status()["state"] == "ready",
        }


def _strict_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def serve(backend: Backend, source: BinaryIO, sink: BinaryIO) -> None:
    try:
        while True:
            try:
                payload = read_frame(source)
            except FrameError:
                # Framing cannot be resynchronized safely: one error, then terminate.
                write_frame(sink, error(None, -32700, "invalid frame"))
                return
            if payload is None:
                return
            try:
                message = json.loads(
                    payload, object_pairs_hook=_strict_object, parse_constant=_invalid_constant
                )
            except (ValueError, UnicodeError, RecursionError):
                reply = error(None, -32700, "invalid JSON")
            else:
                reply = backend.dispatch(message)
            if reply is not None:
                try:
                    write_frame(sink, reply)
                except FrameError:
                    identifier = message.get("id") if isinstance(message, dict) else None
                    write_frame(sink, error(identifier, -32011, "response exceeds size limit"))
    finally:
        backend.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    serve(Backend(args.workspace), sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    main()
