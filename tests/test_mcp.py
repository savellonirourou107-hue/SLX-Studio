from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

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


@pytest.mark.parametrize(
    ("tool", "path_key"),
    [
        ("slx_inspect_model", "path"),
        ("slx_diff_models", "left_path"),
        ("slx_diff_models", "right_path"),
        ("slx_review_intelligence", "left_path"),
        ("slx_review_intelligence", "right_path"),
    ],
)
def test_mcp_rejects_absolute_workspace_escape(tmp_path: Path, tool: str, path_key: str) -> None:
    workspace = tmp_path / "workspace"
    create_test_slx(workspace / "safe.slx")
    outside = tmp_path / "workspace-other" / "private.slx"
    create_test_slx(outside)
    arguments = {"path": "safe.slx", "left_path": "safe.slx", "right_path": "safe.slx"}
    arguments[path_key] = str(outside)
    with pytest.raises(ValueError, match="workspace root"):
        McpServer(workspace).call_tool(tool, arguments)


def test_mcp_absolute_path_inside_workspace_is_allowed(tmp_path: Path) -> None:
    model = tmp_path / "model.slx"
    create_test_slx(model)
    assert McpServer(tmp_path).call_tool("slx_inspect_model", {"path": str(model)})["isError"] is False


def test_mcp_rejects_symlink_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "private.slx"
    create_test_slx(outside)
    link = workspace / "linked.slx"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation requires platform support/privilege")
    server = McpServer(workspace)
    for supplied_path in (str(link), "linked.slx", "../private.slx"):
        with pytest.raises(ValueError, match="workspace root"):
            server.call_tool("slx_inspect_model", {"path": supplied_path})


@pytest.mark.parametrize(
    "payload", [[], None, 42, "request", {"id": 1}, {"jsonrpc": "1.0", "id": 1, "method": "ping"}]
)
def test_mcp_invalid_envelope_returns_protocol_error(payload: object) -> None:
    response = json.loads(McpServer().process_message(json.dumps(payload)))
    assert response["error"]["code"] == -32600


@pytest.mark.parametrize("params", [[], "params", False, 12])
def test_mcp_invalid_params_returns_protocol_error(params: object) -> None:
    response = json.loads(
        McpServer().process_message(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params})
        )
    )
    assert response["error"]["code"] == -32602


@pytest.mark.parametrize("binary", [False, True])
def test_mcp_oversized_line_is_bounded_and_next_request_survives(binary: bool) -> None:
    from slxdiff.mcp import MAX_REQUEST_BYTES

    ping = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "ping"})
    source = '"' + "x" * (MAX_REQUEST_BYTES + 5) + '"\n' + ping + "\n"
    reader = io.BytesIO(source.encode()) if binary else io.StringIO(source)
    writer = io.BytesIO() if binary else io.StringIO()
    run_mcp_server(in_stream=reader, out_stream=writer)
    responses = [json.loads(line) for line in writer.getvalue().splitlines()]
    assert len(responses) == 2
    assert responses[0]["error"]["code"] == -32600
    assert responses[1] == {"jsonrpc": "2.0", "id": 7, "result": {}}


def test_mcp_invalid_utf8_does_not_stop_stream() -> None:
    reader = io.BytesIO(b'\xff\n{"jsonrpc":"2.0","id":2,"method":"ping"}\n')
    writer = io.BytesIO()
    run_mcp_server(in_stream=reader, out_stream=writer)
    responses = [json.loads(line) for line in writer.getvalue().splitlines()]
    assert responses[0]["error"]["code"] == -32700
    assert responses[1]["result"] == {}


def test_mcp_integer_decoder_limit_does_not_stop_stream() -> None:
    # Modern Python raises ValueError (not JSONDecodeError) for oversized ints.
    # Older Python decodes it, then correctly rejects the non-object envelope.
    reader = io.StringIO("9" * 5000 + '\n{"jsonrpc":"2.0","id":2,"method":"ping"}\n')
    writer = io.StringIO()
    run_mcp_server(in_stream=reader, out_stream=writer)
    responses = [json.loads(line) for line in writer.getvalue().splitlines()]
    assert responses[0]["error"]["code"] in {-32600, -32700}
    assert responses[1]["result"] == {}
