"""Private, bounded JSON-RPC stdio adapter; no listeners or implicit execution."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, BinaryIO

from .documents import DocumentConflict, list_directory, read_document, save_document
from .workspace import workspace_root

MAX_FRAME_BYTES = 16 * 1024 * 1024


class FrameError(ValueError):
    pass


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
        except Exception:  # noqa: BLE001 - isolate unexpected faults at the RPC boundary.
            reply = error(identifier, -32603, "internal backend error")
        return reply if "id" in message else None

    def initialize(self) -> dict:
        return {
            "protocol_version": 1,
            "root": str(self.root),
            "initial_file": self.initial_file,
            "capabilities": ["workspace.listDirectory", "document.read", "document.save"],
            "matlab_started": False,
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
            message = json.loads(payload, object_pairs_hook=_strict_object, parse_constant=_invalid_constant)
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    serve(Backend(args.workspace), sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    main()
