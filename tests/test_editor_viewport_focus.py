"""Regression tests for the semantic Level Editor viewport focus tool."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "src" / "dcc_mcp_unreal" / "skills" / "unreal-level"
SCRIPT = SKILL / "scripts" / "focus_level_editor_viewport.py"
TOOLS = SKILL / "tools.yaml"
HEADER = ROOT / "unreal" / "plugin" / "Source" / "DccMcpUnreal" / "Public" / "DccMcpAutomationLibrary.h"
IMPLEMENTATION = ROOT / "unreal" / "plugin" / "Source" / "DccMcpUnreal" / "Private" / "DccMcpAutomationLibrary.cpp"
AUTOMATION = ROOT / "unreal" / "plugin" / "Source" / "DccMcpUnreal" / "Private" / "DccMcpUnrealAutomationTests.cpp"


def _load_script():
    spec = importlib.util.spec_from_file_location("test_focus_level_editor_viewport", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tool_routes_to_native_bridge_and_returns_verified_postconditions() -> None:
    native_result = {
        "success": True,
        "closed_items": ["OutputLog", "MessageLog"],
        "close_requested_items": ["OutputLog", "MessageLog"],
        "remaining_log_tabs": [],
        "level_editor_activated": True,
        "viewport_focused": True,
        "postcondition_met": True,
    }
    bridge = types.SimpleNamespace(focus_level_editor_viewport=MagicMock(return_value=json.dumps(native_result)))
    unreal = types.ModuleType("unreal")
    unreal.DccMcpAutomationLibrary = bridge

    with patch.dict(sys.modules, {"unreal": unreal}):
        result = _load_script().focus_level_editor_viewport()

    assert result["success"] is True
    assert result["context"]["closed_items"] == ["OutputLog", "MessageLog"]
    assert result["context"]["remaining_log_tabs"] == []
    assert result["context"]["level_editor_activated"] is True
    assert result["context"]["viewport_focused"] is True
    assert result["context"]["postcondition_met"] is True
    bridge.focus_level_editor_viewport.assert_called_once_with()


def test_tool_fails_closed_when_native_postconditions_are_incomplete() -> None:
    native_result = {
        "success": True,
        "closed_items": ["OutputLog"],
        "close_requested_items": ["OutputLog", "MessageLog"],
        "remaining_log_tabs": ["MessageLog"],
        "level_editor_activated": True,
        "viewport_focused": True,
        "postcondition_met": False,
    }
    bridge = types.SimpleNamespace(focus_level_editor_viewport=MagicMock(return_value=json.dumps(native_result)))
    unreal = types.ModuleType("unreal")
    unreal.DccMcpAutomationLibrary = bridge

    with patch.dict(sys.modules, {"unreal": unreal}):
        result = _load_script().focus_level_editor_viewport()

    assert result["success"] is False
    assert result["context"]["native_result"] == native_result


def test_tool_rejects_nonboolean_native_success() -> None:
    native_result = {
        "success": "true",
        "closed_items": [],
        "close_requested_items": [],
        "remaining_log_tabs": [],
        "level_editor_activated": True,
        "viewport_focused": True,
        "postcondition_met": True,
    }
    bridge = types.SimpleNamespace(focus_level_editor_viewport=MagicMock(return_value=json.dumps(native_result)))
    unreal = types.ModuleType("unreal")
    unreal.DccMcpAutomationLibrary = bridge

    with patch.dict(sys.modules, {"unreal": unreal}):
        result = _load_script().focus_level_editor_viewport()

    assert result["success"] is False
    assert result["context"]["native_result"] == native_result


def test_tool_contract_is_main_affinity_and_has_no_input_surface() -> None:
    catalog = yaml.safe_load(TOOLS.read_text(encoding="utf-8"))
    tool = next(item for item in catalog["tools"] if item["name"] == "focus_level_editor_viewport")

    assert tool["source_file"] == "scripts/focus_level_editor_viewport.py"
    assert tool["execution"] == "sync"
    assert tool["affinity"] == "main"
    assert tool["enforce_thread_affinity"] is True
    assert tool["read_only"] is False
    assert tool["destructive"] is False
    assert tool["idempotent"] is True
    assert tool["input_schema"] == {"type": "object", "properties": {}}


def test_native_bridge_uses_slate_level_editor_apis_and_has_an_automation_test() -> None:
    header = HEADER.read_text(encoding="utf-8")
    implementation = IMPLEMENTATION.read_text(encoding="utf-8")
    automation = AUTOMATION.read_text(encoding="utf-8")

    assert "static FString FocusLevelEditorViewport();" in header
    assert "FString UDccMcpAutomationLibrary::FocusLevelEditorViewport()" in implementation
    assert "IsInGameThread()" in implementation
    assert 'TEXT("OutputLog")' in implementation
    assert 'TEXT("MessageLog")' in implementation
    assert "FGlobalTabmanager::Get()" in implementation
    assert "FindExistingLiveTab" in implementation
    assert "RequestCloseTab()" in implementation
    assert "LoadModulePtr<FLevelEditorModule>" in implementation
    assert "GetFirstLevelEditor()" in implementation
    assert "GetActiveViewportInterface()" in implementation
    assert "ActivateInParent(ETabActivationCause::SetDirectly)" in implementation
    assert "FindWidgetWindow" in implementation
    assert "BringToFront(true)" in implementation
    assert "SetAllUserFocus" in implementation
    assert "SetKeyboardFocus" in implementation
    assert "HasKeyboardFocus()" in implementation
    assert "HasFocusedDescendants()" in implementation
    assert "postcondition_met" in implementation
    assert "SendInput" not in implementation
    assert "FDccMcpEditorViewportFocusTest" in automation
    assert "DccMcp.Smoke.EditorViewportFocus" in automation
