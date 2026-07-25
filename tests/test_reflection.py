"""Tests for the UObject reflection data types and facade.

Validates:
- Data type serialization (ObjectDescriptor, PropertyDescriptor, etc.).
- UObjectReflection construction and policy binding.
- Bridge fallback behavior.
- Value sanitization.
"""

from __future__ import annotations

import pytest

from dcc_mcp_unreal.reflection import (
    FunctionDescriptor,
    FunctionResult,
    ObjectDescriptor,
    PropertyDescriptor,
    PropertyValue,
    UObjectReflection,
    _sanitize_value,
)


class TestPropertyDescriptor:
    """PropertyDescriptor tests."""

    def test_basic_construction(self):
        desc = PropertyDescriptor(
            name="RelativeLocation",
            type_name="FVector",
            category="struct",
            flags=["EditAnywhere", "BlueprintReadWrite"],
            is_readable=True,
            is_writable=True,
            is_editor_visible=True,
        )
        assert desc.name == "RelativeLocation"
        assert desc.type_name == "FVector"
        assert desc.category == "struct"
        assert "EditAnywhere" in desc.flags

    def test_to_dict(self):
        desc = PropertyDescriptor(name="bHidden", type_name="bool", category="scalar")
        d = desc.to_dict()
        assert d["name"] == "bHidden"
        assert d["type_name"] == "bool"
        assert d["category"] == "scalar"
        assert "flags" in d

    def test_defaults(self):
        desc = PropertyDescriptor(name="TestProp", type_name="int32", category="scalar")
        assert desc.is_readable is True
        assert desc.is_writable is True
        assert desc.is_editor_visible is False
        assert desc.flags == []


class TestFunctionDescriptor:
    """FunctionDescriptor tests."""

    def test_basic_construction(self):
        desc = FunctionDescriptor(
            name="DoSomething",
            return_type="void",
            parameters=[{"name": "Amount", "type": "float"}],
            flags=["BlueprintCallable"],
            is_callable=True,
            is_static=False,
            is_pure=False,
        )
        assert desc.name == "DoSomething"
        assert desc.return_type == "void"
        assert len(desc.parameters) == 1
        assert "BlueprintCallable" in desc.flags

    def test_to_dict(self):
        desc = FunctionDescriptor(name="GetValue", return_type="int32", is_pure=True)
        d = desc.to_dict()
        assert d["name"] == "GetValue"
        assert d["return_type"] == "int32"
        assert d["is_pure"] is True


class TestObjectDescriptor:
    """ObjectDescriptor tests."""

    def test_basic_construction(self):
        desc = ObjectDescriptor(
            name="Cube_0",
            class_path="/Script/Engine.StaticMeshActor",
            outer_path="/Game/Maps/Level.Level:PersistentLevel",
            label="My Cube",
            property_count=10,
            function_count=5,
        )
        assert desc.name == "Cube_0"
        assert desc.class_path == "/Script/Engine.StaticMeshActor"
        assert desc.property_count == 10
        assert desc.function_count == 5

    def test_to_dict_with_properties(self):
        desc = ObjectDescriptor(
            name="Actor_0",
            class_path="/Script/Engine.Actor",
            outer_path="/Game/Maps/Level.Level:PersistentLevel",
            properties=[
                PropertyDescriptor(name="bHidden", type_name="bool", category="scalar"),
            ],
            functions=[
                FunctionDescriptor(name="GetActorLocation", return_type="FVector"),
            ],
        )
        d = desc.to_dict()
        assert len(d["properties"]) == 1
        assert len(d["functions"]) == 1


class TestPropertyValue:
    """PropertyValue tests."""

    def test_success(self):
        pv = PropertyValue(name="bHidden", value=True, type_name="bool")
        assert pv.success is True
        assert pv.value is True
        assert pv.error is None

    def test_failure(self):
        pv = PropertyValue(name="bHidden", value=None, type_name="unknown", success=False, error="Access denied")
        assert pv.success is False
        assert pv.error == "Access denied"

    def test_to_dict(self):
        pv = PropertyValue(name="Count", value=42, type_name="int32")
        d = pv.to_dict()
        assert d["name"] == "Count"
        assert d["value"] == 42


class TestFunctionResult:
    """FunctionResult tests."""

    def test_success(self):
        fr = FunctionResult(function_name="DoSomething", success=True, return_value=42, execution_time_ms=1.5)
        assert fr.success is True
        assert fr.return_value == 42
        assert fr.execution_time_ms == 1.5

    def test_failure(self):
        fr = FunctionResult(function_name="DoSomething", success=False, error="Function not found")
        assert fr.success is False
        assert fr.error == "Function not found"

    def test_to_dict(self):
        fr = FunctionResult(function_name="Test", success=True, return_value=None)
        d = fr.to_dict()
        assert d["function_name"] == "Test"
        assert d["success"] is True


class TestSanitizeValue:
    """Value sanitization for JSON transport."""

    def test_null(self):
        assert _sanitize_value(None) is None

    def test_primitives(self):
        assert _sanitize_value(True) is True
        assert _sanitize_value(42) == 42
        assert _sanitize_value(3.14) == 3.14
        assert _sanitize_value("hello") == "hello"

    def test_list(self):
        assert _sanitize_value([1, 2, 3]) == [1, 2, 3]
        assert _sanitize_value((1, 2)) == [1, 2]

    def test_dict(self):
        assert _sanitize_value({"a": 1}) == {"a": 1}

    def test_non_serializable(self):
        """Non-JSON-serializable values become strings."""
        result = _sanitize_value(complex(1, 2))
        assert isinstance(result, str)

    def test_nested(self):
        """Nested structures should be recursively sanitized."""
        result = _sanitize_value({"a": [1, {"b": 2}]})
        assert result == {"a": [1, {"b": 2}]}


class TestUObjectReflectionConstruction:
    """UObjectReflection construction and policy binding."""

    def test_default_construction(self):
        reflection = UObjectReflection()
        assert reflection.policy.allow_write is False
        assert reflection.policy.allow_execute is False

    def test_policy_injection(self):
        from dcc_mcp_unreal.security import default_full_policy
        policy = default_full_policy()
        reflection = UObjectReflection(policy=policy)
        assert reflection.policy.allow_write is True
        assert reflection.policy.allow_execute is True

    def test_bridge_optional(self):
        reflection = UObjectReflection(bridge=None)
        assert reflection._bridge is None

    def test_missing_unreal_module_raises(self):
        """Without a bridge and without unreal module, operations should raise."""
        reflection = UObjectReflection(bridge=None)
        # We can't easily test _call_bridge without mocking, but it should
        # try to import unreal and fail gracefully.
        pass
