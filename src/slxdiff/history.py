from __future__ import annotations

import hashlib
import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class HistoryRecord:
    before: Path
    after: Path
    before_sha256: str
    after_sha256: str


class ModelHistory:
    """Session-scoped, disk-backed undo/redo snapshots for SLX structural edits.

    Snapshots live in a temporary directory owned by the workbench process.  The
    current file hash is checked before every undo/redo so an external edit is
    never silently overwritten.
    """

    def __init__(self, *, max_records_per_file: int = 25) -> None:
        self._temp = tempfile.TemporaryDirectory(prefix="slx-studio-history-")
        self._root = Path(self._temp.name)
        self._records: dict[str, list[HistoryRecord]] = {}
        self._cursor: dict[str, int] = {}
        self._max = max(1, int(max_records_per_file))
        self._counter = 0
        self._lock = threading.RLock()

    def close(self) -> None:
        with self._lock:
            self._temp.cleanup()

    @staticmethod
    def _key(path: str | Path) -> str:
        return str(Path(path).resolve())

    def capture(self, path: str | Path, *, label: str) -> Path:
        with self._lock:
            return self._capture_unlocked(path, label=label)

    def _capture_unlocked(self, path: str | Path, *, label: str) -> Path:
        source = Path(path).resolve()
        if not source.exists():
            raise FileNotFoundError(source)
        self._counter += 1
        target = self._root / f"{self._counter:08d}-{label}{source.suffix}"
        shutil.copy2(source, target)
        return target

    def discard_capture(self, snapshot: str | Path | None) -> None:
        with self._lock:
            self._discard_capture_unlocked(snapshot)

    def _discard_capture_unlocked(self, snapshot: str | Path | None) -> None:
        if snapshot is None:
            return
        try:
            Path(snapshot).unlink(missing_ok=True)
        except OSError:
            pass

    def record(self, path: str | Path, before_snapshot: str | Path) -> dict[str, bool | int]:
        with self._lock:
            return self._record_unlocked(path, before_snapshot)

    def _record_unlocked(self, path: str | Path, before_snapshot: str | Path) -> dict[str, bool | int]:
        current = Path(path).resolve()
        before = Path(before_snapshot).resolve()
        if not before.exists() or not current.exists():
            raise FileNotFoundError(current if not current.exists() else before)
        after = self._capture_unlocked(current, label="after")
        key = self._key(current)
        records = self._records.setdefault(key, [])
        cursor = self._cursor.get(key, len(records))

        # A new edit after undo creates a new branch; redo entries are dropped.
        for stale in records[cursor:]:
            self._discard_capture_unlocked(stale.before)
            self._discard_capture_unlocked(stale.after)
        del records[cursor:]

        records.append(
            HistoryRecord(
                before=before,
                after=after,
                before_sha256=_sha256(before),
                after_sha256=_sha256(after),
            )
        )
        if len(records) > self._max:
            removed = records.pop(0)
            self._discard_capture_unlocked(removed.before)
            self._discard_capture_unlocked(removed.after)
        self._cursor[key] = len(records)
        return self._status_unlocked(current)

    def status(self, path: str | Path) -> dict[str, bool | int]:
        with self._lock:
            return self._status_unlocked(path)

    def _status_unlocked(self, path: str | Path) -> dict[str, bool | int]:
        key = self._key(path)
        records = self._records.get(key, [])
        cursor = min(self._cursor.get(key, len(records)), len(records))
        return {
            "can_undo": cursor > 0,
            "can_redo": cursor < len(records),
            "undo_count": cursor,
            "redo_count": len(records) - cursor,
        }

    def undo(self, path: str | Path) -> dict[str, bool | int]:
        with self._lock:
            return self._undo_unlocked(path)

    def _undo_unlocked(self, path: str | Path) -> dict[str, bool | int]:
        target = Path(path).resolve()
        key = self._key(target)
        records = self._records.get(key, [])
        cursor = min(self._cursor.get(key, len(records)), len(records))
        if cursor <= 0:
            raise ValueError("nothing to undo")
        record = records[cursor - 1]
        if _sha256(target) != record.after_sha256:
            raise ValueError("model changed outside SLX Studio; reload before undo")
        shutil.copy2(record.before, target)
        self._cursor[key] = cursor - 1
        return self._status_unlocked(target)

    def redo(self, path: str | Path) -> dict[str, bool | int]:
        with self._lock:
            return self._redo_unlocked(path)

    def _redo_unlocked(self, path: str | Path) -> dict[str, bool | int]:
        target = Path(path).resolve()
        key = self._key(target)
        records = self._records.get(key, [])
        cursor = min(self._cursor.get(key, len(records)), len(records))
        if cursor >= len(records):
            raise ValueError("nothing to redo")
        record = records[cursor]
        if _sha256(target) != record.before_sha256:
            raise ValueError("model changed outside SLX Studio; reload before redo")
        shutil.copy2(record.after, target)
        self._cursor[key] = cursor + 1
        return self._status_unlocked(target)
