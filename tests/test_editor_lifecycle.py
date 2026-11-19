from __future__ import annotations

import json
import runpy
import sys
import types
from pathlib import Path
from unittest.mock import Mock

import pytest

import dcc_mcp_unreal

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src/dcc_mcp_unreal/skills/unreal-lifecycle/scripts"
SCRIPT = SCRIPTS / "_editor_close.py"
NATIVE = ROOT / "unreal/plugin/Source/DccMcpUnreal/Private/DccMcpEditorLifecycleLibrary.cpp"
INSTANCE = "11111111-1111-4111-8111-111111111111"


def _guard() -> dict:
    return {
        "instance_id": INSTANCE,
        "owner": "robot-test",
        "session": "b2",
        "host_pid": 4242,
        "creation_filetime": "134360052743565450",
        "project_file": "F:/owned/Test.uproject",
        "request_id": "22222222-2222-4222-8222-222222222222",
        "expires_unix_ms": "1791532801000",
        "proof": "a" * 40,
    }


def _script(monkeypatch, result=None, running=True):
    native = (
        {
            "schema": "dcc-unreal-editor-close/v1",
            "state": "scheduled",
            "process_exit_verified": False,
            "response_flush_verified": False,
        }
        if result is None
        else result
    )
    bridge = types.SimpleNamespace(
        request_editor_close_json=Mock(return_value=json.dumps(native)),
        inspect_editor_close_json=Mock(return_value=json.dumps({**native, "state": "ready"})),
        get_editor_close_status_json=Mock(return_value=json.dumps(native)),
    )
    monkeypatch.setitem(sys.modules, "unreal", types.SimpleNamespace(DccMcpEditorLifecycleLibrary=bridge))
    server_module = types.SimpleNamespace(
        _server_instance=types.SimpleNamespace(is_running=running, instance_id=INSTANCE),
    )
    monkeypatch.setitem(sys.modules, "dcc_mcp_unreal.server", server_module)
    monkeypatch.setattr(dcc_mcp_unreal, "server", server_module, raising=False)
    return runpy.run_path(str(SCRIPT), run_name="editor_lifecycle_test"), bridge


def test_typed_request_narrows_actual_instance_and_never_claims_exit(monkeypatch):
    module, bridge = _script(monkeypatch)
    result = module["request_editor_close"](**_guard())
    assert result["success"] is True
    native = result["context"]["native_result"]
    assert native["instance_id"] == INSTANCE
    assert native["cleanup_state"] == "cleanup_unknown"
    assert native["process_exit_verified"] is False
    assert native["response_flush_verified"] is False
    guard = json.loads(bridge.request_editor_close_json.call_args.args[0])
    assert guard["host_pid"] == "4242"
    assert "nonce" not in guard
    assert _guard()["proof"] not in json.dumps(result)


def test_wrong_instance_cannot_reach_native(monkeypatch):
    module, bridge = _script(monkeypatch)
    guard = {**_guard(), "instance_id": "33333333-3333-4333-8333-333333333333"}
    assert module["request_editor_close"](**guard)["success"] is False
    bridge.request_editor_close_json.assert_not_called()


@pytest.mark.parametrize(
    "key,value",
    [
        ("host_pid", True),
        ("host_pid", 0),
        ("host_pid", "4242"),
        ("owner", "owner\nwrong"),
        ("owner", ""),
        ("session", "../other"),
        ("creation_filetime", 134360052743565450),
        ("creation_filetime", "1e10"),
        ("expires_unix_ms", "1791532801000\n"),
        ("proof", "A" * 40),
        ("request_id", "bad"),
        ("instance_id", "bad"),
        ("project_file", "F:/test\0.uproject"),
    ],
)
def test_invalid_guards_are_refused_before_native(monkeypatch, key, value):
    module, bridge = _script(monkeypatch)
    assert module["request_editor_close"](**{**_guard(), key: value})["success"] is False
    bridge.request_editor_close_json.assert_not_called()


@pytest.mark.parametrize(
    "mutation",
    [
        {"process_exit_verified": True},
        {"response_flush_verified": True},
        {"state": "completed"},
        {"schema": "another"},
    ],
)
def test_unexpected_native_claims_are_not_promoted(monkeypatch, mutation):
    native = {
        "schema": "dcc-unreal-editor-close/v1",
        "state": "scheduled",
        "process_exit_verified": False,
        "response_flush_verified": False,
        **mutation,
    }
    module, _ = _script(monkeypatch, native)
    assert module["request_editor_close"](**_guard())["success"] is False


def test_native_exception_does_not_echo_credentials(monkeypatch):
    module, bridge = _script(monkeypatch)
    bridge.request_editor_close_json.side_effect = RuntimeError("secret nonce and proof " + _guard()["proof"])
    result = module["request_editor_close"](**_guard())
    assert result["success"] is False
    assert "secret nonce" not in json.dumps(result)
    assert _guard()["proof"] not in json.dumps(result)


def test_stopped_server_does_not_reach_native(monkeypatch):
    module, bridge = _script(monkeypatch, running=False)
    assert module["request_editor_close"](**_guard())["success"] is False
    bridge.request_editor_close_json.assert_not_called()


def test_inspection_and_status_have_no_request_side_effect(monkeypatch):
    module, bridge = _script(monkeypatch)
    assert module["_native"]("inspect_editor_close_json")["success"] is True
    assert module["_native"]("get_editor_close_status_json")["success"] is True
    bridge.request_editor_close_json.assert_not_called()


def test_manifest_routes_have_one_entry_each_and_execute_the_named_action(monkeypatch):
    from dcc_mcp_unreal.skill_runner import run_skill_script

    _, bridge = _script(monkeypatch)
    monkeypatch.syspath_prepend(str(SCRIPTS))
    monkeypatch.delitem(sys.modules, "_editor_close", raising=False)
    for action, params in (
        ("inspect_editor_close", {}),
        ("get_editor_close_status", {}),
        ("request_editor_close", _guard()),
    ):
        result = run_skill_script(str(SCRIPTS / (action + ".py")), params)
        assert result["success"] is True
        getattr(bridge, action + "_json").assert_called_once()


def test_native_contract_uses_normal_close_and_rechecks_before_mutation():
    source = NATIVE.read_text(encoding="utf-8")
    assert "RequestEngineExit" not in source and "QuitEditor" not in source and "TerminateProc" not in source
    assert source.count("UnsafeReason();") >= 3
    assert "GIsSavingPackage || IsLoading() || IsGarbageCollecting() || GIsSlowTask" in source
    assert "GetDirtyWorldPackages(Dirty)" in source and "GetDirtyContentPackages(Dirty)" in source
    assert "IsPlaySessionInProgress()" in source and "bIsPlayWorldQueued" in source
    assert "GetActiveModalWindow().IsValid()" in source and "FApp::IsUnattended()" in source
    assert "GetProcessTimes(::GetCurrentProcess()" in source and "OwnedCloseBinding.Project != ProjectFile()" in source
    assert "Remaining > 2000" in source and "OwnedCloseBinding.ExpiresMonotonic" in source
    assert "RequestId == OwnedCloseBinding.RequestId" in source and "request_already_consumed" in source
    assert "FSHA1::HMACBuffer" in source and "Difference |= Expected[Index] ^ Proof[Index]" in source
    assert "->RequestCloseEditor();" in source
    assert 'SetBoolField(TEXT("response_flush_verified"), false)' in source
    assert 'SetBoolField(TEXT("process_exit_verified"), false)' in source
