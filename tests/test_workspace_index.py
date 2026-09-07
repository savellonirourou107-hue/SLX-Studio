"""Regression coverage for incremental index lifecycle and search boundaries."""

import threading
import time

import pytest

from slxdiff import workspace


def ready(index):
    deadline = time.monotonic() + 5
    while index.snapshot()["indexing"] and time.monotonic() < deadline:
        time.sleep(0.01)
    assert index.snapshot()["index_state"] == "ready"


@pytest.mark.parametrize("limits", [(100, 1, 100), (1, 100, 1)])
def test_search_limit_is_request_scoped(tmp_path, limits):
    (tmp_path / "controller.m").write_text("target = 42;", encoding="utf-8")
    index = workspace.WorkspaceIndex(tmp_path)
    ready(index)
    for limit in limits:
        results = index.search("target", max_file_bytes=limit)["results"]
        assert bool(results) == (limit == 100)


@pytest.mark.parametrize("fail_first", [False, True])
def test_write_during_build_schedules_followup(tmp_path, monkeypatch, fail_first):
    captured = threading.Event()
    release = threading.Event()
    walk = workspace._walk_indexed
    calls = []

    def blocked(*args, **kwargs):
        result = walk(*args, **kwargs)
        calls.append(1)
        if len(calls) == 1:
            captured.set()
            assert release.wait(5)
            if fail_first:
                raise OSError("scan interrupted")
        return result

    monkeypatch.setattr(workspace, "_walk_indexed", blocked)
    index = workspace.WorkspaceIndex(tmp_path)
    try:
        assert captured.wait(5)
        (tmp_path / "new.m").write_text("target = 1;", encoding="utf-8")
        index.invalidate()
        index.invalidate()
    finally:
        release.set()
    ready(index)
    assert len(calls) == 2
    assert index.search("target")["results"]


def test_search_revalidates_indexed_path(tmp_path, monkeypatch):
    (tmp_path / "model.slx").write_bytes(b"not a model")
    index = workspace.WorkspaceIndex(tmp_path)
    ready(index)
    checked = []

    def escaped(root, relative):
        checked.append(relative)
        raise ValueError("workspace path escapes the workspace root")

    monkeypatch.setattr(workspace, "resolve_workspace_path", escaped)
    assert index.search("Gain")["results"] == []
    assert checked == ["model.slx"]


def test_unchanged_search_reuses_text_and_detects_external_edit(tmp_path, monkeypatch):
    path = tmp_path / "controller.m"
    path.write_text("target = 1;", encoding="utf-8")
    index = workspace.WorkspaceIndex(tmp_path)
    ready(index)
    read = workspace.read_text_file
    reads = []

    def counted(*args):
        reads.append(1)
        return read(*args)

    monkeypatch.setattr(workspace, "read_text_file", counted)
    assert index.search("target")["results"]
    assert index.search("target")["results"]
    assert len(reads) == 1
    path.write_text("replacement = 200;", encoding="utf-8")
    assert not index.search("target")["results"]
    assert index.search("replacement")["results"]
    assert len(reads) == 2
