"""Process-tree cancellation limited to a MATLAB worker launched by this app."""

import os
import signal
import subprocess
from pathlib import Path


class WorkerProcess(subprocess.Popen):
    """Keep the normal Popen interface used by the job managers.

    Windows MATLAB's bin/matlab.exe is a launcher; terminating only that PID
    leaves bin/win64/MATLAB.exe alive. On POSIX each worker owns a new process
    group. Never target processes by executable name or attach to user sessions.
    """

    def __init__(self, *args, **kwargs):
        if os.name != "nt":
            kwargs["start_new_session"] = True
        super().__init__(*args, **kwargs)

    def _stop_tree(self, sig):
        if self.poll() is not None:
            return
        if os.name == "nt":
            taskkill = Path(os.environ["SystemRoot"]) / "System32" / "taskkill.exe"
            result = subprocess.run(
                [str(taskkill), "/PID", str(self.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=10,
            )
            if result.returncode and self.poll() is None:
                raise OSError("Could not stop the owned MATLAB process tree")
        else:
            try:
                os.killpg(self.pid, sig)
            except ProcessLookupError:
                pass

    def terminate(self):
        self._stop_tree(signal.SIGTERM)

    def kill(self):
        self._stop_tree(getattr(signal, "SIGKILL", signal.SIGTERM))
