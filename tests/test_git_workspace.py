from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from slxdiff.git_workspace import GitWorkspaceError, git_diff, git_status

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git executable is required")


def run_git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )


def write_slx(path: Path, gain: str) -> None:
    xml = (
        '<System><Block BlockType="Gain" Name="Gain" SID="1">'
        f'<P Name="Gain">{gain}</P>'
        "</Block></System>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("simulink/systems/system_root.xml", xml)


def initialized_workspace(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    workspace = repo / "project"
    workspace.mkdir(parents=True)
    run_git(repo, "init")
    run_git(repo, "config", "user.email", "tests@example.invalid")
    run_git(repo, "config", "user.name", "SLX Studio Tests")
    (repo / "outside.m").write_text("outside = 1;\n", encoding="utf-8")
    (workspace / "controller.m").write_text("gain = 1;\n", encoding="utf-8")
    write_slx(workspace / "model.slx", "1")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-m", "baseline")
    return repo, workspace


def test_status_and_diffs_are_scoped_to_workspace(tmp_path):
    repo, workspace = initialized_workspace(tmp_path)
    (repo / "outside.m").write_text("outside = 2;\n", encoding="utf-8")
    (workspace / "controller.m").write_text("gain = 2;\n", encoding="utf-8")
    (workspace / "new.m").write_text("fresh = 1;\n", encoding="utf-8")
    write_slx(workspace / "model.slx", "2")

    status = git_status(workspace)
    assert status["available"] is True
    paths = {entry["path"] for entry in status["entries"]}
    assert paths == {"controller.m", "model.slx", "new.m"}
    assert "outside.m" not in paths
    assert status["head"]
    assert status["truncated"] is False

    text = git_diff(workspace, "controller.m")
    assert text["kind"] == "text"
    assert "-gain = 1;" in text["diff"]
    assert "+gain = 2;" in text["diff"]

    untracked = git_diff(workspace, "new.m")
    assert untracked["kind"] == "text"
    assert "--- /dev/null" in untracked["diff"]
    assert "+fresh = 1;" in untracked["diff"]

    model = git_diff(workspace, "model.slx")
    assert model["kind"] == "slx"
    assert model["change_count"] == 1
    assert model["changed_blocks"][0]["path"] == "Gain"
    assert model["changed_blocks"][0]["parameter_changes"] == ["Gain"]


def test_git_workspace_rejects_escape_and_handles_non_repo(tmp_path):
    status = git_status(tmp_path)
    assert status["available"] is False
    assert status["entries"] == []

    repo, workspace = initialized_workspace(tmp_path / "nested")
    del repo
    with pytest.raises(GitWorkspaceError, match="workspace|path|escape"):
        git_diff(workspace, "../outside.m")


def test_status_handles_rename_without_leaking_repo_prefix(tmp_path):
    _, workspace = initialized_workspace(tmp_path)
    run_git(workspace, "mv", "controller.m", "renamed.m")
    status = git_status(workspace)
    entry = next(item for item in status["entries"] if item["path"] == "renamed.m")
    assert entry["old_path"] == "controller.m"
    assert entry["index"] == "R"
