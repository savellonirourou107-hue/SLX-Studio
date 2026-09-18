from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from typing import Any

from .diff import compare_models
from .model import Model
from .parser import parse_slx, parse_slx_bytes

_MAX_GIT_OUTPUT = 1024 * 1024
_MAX_GIT_DIFF = 512 * 1024
_MAX_SLX_BLOB = 32 * 1024 * 1024
_MAX_STATUS_ENTRIES = 500
_MAX_SLX_DETAILS = 100
_GIT_TIMEOUT_SECONDS = 8.0


class GitWorkspaceError(ValueError):
    """A bounded read-only Git operation could not be completed."""


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "GIT_PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_LITERAL_PATHSPECS": "1",
            "LC_ALL": "C",
        }
    )
    return env


def _git(root: Path, *args: str, max_bytes: int = _MAX_GIT_OUTPUT) -> bytes:
    """Run a read-only Git command with bounded combined output and wall time."""

    command = [
        "git",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "diff.external=",
        "-c",
        "submodule.recurse=false",
        *args,
    ]
    try:
        process = subprocess.Popen(
            command,
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=_git_env(),
        )
    except FileNotFoundError as exc:
        raise GitWorkspaceError("git executable was not found") from exc

    output = bytearray()
    overflow = False
    reader_error: BaseException | None = None

    def drain() -> None:
        nonlocal overflow, reader_error
        try:
            assert process.stdout is not None
            while True:
                chunk = process.stdout.read(64 * 1024)
                if not chunk:
                    return
                if len(output) + len(chunk) > max_bytes:
                    overflow = True
                    process.kill()
                    return
                output.extend(chunk)
        except BaseException as exc:  # pragma: no cover - defensive pipe failure
            reader_error = exc
            process.kill()

    reader = threading.Thread(target=drain, name="slx-studio-git-output", daemon=True)
    reader.start()
    reader.join(_GIT_TIMEOUT_SECONDS)
    if reader.is_alive():
        process.kill()
        reader.join(1)
        raise GitWorkspaceError("git command timed out")
    try:
        return_code = process.wait(timeout=1)
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - kill should be immediate
        process.kill()
        raise GitWorkspaceError("git process did not terminate") from exc
    if reader_error is not None:
        raise GitWorkspaceError(f"could not read git output: {reader_error}")
    if overflow:
        raise GitWorkspaceError(f"git output exceeded the {max_bytes}-byte safety limit")
    if return_code != 0:
        message = bytes(output).decode("utf-8", errors="replace").strip()
        raise GitWorkspaceError(message or f"git {args[0] if args else ''} failed")
    return bytes(output)


def _relative(root: Path, raw: str, *, must_exist: bool = False) -> str:
    if not isinstance(raw, str) or not raw or len(raw) > 4096 or "\x00" in raw:
        raise GitWorkspaceError("git path must be a bounded workspace-relative string")
    normalized = raw.replace("\\", "/")
    parts = normalized.split("/")
    if normalized.startswith("/") or any(not part or part in {".", ".."} for part in parts):
        raise GitWorkspaceError("git path must stay inside the workspace")
    candidate = (root / normalized).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise GitWorkspaceError("git path escapes the workspace") from exc
    if must_exist and not candidate.exists():
        raise GitWorkspaceError(f"workspace file no longer exists: {normalized}")
    return Path(*parts).as_posix()


def _repository_available(root: Path) -> tuple[bool, str]:
    try:
        top = _git(root, "rev-parse", "--show-toplevel", max_bytes=16 * 1024)
    except GitWorkspaceError as exc:
        return False, str(exc)
    if not top.strip():
        return False, "workspace is not inside a Git repository"
    return True, "Git repository detected"


def _head(root: Path) -> str | None:
    try:
        value = _git(root, "rev-parse", "--verify", "HEAD", max_bytes=4096).decode("ascii").strip()
    except GitWorkspaceError:
        return None
    return value or None


def _branch(root: Path) -> str:
    try:
        value = _git(root, "branch", "--show-current", max_bytes=4096).decode("utf-8").strip()
    except GitWorkspaceError:
        return ""
    return value


def _parse_status(root: Path, raw: bytes) -> tuple[list[dict[str, Any]], int, bool]:
    fields = raw.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    entries: list[dict[str, Any]] = []
    ignored_other = 0
    truncated = False
    index = 0
    while index < len(fields):
        field = fields[index]
        index += 1
        if len(field) < 4 or field[2:3] != b" ":
            raise GitWorkspaceError("unexpected output from git status")
        status = field[:2].decode("ascii", errors="strict")
        try:
            path = field[3:].decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            ignored_other += 1
            continue
        old_path: str | None = None
        if "R" in status or "C" in status:
            if index >= len(fields):
                raise GitWorkspaceError("truncated rename/copy record from git status")
            try:
                old_path = fields[index].decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                old_path = None
            index += 1
        try:
            path = _relative(root, path)
            old_path = _relative(root, old_path) if old_path else None
        except GitWorkspaceError:
            ignored_other += 1
            continue
        suffix = Path(path).suffix.lower()
        if suffix not in {".m", ".slx"}:
            ignored_other += 1
            continue
        if len(entries) == _MAX_STATUS_ENTRIES:
            truncated = True
            continue
        entries.append(
            {
                "path": path,
                "old_path": old_path,
                "index": status[0],
                "worktree": status[1],
                "kind": "matlab" if suffix == ".m" else "simulink",
                "untracked": status == "??",
            }
        )
    entries.sort(key=lambda item: str(item["path"]).casefold())
    return entries, ignored_other, truncated


def git_status(root: str | Path) -> dict[str, Any]:
    workspace = Path(root).resolve()
    available, detail = _repository_available(workspace)
    if not available:
        return {
            "available": False,
            "detail": detail,
            "branch": "",
            "head": None,
            "entries": [],
            "ignored_other": 0,
            "truncated": False,
        }
    raw = _git(
        workspace,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=normal",
        "--ignore-submodules=all",
        "--",
        ".",
    )
    entries, ignored_other, truncated = _parse_status(workspace, raw)
    return {
        "available": True,
        "detail": detail,
        "branch": _branch(workspace),
        "head": _head(workspace),
        "entries": entries,
        "ignored_other": ignored_other,
        "truncated": truncated,
    }


def _status_entry(root: Path, relative: str) -> dict[str, Any] | None:
    status = git_status(root)
    if not status["available"]:
        raise GitWorkspaceError(status["detail"])
    for entry in status["entries"]:
        if entry["path"] == relative or entry.get("old_path") == relative:
            return entry
    return None


def _empty_model(name: str) -> Model:
    return Model(name=Path(name).stem)


def _text_diff(root: Path, relative: str, entry: dict[str, Any] | None) -> dict[str, Any]:
    if entry and entry.get("untracked"):
        path = root / relative
        with path.open("rb") as handle:
            data = handle.read(_MAX_GIT_DIFF + 1)
        if len(data) > _MAX_GIT_DIFF:
            raise GitWorkspaceError("untracked MATLAB preview exceeds the 512 KiB limit")
        text = data.decode("utf-8-sig", errors="strict")
        lines = text.splitlines()
        preview = "\n".join(
            [
                "--- /dev/null",
                f"+++ b/{relative}",
                f"@@ -0,0 +1,{len(lines)} @@",
                *[f"+{line}" for line in lines],
            ]
        )
        if len(preview.encode("utf-8")) > _MAX_GIT_DIFF:
            raise GitWorkspaceError("untracked MATLAB diff exceeds the 512 KiB limit")
        return {"kind": "text", "path": relative, "diff": preview, "truncated": False}

    if _head(root) is None:
        raise GitWorkspaceError("Git diff requires at least one commit")
    paths = [relative]
    if entry and entry.get("old_path") and entry["old_path"] != relative:
        paths.append(str(entry["old_path"]))
    raw = _git(
        root,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--no-color",
        "--unified=3",
        "HEAD",
        "--",
        *paths,
        max_bytes=_MAX_GIT_DIFF,
    )
    return {
        "kind": "text",
        "path": relative,
        "diff": raw.decode("utf-8", errors="replace"),
        "truncated": False,
    }


def _slx_diff(root: Path, relative: str, entry: dict[str, Any] | None) -> dict[str, Any]:
    current = root / relative
    deleted = entry is not None and entry.get("worktree") == "D"
    added = entry is not None and (entry.get("untracked") or entry.get("index") == "A")
    old_path = str(entry.get("old_path") or relative) if entry else relative

    if added or _head(root) is None:
        old = _empty_model(relative)
    else:
        old_blob = _git(root, "show", f"HEAD:{old_path}", max_bytes=_MAX_SLX_BLOB)
        old = parse_slx_bytes(old_blob, name=old_path)

    if deleted:
        new = _empty_model(relative)
    else:
        _relative(root, relative, must_exist=True)
        new = parse_slx(current)

    result = compare_models(old, new)
    changed = [
        {
            "path": item.after.path,
            "before_name": item.before.name,
            "after_name": item.after.name,
            "parameter_changes": [change.name for change in item.parameter_changes[:25]],
        }
        for item in result.changed_blocks[:_MAX_SLX_DETAILS]
    ]
    return {
        "kind": "slx",
        "path": relative,
        "change_count": result.change_count,
        "added_blocks": [item.path for item in result.added_blocks[:_MAX_SLX_DETAILS]],
        "removed_blocks": [item.path for item in result.removed_blocks[:_MAX_SLX_DETAILS]],
        "changed_blocks": changed,
        "added_lines": len(result.added_lines),
        "removed_lines": len(result.removed_lines),
        "truncated": any(
            len(items) > _MAX_SLX_DETAILS
            for items in (result.added_blocks, result.removed_blocks, result.changed_blocks)
        ),
    }


def git_diff(root: str | Path, relative: str) -> dict[str, Any]:
    workspace = Path(root).resolve()
    relative = _relative(workspace, relative)
    suffix = Path(relative).suffix.lower()
    if suffix not in {".m", ".slx"}:
        raise GitWorkspaceError("source-control preview supports only .m and .slx files")
    entry = _status_entry(workspace, relative)
    if suffix == ".m":
        return _text_diff(workspace, relative, entry)
    return _slx_diff(workspace, relative, entry)
