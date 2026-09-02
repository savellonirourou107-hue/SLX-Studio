from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

from .state import StudioState
from .workbench_server import serve_workbench


def _choose_path() -> Path:
    recent_dir = None
    try:
        recent = StudioState().recent_projects()
        recent_dir = next((item["path"] for item in recent if item.get("exists")), None)
    except (OSError, ValueError, TypeError):
        recent_dir = None
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.update()
        selected = filedialog.askopenfilename(
            title="Open MATLAB / Simulink file",
            filetypes=[("MATLAB & Simulink", "*.m *.slx"), ("MATLAB script", "*.m"), ("Simulink model", "*.slx"), ("All files", "*.*")],
            initialdir=recent_dir or None,
        )
        if not selected:
            selected = filedialog.askdirectory(title="Open SLX Studio workspace", initialdir=recent_dir or None)
        root.destroy()
        if selected:
            return Path(selected)
    except Exception:  # noqa: BLE001 - GUI initialization must fall back to the current directory
        return Path.cwd()
    return Path.cwd()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="slx-studio", description="Lightweight .m + .slx editor for MATLAB/Simulink.")
    parser.add_argument("path", nargs="?", type=Path, help="Workspace folder, .m file, or .slx file")
    parser.add_argument("--matlab", help="MATLAB executable path")
    parser.add_argument("--browser", action="store_true", help="Use the system browser instead of an embedded WebView")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    path = args.path or _choose_path()

    server, url = serve_workbench(path, matlab=args.matlab, open_browser=False)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.15}, daemon=True)
    thread.start()
    try:
        if not args.browser:
            try:
                import webview  # type: ignore

                webview.create_window("SLX Studio", url, width=1440, height=900, min_size=(900, 600))
                webview.start()
                return 0
            except Exception:  # noqa: BLE001,S110 - WebView failures use the browser fallback below
                # A packaged desktop build can still be useful if the native
                # WebView runtime is missing or fails to initialize.  Fall back
                # to the default browser instead of exiting with a blank app.
                pass
        webbrowser.open(url)
        try:
            while thread.is_alive():
                thread.join(timeout=0.5)
        except KeyboardInterrupt:
            pass
        return 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
