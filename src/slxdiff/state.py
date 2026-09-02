from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

_MAX_RECENTS = 12
_MAX_RECOVERY_BYTES = 2 * 1024 * 1024


def _default_state_dir() -> Path:
    override = os.environ.get("SLX_STUDIO_STATE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".slx-studio").resolve()


class StudioState:
    """Small local-only state store for recent projects and crash recovery drafts."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root).expanduser().resolve() if root is not None else _default_state_dir()
        self.path = self.root / "state.json"
        self._lock = threading.RLock()

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("version", 1)
                data.setdefault("recent_projects", [])
                data.setdefault("recovery", {})
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return {"version": 1, "recent_projects": [], "recovery": {}}

    def _save(self, data: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
        fd, temp_name = tempfile.mkstemp(prefix="state-", suffix=".json", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.write("\n")
            os.replace(temp_name, self.path)
        finally:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _recovery_key(project_root: str | Path, relative_path: str) -> str:
        root = str(Path(project_root).resolve())
        return root + "\n" + str(relative_path).replace("\\", "/")

    def mark_recent(self, project_root: str | Path) -> list[dict[str, Any]]:
        root = str(Path(project_root).resolve())
        with self._lock:
            data = self._load()
            existing = [item for item in data.get("recent_projects", []) if isinstance(item, dict) and item.get("path") != root]
            existing.insert(0, {"path": root, "opened_at": time.time()})
            data["recent_projects"] = existing[:_MAX_RECENTS]
            self._save(data)
            return list(data["recent_projects"])

    def recent_projects(self) -> list[dict[str, Any]]:
        with self._lock:
            data = self._load()
            result: list[dict[str, Any]] = []
            for item in data.get("recent_projects", []):
                if not isinstance(item, dict) or not item.get("path"):
                    continue
                path = Path(str(item["path"]))
                result.append(
                    {
                        "path": str(path),
                        "name": path.name or str(path),
                        "opened_at": float(item.get("opened_at") or 0),
                        "exists": path.exists(),
                    }
                )
            return result

    def save_recovery(
        self,
        project_root: str | Path,
        relative_path: str,
        content: str,
        *,
        disk_mtime_ns: int | None = None,
    ) -> dict[str, Any]:
        if not isinstance(content, str):
            raise ValueError("recovery content must be text")  # noqa: TRY004 - preserve state validation errors
        size = len(content.encode("utf-8"))
        if size > _MAX_RECOVERY_BYTES:
            raise ValueError("recovery draft is too large")
        key = self._recovery_key(project_root, relative_path)
        entry = {
            "project_root": str(Path(project_root).resolve()),
            "relative_path": str(relative_path).replace("\\", "/"),
            "content": content,
            "saved_at": time.time(),
            "disk_mtime_ns": int(disk_mtime_ns or 0),
            "bytes": size,
        }
        with self._lock:
            data = self._load()
            recovery = data.setdefault("recovery", {})
            recovery[key] = entry
            # Keep the state file bounded even if many projects are edited.
            if len(recovery) > 80:
                ordered = sorted(recovery.items(), key=lambda item: float(item[1].get("saved_at") or 0), reverse=True)
                data["recovery"] = dict(ordered[:80])
            self._save(data)
        return {k: v for k, v in entry.items() if k != "content"}

    def get_recovery(self, project_root: str | Path, relative_path: str) -> dict[str, Any] | None:
        key = self._recovery_key(project_root, relative_path)
        with self._lock:
            raw = self._load().get("recovery", {}).get(key)
            if not isinstance(raw, dict) or not isinstance(raw.get("content"), str):
                return None
            return dict(raw)

    def clear_recovery(self, project_root: str | Path, relative_path: str) -> bool:
        key = self._recovery_key(project_root, relative_path)
        with self._lock:
            data = self._load()
            recovery = data.setdefault("recovery", {})
            existed = key in recovery
            recovery.pop(key, None)
            if existed:
                self._save(data)
            return existed
