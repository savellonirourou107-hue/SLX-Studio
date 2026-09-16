from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .slx_path import parent_path


@dataclass(frozen=True)
class Block:
    """A normalized Simulink block extracted from an SLX package."""

    system_id: str
    sid: str
    name: str
    block_type: str
    path: str
    parameters: Mapping[str, str] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str]:
        return (self.system_id, self.sid)


@dataclass(frozen=True, order=True)
class Line:
    """A normalized signal connection."""

    system_id: str
    src: str
    dst: str
    name: str = ""


@dataclass
class Model:
    """A canonical, diff-friendly representation of an SLX model."""

    name: str
    blocks: dict[tuple[str, str], Block] = field(default_factory=dict)
    lines: set[Line] = field(default_factory=set)
    # Existing string metadata fields remain unchanged; parser diagnostics may
    # add arrays or nested JSON values without changing the canonical schema.
    metadata: dict[str, Any] = field(default_factory=dict)


def system_groups(model: Model) -> dict[str, tuple[str, list[Block]]]:
    """Group blocks for display, retaining navigable empty Subsystems.

    Synthetic empty IDs are display identities, not fabricated parser/SLX IDs.
    They disappear when a real child system can be identified after a save.
    """
    grouped: dict[str, tuple[str, list[Block]]] = {}
    for block in model.blocks.values():
        grouped.setdefault(block.system_id, (parent_path(block.path), []))[1].append(block)
    represented = {scope for scope, _ in grouped.values()}
    if "" not in represented:
        grouped["empty:root"] = ("", [])
    for block in model.blocks.values():
        if block.block_type == "SubSystem" and block.path not in represented:
            grouped[f"empty:{block.path}"] = (block.path, [])
    return grouped
