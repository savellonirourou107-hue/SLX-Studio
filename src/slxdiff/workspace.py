from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path
from typing import Any

VISIBLE_SUFFIXES = {".m", ".slx"}
TEXT_SUFFIXES = {".m"}
_IGNORED_DIRS = {
    ".git",
    ".svn",
    ".hg",
    "__pycache__",
    ".pytest_cache",
    "build",
    "dist",
    ".venv",
    "venv",
    "node_modules",
}
_MAX_TEXT_BYTES = 4 * 1024 * 1024


def workspace_root(path: str | Path | None) -> tuple[Path, str | None]:
    """Return (root, initial relative file) for a folder or .m/.slx path."""
    source = Path(path or Path.cwd()).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    if source.is_dir():
        return source, None
    if source.suffix.lower() not in VISIBLE_SUFFIXES:
        raise ValueError("SLX Studio workspace must be a folder, .m file, or .slx file")
    return source.parent, source.name


def resolve_workspace_path(root: str | Path, relative: str | Path, *, must_exist: bool = True) -> Path:
    base = Path(root).resolve()
    raw = str(relative).replace("\\", "/").strip()
    if not raw or raw.startswith(("/", "~")):
        raise ValueError("workspace path must be relative")
    candidate = (base / raw).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError("workspace path escapes the workspace root") from exc
    if must_exist and not candidate.exists():
        raise FileNotFoundError(candidate)
    return candidate


def _walk(root: Path, *, max_files: int, max_depth: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    count = 0

    def visit(folder: Path, depth: int) -> list[dict[str, Any]]:
        nonlocal count
        if depth > max_depth or count >= max_files:
            return []
        children: list[dict[str, Any]] = []
        try:
            entries = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            return []
        for entry in entries:
            if count >= max_files:
                break
            if entry.name.startswith(".") and entry.is_dir():
                continue
            if entry.is_dir():
                if entry.name in _IGNORED_DIRS or entry.is_symlink():
                    continue
                nested = visit(entry, depth + 1)
                if nested:
                    children.append(
                        {
                            "type": "directory",
                            "name": entry.name,
                            "path": entry.relative_to(root).as_posix(),
                            "children": nested,
                        }
                    )
                continue
            if entry.is_symlink() or entry.suffix.lower() not in VISIBLE_SUFFIXES:
                continue
            count += 1
            children.append(
                {
                    "type": "file",
                    "name": entry.name,
                    "path": entry.relative_to(root).as_posix(),
                    "kind": "matlab" if entry.suffix.lower() == ".m" else "simulink",
                    "size": entry.stat().st_size,
                }
            )
        return children

    items = visit(root, 0)
    return items


class WorkspaceIndex:
    """Asynchronously build and cache the lightweight Workbench file tree.

    The index is session-scoped and deliberately contains only visible `.m` and
    `.slx` entries.  A first request can return immediately while the directory
    walk continues in a daemon thread; explicit refreshes and Workbench writes
    invalidate it without adding a persistent database or runtime dependency.
    """

    def __init__(self, root: str | Path, *, max_files: int = 2000, max_depth: int = 8) -> None:
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError("workspace root must be a directory")
        self.max_files = max_files
        self.max_depth = max_depth
        self._lock = threading.RLock()
        self._items: list[dict[str, Any]] = []
        self._state = "idle"
        self._error = ""
        self._generation = 0
        self._thread: threading.Thread | None = None
        self._schedule_locked()

    def _schedule_locked(self) -> None:
        if self._state == "indexing":
            return
        self._state = "indexing"
        self._error = ""
        self._generation += 1
        generation = self._generation
        self._thread = threading.Thread(
            target=self._build, args=(generation,), name="slx-studio-workspace-index", daemon=True
        )
        self._thread.start()

    def _build(self, generation: int) -> None:
        try:
            items = _walk(self.root, max_files=self.max_files, max_depth=self.max_depth)
        except Exception as exc:  # noqa: BLE001 - report indexing failure through the API
            with self._lock:
                if generation == self._generation:
                    self._state = "error"
                    self._error = str(exc)
            return
        with self._lock:
            if generation != self._generation:
                return
            self._items = items
            self._state = "ready"
            self._error = ""

    def invalidate(self) -> None:
        """Schedule a fresh index after a write or an explicit user refresh."""

        with self._lock:
            self._schedule_locked()

    def snapshot(self, *, force: bool = False) -> dict[str, Any]:
        with self._lock:
            if force:
                self._schedule_locked()
            return {
                "root": str(self.root),
                "items": self._items,
                "max_files": self.max_files,
                "max_depth": self.max_depth,
                "indexing": self._state == "indexing",
                "index_state": self._state,
                "index_error": self._error,
                "index_generation": self._generation,
            }


def list_workspace(root: str | Path, *, max_files: int = 2000, max_depth: int = 8) -> dict[str, Any]:
    base = Path(root).resolve()
    if not base.is_dir():
        raise ValueError("workspace root must be a directory")
    files = _walk(base, max_files=max_files, max_depth=max_depth)
    return {"root": str(base), "items": files, "max_files": max_files, "max_depth": max_depth}


def read_text_file(root: str | Path, relative: str | Path) -> str:
    path = resolve_workspace_path(root, relative)
    if path.suffix.lower() not in TEXT_SUFFIXES:
        raise ValueError("only .m files are editable as text")
    size = path.stat().st_size
    if size > _MAX_TEXT_BYTES:
        raise ValueError("text file is too large for the lightweight editor")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8-sig")


def write_text_file(root: str | Path, relative: str | Path, content: str) -> Path:
    path = resolve_workspace_path(root, relative, must_exist=False)
    if path.suffix.lower() not in TEXT_SUFFIXES:
        raise ValueError("only .m files can be saved by the text editor")
    raw = content.encode("utf-8")
    if len(raw) > _MAX_TEXT_BYTES:
        raise ValueError("text file is too large for the lightweight editor")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return path


def create_m_file(root: str | Path, relative: str | Path) -> Path:
    path = resolve_workspace_path(root, relative, must_exist=False)
    if path.suffix.lower() != ".m":
        raise ValueError("MATLAB script file name must end in .m")
    if path.exists():
        raise ValueError(f"file already exists: {relative}")
    name = path.stem
    content = f"%% {name}\n% Created with SLX Studio\n\nclear; clc;\n\n"
    return write_text_file(root, relative, content)


def copy_workspace_file(
    root: str | Path, source_relative: str | Path, destination_relative: str | Path
) -> Path:
    """Copy a .m/.slx workspace file without overwriting an existing destination."""
    import shutil

    source = resolve_workspace_path(root, source_relative)
    destination = resolve_workspace_path(root, destination_relative, must_exist=False)
    if source.suffix.lower() not in VISIBLE_SUFFIXES:
        raise ValueError("only .m and .slx files can be copied by the workbench")
    if destination.suffix.lower() != source.suffix.lower():
        raise ValueError("Save As must preserve the file extension")
    if destination.exists():
        raise ValueError(f"destination already exists: {destination_relative}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def search_workspace(
    root: str | Path,
    query: str,
    *,
    max_results: int = 100,
    max_file_bytes: int = 1024 * 1024,
) -> dict[str, Any]:
    """Search workspace file names and MATLAB source text without executing MATLAB."""
    base = Path(root).resolve()
    needle = str(query).strip()
    if not needle:
        return {"query": "", "results": []}
    needle_fold = needle.casefold()
    results: list[dict[str, Any]] = []

    def add(item: dict[str, Any]) -> None:
        if len(results) < max_results:
            results.append(item)

    for folder, dirs, files in os.walk(base):
        dirs[:] = [
            name
            for name in dirs
            if name not in _IGNORED_DIRS
            and not name.startswith(".")
            and not (Path(folder) / name).is_symlink()
        ]
        for name in sorted(files, key=str.casefold):
            if len(results) >= max_results:
                break
            path = Path(folder) / name
            if path.is_symlink() or path.suffix.lower() not in VISIBLE_SUFFIXES:
                continue
            relative = path.relative_to(base).as_posix()
            if needle_fold in relative.casefold():
                add({"type": "file", "path": relative, "line": 0, "preview": relative})
            if len(results) >= max_results:
                continue
            if path.suffix.lower() == ".m":
                try:
                    if path.stat().st_size > max_file_bytes:
                        continue
                    text = read_text_file(base, relative)
                except (OSError, UnicodeError, ValueError):
                    continue
                for line_number, line in enumerate(text.splitlines(), start=1):
                    if needle_fold not in line.casefold():
                        continue
                    add(
                        {
                            "type": "match",
                            "path": relative,
                            "line": line_number,
                            "preview": line.strip()[:240],
                        }
                    )
                    if len(results) >= max_results:
                        break
                continue
            if path.suffix.lower() == ".slx":
                try:
                    from .parser import parse_slx

                    model = parse_slx(path)
                except Exception:  # noqa: BLE001,S112 - malformed SLX files are skipped during search
                    continue
                for block in model.blocks.values():
                    haystack = " ".join(
                        [block.name, block.path, block.block_type]
                        + [f"{key} {value}" for key, value in block.parameters.items()]
                    )
                    if needle_fold not in haystack.casefold():
                        continue
                    add(
                        {
                            "type": "block",
                            "path": relative,
                            "line": 0,
                            "preview": f"{block.path or block.name} · {block.block_type}"[:240],
                            "block_path": block.path,
                        }
                    )
                    if len(results) >= max_results:
                        break
                if len(results) >= max_results:
                    break
                for line in model.lines:
                    haystack = f"{line.src} {line.dst} {line.name}"
                    if needle_fold in haystack.casefold():
                        add(
                            {
                                "type": "signal",
                                "path": relative,
                                "line": 0,
                                "preview": f"{line.src} → {line.dst}"[:240],
                            }
                        )
                        if len(results) >= max_results:
                            break
        if len(results) >= max_results:
            break
    return {"query": needle, "results": results}
