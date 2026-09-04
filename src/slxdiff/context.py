from __future__ import annotations

import json

from .diff import compare_models
from .model import Model
from .review import build_review_report


def build_agent_context(old: Model, new: Model, *, max_hotspots: int = 20) -> dict:
    """Return a compact, agent-friendly semantic context for a model change."""
    result = compare_models(old, new, include_layout=False)
    review = build_review_report(old, new)
    hotspots = review.items[: max(0, max_hotspots)]
    return {
        "schema_version": "0.1",
        "kind": "slx-agent-review-context",
        "models": {
            "before": {
                "name": old.name,
                "sha256": old.metadata.get("sha256", ""),
                "unsupported_features": list(old.metadata.get("unsupported_features", [])),
            },
            "after": {
                "name": new.name,
                "sha256": new.metadata.get("sha256", ""),
                "unsupported_features": list(new.metadata.get("unsupported_features", [])),
            },
        },
        "summary": {
            "change_count": result.change_count,
            "added_blocks": len(result.added_blocks),
            "removed_blocks": len(result.removed_blocks),
            "changed_blocks": len(result.changed_blocks),
            "added_connections": len(result.added_lines),
            "removed_connections": len(result.removed_lines),
            "max_review_priority": review.max_priority,
            "review_priority_counts": review.priority_counts,
        },
        "semantic_changes": {
            "added_blocks": [{"path": block.path, "type": block.block_type} for block in result.added_blocks],
            "removed_blocks": [
                {"path": block.path, "type": block.block_type} for block in result.removed_blocks
            ],
            "changed_blocks": [
                {
                    "path": change.after.path,
                    "type_before": change.before.block_type,
                    "type_after": change.after.block_type,
                    "renamed_from": change.before.name if change.renamed else None,
                    "parameters": [
                        {"name": item.name, "before": item.before, "after": item.after}
                        for item in change.parameter_changes
                    ],
                }
                for change in result.changed_blocks
            ],
            "added_connections": [
                {"src": line.src, "dst": line.dst, "name": line.name} for line in result.added_lines
            ],
            "removed_connections": [
                {"src": line.src, "dst": line.dst, "name": line.name} for line in result.removed_lines
            ],
        },
        "review_hotspots": [
            {
                "block_path": item.block_path,
                "block_type": item.block_type,
                "status": item.status,
                "score": item.score,
                "priority": item.priority,
                "changed_parameters": item.changed_parameters,
                "direct_consumers": item.direct_consumers,
                "downstream_count": len(item.downstream_blocks),
                "affected_outports": item.affected_outports,
                "reason_codes": [reason.code for reason in item.reasons],
            }
            for item in hotspots
        ],
        "interpretation": {
            "static_only": True,
            "does_not_compile_or_execute_model": True,
            "review_priority_is_not_safety_or_stability_proof": True,
        },
    }


def render_agent_context_json(old: Model, new: Model, *, max_hotspots: int = 20) -> str:
    return json.dumps(build_agent_context(old, new, max_hotspots=max_hotspots), indent=2, ensure_ascii=False)
