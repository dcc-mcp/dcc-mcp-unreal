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


def test_bridge_calls_tool_search_meta_tool_and_closes_session(monkeypatch):
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

    def fake_urlopen(request, timeout):
        requests.append(request)
        assert timeout == 15.0
        return next(responses)

    monkeypatch.setattr(official_mcp, "urlopen", fake_urlopen)

    result = official_mcp.bridge_official_mcp(
        "call_tool",
        toolset_name="ActorTools",
        tool_name="get_selected_actors",
        arguments={"include_components": False},
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
