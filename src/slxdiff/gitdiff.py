from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .diff import DiffResult, compare_models
from .model import Model
from .parser import parse_slx_bytes
from .review import ReviewReport, build_review_report


@dataclass(frozen=True)
class GitModelDiff:
    status: str
    old_path: str | None
    new_path: str | None
    result: DiffResult
    review: ReviewReport

    @property
    def display_path(self) -> str:
        if self.old_path and self.new_path and self.old_path != self.new_path:
            return f"{self.old_path} → {self.new_path}"
        return self.new_path or self.old_path or "(unknown model)"


def _git(cwd: Path, *args: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
        )
    except FileNotFoundError as exc:
        raise ValueError("git executable was not found") from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(message or f"git {' '.join(args)} failed") from exc
    return completed.stdout


def _blob(cwd: Path, ref: str, path: str) -> bytes:
    return _git(cwd, "show", f"{ref}:{path}")


def _empty(name: str) -> Model:
    return Model(name=Path(name).stem)


def _name_status(cwd: Path, base: str, head: str) -> list[tuple[str, str | None, str | None]]:
    raw = _git(cwd, "diff", "--name-status", "-z", "--find-renames", base, head, "--", "*.slx")
    fields = raw.decode("utf-8", errors="surrogateescape").split("\0")
    if fields and fields[-1] == "":
        fields.pop()

    changes: list[tuple[str, str | None, str | None]] = []
    index = 0
    while index < len(fields):
        status_token = fields[index]
        index += 1
        status = status_token[:1]
        if status in {"R", "C"}:
            if index + 1 >= len(fields):
                raise ValueError("unexpected truncated output from git diff --name-status")
            old_path, new_path = fields[index], fields[index + 1]
            index += 2
        else:
            if index >= len(fields):
                raise ValueError("unexpected truncated output from git diff --name-status")
            path = fields[index]
            index += 1
            old_path = None if status == "A" else path
            new_path = None if status == "D" else path
        changes.append((status, old_path, new_path))
    return changes


def compare_git_refs(
    base: str,
    head: str = "HEAD",
    *,
    cwd: str | Path = ".",
    include_layout: bool = False,
) -> list[GitModelDiff]:
    """Compare every SLX model changed between two Git refs."""
    repo = Path(cwd)
    diffs: list[GitModelDiff] = []
    for status, old_path, new_path in _name_status(repo, base, head):
        if old_path is None:
            assert new_path is not None
            old = _empty(new_path)
            new = parse_slx_bytes(_blob(repo, head, new_path), name=new_path)
        elif new_path is None:
            old = parse_slx_bytes(_blob(repo, base, old_path), name=old_path)
            new = _empty(old_path)
        else:
            old = parse_slx_bytes(_blob(repo, base, old_path), name=old_path)
            new = parse_slx_bytes(_blob(repo, head, new_path), name=new_path)

        diffs.append(
            GitModelDiff(
                status=status,
                old_path=old_path,
                new_path=new_path,
                result=compare_models(old, new, include_layout=include_layout),
                review=build_review_report(old, new),
            )
        )
    return diffs
