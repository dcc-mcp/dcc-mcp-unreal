"""Tests for the fail-closed security policy.

Validates that:
- Denied prefixes (_-prefixed, K2Node_*, etc.) are rejected.
- Denied class patterns are rejected.
- Denied property names are rejected.
- Denied function patterns are rejected.
- Default policy denies writes and execute.
- Full policy allows writes and execute.
- Empty property/function names are rejected.
- Callable values are rejected.
- Large string values are rejected.
"""

from __future__ import annotations

import pytest

from dcc_mcp_unreal.security import (
    OperationKind,
    ReflectionPolicy,
    SecurityDeniedError,
    default_full_policy,
    default_read_policy,
)


class TestDefaultReadPolicy:
    """The default read policy allows reads but denies writes and executes."""

    def test_allows_read(self, read_policy):
        """Reading a non-denied property should pass."""
        # Should not raise
        read_policy.check_property_read("RelativeLocation", "/Script/Engine.StaticMeshActor")

    def test_denies_write(self, read_policy):
        """Writing should be denied because allow_write=False."""
        with pytest.raises(SecurityDeniedError, match="Property writes are not permitted"):
            read_policy.check_property_write("RelativeLocation", "/Script/Engine.StaticMeshActor", 100.0)

    def test_denies_execute(self, read_policy):
        """Executing should be denied because allow_execute=False."""
        with pytest.raises(SecurityDeniedError, match="UFunction calls are not permitted"):
            read_policy.check_function_call("DoSomething", "/Script/Engine.StaticMeshActor")


class TestFullPolicy:
    """The full policy allows reads, writes, and executes."""

    def test_allows_write(self, full_policy):
        """Writing a non-denied property should pass."""
        # Should not raise
        full_policy.check_property_write("RelativeLocation", "/Script/Engine.StaticMeshActor", 100.0)

    def test_allows_execute(self, full_policy):
        """Calling a non-denied function should pass."""
        full_policy.check_function_call("DoSomething", "/Script/Engine.StaticMeshActor")


class TestDeniedPrefixes:
    """Properties and functions with denied prefixes should always be rejected."""

    @pytest.mark.parametrize("name", [
        "_internal",
        "_private_field",
        "bOverride_SomeSetting",
        "K2Node_SomeNode",
        "ExecuteUbergraph_SomeGraph",
    ])
    def test_property_read_denied(self, full_policy, name):
        """Private prefixed properties should be denied even with full policy."""
        with pytest.raises(SecurityDeniedError):
            full_policy.check_property_read(name, "/Script/Engine.Actor")

    @pytest.mark.parametrize("name", [
        "Server_SomeRPC",
        "Client_SomeRPC",
        "OnRep_SomeRep",
        "BeginPlay",
        "ReceiveBeginPlay",
        "EndPlay",
        "ReceiveEndPlay",
        "Tick",
        "ReceiveTick",
        "K2_DestroyActor",
        "K2_DestroyComponent",
        "BndEvt__SomeEvent",
        "_private_function",
    ])
    def test_function_call_denied(self, full_policy, name):
        """Denied function patterns should be rejected even with full policy."""
        with pytest.raises(SecurityDeniedError):
            full_policy.check_function_call(name, "/Script/Engine.Actor")


class TestDeniedClasses:
    """Classes matching denied patterns should be rejected."""

    @pytest.mark.parametrize("class_path", [
        "/Script/Engine.Default__SomeClass",
        "/Script/CoreUObject.Package",
        "/Script/CoreUObject.Class",
        "/Script/Engine.PlayerController",
        "/Script/Engine.GameModeBase",
        "/Script/Engine.GameStateBase",
        "/Script/Engine.WorldSettings",
    ])
    def test_denied_classes_blocked(self, full_policy, class_path):
        """Denied class patterns should be rejected."""
        with pytest.raises(SecurityDeniedError):
            full_policy.check_class(class_path)


class TestDeniedPropertyNames:
    """Explicitly denied property names should always be rejected."""

    @pytest.mark.parametrize("name", ["bIsEditorOnly", "InternalIndex", "NativeIndex"])
    def test_denied_property_names(self, full_policy, name):
        """Denied property names should be rejected."""
        with pytest.raises(SecurityDeniedError):
            full_policy.check_property_read(name, "/Script/Engine.Actor")


class TestEdgeCases:
    """Edge case behavior."""

    def test_empty_property_name(self, full_policy):
        """Empty property names should be rejected."""
        with pytest.raises(SecurityDeniedError):
            full_policy.check_property_read("", "/Script/Engine.Actor")

    def test_callable_value_rejected(self, full_policy):
        """Callable values should be rejected in writes."""
        with pytest.raises(SecurityDeniedError, match="callable"):
            full_policy.check_property_write("SomeProperty", "/Script/Engine.Actor", lambda: None)

    def test_callable_arg_rejected(self, full_policy):
        """Callable function arguments should be rejected."""
        with pytest.raises(SecurityDeniedError, match="callable"):
            full_policy.check_function_call("SomeFunc", "/Script/Engine.Actor", {"callback": lambda: None})

    def test_large_string_value_rejected(self, full_policy):
        """Strings over 1MB should be rejected."""
        with pytest.raises(SecurityDeniedError, match="1MB"):
            full_policy.check_property_write("SomeProperty", "/Script/Engine.Actor", "x" * 2_000_000)

    def test_large_bytes_value_rejected(self, full_policy):
        """Bytes over 1MB should be rejected."""
        with pytest.raises(SecurityDeniedError, match="1MB"):
            full_policy.check_property_write("SomeProperty", "/Script/Engine.Actor", b"x" * 2_000_000)

    def test_empty_allowed_lists_allow_all_non_denied(self):
        """When allowlists are empty, only denied patterns are blocked."""
        policy = ReflectionPolicy(allow_write=True, allow_execute=True)
        # This should pass because the class is not in denied patterns
        policy.check_property_read("MyProp", "/Script/MyGame.MyActor")
        policy.check_function_call("MyFunc", "/Script/MyGame.MyActor")

    def test_allowed_classes_restricts(self):
        """When allowed_classes is set, only matching classes pass."""
        policy = ReflectionPolicy(
            allow_write=True,
            allow_execute=True,
            allowed_classes=["*/MyGame.*"],
        )
        # Allowed pattern matches
        policy.check_class("/Script/MyGame.MyActor")
        # Non-matching class should be denied
        with pytest.raises(SecurityDeniedError, match="allowlist"):
            policy.check_class("/Script/OtherGame.OtherActor")


class TestOperationKind:
    """OperationKind enum tests."""

    def test_level_values(self):
        assert OperationKind.READ.level > 0
        assert OperationKind.WRITE.level > 0
        assert OperationKind.EXECUTE.level > 0

    def test_string_values(self):
        assert OperationKind.READ.value == "read"
        assert OperationKind.WRITE.value == "write"
        assert OperationKind.EXECUTE.value == "execute"


class TestSecurityDeniedError:
    """SecurityDeniedError formatting."""

    def test_full_message(self):
        exc = SecurityDeniedError(
            "Test denial",
            operation=OperationKind.WRITE,
            path="/Script/Engine.Actor::_private",
        )
        msg = str(exc)
        assert "[SECURITY DENIED]" in msg
        assert "Test denial" in msg
        assert "write" in msg
        assert "_private" in msg

    def test_minimal_message(self):
        exc = SecurityDeniedError("Simple denial")
        msg = str(exc)
        assert "[SECURITY DENIED]" in msg
        assert "Simple denial" in msg
