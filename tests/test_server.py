"""Basic tests for UnrealMcpServer (without real Unreal Engine)."""

from __future__ import annotations

import pytest


def test_import():
    """Package imports without errors."""
    import dcc_mcp_unreal  # noqa: F401

    assert dcc_mcp_unreal.__version__ == "0.1.0"


def test_api_imports():
    """All public API symbols are importable."""
    from dcc_mcp_unreal import (
        UnrealMcpServer,
        is_unreal_available,
        start_server,
        stop_server,
        unreal_error,
        unreal_success,
        with_unreal,
    )

    assert callable(UnrealMcpServer)
    assert callable(start_server)
    assert callable(stop_server)
    assert callable(unreal_success)
    assert callable(unreal_error)
    assert callable(with_unreal)
    assert callable(is_unreal_available)


def test_is_unreal_available_false_outside_unreal():
    """is_unreal_available() returns False outside Unreal Engine."""
    from dcc_mcp_unreal import is_unreal_available

    # Outside Unreal Engine, unreal module is not available
    assert is_unreal_available() is False


def test_unreal_success_returns_dict():
    """unreal_success() returns a dict with expected keys."""
    from dcc_mcp_unreal import unreal_success

    result = unreal_success("test done", count=3)
    assert isinstance(result, dict)
    assert result.get("success") is True
    assert result.get("message") == "test done"


def test_unreal_error_returns_dict():
    """unreal_error() returns a failure dict."""
    from dcc_mcp_unreal import unreal_error

    result = unreal_error("failed", error="ImportError: unreal")
    assert isinstance(result, dict)
    assert result.get("success") is False
    assert result.get("error") == "ImportError: unreal"


def test_with_unreal_catches_import_error():
    """@with_unreal decorator catches ImportError and returns error dict."""
    from dcc_mcp_unreal import unreal_success, with_unreal

    @with_unreal
    def needs_unreal(**kwargs):
        import no_such_module_unreal  # noqa: F401

        return unreal_success("never")

    result = needs_unreal()
    assert result.get("success") is False
    assert "not available" in result.get("message", "").lower()


def test_server_instantiation():
    """UnrealMcpServer can be instantiated with custom port."""
    from dcc_mcp_unreal import UnrealMcpServer

    server = UnrealMcpServer(port=9999)
    assert server._port == 9999


def test_server_with_extra_paths():
    """UnrealMcpServer accepts extra_skill_paths."""
    from dcc_mcp_unreal import UnrealMcpServer

    server = UnrealMcpServer(port=8765, extra_skill_paths=["/custom/skills"])
    assert "/custom/skills" in server._extra_skill_paths


def test_unreal_success_with_prompt():
    """unreal_success() preserves prompt field."""
    from dcc_mcp_unreal import unreal_success

    result = unreal_success("done", prompt="Check the viewport")
    assert result.get("prompt") == "Check the viewport"


def test_unreal_error_with_possible_solutions():
    """unreal_error() stores possible_solutions in context or accessible field."""
    from dcc_mcp_unreal import unreal_error

    result = unreal_error(
        "Plugin not found",
        error="PluginError: Python plugin disabled",
        possible_solutions=["Enable Python Editor Script Plugin"],
    )
    assert result.get("success") is False
    # possible_solutions is stored in context
    ctx = result.get("context", {})
    assert "possible_solutions" in ctx
    assert "Enable Python Editor Script Plugin" in ctx["possible_solutions"]


def test_unreal_from_exception():
    """unreal_from_exception() builds error dict from an exception."""
    from dcc_mcp_unreal import unreal_from_exception

    try:
        raise RuntimeError("test error")
    except RuntimeError as exc:
        result = unreal_from_exception(exc, message="Skill failed")

    assert result.get("success") is False
    assert result.get("message") == "Skill failed"
