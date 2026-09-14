from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from slxdiff.mcp import McpServer, run_mcp_server


def create_test_slx(path: Path, *, gain: str = "5") -> None:
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<System>
  <Block BlockType="Inport" Name="In1" SID="1"><P Name="Position">[10 10 30 30]</P></Block>
  <Block BlockType="Gain" Name="Gain1" SID="2">
    <P Name="Gain">{gain}</P>
    <P Name="Position">[50 10 80 30]</P>
  </Block>
  <Block BlockType="Outport" Name="Out1" SID="3"><P Name="Position">[100 10 120 30]</P></Block>
  <Line><P Name="Src">1#out:1</P><P Name="Dst">2#in:1</P></Line>
  <Line><P Name="Src">2#out:1</P><P Name="Dst">3#in:1</P></Line>
</System>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("simulink/systems/system_root.xml", xml)


def test_mcp_initialize() -> None:
    server = McpServer()
    resp_str = server.process_message(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}))
    assert resp_str is not None
    data = json.loads(resp_str)
    assert data["id"] == 1
    assert data["result"]["protocolVersion"] == "2024-11-05"
    assert data["result"]["serverInfo"]["name"] == "slx-studio"


def test_mcp_ping_and_notifications() -> None:
    server = McpServer()
    resp_str = server.process_message(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}))
    assert resp_str is not None
    data = json.loads(resp_str)
    assert data["id"] == 2
    assert data["result"] == {}

    # Notifications return None
    assert (
        server.process_message(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})) is None
    )


def test_mcp_tools_list() -> None:
    server = McpServer()
    resp_str = server.process_message(json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/list"}))
    assert resp_str is not None
    data = json.loads(resp_str)
    tool_names = [t["name"] for t in data["result"]["tools"]]
    assert "slx_inspect_model" in tool_names
    assert "slx_diff_models" in tool_names
    assert "slx_review_intelligence" in tool_names
    assert "slx_read_script" in tool_names
    assert "slx_search_workspace" in tool_names
    assert "slx_propose_script_edit" in tool_names


def test_mcp_script_tools(tmp_path: Path) -> None:
    server = McpServer(root=tmp_path)
    script = tmp_path / "controller.m"
    script.write_text("Kp = 10;\nKi = 2;\n", encoding="utf-8")

    # 1. Read script
    read_resp = server.process_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "slx_read_script", "arguments": {"path": "controller.m"}},
            }
        )
    )
    assert read_resp is not None
    read_data = json.loads(read_resp)
    assert read_data["result"]["isError"] is False
    assert "Kp = 10;" in read_data["result"]["content"][0]["text"]

    # 2. Search workspace
    search_resp = server.process_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "slx_search_workspace", "arguments": {"query": "Kp"}},
            }
        )
    )
    assert search_resp is not None
    search_data = json.loads(search_resp)
    assert "controller.m" in search_data["result"]["content"][0]["text"]

    # 3. Propose script edit
    edit_resp = server.process_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "slx_propose_script_edit",
                    "arguments": {
                        "path": "controller.m",
                        "content": "Kp = 20;\nKi = 2;\n",
                    },
                },
            }
        )
    )
    assert edit_resp is not None
    edit_data = json.loads(edit_resp)
    assert edit_data["result"]["isError"] is False
    assert "+Kp = 20;" in edit_data["result"]["content"][0]["text"]


def test_mcp_slx_tools(tmp_path: Path) -> None:
    server = McpServer(root=tmp_path)
    model1 = tmp_path / "m1.slx"
    model2 = tmp_path / "m2.slx"
    create_test_slx(model1, gain="5")
    create_test_slx(model2, gain="10")

    # 1. Inspect model
    inspect_resp = server.process_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "slx_inspect_model", "arguments": {"path": "m1.slx"}},
            }
        )
    )
    assert inspect_resp is not None
    inspect_data = json.loads(inspect_resp)
    assert inspect_data["result"]["isError"] is False
    assert '"block_count": 3' in inspect_data["result"]["content"][0]["text"]

    # 2. Diff models
    diff_resp = server.process_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": {
                    "name": "slx_diff_models",
                    "arguments": {"left_path": "m1.slx", "right_path": "m2.slx"},
                },
            }
        )
    )
    assert diff_resp is not None
    diff_data = json.loads(diff_resp)
    assert diff_data["result"]["isError"] is False
    assert "Gain" in diff_data["result"]["content"][0]["text"]

    # 3. Review intelligence
    review_resp = server.process_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {
                    "name": "slx_review_intelligence",
                    "arguments": {"left_path": "m1.slx", "right_path": "m2.slx"},
                },
            }
        )
    )
    assert review_resp is not None
    review_data = json.loads(review_resp)
    assert review_data["result"]["isError"] is False


def test_mcp_error_handling() -> None:
    server = McpServer()

    # Unknown method
    res1 = json.loads(server.process_message(json.dumps({"jsonrpc": "2.0", "id": 10, "method": "foo"})))
    assert "error" in res1
    assert res1["error"]["code"] == -32601

    # Invalid JSON
    res2 = json.loads(server.process_message("not valid json"))
    assert res2["error"]["code"] == -32700

    # Unknown tool call
    res3 = json.loads(
        server.process_message(
            json.dumps(
                {"jsonrpc": "2.0", "id": 11, "method": "tools/call", "params": {"name": "non_existent"}}
            )
        )
    )
    assert res3["result"]["isError"] is True


def test_run_mcp_server_stream() -> None:
    in_buf = io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}) + "\n")
    out_buf = io.StringIO()
    run_mcp_server(in_stream=in_buf, out_stream=out_buf)

    result_line = out_buf.getvalue().strip()
    data = json.loads(result_line)
    assert data["id"] == 1
    assert data["result"] == {}
