"""Current-project plugin plans and independently consented descriptor writes."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from dcc_mcp_unreal.plugin_preflight import CAPABILITY_PLUGIN_REQUIREMENTS, _enabled_plugin_names


def _digest(data):
    return hashlib.sha256(data).hexdigest()


@contextmanager
def _descriptor_lock(path):
    stream = path.open("x")
    try:
        yield
    finally:
        stream.close()
        path.unlink()


def plugin_configuration_plan(unreal, capability):
    """Distinguish descriptor inheritance, installation and runtime enablement."""
    required = CAPABILITY_PLUGIN_REQUIREMENTS[capability]
    path = Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.get_project_file_path())).resolve(strict=True)
    if path.suffix.lower() != ".uproject":
        raise ValueError("Active project must be a .uproject descriptor")
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8-sig"))
    entries = data.get("Plugins", [])
    if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
        raise ValueError("Malformed project Plugins list")
    names = [entry.get("Name") for entry in entries]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate project plugin entries")
    enabled = set(_enabled_plugin_names(unreal))
    rows = []
    for name in required:
        entry = next((item for item in entries if item.get("Name") == name), {})
        declared = entry.get("Enabled")
        if declared is not None and type(declared) is not bool:
            raise ValueError("Plugin Enabled must be a boolean")
        descriptor = unreal.PluginBlueprintLibrary.get_plugin_descriptor_file_path(name)
        row = {
            "name": name,
            "project_enabled": declared,
            "installed": bool(descriptor),
            "runtime_enabled": name in enabled,
            "modules_loaded": {"status": "unavailable", "reason": "Runtime enabled is not module load evidence"},
        }
        if descriptor:
            descriptor_path = Path(unreal.Paths.convert_relative_path_to_full(descriptor))
            descriptor_raw = descriptor_path.read_bytes()
            plugin = json.loads(descriptor_raw.decode("utf-8-sig"))
            row.update(
                descriptor_path=str(descriptor_path),
                descriptor_sha256=_digest(descriptor_raw),
                enabled_by_default=plugin.get("EnabledByDefault"),
            )
        else:
            row["enabled_by_default"] = None
        row["configuration_source"] = "project_override" if declared is not None else "inherited"
        rows.append(row)
    return {
        "schema_version": 1,
        "capability": capability,
        "project_path": str(path),
        "project_sha256": _digest(raw),
        "plugins": rows,
        "proposed_changes": [
            {"Name": row["name"], "Enabled": True} for row in rows if row["project_enabled"] is not True
        ],
        "restart_automatically": False,
        "runtime_ready": all(row["runtime_enabled"] for row in rows),
    }


def apply_plugin_configuration(unreal, capability, expected_sha256):
    """Bind independent core elicitation to a concrete plan, then recheck it."""
    from dcc_mcp_core.elicitation import elicit_form_sync  # noqa: PLC0415

    plan = plugin_configuration_plan(unreal, capability)
    if plan["project_sha256"] != expected_sha256:
        return {"status": "conflict", "plan": plan}
    if not all(row["installed"] for row in plan["plugins"]):
        return {"status": "plugin_not_installed", "plan": plan}
    if not plan["proposed_changes"]:
        return {"status": "unchanged", "plan": plan}
    response = elicit_form_sync(
        "Enable these project plugins? A backup will be written; the editor will not restart.\n"
        + json.dumps(plan, indent=2),
        {"type": "object", "properties": {"enable_plugins": {"type": "boolean"}}, "required": ["enable_plugins"]},
        title="Configure Unreal project plugins",
    )
    if not response.accepted or not response.data or response.data.get("enable_plugins") is not True:
        return {"status": "consent_required", "reason": response.message or "not_accepted", "plan": plan}
    if plugin_configuration_plan(unreal, capability) != plan:
        return {"status": "conflict", "plan": plan}
    path = Path(plan["project_path"])
    raw = path.read_bytes()
    if _digest(raw) != expected_sha256:
        return {"status": "conflict", "plan": plan}
    data = json.loads(raw.decode("utf-8-sig"))
    entries = data.setdefault("Plugins", [])
    for change in plan["proposed_changes"]:
        entry = next((item for item in entries if item.get("Name") == change["Name"]), None)
        if entry is None:
            entries.append(change)
        else:
            entry["Enabled"] = True
    # An exclusive sibling lock prevents concurrent adapter writers. Other editors
    # are guarded optimistically by the original descriptor hash immediately before replace.
    lock = path.with_suffix(path.suffix + ".dcc-mcp.lock")
    temporary = None
    with _descriptor_lock(lock):
        try:
            backup_fd, backup = tempfile.mkstemp(prefix=path.name + ".", suffix=".bak", dir=path.parent)
            with os.fdopen(backup_fd, "wb") as stream:
                stream.write(raw)
            fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
            with os.fdopen(fd, "wb") as stream:
                stream.write((json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
            if _digest(path.read_bytes()) != expected_sha256:
                return {"status": "conflict", "backup_path": backup, "plan": plan}
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)
    return {
        "status": "configured",
        "backup_path": backup,
        "project_sha256": _digest(path.read_bytes()),
        "restart_required": True,
        "runtime_verified": False,
        "plan": plan,
    }
