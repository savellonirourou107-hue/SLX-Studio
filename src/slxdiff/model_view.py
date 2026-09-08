"""Bounded, non-executing model viewport queries for the opt-in desktop."""

from __future__ import annotations

import json
import re
import stat
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .documents import DocumentConflict, document_path
from .parser import parse_slx
from .slx_path import parent_path

MAX_VIEW_BLOCKS = 160
MAX_VIEW_LINES = 512
MAX_VIEW_SYSTEMS = 512
MAX_LIST_BYTES = 2 * 1024 * 1024


def _bounded(records, limit: int) -> list[dict[str, Any]]:
    selected = []
    size = 2
    for record in records:
        encoded = json.dumps(record, ensure_ascii=False, allow_nan=False).encode("utf-8")
        size += len(encoded) + (2 if selected else 0)
        if size > MAX_LIST_BYTES or len(selected) == limit:
            break
        selected.append(record)
    return selected


def model_viewport(
    root: Path,
    relative: str,
    system_id: str | None = None,
    query: str = "",
    cursor: int = 0,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    if system_id is not None and (not isinstance(system_id, str) or len(system_id) > 4096):
        raise ValueError("system ID must be a bounded string")
    if not isinstance(query, str) or len(query) > 200:
        raise ValueError("block query must be a string of at most 200 characters")
    if isinstance(cursor, bool) or not isinstance(cursor, int) or not 0 <= cursor <= 1_000_000:
        raise ValueError("viewport cursor must be a bounded non-negative integer")
    if expected_sha256 is not None and (
        not isinstance(expected_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256)
    ):
        raise ValueError("invalid model version")
    path = document_path(root, relative)
    before = path.stat()
    if path.suffix.lower() != ".slx" or not stat.S_ISREG(before.st_mode):
        raise ValueError("viewport requires a regular .slx file")
    model = parse_slx(path)
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise DocumentConflict("Model changed while reading; reload the model.")
    version = model.metadata["sha256"]
    if expected_sha256 is not None and expected_sha256 != version:
        raise DocumentConflict("Model changed on disk; reload before navigating further.")

    grouped = defaultdict(list)
    for block in model.blocks.values():
        grouped[block.system_id].append(block)
    systems = sorted(
        (
            {"id": identifier, "label": parent_path(blocks[0].path) or "Root", "blocks": len(blocks)}
            for identifier, blocks in grouped.items()
        ),
        key=lambda item: (item["label"] != "Root", item["label"].casefold(), item["id"]),
    )
    selected_system = system_id if system_id is not None else (systems[0]["id"] if systems else "")
    if selected_system not in grouped and systems:
        raise ValueError("unknown model subsystem")
    system_blocks = grouped[selected_system]
    search = query.casefold().strip()
    matches = sorted(
        (
            block
            for block in system_blocks
            if not search
            or any(
                search in value.casefold() for value in (block.name, block.path, block.block_type, block.sid)
            )
        ),
        key=lambda block: (block.name.casefold(), block.sid),
    )
    blocks = _bounded(
        (asdict(block) for block in matches[cursor : cursor + MAX_VIEW_BLOCKS]), MAX_VIEW_BLOCKS
    )
    if cursor < len(matches) and not blocks:
        raise ValueError("A block exceeds the 2 MiB viewport limit; use the legacy inspector.")
    visible = {block["path"] for block in blocks}
    system_lines = sorted(line for line in model.lines if line.system_id == selected_system)
    lines = _bounded(
        (
            asdict(line)
            for line in system_lines
            if line.src.rsplit(":", 1)[0] in visible and line.dst.rsplit(":", 1)[0] in visible
        ),
        MAX_VIEW_LINES,
    )
    visible_systems = _bounded(iter(systems), MAX_VIEW_SYSTEMS)
    end = cursor + len(blocks)
    return {
        "schema_version": "0.5",
        "name": model.name,
        "sha256": version,
        "metadata": model.metadata,
        "systems": visible_systems,
        "total_systems": len(systems),
        "systems_truncated": len(visible_systems) < len(systems),
        "system_id": selected_system,
        "total_blocks": len(model.blocks),
        "total_lines": len(model.lines),
        "system_blocks": len(system_blocks),
        "system_lines": len(system_lines),
        "matched_blocks": len(matches),
        "cursor": cursor,
        "next_cursor": end if end < len(matches) else None,
        "blocks": blocks,
        "lines": lines,
        "omitted_lines": len(system_lines) - len(lines),
    }
