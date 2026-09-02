from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .context import render_agent_context_json
from .diff import compare_models
from .gitdiff import compare_git_refs
from .matlab_bridge import apply_patch_with_matlab, find_matlab
from .parser import parse_slx
from .patching import load_patch
from .server import run_studio_server
from .workbench_server import run_workbench_server
from .mrunner import run_m_file
from .render import render_git_markdown, render_json, render_markdown, render_text
from .review import build_review_report, render_review_json, render_review_markdown, render_review_text
from .studio import open_studio, write_studio_html


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="slx-diff",
        description="Git-native review intelligence and visual diffs for Simulink .slx models.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    diff_cmd = sub.add_parser("diff", help="Compare two .slx files")
    diff_cmd.add_argument("old", type=Path)
    diff_cmd.add_argument("new", type=Path)
    diff_cmd.add_argument("--format", choices=("text", "markdown", "json"), default="text")
    diff_cmd.add_argument(
        "--include-layout",
        action="store_true",
        help="Include position/color/orientation changes",
    )
    diff_cmd.add_argument(
        "--fail-on-change",
        action="store_true",
        help="Exit 1 when semantic changes are found",
    )

    git_cmd = sub.add_parser("git-diff", help="Compare every .slx model changed between two Git refs")
    git_cmd.add_argument("--base", required=True, help="Base Git ref or commit")
    git_cmd.add_argument("--head", default="HEAD", help="Head Git ref or commit (default: HEAD)")
    git_cmd.add_argument("--repo", type=Path, default=Path("."), help="Repository directory")
    git_cmd.add_argument("--include-layout", action="store_true")
    git_cmd.add_argument("--output", type=Path, help="Write Markdown report to this file")
    git_cmd.add_argument(
        "--fail-on-change",
        action="store_true",
        help="Exit 1 when semantic changes are found",
    )

    review_cmd = sub.add_parser("review", help="Prioritize semantic changes by static signal-flow impact")
    review_cmd.add_argument("old", type=Path)
    review_cmd.add_argument("new", type=Path)
    review_cmd.add_argument("--format", choices=("text", "markdown", "json"), default="text")

    context_cmd = sub.add_parser("context", help="Export compact AI-agent context for a model change")
    context_cmd.add_argument("old", type=Path)
    context_cmd.add_argument("new", type=Path)
    context_cmd.add_argument("-o", "--output", type=Path)
    context_cmd.add_argument("--max-hotspots", type=int, default=20)

    inspect_cmd = sub.add_parser("inspect", help="Export a canonical JSON view of one .slx file")
    inspect_cmd.add_argument("model", type=Path)

    view_cmd = sub.add_parser("view", help="Open the visual SLX Studio in your browser")
    view_cmd.add_argument("model", type=Path, help="Model to visualize, or the before model for a diff")
    view_cmd.add_argument("compare", type=Path, nargs="?", help="Optional after model for visual diff mode")

    html_cmd = sub.add_parser("html", help="Write a standalone interactive SLX Studio HTML report")
    html_cmd.add_argument("model", type=Path, help="Model to visualize, or the before model for a diff")
    html_cmd.add_argument("compare", type=Path, nargs="?", help="Optional after model for visual diff mode")
    html_cmd.add_argument("-o", "--output", type=Path, required=True, help="Destination .html file")

    studio_cmd = sub.add_parser("studio", help="Open the lightweight .m + .slx editor workbench")
    studio_cmd.add_argument("path", type=Path, nargs="?", default=Path("."), help="Workspace folder, .m file, or .slx file")
    studio_cmd.add_argument("--matlab", help="MATLAB executable path; defaults to PATH or SLX_DIFF_MATLAB")
    studio_cmd.add_argument("--host", default="127.0.0.1", help="Local bind address")
    studio_cmd.add_argument("--port", type=int, default=0, help="Local port; 0 chooses a free port")
    studio_cmd.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically")
    studio_cmd.add_argument("--token", help="Explicit local API token; random by default")

    serve_cmd = sub.add_parser("serve", help="Run the SLX Studio workbench API without opening a browser")
    serve_cmd.add_argument("path", type=Path, nargs="?", default=Path("."), help="Workspace folder, .m file, or .slx file")
    serve_cmd.add_argument("--matlab", help="MATLAB executable path")
    serve_cmd.add_argument("--host", default="127.0.0.1")
    serve_cmd.add_argument("--port", type=int, default=8765)
    serve_cmd.add_argument("--token", help="Explicit API token; random by default")

    run_m_cmd = sub.add_parser("run-m", help="Run a MATLAB .m script and stream its captured output")
    run_m_cmd.add_argument("script", type=Path)
    run_m_cmd.add_argument("--matlab", help="MATLAB executable path")
    run_m_cmd.add_argument("--timeout", type=float, default=300.0)

    apply_cmd = sub.add_parser("apply", help="Apply a staged SLX Studio patch through MATLAB")
    apply_cmd.add_argument("model", type=Path)
    apply_cmd.add_argument("patch", type=Path)
    apply_cmd.add_argument("-o", "--output", type=Path, required=True)
    apply_cmd.add_argument("--matlab", help="MATLAB executable path")
    apply_cmd.add_argument("--simulate", action="store_true", help="Run a simulation after applying the patch")
    apply_cmd.add_argument("--stop-time", default="10", help="Simulation stop time when --simulate is used")

    status_cmd = sub.add_parser("matlab-status", help="Check whether the MATLAB bridge can find MATLAB")
    status_cmd.add_argument("--matlab", help="MATLAB executable path")
    return parser


def _inspect(path: Path) -> str:
    model = parse_slx(path)
    payload = {
        "schema_version": "0.5",
        "name": model.name,
        "metadata": model.metadata,
        "blocks": [asdict(block) for _, block in sorted(model.blocks.items())],
        "lines": [asdict(line) for line in sorted(model.lines)],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    raw = list(sys.argv[1:] if argv is None else argv)
    if len(raw) >= 2 and not raw[0].startswith("-") and raw[0] not in {"diff", "git-diff", "review", "context", "inspect", "view", "html", "studio", "serve", "run-m", "apply", "matlab-status"}:
        raw = ["diff", *raw]

    args = parser.parse_args(raw)
    if args.command is None:
        parser.print_help()
        return 2

    try:
        if args.command == "review":
            old = parse_slx(args.old)
            new = parse_slx(args.new)
            report = build_review_report(old, new)
            renderer = {"text": render_review_text, "markdown": render_review_markdown, "json": render_review_json}[args.format]
            print(renderer(report))
            return 0

        if args.command == "context":
            old = parse_slx(args.old)
            new = parse_slx(args.new)
            text = render_agent_context_json(old, new, max_hotspots=max(0, args.max_hotspots))
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(text + "\n", encoding="utf-8")
                print(args.output)
            else:
                print(text)
            return 0

        if args.command == "inspect":
            print(_inspect(args.model))
            return 0

        if args.command == "matlab-status":
            status = find_matlab(args.matlab)
            print(json.dumps({"available": status.available, "executable": status.executable, "detail": status.detail}, indent=2))
            return 0 if status.available else 1

        if args.command in {"studio", "serve"}:
            run_workbench_server(
                path=args.path,
                matlab=args.matlab,
                host=args.host,
                port=args.port,
                open_browser=(args.command == "studio" and not getattr(args, "no_browser", False)),
                token=args.token,
            )
            return 0

        if args.command == "run-m":
            result = run_m_file(args.script, matlab=args.matlab, timeout=args.timeout)
            if result.get("stdout"):
                print(result["stdout"], end="" if result["stdout"].endswith("\n") else "\n")
            if result.get("stderr"):
                print(result["stderr"], file=sys.stderr, end="" if result["stderr"].endswith("\n") else "\n")
            return 0 if result.get("ok") else int(result.get("returncode") or 1)

        if args.command == "apply":
            patch = load_patch(args.patch)
            result = apply_patch_with_matlab(
                args.model,
                patch,
                output_path=args.output,
                matlab=args.matlab,
                simulate=args.simulate,
                stop_time=args.stop_time,
            )
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0

        if args.command == "view":
            path = open_studio(args.model, args.compare)
            print(f"SLX Studio opened: {path}")
            return 0

        if args.command == "html":
            path = write_studio_html(args.model, args.compare, output=args.output)
            print(path)
            return 0

        if args.command == "git-diff":
            diffs = compare_git_refs(
                args.base,
                args.head,
                cwd=args.repo,
                include_layout=args.include_layout,
            )
            report = render_git_markdown(diffs)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(report + "\n", encoding="utf-8")
            else:
                print(report)
            if args.fail_on_change and any(item.result.changed for item in diffs):
                return 1
            return 0

        old = parse_slx(args.old)
        new = parse_slx(args.new)
        result = compare_models(old, new, include_layout=args.include_layout)
        renderer = {"text": render_text, "markdown": render_markdown, "json": render_json}[args.format]
        print(renderer(result))
        if args.fail_on_change and result.changed:
            return 1
        return 0
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"slx-diff: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
