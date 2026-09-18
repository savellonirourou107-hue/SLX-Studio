"""Desktop RPC coverage for bounded workspace search and index refresh."""

from __future__ import annotations

import time

from slxdiff.rpc import Backend


def request(backend: Backend, method: str, params: dict | None = None, identifier: int = 1) -> dict:
    reply = backend.dispatch({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params or {}})
    assert isinstance(reply, dict)
    return reply


def search_ready(backend: Backend, query: str) -> dict:
    deadline = time.monotonic() + 5
    while True:
        reply = request(backend, "workspace/search", {"query": query})
        assert "error" not in reply, reply
        result = reply["result"]
        if not result.get("indexing"):
            return result
        assert time.monotonic() < deadline
        time.sleep(0.01)


def test_rpc_workspace_search_is_bounded_and_refreshable(tmp_path):
    (tmp_path / "controller.m").write_text("gain = 3;\nresponse = gain;\n", encoding="utf-8")
    backend = Backend(str(tmp_path))
    try:
        result = search_ready(backend, "gain")
        assert any(item["path"] == "controller.m" and item["line"] == 1 for item in result["results"])

        invalid = request(backend, "workspace/search", {"query": "x" * 201})
        assert invalid["error"]["data"]["kind"] == "invalid_params"
        assert "1-200" in invalid["error"]["message"]

        invalid_limit = request(backend, "workspace/search", {"query": "gain", "max_results": 0})
        assert invalid_limit["error"]["data"]["kind"] == "invalid_params"

        (tmp_path / "fresh.m").write_text("fresh_signal = 1;\n", encoding="utf-8")
        assert search_ready(backend, "fresh_signal")["results"] == []

        refreshed = request(backend, "workspace/index/refresh")
        assert refreshed["result"] == {"indexing": True}
        result = search_ready(backend, "fresh_signal")
        assert any(item["path"] == "fresh.m" for item in result["results"])
    finally:
        backend.close()
