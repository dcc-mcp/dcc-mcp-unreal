"""Regression checks for native bridge ownership and thread-affinity invariants."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_SOURCE = REPO_ROOT / "plugin/Source/DccMcpUnreal/Private/DccMcpBridge.cpp"
BRIDGE_HEADER = REPO_ROOT / "plugin/Source/DccMcpUnreal/Public/DccMcpBridge.h"
BUILD_RULES = REPO_ROOT / "plugin/Source/DccMcpUnreal/DccMcpUnreal.Build.cs"
SECURITY_SOURCE = REPO_ROOT / "plugin/Source/DccMcpUnreal/Private/DccMcpSecurity.cpp"


def test_bridge_uses_requested_port_and_owns_its_route() -> None:
    source = BRIDGE_SOURCE.read_text(encoding="utf-8")
    header = BRIDGE_HEADER.read_text(encoding="utf-8")

    assert "GetHttpRouter(static_cast<uint32>(Port), true)" in source
    assert "GetHttpRouter(BoundPort" not in source
    assert "RouteHandle = HttpRouter->BindRoute" in source
    assert "HttpRouter->UnbindRoute(RouteHandle)" in source
    assert "FHttpRouteHandle RouteHandle" in header
    assert "StopAllListeners" not in source


def test_uobject_dispatch_is_async_and_capture_safe() -> None:
    source = BRIDGE_SOURCE.read_text(encoding="utf-8")

    assert "AsyncTask(" in source
    assert "ENamedThreads::GameThread" in source
    assert "DispatchOnGameThread" in source
    assert "SyncResult" not in source
    assert "[&]" not in source


def test_http_server_version_guard_accepts_future_major_versions() -> None:
    source = BRIDGE_SOURCE.read_text(encoding="utf-8")
    build_rules = BUILD_RULES.read_text(encoding="utf-8")

    assert "(ENGINE_MAJOR_VERSION > 5)" in source
    assert "Target.Version.MajorVersion > 5" in build_rules


def test_native_security_patterns_cover_real_unreal_paths() -> None:
    source = SECURITY_SOURCE.read_text(encoding="utf-8")

    assert 'TEXT("*/Script/Engine.WorldSettings*")' in source
    assert "Pattern.RightChop(2)" in source
