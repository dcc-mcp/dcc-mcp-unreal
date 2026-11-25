"""Optional bridge to Unreal Engine 5.8+ built-in MCP servers."""

from __future__ import annotations

import json
from contextlib import contextmanager
from time import monotonic
from typing import Any, Dict, Iterator, Mapping, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

DEFAULT_OFFICIAL_MCP_URL = "http://127.0.0.1:8000/mcp"
PROTOCOL_VERSION = "2025-06-18"


class OfficialMcpError(RuntimeError):
    """Raised when the optional Epic MCP endpoint cannot serve a request."""


def _validate_endpoint(endpoint: str) -> str:
    endpoint = endpoint.strip().rstrip("/")
    parsed = urlsplit(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise OfficialMcpError("Epic MCP bridging is restricted to a loopback HTTP endpoint")
    if not parsed.path:
        raise OfficialMcpError("Epic MCP endpoint must include its URL path, normally /mcp")
    return endpoint


def _decode_response(payload: bytes) -> Dict[str, Any]:
    text = payload.decode("utf-8").strip()
    if not text:
        return {}
    if text.startswith("event:") or "\ndata:" in text:
        data_lines = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
        if not data_lines:
            raise OfficialMcpError("Epic MCP returned an SSE response without JSON data")
        text = "\n".join(data_lines)
    try:
        decoded = json.loads(text)
    except ValueError as exc:
        raise OfficialMcpError("Epic MCP returned invalid JSON: {}".format(exc)) from exc
    if not isinstance(decoded, dict):
        raise OfficialMcpError("Epic MCP returned a non-object JSON-RPC response")
    return decoded


class OfficialMcpClient:
    """Small, dependency-free Streamable HTTP client for the local Epic server."""

    def __init__(self, endpoint: str = DEFAULT_OFFICIAL_MCP_URL, timeout: float = 15.0) -> None:
        self.endpoint = _validate_endpoint(endpoint)
        self.timeout = timeout
        self._deadline = monotonic() + timeout
        self.session_id = ""
        self._request_id = 0

    def _remaining_timeout(self) -> float:
        remaining = self._deadline - monotonic()
        if remaining <= 0:
            raise OfficialMcpError("Epic MCP operation timed out after {:g}s".format(self.timeout))
        return remaining

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _send(self, method: str, params: Optional[Mapping[str, Any]], notification: bool = False) -> Dict[str, Any]:
        body: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if not notification:
            body["id"] = self._next_id()
        if params is not None:
            body["params"] = dict(params)

        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "Mcp-Protocol-Version": PROTOCOL_VERSION,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id

        request = Request(
            self.endpoint,
            data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._remaining_timeout()) as response:
                if not self.session_id:
                    self.session_id = response.headers.get("Mcp-Session-Id", "")
                result = _decode_response(response.read())
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            raise OfficialMcpError("Epic MCP HTTP {}: {}".format(exc.code, detail or exc.reason)) from exc
        except (URLError, OSError) as exc:
            raise OfficialMcpError("Epic MCP is unavailable at {}: {}".format(self.endpoint, exc)) from exc

        error = result.get("error")
        if error:
            raise OfficialMcpError("Epic MCP JSON-RPC error: {}".format(error))
        return result

    def initialize(self) -> Dict[str, Any]:
        response = self._send(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "dcc-mcp-unreal", "version": "0.2.0"},
            },
        )
        if not self.session_id:
            raise OfficialMcpError("Epic MCP initialize response did not provide Mcp-Session-Id")
        self._send("notifications/initialized", {}, notification=True)
        return response.get("result", {})

    def list_tools(self) -> Dict[str, Any]:
        return self._send("tools/list", {}).get("result", {})

    def list_resources(self) -> Dict[str, Any]:
        return self._send("resources/list", {}).get("result", {})

    def read_resource(self, uri: str) -> Dict[str, Any]:
        return self._send("resources/read", {"uri": uri}).get("result", {})

    def call_tool(self, name: str, arguments: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        result = self._send("tools/call", {"name": name, "arguments": dict(arguments or {})}).get("result", {})
        if result.get("isError"):
            content = result.get("content", ())
            detail = next(
                (
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text" and item.get("text")
                ),
                "unknown tool error",
            )
            raise OfficialMcpError("Epic MCP tool error: {}".format(detail[:1000]))
        return result

    def close(self) -> None:
        if not self.session_id:
            return
        request = Request(
            self.endpoint,
            headers={"Mcp-Session-Id": self.session_id, "Mcp-Protocol-Version": PROTOCOL_VERSION},
            method="DELETE",
        )
        try:
            with urlopen(request, timeout=self._remaining_timeout()):
                pass
        except (HTTPError, URLError, OSError, OfficialMcpError):
            pass
        finally:
            self.session_id = ""

    @contextmanager
    def connected(self) -> Iterator["OfficialMcpClient"]:
        self.initialize()
        try:
            yield self
        finally:
            self.close()


def _tool_names(tool_list: Mapping[str, Any]) -> Tuple[str, ...]:
    tools = tool_list.get("tools", [])
    return tuple(item.get("name", "") for item in tools if isinstance(item, dict) and item.get("name"))


def bridge_official_mcp(
    operation: str,
    endpoint: str = DEFAULT_OFFICIAL_MCP_URL,
    toolset_name: str = "",
    tool_name: str = "",
    arguments: Optional[Mapping[str, Any]] = None,
    timeout: float = 15.0,
    tool_names: Optional[Sequence[str]] = None,
    resource_uri: str = "",
) -> Dict[str, Any]:
    """Execute one bounded operation against Epic's optional UE 5.8+ MCP server."""
    operation = operation.strip().lower()
    client = OfficialMcpClient(endpoint, timeout=timeout)
    with client.connected():
        tool_list = client.list_tools()
        names = _tool_names(tool_list)
        if operation == "status":
            return {"endpoint": client.endpoint, "protocol_version": PROTOCOL_VERSION, "tools": names}
        if operation == "list_tools":
            return tool_list
        if operation == "list_toolsets":
            return client.call_tool("list_toolsets")
        if operation == "list_resources":
            return client.list_resources()
        if operation == "read_resource":
            if not resource_uri:
                raise OfficialMcpError("resource_uri is required for read_resource")
            return client.read_resource(resource_uri)
        if operation == "describe_toolset":
            if not toolset_name:
                raise OfficialMcpError("toolset_name is required for describe_toolset")
            if "describe_toolsets" in names:
                tool = next(
                    item
                    for item in tool_list["tools"]
                    if isinstance(item, dict) and item.get("name") == "describe_toolsets"
                )
                schema = tool.get("inputSchema")
                properties = schema.get("properties") if isinstance(schema, dict) else None
                if not isinstance(properties, dict) or schema.get("type", "object") != "object":
                    raise OfficialMcpError("Epic MCP describe_toolsets has an unsupported input schema")
                selectors = [
                    name
                    for name, prop in properties.items()
                    if isinstance(prop, dict)
                    and prop.get("type") == "array"
                    and isinstance(prop.get("items"), dict)
                    and prop["items"].get("type") == "string"
                ]
                include_schemas = properties.get("include_schemas")
                required = schema.get("required", [])
                if (
                    len(selectors) != 1
                    or not isinstance(include_schemas, dict)
                    or include_schemas.get("type") != "boolean"
                    or not isinstance(required, list)
                    or any(not isinstance(name, str) for name in required)
                ):
                    raise OfficialMcpError("Epic MCP describe_toolsets has an unsupported input schema")
                description_arguments = {selectors[0]: [toolset_name], "include_schemas": True}
                if set(required).difference(description_arguments):
                    raise OfficialMcpError("Epic MCP describe_toolsets schema requires unsupported arguments")
                return client.call_tool("describe_toolsets", description_arguments)
            if "describe_toolset" in names:
                return client.call_tool("describe_toolset", {"toolset_name": toolset_name})
            raise OfficialMcpError("Epic MCP did not advertise a toolset description tool")
        if operation == "describe_tools":
            names_to_describe = list(tool_names or ())
            if tool_name and not names_to_describe:
                names_to_describe = [tool_name]
            if not names_to_describe:
                raise OfficialMcpError("tool_names or tool_name is required for describe_tools")
            if "describe_tools" not in names:
                raise OfficialMcpError("Epic MCP did not advertise the describe_tools discovery tool")
            tool = next(
                item
                for item in tool_list["tools"]
                if isinstance(item, dict) and item.get("name") == "describe_tools"
            )
            schema = tool.get("inputSchema")
            properties = schema.get("properties") if isinstance(schema, dict) else None
            selectors = [
                name
                for name, prop in (properties or {}).items()
                if isinstance(prop, dict)
                and prop.get("type") == "array"
                and isinstance(prop.get("items"), dict)
                and prop["items"].get("type") == "string"
            ]
            if not isinstance(properties, dict) or schema.get("type", "object") != "object" or len(selectors) != 1:
                raise OfficialMcpError("Epic MCP describe_tools has an unsupported input schema")
            return client.call_tool("describe_tools", {selectors[0]: names_to_describe})
        if operation == "call_tool":
            if not tool_name:
                raise OfficialMcpError("tool_name is required for call_tool")
            if "call_tool" in names:
                return client.call_tool(
                    "call_tool",
                    {"toolset_name": toolset_name, "tool_name": tool_name, "arguments": dict(arguments or {})},
                )
            direct_name = "{}.{}".format(toolset_name, tool_name) if toolset_name else tool_name
            return client.call_tool(direct_name, arguments)
        raise OfficialMcpError(
            "Unsupported operation {!r}; use status, list_tools, list_toolsets, describe_toolset, or call_tool".format(
                operation
            )
        )
