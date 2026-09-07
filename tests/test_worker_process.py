"""Verify that Windows cancellation stops the calculation child, not just its launcher."""

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes

import pytest

from slxdiff.worker_process import WorkerProcess


@pytest.mark.skipif(os.name != "nt", reason="Windows launcher/child ownership regression")
@pytest.mark.parametrize("stop", ["terminate", "kill"])
def test_windows_owned_child_exits_with_launcher(stop):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    code = (
        "import subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); "
        "print(child.pid,flush=True); time.sleep(60)"
    )
    process = WorkerProcess(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    handle = None
    try:
        child_pid = int(process.stdout.readline())
        handle = kernel.OpenProcess(0x00100000, False, child_pid)  # SYNCHRONIZE
        assert handle, ctypes.get_last_error()
        getattr(process, stop)()
        process.wait(timeout=5)
        assert kernel.WaitForSingleObject(handle, 5000) == 0
    finally:
        process.kill()
        process.wait(timeout=5)
        process.stdout.close()
        if handle:
            kernel.CloseHandle(handle)
