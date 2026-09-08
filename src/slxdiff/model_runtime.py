"""Asynchronous desktop model transactions; original files are never MATLAB scratch files."""

from __future__ import annotations

import copy
import os
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path

from .documents import DocumentConflict, document_path
from .history import ModelHistory, atomic_model_replace
from .matlab_bridge import (
    apply_model_edit_with_matlab,
    apply_patch_with_matlab,
    validate_simulation_stop_time,
)
from .model_edit import edit_document_from_dict, validate_edit_document
from .parser import parse_slx
from .patching import PatchDocument, sha256_file


class ModelRuntime:
    def __init__(self, root: Path, *, matlab=None):
        self.root = root.resolve()
        self.matlab = matlab or os.environ.get("SLX_STUDIO_MATLAB") or os.environ.get("SLX_DIFF_MATLAB")
        self._lock = threading.RLock()
        self._history = None
        self._jobs = {}
        self._thread = None
        self._active = None
        self._closed = False

    def _path(self, relative):
        path = document_path(self.root, relative)
        if path.suffix.lower() != ".slx" or not path.is_file():
            raise ValueError("model operation requires a regular .slx file")
        return path

    @property
    def history(self):
        if self._history is None:
            self._history = ModelHistory()
        return self._history

    def history_action(self, relative, action="status"):
        if action not in {"status", "undo", "redo"}:
            raise ValueError("unknown history action")
        with self._lock:
            if self._active and action != "status":
                raise RuntimeError("wait for or stop the active model job first")
            path = self._path(relative)
            state = getattr(self.history, action)(path)
            return {**state, "sha256": sha256_file(path), "path": relative}

    def start_edit(self, relative, edit, output_relative=None):
        source = self._path(relative)
        if output_relative is not None and self._path(output_relative) != source:
            raise ValueError("model edits save in place; Save As remains a legacy workflow")
        document = edit_document_from_dict(edit)
        validate_edit_document(document, parse_slx(source), source_path=source)
        return self._start(relative, "edit", document.source_sha256, document=document)

    def start_simulation(self, relative, expected_sha256, stop_time="10"):
        path = self._path(relative)
        if not isinstance(expected_sha256, str) or sha256_file(path) != expected_sha256:
            raise DocumentConflict("model changed on disk; reload before simulation")
        return self._start(
            relative, "simulation", expected_sha256, stop_time=validate_simulation_stop_time(stop_time)
        )

    def _start(self, relative, kind, version, *, document=None, stop_time="10"):
        with self._lock:
            if self._closed or self._active:
                raise RuntimeError("model runtime is closed or another model job is active")
            # Keep a bounded number of results; each simulation has <= 12 traces
            # and <= 1500 samples/trace, from the existing bridge contract.
            while len(self._jobs) >= 16:
                self._jobs.pop(next(iter(self._jobs)))
            identifier = uuid.uuid4().hex
            job = {
                "id": identifier,
                "path": relative,
                "kind": kind,
                "state": "running",
                "started_at": time.time(),
                "source_sha256": version,
                "backend": "matlab_batch",
                "stop_time": stop_time if kind == "simulation" else None,
                "process": None,
                "cancel": threading.Event(),
            }
            self._jobs[identifier] = job
            self._active = identifier

            def process_started(proc):
                with self._lock:
                    job["process"] = proc
                    if job["cancel"].is_set() and proc.poll() is None:
                        proc.terminate()

            def worker():
                before = None
                try:
                    source = self._path(relative)
                    with tempfile.TemporaryDirectory(prefix="slx-model-job-") as directory:
                        root = Path(directory)
                        incoming = root / "input" / source.name
                        outgoing = root / "output" / source.name
                        incoming.parent.mkdir()
                        outgoing.parent.mkdir()
                        shutil.copy2(source, incoming)
                        if sha256_file(incoming) != version:
                            raise DocumentConflict("model changed before job startup; reload before retrying")
                        if job["cancel"].is_set():
                            result = {"ok": False, "cancelled": True}
                        elif kind == "edit":
                            result = apply_model_edit_with_matlab(
                                incoming,
                                document,
                                output_path=outgoing,
                                matlab=self.matlab,
                                on_process=process_started,
                                cancelled=job["cancel"].is_set,
                                work_dir=source.parent,
                            )
                        else:
                            model = parse_slx(incoming)
                            patch = PatchDocument("0.1", model.name, version, ())
                            result = apply_patch_with_matlab(
                                incoming,
                                patch,
                                output_path=outgoing,
                                matlab=self.matlab,
                                simulate=True,
                                stop_time=stop_time,
                                on_process=process_started,
                                cancelled=job["cancel"].is_set,
                                work_dir=source.parent,
                            )
                        with self._lock:
                            if job["cancel"].is_set():
                                result = {
                                    "ok": False,
                                    "cancelled": True,
                                    "message": "Cancelled; original model unchanged",
                                }
                            elif not result.get("ok"):
                                raise RuntimeError(result.get("message") or "MATLAB model operation failed")
                            elif kind == "edit":
                                source = self._path(relative)
                                if sha256_file(source) != version:
                                    raise DocumentConflict(
                                        "model changed during MATLAB execution; staged edit was not written"
                                    )
                                before = self.history.capture(source, label="desktop-before")
                                atomic_model_replace(outgoing, source, version)
                                try:
                                    job["history"] = self.history.record(source, before)
                                except Exception:
                                    atomic_model_replace(before, source, sha256_file(outgoing))
                                    raise
                                before = None
                                job["saved_sha256"] = sha256_file(source)
                            result.pop(
                                "output_model", None
                            )  # private temporary paths are not result provenance
                            result.pop("stdout", None)
                            result.pop("stderr", None)
                            job["result"] = result
                            job["_terminal_state"] = "cancelled" if result.get("cancelled") else "finished"
                except Exception as exc:  # noqa: BLE001 - propagate background failures to the job API
                    with self._lock:
                        job["_terminal_state"] = "cancelled" if job["cancel"].is_set() else "failed"
                        job["error"] = str(exc)[:8192]
                finally:
                    with self._lock:
                        if before is not None:
                            self.history.discard_capture(before)
                        job["process"] = None
                        job["finished_at"] = time.time()
                        job["state"] = job.pop("_terminal_state", "failed")
                        self._active = None

            self._thread = threading.Thread(target=worker, name=f"slx-model-{identifier[:8]}", daemon=True)
            self._thread.start()
            return self.status(identifier)

    def status(self, job_id):
        with self._lock:
            if job_id not in self._jobs:
                raise ValueError("unknown model job")
            return copy.deepcopy(
                {
                    key: value
                    for key, value in self._jobs[job_id].items()
                    if key not in {"process", "cancel", "_terminal_state"}
                }
            )

    def stop(self, job_id):
        with self._lock:
            if job_id not in self._jobs:
                raise ValueError("unknown model job")
            job = self._jobs[job_id]
            if job["state"] == "running" and "_terminal_state" not in job:
                job["cancel"].set()
                proc = job["process"]
                if proc is not None and proc.poll() is None:
                    proc.terminate()
            return self.status(job_id)

    def close(self):
        with self._lock:
            self._closed = True
            if self._active:
                self.stop(self._active)
        if self._thread:
            self._thread.join(timeout=15)
        if self._history is not None and (not self._thread or not self._thread.is_alive()):
            self._history.close()
