"""Bounded, cancellable execution for explicitly requested MATLAB batch jobs."""

from __future__ import annotations

import codecs
import os
import subprocess
import threading
import time

from .worker_process import WorkerProcess


def run_batch(command, *, timeout, cwd=None, on_process=None, cancelled=None):
    proc = WorkerProcess(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    output = {"stdout": "", "stderr": ""}
    limit = 1_048_576

    def read(name, pipe):
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        try:
            while chunk := os.read(pipe.fileno(), 4096):
                text = decoder.decode(chunk)
                remaining = max(0, limit - len(output[name]))
                output[name] += text[:remaining]
        finally:
            pipe.close()

    readers = [
        threading.Thread(target=read, args=(name, getattr(proc, name)), daemon=True) for name in output
    ]
    for reader in readers:
        reader.start()
    deadline = time.monotonic() + timeout
    try:
        if on_process:
            on_process(proc)
        while proc.poll() is None:
            if cancelled and cancelled():
                proc.terminate()
                break
            if time.monotonic() >= deadline:
                raise RuntimeError(f"MATLAB bridge timed out after {timeout:g} seconds")
            time.sleep(0.03)
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)
        for reader in readers:
            reader.join(timeout=5)
    return subprocess.CompletedProcess(command, proc.returncode, output["stdout"], output["stderr"])
