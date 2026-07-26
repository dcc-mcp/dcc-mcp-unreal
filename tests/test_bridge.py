"""Tests for the native Unreal bridge HTTP client contract."""

from __future__ import annotations

import io
import json
import sys
import types
import urllib.error
from unittest.mock import patch

import pytest

from dcc_mcp_unreal.bridge import DccMcpBridge


class _Response:
    def __init__(self, payload: object) -> None:
        self._body = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body.read()


def test_origin_url_uses_native_bridge_endpoint() -> None:
    bridge = DccMcpBridge("http://127.0.0.1:19876")

    assert bridge._bridge_url == "http://127.0.0.1:19876/bridge"


def test_explicit_endpoint_is_preserved() -> None:
    bridge = DccMcpBridge("http://127.0.0.1:19876/custom")

    assert bridge._bridge_url == "http://127.0.0.1:19876/custom"


def test_origin_query_is_preserved_when_endpoint_is_added() -> None:
    bridge = DccMcpBridge("http://127.0.0.1:19876?trace=1")

    assert bridge._bridge_url == "http://127.0.0.1:19876/bridge?trace=1"


def test_namespace_package_is_not_treated_as_unreal_editor_api() -> None:
    bridge = DccMcpBridge()

    with patch.dict(sys.modules, {"unreal": types.ModuleType("unreal")}):
        assert bridge.use_direct is False


@pytest.mark.parametrize(
    ("method", "wire_payload", "expected"),
    [
        ("discover_objects", {"objects": [{"name": "Cube"}]}, [{"name": "Cube"}]),
        ("get_properties", {"properties": [{"name": "Hidden"}]}, [{"name": "Hidden"}]),
        ("set_properties", {"properties": [{"success": True}]}, [{"success": True}]),
        ("get_property", {"success": True, "value": 4}, {"success": True, "value": 4}),
    ],
)
def test_http_response_matches_direct_transport_shape(
    method: str,
    wire_payload: object,
    expected: object,
) -> None:
    bridge = DccMcpBridge()
    bridge._use_direct = False

    with patch("urllib.request.urlopen", return_value=_Response(wire_payload)):
        assert bridge.call(method) == expected


def test_http_error_names_the_failed_method() -> None:
    bridge = DccMcpBridge()
    bridge._use_direct = False
    failure = urllib.error.URLError("connection refused")

    with (
        patch("urllib.request.urlopen", side_effect=failure),
        pytest.raises(RuntimeError, match="discover_objects"),
    ):
        bridge.call("discover_objects")


def test_collection_error_is_not_converted_to_empty_success() -> None:
    bridge = DccMcpBridge()
    bridge._use_direct = False

    with (
        patch(
            "urllib.request.urlopen",
            return_value=_Response({"success": False, "error": "invalid property_names"}),
        ),
        pytest.raises(RuntimeError, match="invalid property_names"),
    ):
        bridge.call("get_properties")
