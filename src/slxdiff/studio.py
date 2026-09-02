from __future__ import annotations

import json
import tempfile
import webbrowser
from collections import defaultdict
from dataclasses import asdict
from importlib import resources
from pathlib import Path

from .agent import provider_catalog_payload
from .context import build_agent_context
from .blueprint import catalog_payload
from .diff import compare_models
from .model import Block, Model
from .parser import parse_slx
from .patching import PATCH_SCHEMA_VERSION
from .review import build_review_report, review_to_dict
from .slx_path import parent_path, split_path


def _system_label(blocks: list[Block], system_id: str) -> str:
    if not blocks:
        return system_id
    parents = [parent_path(block.path) for block in blocks]
    nonempty = [p for p in parents if p]
    if not nonempty:
        return "Root"
    prefix = split_path(nonempty[0])
    for parent in nonempty[1:]:
        parts = split_path(parent)
        limit = min(len(prefix), len(parts))
        i = 0
        while i < limit and prefix[i] == parts[i]:
            i += 1
        prefix = prefix[:i]
        if not prefix:
            break
    return "/".join(prefix) if prefix else "/".join(split_path(nonempty[0]))


def _model_payload(model: Model) -> dict:
    grouped: dict[str, list[Block]] = defaultdict(list)
    for block in model.blocks.values():
        grouped[block.system_id].append(block)

    systems = []
    for system_id, blocks in sorted(grouped.items(), key=lambda item: _system_label(item[1], item[0]).lower()):
        systems.append(
            {
                "id": system_id,
                "label": _system_label(blocks, system_id),
                "block_count": len(blocks),
            }
        )

    return {
        "name": model.name,
        "metadata": dict(model.metadata),
        "systems": systems,
        "blocks": [
            {
                **asdict(block),
                "id": f"{block.system_id}:{block.sid}",
                "status": "unchanged",
            }
            for _, block in sorted(model.blocks.items())
        ],
        "lines": [
            {
                **asdict(line),
                "id": f"{line.system_id}:{line.src}->{line.dst}:{line.name}",
                "status": "unchanged",
            }
            for line in sorted(model.lines)
        ],
    }


def model_payload(model: Model) -> dict:
    """Public JSON-ready model payload used by Studio and the local API."""
    return _model_payload(model)


def _diff_payload(old: Model, new: Model) -> dict:
    result = compare_models(old, new, include_layout=False)
    old_payload = _model_payload(old)
    new_payload = _model_payload(new)

    added_keys = {(b.system_id, b.sid) for b in result.added_blocks}
    removed_keys = {(b.system_id, b.sid) for b in result.removed_blocks}
    changed_after = {(c.after.system_id, c.after.sid): c for c in result.changed_blocks}
    changed_before = {(c.before.system_id, c.before.sid): c for c in result.changed_blocks}

    for block in new_payload["blocks"]:
        key = (block["system_id"], block["sid"])
        if key in added_keys:
            block["status"] = "added"
        elif key in changed_after:
            change = changed_after[key]
            block["status"] = "changed"
            block["before"] = {
                "name": change.before.name,
                "block_type": change.before.block_type,
                "path": change.before.path,
                "parameters": dict(change.before.parameters),
            }
            block["parameter_changes"] = [asdict(item) for item in change.parameter_changes]

    for block in old_payload["blocks"]:
        key = (block["system_id"], block["sid"])
        if key in removed_keys:
            block["status"] = "removed"
        elif key in changed_before:
            block["status"] = "changed"

    added_lines = set(result.added_lines)
    removed_lines = set(result.removed_lines)
    for item, line in zip(new_payload["lines"], sorted(new.lines)):
        if line in added_lines:
            item["status"] = "added"
    for item, line in zip(old_payload["lines"], sorted(old.lines)):
        if line in removed_lines:
            item["status"] = "removed"

    summary = {
        "change_count": result.change_count,
        "added_blocks": len(result.added_blocks),
        "removed_blocks": len(result.removed_blocks),
        "changed_blocks": len(result.changed_blocks),
        "added_lines": len(result.added_lines),
        "removed_lines": len(result.removed_lines),
    }
    review = review_to_dict(build_review_report(old, new))
    agent_context = build_agent_context(old, new)
    return {"mode": "diff", "old": old_payload, "new": new_payload, "summary": summary, "review": review, "agent_context": agent_context}


def _safe_json_for_html(payload: dict) -> str:
    # Prevent model-controlled strings from terminating the script element.
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def render_studio_html(
    model: Model,
    compare_to: Model | None = None,
    *,
    bridge: dict | None = None,
) -> str:
    """Render a self-contained SLX Studio HTML document."""
    target = compare_to or model
    editor = {
        "patch_schema_version": PATCH_SCHEMA_VERSION,
        "model_name": target.name,
        "source_sha256": target.metadata.get("sha256", ""),
        "bridge": bridge or {"enabled": False},
        "providers": provider_catalog_payload(),
        "block_catalog": catalog_payload(),
    }
    if compare_to is None:
        payload = {"mode": "model", "model": _model_payload(model), "editor": editor}
    else:
        payload = _diff_payload(model, compare_to)
        payload["editor"] = editor
    template = resources.files("slxdiff").joinpath("studio.html").read_text(encoding="utf-8")
    return template.replace("__SLX_STUDIO_PAYLOAD__", _safe_json_for_html(payload))


def write_studio_html(
    model_path: str | Path,
    compare_path: str | Path | None = None,
    *,
    output: str | Path,
) -> Path:
    old = parse_slx(model_path)
    new = parse_slx(compare_path) if compare_path is not None else None
    html = render_studio_html(old, new)
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path


def open_studio(model_path: str | Path, compare_path: str | Path | None = None) -> Path:
    """Write a temporary standalone report and open it in the default browser."""
    old = parse_slx(model_path)
    new = parse_slx(compare_path) if compare_path is not None else None
    html = render_studio_html(old, new)
    handle = tempfile.NamedTemporaryFile(prefix="slx-studio-", suffix=".html", delete=False)
    path = Path(handle.name)
    with handle:
        handle.write(html.encode("utf-8"))
    webbrowser.open(path.resolve().as_uri())
    return path
