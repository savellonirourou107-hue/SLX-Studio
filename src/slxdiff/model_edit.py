from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .blueprint import BLOCK_CATALOG
from .model import Block, Line, Model
from .patching import sha256_file
from .slx_path import join_path, parent_path, separator_indexes

EDIT_SCHEMA_VERSION = "0.1"
_NAME_RE = re.compile(r"^[^/\r\n\x00]{1,128}$")
_MAX_OPERATIONS = 100


@dataclass(frozen=True)
class ModelEditDocument:
    schema_version: str
    model_name: str
    source_sha256: str
    operations: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": "slx-model-edit",
            "model_name": self.model_name,
            "source_sha256": self.source_sha256,
            "operations": [dict(item) for item in self.operations],
        }


def _text(value: Any, *, field: str, max_chars: int = 4096) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    if len(value) > max_chars or "\x00" in value or "\r" in value or "\n" in value:
        raise ValueError(f"invalid {field}")
    return value


def _port(value: Any, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not (1 <= value <= 64):
        raise ValueError(f"{field} must be an integer between 1 and 64")
    return value


def _position(value: Any) -> list[int]:
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("position must be [left, top, right, bottom]")
    result: list[int] = []
    for item in value:
        if not isinstance(item, (int, float)) or isinstance(item, bool):
            raise TypeError("position values must be numeric")
        numeric = float(item)
        if not math.isfinite(numeric) or abs(numeric) > 1_000_000:
            raise ValueError("position values must be finite and bounded")
        result.append(round(numeric))
    if result[2] <= result[0] or result[3] <= result[1]:
        raise ValueError("position must have positive width and height")
    return result


def edit_document_from_dict(payload: dict[str, Any]) -> ModelEditDocument:
    if not isinstance(payload, dict):
        raise TypeError("model edit must be a JSON object")
    version = _text(payload.get("schema_version", ""), field="schema_version", max_chars=32)
    if version != EDIT_SCHEMA_VERSION:
        raise ValueError(f"unsupported model edit schema {version!r}")
    model_name = _text(payload.get("model_name", ""), field="model_name", max_chars=128)
    source_sha256 = _text(payload.get("source_sha256", ""), field="source_sha256", max_chars=64).lower()
    if len(source_sha256) != 64 or any(c not in "0123456789abcdef" for c in source_sha256):
        raise ValueError("source_sha256 must be a SHA-256 hexadecimal digest")
    raw_ops = payload.get("operations")
    if not isinstance(raw_ops, list) or not raw_ops:
        raise ValueError("model edit operations must be a non-empty array")
    if len(raw_ops) > _MAX_OPERATIONS:
        raise ValueError("too many model edit operations")

    ops: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_ops):
        if not isinstance(raw, dict):
            raise ValueError(f"operation {index} must be an object")  # noqa: TRY004 - preserve API validation errors
        op = _text(raw.get("op", ""), field=f"operations[{index}].op", max_chars=32)
        if op == "set_param":
            ops.append(
                {
                    "op": op,
                    "block_path": _text(raw.get("block_path", ""), field="block_path", max_chars=1024),
                    "parameter": _text(raw.get("parameter", ""), field="parameter", max_chars=128),
                    "before": _text(raw.get("before", ""), field="before"),
                    "after": _text(raw.get("after", ""), field="after"),
                    "sid": _text(raw.get("sid", ""), field="sid", max_chars=128),
                }
            )
        elif op == "add_block":
            block_type = _text(raw.get("block_type", ""), field="block_type", max_chars=64)
            if block_type not in BLOCK_CATALOG:
                raise ValueError(f"unsupported block type {block_type!r}")
            name = _text(raw.get("name", ""), field="name", max_chars=128).strip()
            if not _NAME_RE.fullmatch(name):
                raise ValueError("block name must be non-empty and may not contain '/'")
            parent = _text(raw.get("parent", ""), field="parent", max_chars=1024)
            params = raw.get("parameters", {})
            if not isinstance(params, dict):
                raise ValueError("add_block parameters must be an object")
            allowed = BLOCK_CATALOG[block_type].parameters
            clean_params: dict[str, str] = {}
            for key, value in params.items():
                key = _text(key, field="parameter", max_chars=128)
                if key not in allowed:
                    raise ValueError(f"parameter {key!r} is not allowed for {block_type!r}")
                clean_params[key] = _text(value, field=f"parameter {key}")
            ops.append(
                {
                    "op": op,
                    "block_type": block_type,
                    "name": name,
                    "parent": parent,
                    "position": _position(raw.get("position", [100, 100, 160, 140])),
                    "parameters": clean_params,
                }
            )
        elif op in {"delete_block", "rename_block", "move_block"}:
            item = {
                "op": op,
                "block_path": _text(raw.get("block_path", ""), field="block_path", max_chars=1024),
                "sid": _text(raw.get("sid", ""), field="sid", max_chars=128),
            }
            if op == "rename_block":
                name = _text(raw.get("new_name", ""), field="new_name", max_chars=128).strip()
                if not _NAME_RE.fullmatch(name):
                    raise ValueError("new block name must be non-empty and may not contain '/'")
                item["new_name"] = name
            elif op == "move_block":
                item["before_position"] = _position(raw.get("before_position"))
                item["position"] = _position(raw.get("position"))
            ops.append(item)
        elif op in {"add_line", "delete_line"}:
            ops.append(
                {
                    "op": op,
                    "system_path": _text(raw.get("system_path", ""), field="system_path", max_chars=1024),
                    "src_path": _text(raw.get("src_path", ""), field="src_path", max_chars=1024),
                    "src_port": _port(raw.get("src_port", 1), field="src_port"),
                    "dst_path": _text(raw.get("dst_path", ""), field="dst_path", max_chars=1024),
                    "dst_port": _port(raw.get("dst_port", 1), field="dst_port"),
                }
            )
        else:
            raise ValueError(f"unsupported model edit operation {op!r}")
    return ModelEditDocument(version, model_name, source_sha256, tuple(ops))


def _endpoint_parts(endpoint: str) -> tuple[str, str, int] | None:
    match = re.fullmatch(r"(?P<path>.*):(?P<kind>in|out)(?P<port>[0-9]+)", endpoint)
    if not match:
        return None
    return match.group("path"), match.group("kind"), int(match.group("port"))


def _replace_path_prefix(path: str, old: str, new: str) -> str:
    if path == old:
        return new
    prefix = f"{old}/"
    return f"{new}{path[len(old) :]}" if path.startswith(prefix) else path


def _replace_endpoint_prefix(endpoint: str, old: str, new: str) -> str:
    parts = _endpoint_parts(endpoint)
    if parts is None:
        return endpoint
    path, kind, port = parts
    return f"{_replace_path_prefix(path, old, new)}:{kind}{port}"


def _declared_port_count(block: Block, direction: str) -> int | None:
    names = (
        ("NumInputPorts", "Inputs", "Ports") if direction == "in" else ("NumOutputPorts", "Outputs", "Ports")
    )
    for name in names:
        raw = block.parameters.get(name)
        if raw is None:
            continue
        match = re.fullmatch(r"\s*([0-9]+)\s*", str(raw))
        if match:
            count = int(match.group(1))
            return max(0, count)
    return None


def validate_edit_document(document: ModelEditDocument, model: Model, *, source_path: str | Path) -> None:
    if document.model_name and document.model_name != model.name:
        raise ValueError(f"edit targets model {document.model_name!r}, not {model.name!r}")
    if sha256_file(source_path) != document.source_sha256:
        raise ValueError("source model changed on disk; reload before editing")

    blocks: dict[str, Block] = {block.path: block for block in model.blocks.values()}
    # Keep a virtual view while validating so rename/add/delete operations have
    # deterministic effects on every subsequent operation in one document.
    virtual_lines: set[Line] = set(model.lines)

    def require_block(path: str) -> Block:
        block = blocks.get(path)
        if block is None:
            raise ValueError(f"block no longer exists: {path}")
        return block

    def endpoint_block(path: str, *, role: str) -> Block:
        block = require_block(path)
        if role == "source" and block.block_type == "Outport":
            raise ValueError("source port direction is invalid; MATLAB further validation is required")
        if role == "target" and block.block_type == "Inport":
            raise ValueError("target port direction is invalid; MATLAB further validation is required")
        if block.block_type in {
            "BusSelector",
            "Demux",
            "Selector",
            "Switch",
            "MultiPortSwitch",
            "VariantSubsystem",
        }:
            raise ValueError("dynamic or conditional port semantics require MATLAB further validation")
        return block

    def ensure_context(system_path: str, src_path: str, dst_path: str, src: Block, dst: Block) -> None:
        if src.system_id != dst.system_id:
            raise ValueError("connection endpoints must belong to the same Simulink system")
        if system_path:
            prefix = f"{system_path}/"
            if not (src_path.startswith(prefix) and dst_path.startswith(prefix)):
                raise ValueError("connection endpoint is outside the requested system context")
        else:
            root_system = next(
                (item.system_id for item in model.blocks.values() if not separator_indexes(item.path)), None
            )
            if root_system is not None and src.system_id != root_system:
                raise ValueError("nested connection requires its explicit Subsystem context")

    def line_key(line: Line) -> tuple[str, str, int, str, int] | None:
        src = _endpoint_parts(line.src)
        dst = _endpoint_parts(line.dst)
        if src is None or dst is None:
            return None
        if src[1] != "out" or dst[1] != "in":
            return None
        return (line.system_id, src[0], src[2], dst[0], dst[2])

    for op in document.operations:
        kind = op["op"]
        if kind == "set_param":
            block = require_block(op["block_path"])
            if op.get("sid") and block.sid != op["sid"]:
                raise ValueError(f"SID mismatch for {op['block_path']}")
            current = block.parameters.get(op["parameter"])
            if current is None:
                raise ValueError(f"parameter {op['parameter']!r} is unavailable on {op['block_path']}")
            if current != op["before"]:
                raise ValueError(f"parameter conflict at {op['block_path']}/{op['parameter']}")
            blocks[op["block_path"]] = Block(
                system_id=block.system_id,
                sid=block.sid,
                name=block.name,
                block_type=block.block_type,
                path=block.path,
                parameters={**dict(block.parameters), op["parameter"]: op["after"]},
            )
        elif kind == "add_block":
            path = join_path(op["parent"], op["name"])
            if op["parent"]:
                parent = require_block(op["parent"])
                if parent.block_type != "SubSystem":
                    raise ValueError(
                        "add_block parent must be a Subsystem; MATLAB further validation is required"
                    )
            if path in blocks:
                raise ValueError(f"block already exists: {path}")
            if op["parent"]:
                # Child blocks parsed from a nested System carry the nested
                # system id; use it for subsequent in-subsystem connections.
                system_id = next(
                    (item.system_id for item in blocks.values() if item.path.startswith(f"{op['parent']}/")),
                    blocks[op["parent"]].system_id,
                )
            else:
                system_id = next((item.system_id for item in blocks.values()), "__pending_root__")
            blocks[path] = Block(
                system_id=system_id,
                sid=f"pending-{len(blocks) + 1}",
                name=op["name"],
                block_type=op["block_type"].title() if op["block_type"] != "saturation" else "Saturate",
                path=path,
                parameters={"Position": str(op["position"]), **dict(op.get("parameters", {}))},
            )
        elif kind in {"delete_block", "rename_block", "move_block"}:
            path = op["block_path"]
            block = require_block(path)
            if op.get("sid") and block.sid != op["sid"]:
                raise ValueError(f"SID mismatch for {path}")
            if kind == "move_block":
                raw_position = block.parameters.get("Position", "")
                try:
                    numbers = [round(float(x)) for x in re.findall(r"[-+]?\d+(?:\.\d+)?", raw_position)]
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ValueError(f"position is not parseable at {path}") from exc
                if len(numbers) != 4 or numbers != op["before_position"]:
                    raise ValueError(f"position conflict at {path}")
                blocks[path] = Block(
                    block.system_id,
                    block.sid,
                    block.name,
                    block.block_type,
                    path,
                    {**dict(block.parameters), "Position": str(op["position"])},
                )
            else:
                if kind == "rename_block":
                    parent = parent_path(path)
                    renamed = join_path(parent, op["new_name"])
                    affected = [item for item in blocks if item == path or item.startswith(f"{path}/")]
                    if renamed in blocks and renamed not in affected:
                        raise ValueError(f"block already exists: {renamed}")
                    moved: dict[str, Block] = {}
                    for old_path in affected:
                        item = blocks.pop(old_path)
                        new_path = _replace_path_prefix(old_path, path, renamed)
                        new_name = op["new_name"] if old_path == path else item.name
                        moved[new_path] = Block(
                            item.system_id,
                            item.sid,
                            new_name,
                            item.block_type,
                            new_path,
                            dict(item.parameters),
                        )
                    blocks.update(moved)
                    virtual_lines = {
                        Line(
                            line.system_id,
                            _replace_endpoint_prefix(line.src, path, renamed),
                            _replace_endpoint_prefix(line.dst, path, renamed),
                            line.name,
                        )
                        for line in virtual_lines
                    }
                else:
                    affected = [item for item in blocks if item == path or item.startswith(f"{path}/")]
                    for item in affected:
                        blocks.pop(item, None)
                    virtual_lines = {
                        line
                        for line in virtual_lines
                        if _endpoint_parts(line.src) is None
                        or (
                            _endpoint_parts(line.src)[0] not in affected
                            and _endpoint_parts(line.dst) is not None
                            and _endpoint_parts(line.dst)[0] not in affected
                        )
                    }
        elif kind in {"add_line", "delete_line"}:
            src = endpoint_block(op["src_path"], role="source")
            dst = endpoint_block(op["dst_path"], role="target")
            ensure_context(op["system_path"], op["src_path"], op["dst_path"], src, dst)
            src_count = _declared_port_count(src, "out")
            dst_count = _declared_port_count(dst, "in")
            if src_count is not None and op["src_port"] > src_count:
                raise ValueError("source port is outside the declared port range")
            if dst_count is not None and op["dst_port"] > dst_count:
                raise ValueError("target port is outside the declared port range")
            if op["src_path"] == op["dst_path"]:
                raise ValueError("self-connections are not allowed")
            key = (src.system_id, op["src_path"], op["src_port"], op["dst_path"], op["dst_port"])
            existing = {item for line in virtual_lines if (item := line_key(line)) is not None}
            if kind == "add_line":
                if key in existing:
                    raise ValueError("duplicate connection is not allowed")
                virtual_lines.add(
                    Line(
                        src.system_id,
                        f"{op['src_path']}:out{op['src_port']}",
                        f"{op['dst_path']}:in{op['dst_port']}",
                    )
                )
            elif key not in existing:
                raise ValueError("connection to delete does not exist")
            else:
                virtual_lines = {line for line in virtual_lines if line_key(line) != key}


def build_single_edit(model: Model, source_path: str | Path, operation: dict[str, Any]) -> ModelEditDocument:
    payload = {
        "schema_version": EDIT_SCHEMA_VERSION,
        "model_name": model.name,
        "source_sha256": sha256_file(source_path),
        "operations": [operation],
    }
    document = edit_document_from_dict(payload)
    validate_edit_document(document, model, source_path=source_path)
    return document


def write_edit_document(document: ModelEditDocument, path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output
