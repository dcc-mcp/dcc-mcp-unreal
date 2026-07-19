from __future__ import annotations

import json

import pytest

from dcc_mcp_unreal import official_mcp


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
