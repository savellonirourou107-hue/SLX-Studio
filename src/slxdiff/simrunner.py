from __future__ import annotations

import hashlib
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .history import ModelHistory
from .matlab_bridge import apply_patch_with_matlab, validate_simulation_stop_time
from .patching import PatchDocument, patch_from_dict


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SimulationRunManager:
    """Cancelable workbench simulation jobs, including optional staged parameter patches."""

    def __init__(self, *, matlab: str | Path | None, history: ModelHistory, timeout: float = 600.0, execution_lock: threading.RLock | None = None) -> None:
        self.matlab = matlab
        self.history = history
        self.timeout = timeout
        self.execution_lock = execution_lock or threading.RLock()
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._active: str | None = None

    def start(self, path: str | Path, *, patch: PatchDocument | dict[str, Any], stop_time: str = "10") -> dict[str, Any]:
        model = Path(path).resolve()
        document = patch if isinstance(patch, PatchDocument) else patch_from_dict(patch)
        stop_time = validate_simulation_stop_time(stop_time)
        # apply_patch_with_matlab performs the authoritative hash/parameter validation.
        with self._lock:
            if self._active and self._jobs.get(self._active, {}).get("state") == "running":
                raise RuntimeError("a Simulink simulation is already active")
            before = self.history.capture(model, label="simulation-before") if document.operations else None
            before_sha = _sha(model)
            job_id = uuid.uuid4().hex
            job: dict[str, Any] = {
                "id": job_id,
                "path": str(model),
                "state": "running",
                "started_at": time.time(),
                "process": None,
                "cancel_requested": False,
                "result": None,
                "error": None,
                "before_snapshot": before,
                "before_sha": before_sha,
                "had_patch": bool(document.operations),
                "history": self.history.status(model),
                "model_changed": False,
            }
            self._jobs[job_id] = job
            self._active = job_id

        def set_process(proc: subprocess.Popen[str]) -> None:
            with self._lock:
                job["process"] = proc
                if job.get("cancel_requested") and proc.poll() is None:
                    proc.terminate()

        def finalize_history() -> None:
            snapshot = job.get("before_snapshot")
            if snapshot is None:
                job["model_changed"] = False
                job["history"] = self.history.status(model)
                return
            try:
                changed = model.exists() and _sha(model) != job.get("before_sha")
                job["model_changed"] = bool(changed)
                if changed:
                    job["history"] = self.history.record(model, snapshot)
                    job["before_snapshot"] = None
                else:
                    self.history.discard_capture(snapshot)
                    job["before_snapshot"] = None
                    job["history"] = self.history.status(model)
            except Exception:
                self.history.discard_capture(snapshot)
                job["before_snapshot"] = None
                raise

        def worker() -> None:
            try:
                with self.execution_lock:
                    if job.get("cancel_requested"):
                        result = {"ok": False, "cancelled": True, "output_variables": [], "series": []}
                    else:
                        result = apply_patch_with_matlab(
                            model,
                            document,
                            output_path=model,
                            matlab=self.matlab,
                            simulate=True,
                            stop_time=stop_time,
                            timeout=self.timeout,
                            on_process=set_process,
                            cancelled=lambda: bool(job.get("cancel_requested")),
                        )
                finalize_history()
                with self._lock:
                    job["result"] = result
                    job["state"] = "cancelled" if result.get("cancelled") else "finished"
            except Exception as exc:
                try:
                    finalize_history()
                except Exception as history_exc:
                    exc = RuntimeError(f"{exc}; history finalization failed: {history_exc}")
                with self._lock:
                    job["error"] = str(exc)
                    job["state"] = "cancelled" if job.get("cancel_requested") else "failed"
            finally:
                with self._lock:
                    job["process"] = None
                    job["finished_at"] = time.time()
                    if self._active == job_id:
                        self._active = None

        threading.Thread(target=worker, name=f"slxstudio-sim-{job_id[:8]}", daemon=True).start()
        return self.status(job_id)

    def status(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(str(job_id))
            if not job:
                raise ValueError("unknown Simulink simulation job")
            payload = {k: job[k] for k in ("id", "path", "state", "started_at", "had_patch", "model_changed")}
            payload["history"] = dict(job.get("history") or {})
            if job.get("finished_at"):
                payload["finished_at"] = job["finished_at"]
            if job.get("result") is not None:
                payload["result"] = job["result"]
            if job.get("error"):
                payload["error"] = job["error"]
            return payload

    def stop(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(str(job_id))
            if not job:
                raise ValueError("unknown Simulink simulation job")
            if job.get("state") != "running":
                return self.status(job_id)
            job["cancel_requested"] = True
            proc = job.get("process")
            if isinstance(proc, subprocess.Popen) and proc.poll() is None:
                try:
                    proc.terminate(); proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                except OSError:
                    pass
            return self.status(job_id)

    def stop_all(self) -> None:
        with self._lock:
            ids = [job_id for job_id, job in self._jobs.items() if job.get("state") == "running"]
        for job_id in ids:
            try:
                self.stop(job_id)
            except (ValueError, OSError):
                pass
