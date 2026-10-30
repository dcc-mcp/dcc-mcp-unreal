"""Optional real-UE commandlet probe for the AI Blackboard vertical slice.

This is an acceptance sketch, NOT part of the headless pytest suite. Run it
inside a real Unreal Editor (for example via ``-run=pythonscript``) on a scratch
project before claiming native/host qualification. It loads the exact skill
core by file path, drives it against the live ``unreal`` module, and fails
closed: it asserts the preflight, authors one typed key, and verifies the
readback. It never ships as a pytest test because a live Editor is required.

The probe deliberately uses a scratch /Game/DccMcpAiProbe path. It must not run
against a user's production content. If the host does not expose the
``BlackboardEntry`` struct, the preflight fails closed with an
``update_adapter_plugin`` action rather than mutating the editor; the C++
``DccMcpAutomationLibrary`` typed bridge is the qualified route on such hosts.
"""

from __future__ import annotations

import importlib.util
import json
import os


def _load_core():
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    path = os.path.join(root, "src", "dcc_mcp_unreal", "skills", "unreal-ai", "scripts", "_ai_blackboard.py")
    spec = importlib.util.spec_from_file_location("_ai_blackboard_probe_core", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def run_probe():
    import unreal  # noqa: PLC0415

    core = _load_core()
    result = {"preflight": core.preflight(unreal)}
    result["preflight_ready"] = result["preflight"]["ready"]
    if not result["preflight_ready"]:
        result["status"] = "blocked_preflight"
        return result

    path = "/Game/DccMcpAiProbe/BB_Probe"
    key_name = "ProbeDistance"
    # The probe authors a "float" key, so its type must read back as this class.
    expected_type = core._KEY_TYPES.get("float", "BlackboardKeyType_Float")
    try:
        # Keep the first inspection inside the guard: an occupied or
        # unloadable target must fail closed with JSON, never a traceback.
        result["inspect_before"] = core.inspect_blackboard(unreal, path)
        # Idempotent: this probe targets a dedicated scratch path, so a key left
        # by an earlier run is reused rather than re-authored. FName equality is
        # case-insensitive, so match names case-insensitively (H3 follow-up).
        matching = [
            k for k in result["inspect_before"].get("keys", []) if str(k.get("name", "")).lower() == key_name.lower()
        ]
        if matching:
            observed_type = matching[0].get("key_type") or ""
            # A name-only match is NOT enough: an asset authored with a
            # transient-outer key type (H2 defect) reads back with an empty type.
            # Reusing it must fail closed, never report status=ok.
            if not observed_type or expected_type not in observed_type:
                result["author"] = {"reused_existing_key": False, "readback_verified": False}
                result["inspect_after"] = result["inspect_before"]
                result["readback_verified"] = False
                result["status"] = "rejected"
                result["reason"] = "reused_key_type_mismatch"
                result["context"] = {"observed_key_type": observed_type, "expected_key_type": expected_type}
                return result
            result["author"] = {"reused_existing_key": True, "readback_verified": True}
        else:
            result["author"] = core.author_blackboard_key(
                unreal, path, key_name, key_type="float", create_if_missing=True
            )
        result["inspect_after"] = core.inspect_blackboard(unreal, path)
        observed = [
            k for k in result["inspect_after"].get("keys", []) if str(k.get("name", "")).lower() == key_name.lower()
        ]
        type_ok = bool(observed) and all(expected_type in (k.get("key_type") or "") for k in observed)
        result["readback_verified"] = result["author"].get("readback_verified") is True and type_ok
        result["status"] = "ok" if result["readback_verified"] else "readback_failed"
    except core.AiBlackboardError as exc:
        result["status"] = "rejected"
        result["reason"] = exc.reason
        result["context"] = exc.context
    except Exception as exc:  # noqa: BLE001 - report, never raise into the Editor
        result["status"] = "error"
        result["error"] = "{}: {}".format(type(exc).__name__, exc)
    return result


if __name__ == "__main__":
    print(json.dumps(run_probe(), indent=2))
