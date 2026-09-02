from __future__ import annotations

from dataclasses import dataclass, field

from .model import Block, Line, Model

LAYOUT_PARAMETERS = {
    "Position",
    "ZOrder",
    "Orientation",
    "ForegroundColor",
    "BackgroundColor",
    "DropShadow",
    "NamePlacement",
    "ShowName",
}


@dataclass(frozen=True)
class ParameterChange:
    name: str
    before: str | None
    after: str | None


@dataclass(frozen=True)
class BlockChange:
    before: Block
    after: Block
    parameter_changes: tuple[ParameterChange, ...] = ()

    @property
    def renamed(self) -> bool:
        return self.before.name != self.after.name

    @property
    def type_changed(self) -> bool:
        return self.before.block_type != self.after.block_type


@dataclass
class DiffResult:
    old_name: str
    new_name: str
    added_blocks: list[Block] = field(default_factory=list)
    removed_blocks: list[Block] = field(default_factory=list)
    changed_blocks: list[BlockChange] = field(default_factory=list)
    added_lines: list[Line] = field(default_factory=list)
    removed_lines: list[Line] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return any(
            (
                self.added_blocks,
                self.removed_blocks,
                self.changed_blocks,
                self.added_lines,
                self.removed_lines,
            )
        )

    @property
    def change_count(self) -> int:
        return sum(
            map(
                len,
                (
                    self.added_blocks,
                    self.removed_blocks,
                    self.changed_blocks,
                    self.added_lines,
                    self.removed_lines,
                ),
            )
        )


def _parameter_changes(before: Block, after: Block, include_layout: bool) -> tuple[ParameterChange, ...]:
    keys = sorted(set(before.parameters) | set(after.parameters))
    changes: list[ParameterChange] = []
    for key in keys:
        if not include_layout and key in LAYOUT_PARAMETERS:
            continue
        old = before.parameters.get(key)
        new = after.parameters.get(key)
        if old != new:
            changes.append(ParameterChange(key, old, new))
    return tuple(changes)


def compare_models(old: Model, new: Model, *, include_layout: bool = False) -> DiffResult:
    result = DiffResult(old_name=old.name, new_name=new.name)

    old_keys = set(old.blocks)
    new_keys = set(new.blocks)
    common = old_keys & new_keys
    unmatched_old = old_keys - common
    unmatched_new = new_keys - common

    # SLX SIDs are usually stable. If they are not, match same path + type as a fallback.
    fallback_new: dict[tuple[str, str], tuple[str, str]] = {}
    for key in unmatched_new:
        block = new.blocks[key]
        fallback_new[(block.path, block.block_type)] = key

    fallback_pairs: list[tuple[tuple[str, str], tuple[str, str]]] = []
    for old_key in list(unmatched_old):
        block = old.blocks[old_key]
        new_key = fallback_new.get((block.path, block.block_type))
        if new_key is not None:
            fallback_pairs.append((old_key, new_key))
            unmatched_old.remove(old_key)
            unmatched_new.remove(new_key)

    for key in sorted(unmatched_old):
        result.removed_blocks.append(old.blocks[key])
    for key in sorted(unmatched_new):
        result.added_blocks.append(new.blocks[key])

    matched_pairs = [(key, key) for key in sorted(common)] + fallback_pairs
    for old_key, new_key in matched_pairs:
        before = old.blocks[old_key]
        after = new.blocks[new_key]
        params = _parameter_changes(before, after, include_layout)
        if before.name != after.name or before.block_type != after.block_type or params:
            result.changed_blocks.append(BlockChange(before=before, after=after, parameter_changes=params))

    result.added_lines = sorted(new.lines - old.lines)
    result.removed_lines = sorted(old.lines - new.lines)
    return result
