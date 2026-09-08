"""Root-scoped, versioned text documents for the desktop and future transports.

No MATLAB import or execution belongs in this module. Existing REST/CLI text
functions remain compatible; the desktop uses the stronger versioned contract.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from .workspace import _IGNORED_DIRS, _MAX_TEXT_BYTES, VISIBLE_SUFFIXES, resolve_workspace_path


class DocumentConflict(ValueError):
    """The on-disk version no longer matches the editor's base version."""


def is_link_or_reparse(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def document_path(root: Path, relative: str, *, allow_root: bool = False) -> Path:
    """Reject ambiguous paths, links and Windows reparse points, including parents."""
    if not isinstance(relative, str) or len(relative) > 4096:
        raise ValueError("path must be a bounded relative string")
    if relative == "" and allow_root:
        return root
    parts = relative.replace("\\", "/").split("/")
    if any(not part or part in {".", ".."} or part != part.strip() or ":" in part for part in parts):
        raise ValueError("path must be an unambiguous workspace-relative path")
    if "\x00" in relative:
        raise ValueError("path contains a null byte")
    current = root
    for part in parts:
        current = current / part
        if is_link_or_reparse(current):
            raise ValueError("links and reparse points are not desktop document targets")
    return resolve_workspace_path(root, relative)


def _raw_document(root: Path, relative: str) -> tuple[Path, bytes, os.stat_result]:
    path = document_path(root, relative)
    if path.suffix.lower() != ".m":
        raise ValueError("only .m text documents are currently editable")
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_TEXT_BYTES:
        raise ValueError("document is not a regular text file within the size limit")
    with path.open("rb") as handle:
        raw = handle.read(_MAX_TEXT_BYTES + 1)
    after = path.stat()
    if len(raw) > _MAX_TEXT_BYTES:
        raise ValueError("document exceeds the text size limit")
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise DocumentConflict("document changed while it was being read; reopen it")
    return path, raw, after


def _snapshot(relative: str, raw: bytes, mtime_ns: int = 0) -> dict[str, Any]:
    content = raw.decode("utf-8-sig", errors="strict")
    return {
        "path": relative.replace("\\", "/"),
        "content": content,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bom": raw.startswith(b"\xef\xbb\xbf"),
        "eol": "CRLF" if "\r\n" in content else "LF",
        "mixed_eol": ("\r\n" in content and "\n" in content.replace("\r\n", ""))
        or "\r" in content.replace("\r\n", ""),
        "bytes": len(raw),
        "mtime_ns": mtime_ns,
    }


def read_document(root: Path, relative: str) -> dict[str, Any]:
    _, raw, info = _raw_document(root, relative)
    return _snapshot(relative, raw, info.st_mtime_ns)


def save_document(root: Path, relative: str, content: str, expected_sha256: str, bom: bool = False) -> dict:
    if not isinstance(content, str) or not isinstance(bom, bool):
        raise TypeError("content must be text and bom must be boolean")
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        raise ValueError("saving requires the base document SHA-256")
    raw = (b"\xef\xbb\xbf" if bom else b"") + content.encode("utf-8")
    if len(raw) > _MAX_TEXT_BYTES:
        raise ValueError("document exceeds the text size limit")
    path, previous, info = _raw_document(root, relative)
    if hashlib.sha256(previous).hexdigest() != expected_sha256:
        raise DocumentConflict("file changed outside SLX Studio; reopen or compare before saving")
    if not info.st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
        raise PermissionError("document is read-only")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, stat.S_IMODE(info.st_mode))
        # Recheck after preparing the temporary file. This is conflict detection,
        # not an OS sandbox or an atomic CAS against hostile concurrent writers.
        _, latest, _ = _raw_document(root, relative)
        if hashlib.sha256(latest).hexdigest() != expected_sha256:
            raise DocumentConflict("file changed during save; editor contents were not written")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    # Return the version actually written, never a later external writer's hash.
    return _snapshot(relative, raw)


def list_directory(root: Path, relative: str = "", cursor: int = 0) -> dict[str, Any]:
    if isinstance(cursor, bool) or not isinstance(cursor, int) or not 0 <= cursor <= 100_000:
        raise ValueError("invalid directory cursor")
    path = document_path(root, relative, allow_root=True)
    entries = []
    scanned = 0
    more = False
    with os.scandir(path) as iterator:
        for index, entry in enumerate(iterator):
            if index < cursor:
                continue
            if scanned >= 512:
                more = True
                break
            scanned += 1
            candidate = Path(entry.path)
            try:
                if is_link_or_reparse(candidate):
                    continue
                folder = entry.is_dir(follow_symlinks=False)
                if folder and (entry.name.startswith(".") or entry.name in _IGNORED_DIRS):
                    continue
                if not folder and candidate.suffix.lower() not in VISIBLE_SUFFIXES:
                    continue
                entries.append(
                    {
                        "name": entry.name,
                        "path": candidate.relative_to(root).as_posix(),
                        "kind": "directory" if folder else candidate.suffix.lower()[1:],
                    }
                )
            except (OSError, ValueError):
                continue
    next_cursor = cursor + scanned if more and cursor + scanned < 100_000 else None
    return {
        "path": relative,
        "items": sorted(entries, key=lambda item: (item["kind"] != "directory", item["name"].casefold())),
        "next_cursor": next_cursor,
        "truncated": more and next_cursor is None,
    }
