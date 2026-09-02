from __future__ import annotations

import json
from dataclasses import asdict

from .diff import DiffResult


def _clip(value: str | None, max_len: int = 100) -> str:
    if value is None:
        return "∅"
    value = value.replace("\n", "\\n")
    if len(value) <= max_len:
        return value
    return value[: max_len - 1] + "…"


def _code(value: str | None) -> str:
    """Render untrusted model text as a safe Markdown code span."""
    text = _clip(value).replace("`", "ˋ")
    return f"`{text}`"


def _count_label(count: int, singular: str, plural: str | None = None) -> str:
    word = singular if count == 1 else (plural or singular + "s")
    return f"{count} {word}"


def render_text(result: DiffResult) -> str:
    if not result.changed:
        return f"No semantic changes: {result.old_name} → {result.new_name}"

    lines = [f"SLX semantic diff: {result.old_name} → {result.new_name}", ""]
    if result.added_blocks:
        lines.append(f"Added blocks ({len(result.added_blocks)}):")
        lines.extend(f"  + {b.path} [{b.block_type}]" for b in result.added_blocks)
    if result.removed_blocks:
        lines.append(f"Removed blocks ({len(result.removed_blocks)}):")
        lines.extend(f"  - {b.path} [{b.block_type}]" for b in result.removed_blocks)
    if result.changed_blocks:
        lines.append(f"Changed blocks ({len(result.changed_blocks)}):")
        for change in result.changed_blocks:
            before, after = change.before, change.after
            lines.append(f"  ~ {before.path} [{before.block_type}]")
            if change.renamed:
                lines.append(f"      name: {_clip(before.name)} -> {_clip(after.name)}")
            if change.type_changed:
                lines.append(f"      type: {_clip(before.block_type)} -> {_clip(after.block_type)}")
            for param in change.parameter_changes:
                lines.append(f"      {param.name}: {_clip(param.before)} -> {_clip(param.after)}")
    if result.added_lines:
        lines.append(f"Added connections ({len(result.added_lines)}):")
        lines.extend(f"  + {line.src} -> {line.dst}" for line in result.added_lines)
    if result.removed_lines:
        lines.append(f"Removed connections ({len(result.removed_lines)}):")
        lines.extend(f"  - {line.src} -> {line.dst}" for line in result.removed_lines)
    return "\n".join(lines)


def render_markdown(result: DiffResult, *, heading_level: int = 2) -> str:
    h = "#" * heading_level
    status = (
        "✅ No semantic changes"
        if not result.changed
        else f"🔎 {result.change_count} semantic change(s)"
    )
    out = [
        f"{h} SLX semantic diff",
        "",
        f"**{_code(result.old_name)} → {_code(result.new_name)}** · {status}",
        "",
    ]
    if not result.changed:
        return "\n".join(out)

    out.extend([
        "| Kind | Count |",
        "|---|---:|",
        f"| Added blocks | {len(result.added_blocks)} |",
        f"| Removed blocks | {len(result.removed_blocks)} |",
        f"| Changed blocks | {len(result.changed_blocks)} |",
        f"| Added connections | {len(result.added_lines)} |",
        f"| Removed connections | {len(result.removed_lines)} |",
        "",
    ])

    if result.added_blocks:
        out.extend([f"{h}# Added blocks", ""])
        out.extend(f"- `+` {_code(b.path)} — {_code(b.block_type)}" for b in result.added_blocks)
        out.append("")
    if result.removed_blocks:
        out.extend([f"{h}# Removed blocks", ""])
        out.extend(f"- `-` {_code(b.path)} — {_code(b.block_type)}" for b in result.removed_blocks)
        out.append("")
    if result.changed_blocks:
        out.extend([f"{h}# Changed blocks", ""])
        for change in result.changed_blocks:
            out.append(f"- `~` **{_code(change.before.path)}**")
            if change.renamed:
                out.append(f"  - name: {_code(change.before.name)} → {_code(change.after.name)}")
            if change.type_changed:
                out.append(
                    f"  - type: {_code(change.before.block_type)} → {_code(change.after.block_type)}"
                )
            for param in change.parameter_changes:
                out.append(f"  - {_code(param.name)}: {_code(param.before)} → {_code(param.after)}")
        out.append("")
    if result.added_lines:
        out.extend([f"{h}# Added connections", ""])
        out.extend(f"- `+` {_code(line.src)} → {_code(line.dst)}" for line in result.added_lines)
        out.append("")
    if result.removed_lines:
        out.extend([f"{h}# Removed connections", ""])
        out.extend(f"- `-` {_code(line.src)} → {_code(line.dst)}" for line in result.removed_lines)
        out.append("")
    return "\n".join(out).rstrip()


def render_git_markdown(diffs) -> str:
    """Render a complete pull-request report for a sequence of GitModelDiff objects."""
    changed = [item for item in diffs if item.result.changed]
    total = sum(item.result.change_count for item in changed)
    if not diffs:
        return "## slx-diff review\n\n✅ No `.slx` files changed in this diff."

    out = [
        "## slx-diff review",
        "",
        (
            f"**{_count_label(len(diffs), 'model')} inspected · "
            f"{_count_label(total, 'semantic change')}**"
        ),
        "",
        "| Model | Git status | Semantic changes | Review priority |",
        "|---|:---:|---:|:---:|",
    ]
    priority_icon = {"high": "🔴", "medium": "🟠", "low": "🟢"}
    for item in diffs:
        priority = item.review.max_priority if item.result.changed else "low"
        review_label = f"{priority_icon[priority]} {priority}" if item.result.changed else "—"
        out.append(f"| {_code(item.display_path)} | `{item.status}` | {item.result.change_count} | {review_label} |")

    for item in diffs:
        out.extend([
            "",
            "<details open>",
            (
                f"<summary><strong>{_code(item.display_path)}</strong> · "
                f"{_count_label(item.result.change_count, 'change')}</summary>"
            ),
            "",
            render_markdown(item.result, heading_level=3),
            "",
        ])
        if item.review.items:
            out.extend(["#### Review hotspots", ""])
            for hotspot in item.review.items[:5]:
                icon = priority_icon[hotspot.priority]
                out.append(
                    f"- {icon} **{hotspot.score}/100** {_code(hotspot.block_path)} · "
                    f"{len(hotspot.downstream_blocks)} downstream · "
                    f"{len(hotspot.affected_outports)} outport(s)"
                )
            out.extend(["", "> Static review-priority heuristic only; this is not a safety, stability, or simulation verdict.", ""])
        out.append("</details>")
    out.extend([
        "",
        "---",
        "_Generated by slx-diff. Layout-only changes are ignored unless explicitly enabled._",
    ])
    return "\n".join(out)


def render_json(result: DiffResult) -> str:
    payload = {
        "old_name": result.old_name,
        "new_name": result.new_name,
        "changed": result.changed,
        "change_count": result.change_count,
        "added_blocks": [asdict(item) for item in result.added_blocks],
        "removed_blocks": [asdict(item) for item in result.removed_blocks],
        "changed_blocks": [
            {
                "before": asdict(item.before),
                "after": asdict(item.after),
                "parameter_changes": [asdict(change) for change in item.parameter_changes],
            }
            for item in result.changed_blocks
        ],
        "added_lines": [asdict(item) for item in result.added_lines],
        "removed_lines": [asdict(item) for item in result.removed_lines],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
