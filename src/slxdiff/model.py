from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


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
