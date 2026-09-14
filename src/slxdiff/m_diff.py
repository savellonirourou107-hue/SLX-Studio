from __future__ import annotations

import difflib
import hashlib
from pathlib import Path
from typing import Any

from .workspace import (
    _MAX_TEXT_BYTES,
    TEXT_SUFFIXES,
    read_text_file,
    resolve_workspace_path,
    write_text_file,
)


def sha256_text(text: str) -> str:
    """Compute 64-character lowercase hexadecimal SHA-256 of UTF-8 encoded text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest().lower()


def generate_m_diff_preview(
    root: str | Path,
    relative: str | Path,
    proposed_content: str,
    *,
    base_sha256: str | None = None,
) -> dict[str, Any]:
    """Generate a unified diff preview and detect conflicts for a proposed .m file edit.

    Raises ValueError or TypeError if input violates bounds, paths escape root,
    or file is not a supported text file.
    """
    if not isinstance(proposed_content, str):
        raise TypeError("proposed_content must be a string")
    if len(proposed_content.encode("utf-8")) > _MAX_TEXT_BYTES:
        raise ValueError("proposed content exceeds maximum allowed script size")

    path = resolve_workspace_path(root, relative, must_exist=False)
    if path.suffix.lower() not in TEXT_SUFFIXES:
        raise ValueError("only .m files support text diff preview")

    exists = path.is_file()
    if exists:
        current_text = read_text_file(root, relative)
        current_sha256 = sha256_text(current_text)
    else:
        current_text = ""
        current_sha256 = ""

    # Conflict occurs when base_sha256 is explicitly provided but differs from disk content
    conflict = False
    if base_sha256 is not None:
        cleaned_base = base_sha256.strip().lower()
        if cleaned_base and cleaned_base != current_sha256:
            conflict = True

    rel_str = str(relative).replace("\\", "/")
    from_file = f"a/{rel_str}" if exists else "/dev/null"
    to_file = f"b/{rel_str}"

    current_lines = current_text.splitlines(keepends=True)
    proposed_lines = proposed_content.splitlines(keepends=True)

    diff_lines = list(
        difflib.unified_diff(
            current_lines,
            proposed_lines,
            fromfile=from_file,
            tofile=to_file,
            lineterm="",
        )
    )
    unified_diff = "\n".join(diff_lines)

    additions = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))

    return {
        "ok": True,
        "path": str(path),
        "relative_path": rel_str,
        "exists": exists,
        "current_sha256": current_sha256,
        "base_sha256": base_sha256 or "",
        "conflict": conflict,
        "identical": current_text == proposed_content,
        "diff": unified_diff,
        "stats": {
            "additions": additions,
            "deletions": deletions,
            "lines_before": len(current_lines),
            "lines_after": len(proposed_lines),
        },
    }


def apply_m_edit(
    root: str | Path,
    relative: str | Path,
    content: str,
    expected_sha256: str,
) -> dict[str, Any]:
    """Atomically write the proposed .m file content after validating disk hash.

    Raises ValueError if expected_sha256 does not match disk content (conflict).
    """
    if not isinstance(content, str):
        raise TypeError("content must be a string")
    if not isinstance(expected_sha256, str):
        raise TypeError("expected_sha256 must be a string")

    path = resolve_workspace_path(root, relative, must_exist=False)
    if path.suffix.lower() not in TEXT_SUFFIXES:
        raise ValueError("only .m files can be edited")

    current_sha256 = sha256_text(read_text_file(root, relative)) if path.is_file() else ""
    expected_clean = expected_sha256.strip().lower()

    if expected_clean != current_sha256:
        raise ValueError(
            f"stale file conflict on '{relative}': expected {expected_clean[:8] or 'empty'}, "
            f"disk has {current_sha256[:8] or 'empty'}"
        )

    saved_path = write_text_file(root, relative, content)
    new_sha256 = sha256_text(content)
    rel_str = str(relative).replace("\\", "/")

    return {
        "ok": True,
        "path": str(saved_path),
        "relative_path": rel_str,
        "sha256": new_sha256,
        "bytes": len(content.encode("utf-8")),
    }
