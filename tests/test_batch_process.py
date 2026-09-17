"""Console byte-stream regressions; Python children are not MATLAB evidence."""

import sys

import pytest

from slxdiff import batch_process


@pytest.mark.parametrize("encoding", ["utf-8", "cp936"])
def test_batch_console_preserves_split_chinese_messages(monkeypatch, encoding):
    monkeypatch.setattr(batch_process, "_console_encoding", lambda: encoding)
    message = "无法与 MathWorks 服务通信 (5001)"
    raw = message.encode(encoding)
    script = (
        "import os,time; "
        f"data={raw!r}; "
        "os.write(1,data[:1]); time.sleep(.1); os.write(1,data[1:]); os.write(2,data)"
    )
    result = batch_process.run_batch([sys.executable, "-c", script], timeout=10)
    assert result.returncode == 0
    assert result.stdout == message
    assert result.stderr == message


def test_batch_console_flushes_incomplete_character_without_crashing(monkeypatch):
    monkeypatch.setattr(batch_process, "_console_encoding", lambda: "utf-8")
    result = batch_process.run_batch(
        [sys.executable, "-c", "import os; os.write(2, b'problem: \\xe4')"], timeout=10
    )
    assert result.stderr == "problem: \ufffd"
