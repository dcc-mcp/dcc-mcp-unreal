from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from dcc_mcp_unreal import official_mcp


def _load_prepare_module():
    script = (
        Path(__file__).parents[1]
        / "src"
        / "dcc_mcp_unreal"
        / "skills"
        / "unreal-official-mcp"
        / "scripts"
        / "prepare_official_mcp.py"
    )
    spec = importlib.util.spec_from_file_location("_test_prepare_official_mcp", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Response:
    def __init__(self, body=b"", headers=None):
        self._body = body
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self._body


def _json_response(payload, headers=None):
    return _Response(json.dumps(payload).encode("utf-8"), headers=headers)


def test_decode_streamable_http_sse_response():
    payload = b'event: message\r\ndata: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\r\n\r\n'
    assert official_mcp._decode_response(payload)["result"] == {"ok": True}


def test_official_bridge_rejects_non_loopback_endpoint():
    with pytest.raises(official_mcp.OfficialMcpError, match="loopback"):
        official_mcp.OfficialMcpClient("https://example.com/mcp")


def test_prepare_official_mcp_upserts_plugins_idempotently():
    prepare = _load_prepare_module()
    project = {"Plugins": [{"Name": "EditorToolset", "Enabled": False}]}

    changed = prepare._upsert_plugins(project, ["ModelContextProtocol", "EditorToolset"])
    unchanged = prepare._upsert_plugins(project, ["ModelContextProtocol", "EditorToolset"])

    assert changed == ["ModelContextProtocol", "EditorToolset"]
    assert unchanged == []
    assert project["Plugins"] == [
        {"Name": "EditorToolset", "Enabled": True},
        {"Name": "ModelContextProtocol", "Enabled": True},
    ]


def test_prepare_official_mcp_resolves_project_and_engine(tmp_path):
    prepare = _load_prepare_module()
    engine = tmp_path / "UE_5.8" / "Engine"
    executable = engine / "Binaries" / "Win64" / "UnrealEditor.exe"
    project = tmp_path / "Rain Car" / "RainCar.uproject"

    project_file, plugin_dir = prepare._resolve_project_context([str(executable), str(project)])

    assert project_file == project.resolve()
    assert plugin_dir == engine.resolve() / "Plugins"


def test_prepare_official_mcp_resolves_equals_project_argument(tmp_path):
    prepare = _load_prepare_module()
    engine = tmp_path / "UE_5.8" / "Engine"
    executable = engine / "Binaries" / "Win64" / "UnrealEditor.exe"
    project = tmp_path / "Rain Car" / "RainCar.uproject"

    project_file, plugin_dir = prepare._resolve_project_context([str(executable), f"-project={project}", "-log"])

    assert project_file == project.resolve()
    assert plugin_dir == engine.resolve() / "Plugins"


def test_prepare_official_mcp_writes_autostart_idempotently(tmp_path):
    prepare = _load_prepare_module()
    config_path = tmp_path / "DefaultEditorPerProjectUserSettings.ini"

    assert prepare._configure_autostart(config_path) is True
    assert prepare._configure_autostart(config_path) is False
    contents = config_path.read_text(encoding="utf-8")
    assert "ServerPortNumber=8000" in contents
    assert "ServerUrlPath=/mcp" in contents
    assert "bAutoStartServer=True" in contents
    assert "bEnableToolSearch=True" in contents


@pytest.mark.parametrize("endpoint", [official_mcp.DEFAULT_OFFICIAL_MCP_URL, "http://127.0.0.1:18081/mcp"])
def test_bridge_calls_tool_search_meta_tool_and_closes_session(monkeypatch, endpoint):
    responses = iter(
        [
            _json_response(
                {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "unreal-mcp"}}},
                headers={"Mcp-Session-Id": "session-1"},
            ),
            _Response(),
            _json_response(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "result": {"tools": [{"name": "list_toolsets"}, {"name": "call_tool"}]},
                }
            ),
            _json_response({"jsonrpc": "2.0", "id": 3, "result": {"structuredContent": {"ok": True}}}),
            _Response(),
        ]
    )
    requests = []
    timeouts = []
    now = [100.0]

    def fake_urlopen(request, timeout):
        requests.append(request)
        timeouts.append(timeout)
        now[0] += 1.0
        return next(responses)

    monkeypatch.setattr(official_mcp, "monotonic", lambda: now[0])
    monkeypatch.setattr(official_mcp, "urlopen", fake_urlopen)

    result = official_mcp.bridge_official_mcp(
        "call_tool",
        endpoint=endpoint,
        toolset_name="ActorTools",
        tool_name="get_selected_actors",
        arguments={"include_components": False},
        timeout=42.0,
    )

    assert result == {"structuredContent": {"ok": True}}
    call_body = json.loads(requests[3].data.decode("utf-8"))
    assert call_body["params"] == {
        "name": "call_tool",
        "arguments": {
            "toolset_name": "ActorTools",
            "tool_name": "get_selected_actors",
            "arguments": {"include_components": False},
        },
    }
    assert requests[-1].method == "DELETE"
    assert all(request.full_url == endpoint for request in requests)
    assert timeouts == [42.0, 41.0, 40.0, 39.0, 38.0]


def test_client_propagates_inner_tool_error(monkeypatch):
    client = official_mcp.OfficialMcpClient()
    monkeypatch.setattr(
        client,
        "_send",
        lambda *args, **kwargs: {
            "result": {"content": [{"type": "text", "text": "CaptureViewport failed"}], "isError": True}
        },
    )
    with pytest.raises(official_mcp.OfficialMcpError, match="CaptureViewport failed"):
        client.call_tool("CaptureViewport")


def test_bridge_reads_official_mcp_resource(monkeypatch):
    responses = iter(
        [
            _json_response({"result": {}}, headers={"Mcp-Session-Id": "resource-session"}),
            _Response(),
            _json_response({"result": {"tools": []}}),
            _json_response({"result": {"contents": [{"uri": "ue://project/context", "text": "context"}]}}),
            _Response(),
        ]
    )
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        return _Response() if request.method == "DELETE" else next(responses)

    monkeypatch.setattr(official_mcp, "urlopen", fake_urlopen)

    result = official_mcp.bridge_official_mcp("read_resource", resource_uri="ue://project/context")

    assert result == {"contents": [{"uri": "ue://project/context", "text": "context"}]}
    assert json.loads(requests[3].data)["params"] == {"uri": "ue://project/context"}
    assert requests[-1].method == "DELETE"


def _stub_description_session(monkeypatch, tools, result=None):
    responses = iter(
        [
            _json_response({"result": {}}, headers={"Mcp-Session-Id": "description-session"}),
            _Response(),
            _json_response({"result": {"tools": tools}}),
            _json_response({"result": result or {"structuredContent": {"tools": []}}}),
            _Response(),
        ]
    )
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        # Validation failures close the session before any tools/call request.
        return _Response() if request.method == "DELETE" else next(responses)

    monkeypatch.setattr(official_mcp, "urlopen", fake_urlopen)
    return requests


def _description_tool(selector="toolset_names"):
    # Synthetic schemas exercise binding; these are not captured UE 5.9 responses.
    return {
        "name": "describe_toolsets",
        "inputSchema": {
            "type": "object",
            "properties": {
                selector: {"type": "array", "items": {"type": "string"}},
                "include_schemas": {"type": "boolean"},
            },
            "required": [selector],
        },
    }


@pytest.mark.parametrize("selector", ["toolset_names", "names"])
def test_describe_toolset_uses_advertised_plural_schema(monkeypatch, selector):
    requests = _stub_description_session(
        monkeypatch, [None, "invalid descriptor", {"name": "describe_toolset"}, _description_tool(selector)]
    )

    result = official_mcp.bridge_official_mcp("describe_toolset", toolset_name="EditorToolset.ActorToolset")

    assert result == {"structuredContent": {"tools": []}}
    assert json.loads(requests[3].data)["params"] == {
        "name": "describe_toolsets",
        "arguments": {selector: ["EditorToolset.ActorToolset"], "include_schemas": True},
    }
    assert requests[-1].method == "DELETE"


def test_describe_toolset_preserves_legacy_contract(monkeypatch):
    requests = _stub_description_session(monkeypatch, [{"name": "describe_toolset"}])

    official_mcp.bridge_official_mcp("describe_toolset", toolset_name="ActorTools")

    assert json.loads(requests[3].data)["params"] == {
        "name": "describe_toolset",
        "arguments": {"toolset_name": "ActorTools"},
    }
    assert requests[-1].method == "DELETE"


def test_describe_tools_uses_ue59_discovery_schema(monkeypatch):
    tool = {
        "name": "describe_tools",
        "inputSchema": {
            "type": "object",
            "properties": {"tool_names": {"type": "array", "items": {"type": "string"}}},
            "required": ["tool_names"],
        },
    }
    requests = _stub_description_session(monkeypatch, [tool])

    official_mcp.bridge_official_mcp(
        "describe_tools",
        tool_names=["EditorToolset.ActorToolset.GetSelectedActors"],
    )

    assert json.loads(requests[3].data)["params"] == {
        "name": "describe_tools",
        "arguments": {"tool_names": ["EditorToolset.ActorToolset.GetSelectedActors"]},
    }
    assert requests[-1].method == "DELETE"


@pytest.mark.parametrize(
    "schema",
    [
        None,
        {},
        {**_description_tool()["inputSchema"], "type": "string"},
        {"properties": []},
        {"properties": {"include_schemas": {"type": "boolean"}}},
        {"properties": {"names": {"type": "array", "items": {"type": "string"}}}},
        {
            "properties": {
                **_description_tool()["inputSchema"]["properties"],
                "other_names": {"type": "array", "items": {"type": "string"}},
            }
        },
        {**_description_tool()["inputSchema"], "required": ["unknown"]},
        {**_description_tool()["inputSchema"], "required": "toolset_names"},
        {**_description_tool()["inputSchema"], "required": [{}]},
    ],
)
def test_describe_toolset_rejects_unknown_plural_schema_without_fallback(monkeypatch, schema):
    requests = _stub_description_session(
        monkeypatch, [{"name": "describe_toolsets", "inputSchema": schema}, {"name": "describe_toolset"}]
    )

    with pytest.raises(official_mcp.OfficialMcpError, match="describe_toolsets.*schema"):
        official_mcp.bridge_official_mcp("describe_toolset", toolset_name="ActorTools")

    assert len(requests) == 4
    assert requests[-1].method == "DELETE"


def test_describe_toolset_requires_advertised_discovery_tool(monkeypatch):
    requests = _stub_description_session(monkeypatch, [{"name": "call_tool"}])

    with pytest.raises(official_mcp.OfficialMcpError, match="description tool"):
        official_mcp.bridge_official_mcp("describe_toolset", toolset_name="ActorTools")

    assert len(requests) == 4
    assert requests[-1].method == "DELETE"


def test_describe_toolset_propagates_plural_tool_error_without_retry(monkeypatch):
    requests = _stub_description_session(
        monkeypatch,
        [_description_tool(), {"name": "describe_toolset"}],
        {"isError": True, "content": [{"type": "text", "text": "Unknown toolset"}]},
    )

    with pytest.raises(official_mcp.OfficialMcpError, match="Unknown toolset"):
        official_mcp.bridge_official_mcp("describe_toolset", toolset_name="ActorTools")

    assert len(requests) == 5
    assert json.loads(requests[3].data)["params"]["name"] == "describe_toolsets"
    assert requests[-1].method == "DELETE"
