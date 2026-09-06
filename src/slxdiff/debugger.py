from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any


class BreakpointRegistry:
    """Session-scoped, validated non-pausing MATLAB tracepoint registry."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self._lock = RLock()
        self._items: dict[Path, set[int]] = {}

    def _resolve(self, relative: str) -> Path:
        path = (self.root / str(relative)).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("debug path must stay inside the workspace") from exc
        if path.suffix.lower() != ".m":
            raise ValueError("debug breakpoints are supported for .m files")
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"MATLAB file not found: {relative}")
        return path

    def _validate_line(self, path: Path, line: Any) -> int:
        if isinstance(line, bool) or not isinstance(line, int) or line < 1:
            raise ValueError("breakpoint line must be a positive integer")
        count = len(path.read_text(encoding="utf-8").splitlines())
        if line > max(1, count):
            raise ValueError(f"breakpoint line {line} is outside the MATLAB file")
        source = path.read_text(encoding="utf-8").splitlines()[line - 1].strip()
        if not source or source.startswith("%") or source.endswith("..."):
            raise ValueError("breakpoint must target a complete non-comment MATLAB line")
        return line

    def set(self, relative: str, line: int) -> dict[str, Any]:
        path = self._resolve(relative)
        number = self._validate_line(path, line)
        with self._lock:
            self._items.setdefault(path, set()).add(number)
            return self.list(relative)

    def clear(self, relative: str, line: int | None = None) -> dict[str, Any]:
        path = self._resolve(relative)
        with self._lock:
            if line is None:
                self._items.pop(path, None)
            else:
                number = self._validate_line(path, line)
                points = self._items.get(path, set())
                points.discard(number)
                if not points:
                    self._items.pop(path, None)
            return self.list(relative)

    def list(self, relative: str | None = None) -> dict[str, Any]:
        with self._lock:
            if relative is None:
                items = [
                    {"path": self._relative(path), "lines": sorted(lines)}
                    for path, lines in self._items.items()
                    if lines
                ]
                return {"breakpoints": sorted(items, key=lambda item: item["path"])}
            path = self._resolve(relative)
            return {"path": self._relative(path), "lines": sorted(self._items.get(path, set()))}

    def lines_for(self, path: str | Path) -> list[int]:
        resolved = Path(path).resolve()
        with self._lock:
            return sorted(self._items.get(resolved, set()))

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()
