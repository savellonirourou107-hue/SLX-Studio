from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .model import Model

PATCH_SCHEMA_VERSION = "0.1"
_MAX_OPERATIONS = 500
_MAX_VALUE_CHARS = 100_000


@dataclass(frozen=True)
class PatchOperation:
    """One explicit, conflict-detecting edit to a Simulink block parameter."""

    op: str
    block_path: str
    parameter: str
    before: str
    after: str
    sid: str = ""
    system_id: str = ""


@dataclass(frozen=True)
class PatchDocument:
    """Portable edit plan emitted by SLX Studio and consumable by the MATLAB bridge."""

    schema_version: str
    model_name: str
    source_sha256: str
    operations: tuple[PatchOperation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "model_name": self.model_name,
            "source_sha256": self.source_sha256,
            "operations": [asdict(item) for item in self.operations],
        }


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _string(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"patch field {field!r} must be a string")
    if len(value) > _MAX_VALUE_CHARS:
        raise ValueError(f"patch field {field!r} is too large")
    return value


def patch_from_dict(payload: dict[str, Any]) -> PatchDocument:
    if not isinstance(payload, dict):
        raise TypeError("patch must be a JSON object")
    version = _string(payload.get("schema_version", ""), field="schema_version")
    if version != PATCH_SCHEMA_VERSION:
        raise ValueError(f"unsupported patch schema {version!r}; expected {PATCH_SCHEMA_VERSION!r}")
    model_name = _string(payload.get("model_name", ""), field="model_name")
    source_sha256 = _string(payload.get("source_sha256", ""), field="source_sha256").lower()
    if len(source_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in source_sha256):
        raise ValueError("source_sha256 must be a 64-character hexadecimal SHA-256")
    raw_ops = payload.get("operations")
    if not isinstance(raw_ops, list):
        raise TypeError("operations must be a JSON array")
    if len(raw_ops) > _MAX_OPERATIONS:
        raise ValueError(f"patch has too many operations (max {_MAX_OPERATIONS})")

    operations: list[PatchOperation] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(raw_ops):
        if not isinstance(item, dict):
            raise TypeError(f"operation {index} must be an object")
        op = _string(item.get("op", ""), field=f"operations[{index}].op")
        if op != "set_param":
            raise ValueError(f"unsupported operation {op!r}; only 'set_param' is supported")
        block_path = _string(item.get("block_path", ""), field=f"operations[{index}].block_path")
        parameter = _string(item.get("parameter", ""), field=f"operations[{index}].parameter")
        before = _string(item.get("before", ""), field=f"operations[{index}].before")
        after = _string(item.get("after", ""), field=f"operations[{index}].after")
        sid = _string(item.get("sid", ""), field=f"operations[{index}].sid")
        system_id = _string(item.get("system_id", ""), field=f"operations[{index}].system_id")
        if not block_path.strip():
            raise ValueError(f"operation {index} has an empty block_path")
        if not parameter.strip():
            raise ValueError(f"operation {index} has an empty parameter")
        if before == after:
            continue
        key = (block_path, parameter)
        if key in seen:
            raise ValueError(f"duplicate set_param operation for {block_path!r} / {parameter!r}")
        seen.add(key)
        operations.append(
            PatchOperation(
                op="set_param",
                block_path=block_path,
                parameter=parameter,
                before=before,
                after=after,
                sid=sid,
                system_id=system_id,
            )
        )

    return PatchDocument(
        schema_version=version,
        model_name=model_name,
        source_sha256=source_sha256,
        operations=tuple(operations),
    )


def load_patch(path: str | Path) -> PatchDocument:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid patch JSON: {exc}") from exc
    return patch_from_dict(payload)


def write_patch(patch: PatchDocument, path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(patch.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return output


def validate_patch_for_model(
    patch: PatchDocument,
    model: Model,
    *,
    source_path: str | Path | None = None,
    require_hash: bool = True,
) -> None:
    """Fail before MATLAB is launched if the patch no longer matches the source model."""
    if patch.model_name and patch.model_name != model.name:
        raise ValueError(f"patch targets model {patch.model_name!r}, not {model.name!r}")
    if require_hash and source_path is not None:
        actual = sha256_file(source_path)
        if actual != patch.source_sha256:
            raise ValueError("source model SHA-256 does not match the patch; regenerate or rebase the patch")

    by_path = {block.path: block for block in model.blocks.values()}
    for item in patch.operations:
        block = by_path.get(item.block_path)
        if block is None:
            raise ValueError(f"patch target block no longer exists: {item.block_path}")
        if item.sid and block.sid != item.sid:
            raise ValueError(f"SID mismatch for {item.block_path}: patch={item.sid}, model={block.sid}")
        current = block.parameters.get(item.parameter)
        if current is None:
            raise ValueError(f"parameter {item.parameter!r} is not present on {item.block_path}")
        if current != item.before:
            raise ValueError(
                f"patch conflict at {item.block_path}/{item.parameter}: expected {item.before!r}, found {current!r}"
            )


def build_patch_document(
    model: Model,
    operations: Iterable[PatchOperation],
    *,
    source_sha256: str,
) -> PatchDocument:
    return PatchDocument(
        schema_version=PATCH_SCHEMA_VERSION,
        model_name=model.name,
        source_sha256=source_sha256,
        operations=tuple(operations),
    )
