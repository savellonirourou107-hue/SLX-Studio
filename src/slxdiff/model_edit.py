from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .blueprint import BLOCK_CATALOG
from .model import Model
from .patching import sha256_file
from .slx_path import join_path, parent_path

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
        result.append(round(float(item)))
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
            ops.append({
                "op": op,
                "block_path": _text(raw.get("block_path", ""), field="block_path", max_chars=1024),
                "parameter": _text(raw.get("parameter", ""), field="parameter", max_chars=128),
                "before": _text(raw.get("before", ""), field="before"),
                "after": _text(raw.get("after", ""), field="after"),
                "sid": _text(raw.get("sid", ""), field="sid", max_chars=128),
            })
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
            ops.append({"op": op, "block_type": block_type, "name": name, "parent": parent, "position": _position(raw.get("position", [100, 100, 160, 140])), "parameters": clean_params})
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
            ops.append({
                "op": op,
                "system_path": _text(raw.get("system_path", ""), field="system_path", max_chars=1024),
                "src_path": _text(raw.get("src_path", ""), field="src_path", max_chars=1024),
                "src_port": _port(raw.get("src_port", 1), field="src_port"),
                "dst_path": _text(raw.get("dst_path", ""), field="dst_path", max_chars=1024),
                "dst_port": _port(raw.get("dst_port", 1), field="dst_port"),
            })
        else:
            raise ValueError(f"unsupported model edit operation {op!r}")
    return ModelEditDocument(version, model_name, source_sha256, tuple(ops))


def validate_edit_document(document: ModelEditDocument, model: Model, *, source_path: str | Path) -> None:
    if document.model_name and document.model_name != model.name:
        raise ValueError(f"edit targets model {document.model_name!r}, not {model.name!r}")
    if sha256_file(source_path) != document.source_sha256:
        raise ValueError("source model changed on disk; reload before editing")

    blocks = {block.path: block for block in model.blocks.values()}
    names = set(blocks)
    for op in document.operations:
        kind = op["op"]
        if kind == "set_param":
            block = blocks.get(op["block_path"])
            if block is None:
                raise ValueError(f"block no longer exists: {op['block_path']}")
            if op.get("sid") and block.sid != op["sid"]:
                raise ValueError(f"SID mismatch for {op['block_path']}")
            current = block.parameters.get(op["parameter"])
            if current is None:
                raise ValueError(f"parameter {op['parameter']!r} is unavailable on {op['block_path']}")
            if current != op["before"]:
                raise ValueError(f"parameter conflict at {op['block_path']}/{op['parameter']}")
        elif kind == "add_block":
            path = join_path(op["parent"], op["name"])
            if path in names:
                raise ValueError(f"block already exists: {path}")
            names.add(path)
        elif kind in {"delete_block", "rename_block", "move_block"}:
            path = op["block_path"]
            block = blocks.get(path)
            if block is None or path not in names:
                raise ValueError(f"block no longer exists: {path}")
            if op.get("sid") and block.sid != op["sid"]:
                raise ValueError(f"SID mismatch for {path}")
            if kind == "move_block":
                raw_position = block.parameters.get("Position", "")
                numbers = [round(float(x)) for x in re.findall(r"[-+]?\d+(?:\.\d+)?", raw_position)]
                if len(numbers) != 4 or numbers != op["before_position"]:
                    raise ValueError(f"position conflict at {path}")
            else:
                names.remove(path)
                if kind == "rename_block":
                    parent = parent_path(path)
                    renamed = join_path(parent, op["new_name"])
                    if renamed in names:
                        raise ValueError(f"block already exists: {renamed}")
                    names.add(renamed)
        elif kind in {"add_line", "delete_line"}:
            if op["src_path"] not in names or op["dst_path"] not in names:
                raise ValueError("connection endpoint does not exist")


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
