from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Iterable

from .diff import BlockChange, DiffResult, ParameterChange, compare_models
from .model import Block, Line, Model

_ENDPOINT_RE = re.compile(r"^(?P<path>.*):(in|out)\d+$")
_SIMPLE_NUMBER_RE = re.compile(r"^\s*[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?\s*$")

# These are review-priority hints, not claims about control-system safety.
_TEMPORAL_PARAMETERS = {"SampleTime", "Ts", "SampleTimeMath"}
_DATA_TYPE_PARAMETERS = {
    "OutDataTypeStr",
    "DataType",
    "OutputDataType",
    "AccumulatorDataTypeStr",
    "ProductOutputDataTypeStr",
}
_LIMIT_PARAMETERS = {
    "UpperLimit",
    "LowerLimit",
    "Threshold",
    "SwitchThreshold",
    "SaturationUpperLimit",
    "SaturationLowerLimit",
}
_INITIAL_PARAMETERS = {"InitialCondition", "InitialOutput", "X0"}
_GAIN_PARAMETERS = {"Gain", "Kp", "Ki", "Kd"}
_OUTPORT_TYPES = {"Outport"}
_TERMINAL_TYPES = {"Outport", "ToWorkspace", "Scope", "Display", "Terminator"}


@dataclass(frozen=True)
class ReviewReason:
    code: str
    weight: int
    detail: str = ""


@dataclass
class ReviewItem:
    block_path: str
    block_type: str
    status: str
    score: int = 0
    priority: str = "low"
    changed_parameters: list[str] = field(default_factory=list)
    connection_changes: int = 0
    direct_consumers: list[str] = field(default_factory=list)
    downstream_blocks: list[str] = field(default_factory=list)
    affected_outports: list[str] = field(default_factory=list)
    affected_terminals: list[str] = field(default_factory=list)
    reasons: list[ReviewReason] = field(default_factory=list)


@dataclass
class ReviewReport:
    old_name: str
    new_name: str
    change_count: int
    items: list[ReviewItem] = field(default_factory=list)

    @property
    def priority_counts(self) -> dict[str, int]:
        counts = {"high": 0, "medium": 0, "low": 0}
        for item in self.items:
            counts[item.priority] = counts.get(item.priority, 0) + 1
        return counts

    @property
    def max_priority(self) -> str:
        counts = self.priority_counts
        if counts.get("high"):
            return "high"
        if counts.get("medium"):
            return "medium"
        return "low"


def _endpoint_path(endpoint: str) -> str:
    match = _ENDPOINT_RE.match(str(endpoint))
    return match.group("path") if match else str(endpoint)


def _graph(model: Model) -> tuple[dict[str, set[str]], dict[str, Block]]:
    by_path = {block.path: block for block in model.blocks.values()}
    outgoing: dict[str, set[str]] = {path: set() for path in by_path}
    for line in model.lines:
        src = _endpoint_path(line.src)
        dst = _endpoint_path(line.dst)
        if src in outgoing and dst in by_path:
            outgoing[src].add(dst)
    return outgoing, by_path


def _downstream(start: str, outgoing: dict[str, set[str]]) -> list[str]:
    seen: set[str] = set()
    queue = list(sorted(outgoing.get(start, ())))
    while queue:
        path = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)
        queue.extend(sorted(outgoing.get(path, ())))
    return sorted(seen)


def _as_number(value: str | None) -> float | None:
    if value is None or not _SIMPLE_NUMBER_RE.match(value):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _magnitude_reason(change: ParameterChange) -> ReviewReason | None:
    before = _as_number(change.before)
    after = _as_number(change.after)
    if before is None or after is None or before == after:
        return None
    if before == 0:
        if abs(after) >= 1:
            return ReviewReason("numeric_scale_jump", 7, change.name)
        return None
    ratio = abs(after / before)
    sign_flip = before * after < 0
    if sign_flip:
        return ReviewReason("numeric_sign_flip", 10, change.name)
    if ratio >= 3 or ratio <= 1 / 3:
        return ReviewReason("numeric_scale_jump", 7, change.name)
    return None


def _parameter_reasons(changes: Iterable[ParameterChange]) -> list[ReviewReason]:
    reasons: list[ReviewReason] = []
    for change in changes:
        name = change.name
        if name in _TEMPORAL_PARAMETERS:
            reasons.append(ReviewReason("sample_time_changed", 32, name))
        elif name in _DATA_TYPE_PARAMETERS or "DataType" in name:
            reasons.append(ReviewReason("data_type_changed", 28, name))
        elif name in _LIMIT_PARAMETERS or "Limit" in name or "Threshold" in name:
            reasons.append(ReviewReason("limit_changed", 17, name))
        elif name in _INITIAL_PARAMETERS or name.startswith("Initial"):
            reasons.append(ReviewReason("initial_condition_changed", 12, name))
        elif name in _GAIN_PARAMETERS or name.endswith("Gain"):
            reasons.append(ReviewReason("gain_changed", 11, name))
        else:
            reasons.append(ReviewReason("parameter_changed", 4, name))
        magnitude = _magnitude_reason(change)
        if magnitude is not None:
            reasons.append(magnitude)
    return reasons


def _priority(score: int) -> str:
    if score >= 55:
        return "high"
    if score >= 28:
        return "medium"
    return "low"


def _block_change_maps(result: DiffResult) -> tuple[dict[str, BlockChange], dict[str, BlockChange]]:
    before = {change.before.path: change for change in result.changed_blocks}
    after = {change.after.path: change for change in result.changed_blocks}
    return before, after


def _changed_connection_counts(result: DiffResult) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in [*result.added_lines, *result.removed_lines]:
        for path in {_endpoint_path(line.src), _endpoint_path(line.dst)}:
            counts[path] = counts.get(path, 0) + 1
    return counts


def build_review_report(old: Model, new: Model) -> ReviewReport:
    """Build an explainable static review-priority report from signal-flow changes.

    The report deliberately avoids claiming formal safety or dynamic impact. It only
    prioritizes human review using observable structural/parameter changes and the
    downstream signal-flow graph present in the SLX package.
    """
    result = compare_models(old, new, include_layout=False)
    old_graph, old_by_path = _graph(old)
    new_graph, new_by_path = _graph(new)
    changed_before, changed_after = _block_change_maps(result)
    connection_counts = _changed_connection_counts(result)

    candidates: dict[str, tuple[str, Block]] = {}
    for block in result.added_blocks:
        candidates[block.path] = ("added", block)
    for block in result.removed_blocks:
        candidates[block.path] = ("removed", block)
    for change in result.changed_blocks:
        candidates[change.after.path] = ("changed", change.after)
    # Pure rewires should still receive a review card even if block parameters did not change.
    for path in connection_counts:
        if path not in candidates:
            block = new_by_path.get(path) or old_by_path.get(path)
            if block is not None:
                candidates[path] = ("rewired", block)

    items: list[ReviewItem] = []
    for path, (status, block) in candidates.items():
        change = changed_after.get(path) or changed_before.get(path)

        # Review impact uses both the before and after signal-flow views for edits and
        # rewires. A deleted edge can matter precisely because the current graph no
        # longer reaches the consumer that used to receive the signal.
        if status == "removed":
            graph_views = [(path, old_graph, old_by_path)]
        elif status == "added":
            graph_views = [(path, new_graph, new_by_path)]
        elif change is not None:
            graph_views = [
                (change.before.path, old_graph, old_by_path),
                (change.after.path, new_graph, new_by_path),
            ]
        else:
            graph_views = [
                (path, old_graph, old_by_path),
                (path, new_graph, new_by_path),
            ]

        downstream_set: set[str] = set()
        direct_set: set[str] = set()
        outport_set: set[str] = set()
        terminal_set: set[str] = set()
        for start, graph, by_path in graph_views:
            view_downstream = _downstream(start, graph)
            downstream_set.update(view_downstream)
            direct_set.update(graph.get(start, ()))
            outport_set.update(
                candidate
                for candidate in view_downstream
                if by_path.get(candidate) and by_path[candidate].block_type in _OUTPORT_TYPES
            )
            terminal_set.update(
                candidate
                for candidate in view_downstream
                if by_path.get(candidate) and by_path[candidate].block_type in _TERMINAL_TYPES
            )

        downstream = sorted(downstream_set)
        direct = sorted(direct_set)
        outports = sorted(outport_set)
        terminals = sorted(terminal_set)

        reasons: list[ReviewReason] = []
        if status == "added":
            reasons.append(ReviewReason("block_added", 16, block.block_type))
        elif status == "removed":
            reasons.append(ReviewReason("block_removed", 30, block.block_type))
        elif status == "rewired":
            reasons.append(ReviewReason("connection_changed", 12, str(connection_counts.get(path, 0))))

        changed_parameters: list[str] = []
        if change is not None:
            if change.type_changed:
                reasons.append(ReviewReason("block_type_changed", 30, f"{change.before.block_type} -> {change.after.block_type}"))
            if change.renamed:
                reasons.append(ReviewReason("block_renamed", 3, f"{change.before.name} -> {change.after.name}"))
            changed_parameters = [item.name for item in change.parameter_changes]
            reasons.extend(_parameter_reasons(change.parameter_changes))

        connection_paths = {path}
        if change is not None:
            connection_paths.update({change.before.path, change.after.path})
        connection_changes = sum(connection_counts.get(candidate, 0) for candidate in connection_paths)
        if connection_changes and status != "rewired":
            reasons.append(ReviewReason("connection_changed", min(14, 5 + connection_changes * 3), str(connection_changes)))
        if downstream:
            reasons.append(ReviewReason("downstream_reach", min(18, 4 + len(downstream) * 2), str(len(downstream))))
        if outports:
            reasons.append(ReviewReason("reaches_outport", min(22, 12 + (len(outports) - 1) * 5), str(len(outports))))

        # Avoid one noisy class of generic parameter changes dominating the score.
        score = min(100, sum(reason.weight for reason in reasons))
        item = ReviewItem(
            block_path=path,
            block_type=block.block_type,
            status=status,
            score=score,
            priority=_priority(score),
            changed_parameters=changed_parameters,
            connection_changes=connection_changes,
            direct_consumers=direct,
            downstream_blocks=downstream,
            affected_outports=outports,
            affected_terminals=terminals,
            reasons=reasons,
        )
        items.append(item)

    items.sort(key=lambda item: (-item.score, item.block_path.lower()))
    return ReviewReport(old.name, new.name, result.change_count, items)


def review_to_dict(report: ReviewReport) -> dict:
    return {
        "schema_version": "0.1",
        "kind": "slx-review-intelligence",
        "old_name": report.old_name,
        "new_name": report.new_name,
        "change_count": report.change_count,
        "max_priority": report.max_priority,
        "priority_counts": report.priority_counts,
        "items": [asdict(item) for item in report.items],
        "disclaimer": (
            "Review priority is a deterministic static heuristic based on SLX structure and signal flow; "
            "it is not a safety, stability, or simulation result."
        ),
    }


def render_review_json(report: ReviewReport) -> str:
    return json.dumps(review_to_dict(report), indent=2, ensure_ascii=False)


def render_review_text(report: ReviewReport) -> str:
    counts = report.priority_counts
    lines = [
        f"SLX review intelligence: {report.old_name} -> {report.new_name}",
        f"Review priority: {report.max_priority.upper()} · {counts['high']} high / {counts['medium']} medium / {counts['low']} low",
        "",
    ]
    if not report.items:
        lines.append("No review hotspots found.")
        return "\n".join(lines)
    for item in report.items:
        lines.append(f"[{item.priority.upper():6}] {item.score:3}/100  {item.block_path} [{item.status}]")
        lines.append(
            f"         downstream={len(item.downstream_blocks)} outports={len(item.affected_outports)} connection_changes={item.connection_changes}"
        )
        for reason in item.reasons:
            detail = f" ({reason.detail})" if reason.detail else ""
            lines.append(f"         - {reason.code} +{reason.weight}{detail}")
    lines.extend(["", "Static review heuristic only; not a safety/stability verdict."])
    return "\n".join(lines)


def render_review_markdown(report: ReviewReport) -> str:
    counts = report.priority_counts
    emoji = {"high": "🔴", "medium": "🟠", "low": "🟢"}
    out = [
        "## SLX review intelligence",
        "",
        f"**{report.old_name} → {report.new_name}** · {emoji[report.max_priority]} **{report.max_priority.upper()} review priority**",
        "",
        f"{counts['high']} high · {counts['medium']} medium · {counts['low']} low hotspot(s)",
        "",
        "| Priority | Score | Block | Change | Downstream | Outports |",
        "|---|---:|---|---|---:|---:|",
    ]
    for item in report.items:
        out.append(
            f"| {emoji[item.priority]} {item.priority} | {item.score} | `{item.block_path}` | {item.status} | {len(item.downstream_blocks)} | {len(item.affected_outports)} |"
        )
    for item in report.items:
        out.extend(["", f"### `{item.block_path}`", ""])
        for reason in item.reasons:
            detail = f" — `{reason.detail}`" if reason.detail else ""
            out.append(f"- `{reason.code}` (+{reason.weight}){detail}")
        if item.affected_outports:
            out.append("- Affected outports: " + ", ".join(f"`{path}`" for path in item.affected_outports))
    out.extend(
        [
            "",
            "> Review priority is a deterministic static heuristic based on SLX structure and signal flow. It is not a safety, stability, or simulation result.",
        ]
    )
    return "\n".join(out)
