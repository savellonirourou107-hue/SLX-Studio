from __future__ import annotations

from pathlib import Path

import pytest

from slxdiff.debugger import BreakpointRegistry
from slxdiff.mrunner import _instrument_tracepoints


def test_breakpoint_registry_validates_and_lists_workspace_lines(tmp_path: Path) -> None:
    script = tmp_path / "controller.m"
    script.write_text("a = 1;\nb = 2;\n", encoding="utf-8")
    registry = BreakpointRegistry(tmp_path)

    assert registry.set("controller.m", 2) == {"path": "controller.m", "lines": [2]}
    assert registry.list() == {"breakpoints": [{"path": "controller.m", "lines": [2]}]}
    assert registry.clear("controller.m", 2) == {"path": "controller.m", "lines": []}
    with pytest.raises(ValueError, match="outside"):
        registry.set("controller.m", 4)


def test_tracepoint_instrumentation_rejects_comments_and_continuations(tmp_path: Path) -> None:
    trace = tmp_path / "events.jsonl"
    source = tmp_path / "controller.m"
    source.write_text("a = 1;\n% comment\na = ...\n    2;\n", encoding="utf-8")

    instrumented = _instrument_tracepoints(source.read_text(encoding="utf-8"), [1], trace, source)
    assert "slxstudio_tracepoint" in instrumented
    with pytest.raises(ValueError, match="debug probe"):
        _instrument_tracepoints(source.read_text(encoding="utf-8"), [2], trace, source)
    with pytest.raises(ValueError, match="debug probe"):
        _instrument_tracepoints(source.read_text(encoding="utf-8"), [3], trace, source)
