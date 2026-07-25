"""Tests for the unreal-pie skill package.

Run without a real Unreal Engine instance — tests validate the module
structure, skill entry points, and error-handling paths.
"""

from __future__ import annotations

import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Setup: add scripts dir to sys.path for bare imports like "from _pie_helpers import ..."
# ---------------------------------------------------------------------------

from pathlib import Path

_PIE_SCRIPTS_DIR = str(
    Path(__file__).resolve().parent.parent
    / "src"
    / "dcc_mcp_unreal"
    / "skills"
    / "unreal-pie"
    / "scripts"
)

if _PIE_SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _PIE_SCRIPTS_DIR)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import_script(name):
    """Import a skill script by module name (bare import from scripts dir)."""
    import importlib

    # Clear cached module so each test gets a fresh import
    if name in sys.modules:
        del sys.modules[name]
    return importlib.import_module(name)


def _ensure_fresh_helpers():
    """Re-import _pie_helpers with clean job registry state."""
    import importlib

    # Also clear any dependent modules
    for mod_name in list(sys.modules.keys()):
        if mod_name.startswith("pie_") or mod_name == "_pie_helpers":
            del sys.modules[mod_name]
    return importlib.import_module("_pie_helpers")


def _fake_unreal_module():
    """Build a minimal fake ``unreal`` module for testing."""
    unreal = types.ModuleType("unreal")

    # Required sentinel attributes for is_unreal_available check
    unreal.log = MagicMock()
    unreal.log.get_log = MagicMock(return_value="Log line 1\nLog line 2")
    unreal.EditorLevelLibrary = MagicMock()
    unreal.SystemLibrary = MagicMock()

    # Paths
    unreal.Paths = MagicMock()
    unreal.Paths.project_dir.return_value = "/tmp/FakeProject"
    unreal.Paths.get_project_file_path.return_value = "/tmp/FakeProject/FakeProject.uproject"

    # Editor subsystem — shared instance, default state is not running
    _fake_subsystem = MagicMock()
    _fake_subsystem.is_pie_running.return_value = False
    _fake_subsystem.is_pie_paused.return_value = False
    _fake_subsystem.start_pie.return_value = None
    _fake_subsystem.pause_pie.return_value = None
    _fake_subsystem.resume_pie.return_value = None
    _fake_subsystem.stop_pie.return_value = None
    _fake_subsystem.get_pie_world.return_value = MagicMock()

    def _get_editor_subsystem(cls):
        return _fake_subsystem

    unreal.get_editor_subsystem = _get_editor_subsystem
    # Store reference so tests can reconfigure the subsystem
    unreal._fake_subsystem = _fake_subsystem

    # Required editor subsystem classes (accessed as unreal.UnrealEditorSubsystem etc.)
    unreal.UnrealEditorSubsystem = MagicMock()
    unreal.LevelEditorSubsystem = MagicMock()

    # SlateBlueprintLibrary (for input injection)
    unreal.SlateBlueprintLibrary = MagicMock()

    # AutomationLibrary (for screenshots)
    unreal.AutomationLibrary = MagicMock()
    unreal.AutomationLibrary.take_high_res_screenshot = MagicMock()

    # SystemLibrary.get_engine_version (for status)
    unreal.SystemLibrary.get_engine_version = MagicMock(return_value="5.5.0")

    return unreal


def _patch_unreal():
    """Context manager that patches the unreal module into sys.modules."""
    fake = _fake_unreal_module()
    return patch.dict(sys.modules, {"unreal": fake})


# ---------------------------------------------------------------------------
# Tests: _pie_helpers
# ---------------------------------------------------------------------------


class TestPieHelpers:
    """Tests for the shared _pie_helpers module."""

    def test_import(self):
        """_pie_helpers imports without errors."""
        mod = _ensure_fresh_helpers()
        assert mod is not None

    def test_create_job(self):
        """create_job returns a unique job_id and stores the entry."""
        mod = _ensure_fresh_helpers()
        job_id = mod.create_job("automation_test", "DccMcp.Smoke")
        assert job_id.startswith("pie_automation_test_")
        assert len(job_id) > 20

        job = mod.get_job(job_id)
        assert job is not None
        assert job["job_type"] == "automation_test"
        assert job["filter"] == "DccMcp.Smoke"
        assert job["status"] == "queued"

    def test_get_job_missing(self):
        """get_job returns None for unknown IDs."""
        mod = _ensure_fresh_helpers()
        assert mod.get_job("nonexistent") is None

    def test_update_job(self):
        """update_job modifies fields."""
        mod = _ensure_fresh_helpers()
        job_id = mod.create_job("test", "")
        updated = mod.update_job(job_id, status="running")
        assert updated["status"] == "running"
        assert job_id in str(updated.values())

    def test_update_job_missing(self):
        """update_job returns None for unknown IDs."""
        mod = _ensure_fresh_helpers()
        assert mod.update_job("nonexistent", status="x") is None

    def test_cancel_job(self):
        """cancel_job marks status as cancelled."""
        mod = _ensure_fresh_helpers()
        job_id = mod.create_job("test", "")
        mod.cancel_job(job_id)
        job = mod.get_job(job_id)
        assert job["status"] == "cancelled"

    def test_list_jobs(self):
        """list_jobs returns jobs sorted by creation time."""
        mod = _ensure_fresh_helpers()
        mod.create_job("type_a", "")
        mod.create_job("type_b", "")
        all_jobs = mod.list_jobs()
        assert len(all_jobs) >= 2

        type_a_jobs = mod.list_jobs("type_a")
        assert all(j["job_type"] == "type_a" for j in type_a_jobs)

    def test_complete_job(self):
        """complete_job sets status and result."""
        mod = _ensure_fresh_helpers()
        job_id = mod.create_job("test", "")
        result_data = {"tests": 5, "passed": 5}
        mod.complete_job(job_id, result=result_data)
        job = mod.get_job(job_id)
        assert job["status"] == "completed"
        assert job["result"] == result_data

    def test_fail_job(self):
        """fail_job sets status to failed with error."""
        mod = _ensure_fresh_helpers()
        job_id = mod.create_job("test", "")
        mod.fail_job(job_id, error="timeout")
        job = mod.get_job(job_id)
        assert job["status"] == "failed"
        assert job["error"] == "timeout"

    def test_is_pie_active_without_unreal(self):
        """is_pie_active returns False when unreal is not available."""
        mod = _ensure_fresh_helpers()
        result = mod.is_pie_active()
        assert result is False

    def test_is_pie_paused_without_unreal(self):
        """is_pie_paused returns False when unreal is not available."""
        mod = _ensure_fresh_helpers()
        result = mod.is_pie_paused()
        assert result is False

    def test_is_pie_active_with_unreal(self):
        """is_pie_active returns True when unreal subsystem reports running."""
        mod = _ensure_fresh_helpers()
        with _patch_unreal():
            import unreal as fake_ue
            fake_ue._fake_subsystem.is_pie_running.return_value = True
            mod2 = _ensure_fresh_helpers()
            assert mod2.is_pie_active() is True

    def test_run_console_command(self):
        """run_console_command executes without error."""
        mod = _ensure_fresh_helpers()
        with _patch_unreal():
            mod2 = _ensure_fresh_helpers()
            result = mod2.run_console_command("stat fps")
            assert result is True


# ---------------------------------------------------------------------------
# Tests: pie_control
# ---------------------------------------------------------------------------


class TestPieControl:
    """Tests for pie_control.py."""

    def test_import(self):
        """Module imports."""
        mod = _import_script("pie_control")
        assert mod is not None
        assert callable(mod.pie_control)

    def test_missing_action(self):
        """Returns error when action is missing."""
        _ensure_fresh_helpers()
        mod = _import_script("pie_control")
        result = mod.pie_control(action="")
        assert result["success"] is False

    def test_invalid_action(self):
        """Returns error for unknown action."""
        _ensure_fresh_helpers()
        mod = _import_script("pie_control")
        result = mod.pie_control(action="invalid_action")
        assert result["success"] is False

    def test_enter_pie(self):
        """enter starts PIE via editor subsystem."""
        _ensure_fresh_helpers()
        mod = _import_script("pie_control")
        with _patch_unreal():
            # Re-import after patching so import unreal resolves inside handler
            mod2 = _import_script("pie_control")
            _ensure_fresh_helpers()
            result = mod2.pie_control(action="enter")
            assert result["success"] is True
            assert "PIE session started" in str(result["message"])

    def test_pause_pie(self):
        """pause freezes a running PIE session."""
        _ensure_fresh_helpers()
        mod = _import_script("pie_control")
        with _patch_unreal():
            import unreal as fake_ue
            fake_ue._fake_subsystem.is_pie_running.return_value = True
            fake_ue._fake_subsystem.is_pie_paused.return_value = False
            mod2 = _import_script("pie_control")
            _ensure_fresh_helpers()
            result = mod2.pie_control(action="pause")
            assert result["success"] is True
            assert "paused" in str(result.get("context", {}).get("pie_state", ""))

    def test_exit_pie(self):
        """exit/stop stops a running PIE session."""
        _ensure_fresh_helpers()
        mod = _import_script("pie_control")
        with _patch_unreal():
            import unreal as fake_ue
            fake_ue._fake_subsystem.is_pie_running.return_value = True
            mod2 = _import_script("pie_control")
            _ensure_fresh_helpers()
            result = mod2.pie_control(action="exit")
            assert result["success"] is True
            assert "stopped" in str(result.get("context", {}).get("pie_state", ""))

    def test_stop_is_alias_for_exit(self):
        """stop is an alias for exit."""
        _ensure_fresh_helpers()
        mod = _import_script("pie_control")
        with _patch_unreal():
            import unreal as fake_ue
            fake_ue._fake_subsystem.is_pie_running.return_value = True
            mod2 = _import_script("pie_control")
            _ensure_fresh_helpers()
            result = mod2.pie_control(action="stop")
            assert result["success"] is True
            assert "stopped" in str(result.get("context", {}).get("pie_state", ""))


# ---------------------------------------------------------------------------
# Tests: pie_inject_input
# ---------------------------------------------------------------------------


class TestPieInjectInput:
    """Tests for pie_inject_input.py."""

    def test_import(self):
        """Module imports."""
        mod = _import_script("pie_inject_input")
        assert mod is not None
        assert callable(mod.pie_inject_input)

    def test_missing_input_type(self):
        """Returns error when input_type is missing."""
        _ensure_fresh_helpers()
        mod = _import_script("pie_inject_input")
        result = mod.pie_inject_input(input_type="")
        assert result["success"] is False

    def test_invalid_input_type(self):
        """Returns error for unknown input_type."""
        _ensure_fresh_helpers()
        mod = _import_script("pie_inject_input")
        result = mod.pie_inject_input(input_type="invalid")
        assert result["success"] is False

    def test_key_press_missing_key(self):
        """Returns error for key_press without key."""
        _ensure_fresh_helpers()
        mod = _import_script("pie_inject_input")
        result = mod.pie_inject_input(input_type="key_press", key="")
        assert result["success"] is False

    def test_key_press(self):
        """key_press injects via console command."""
        _ensure_fresh_helpers()
        with _patch_unreal():
            _ensure_fresh_helpers()
            mod = _import_script("pie_inject_input")
            result = mod.pie_inject_input(input_type="key_press", key="W")
            assert result["success"] is True
            assert "W" in str(result.get("context", {}).get("key", ""))

    def test_mouse_button(self):
        """mouse_button injects via resolved key name."""
        _ensure_fresh_helpers()
        with _patch_unreal():
            _ensure_fresh_helpers()
            mod = _import_script("pie_inject_input")
            result = mod.pie_inject_input(input_type="mouse_button", button="left")
            assert result["success"] is True

    def test_mouse_move(self):
        """mouse_move injects delta."""
        _ensure_fresh_helpers()
        with _patch_unreal():
            _ensure_fresh_helpers()
            mod = _import_script("pie_inject_input")
            result = mod.pie_inject_input(input_type="mouse_move", delta_x=10.0, delta_y=20.0)
            assert result["success"] is True

    def test_key_name_resolution(self):
        """Common short key names resolve to Unreal key names."""
        mod = _import_script("pie_inject_input")
        assert mod._resolve_key_name("space") == "SpaceBar"
        assert mod._resolve_key_name("esc") == "Escape"
        assert mod._resolve_key_name("ctrl") == "LeftControl"
        assert mod._resolve_key_name("lmb") == "LeftMouseButton"
        assert mod._resolve_key_name("W") == "W"  # unchanged


# ---------------------------------------------------------------------------
# Tests: pie_snapshot_log
# ---------------------------------------------------------------------------


class TestPieSnapshotLog:
    """Tests for pie_snapshot_log.py."""

    def test_import(self):
        """Module imports."""
        mod = _import_script("pie_snapshot_log")
        assert mod is not None
        assert callable(mod.pie_snapshot_log)

    def test_snapshot_without_ue(self):
        """Returns a result even without UE (degraded path)."""
        mod = _import_script("pie_snapshot_log")
        with patch("os.path.isdir", return_value=False):
            result = mod.pie_snapshot_log(max_lines=10)
            assert result is not None
            assert "success" in result


# ---------------------------------------------------------------------------
# Tests: pie_get_status
# ---------------------------------------------------------------------------


class TestPieGetStatus:
    """Tests for pie_get_status.py."""

    def test_import(self):
        """Module imports."""
        mod = _import_script("pie_get_status")
        assert mod is not None
        assert callable(mod.pie_get_status)

    def test_get_status_without_ue(self):
        """Returns pie_state=stopped without UE."""
        _ensure_fresh_helpers()
        mod = _import_script("pie_get_status")
        result = mod.pie_get_status()
        assert result is not None
        assert result.get("context", {}).get("pie_state") == "stopped"

    def test_get_status_with_ue(self):
        """Returns pie_state=playing with UE running (PIE active)."""
        _ensure_fresh_helpers()
        with _patch_unreal():
            import unreal as fake_ue
            fake_ue._fake_subsystem.is_pie_running.return_value = True
            _ensure_fresh_helpers()
            mod = _import_script("pie_get_status")
            result = mod.pie_get_status()
            assert result["success"] is True
            assert result.get("context", {}).get("pie_state") == "playing"


# ---------------------------------------------------------------------------
# Tests: pie_run_test / pie_poll_test / pie_cancel_job
# ---------------------------------------------------------------------------


class TestPieJobWorkflow:
    """End-to-end job workflow: create → poll → cancel."""

    def test_import_run(self):
        """Module imports."""
        mod = _import_script("pie_run_test")
        assert mod is not None

    def test_import_poll(self):
        """Module imports."""
        mod = _import_script("pie_poll_test")
        assert mod is not None

    def test_import_cancel(self):
        """Module imports."""
        mod = _import_script("pie_cancel_job")
        assert mod is not None

    def test_run_test_missing_filter(self):
        """Returns error without filter."""
        _ensure_fresh_helpers()
        mod = _import_script("pie_run_test")
        result = mod.pie_run_test(filter="")
        assert result["success"] is False

    def test_run_test(self):
        """Run creates a job and returns job_id."""
        _ensure_fresh_helpers()
        mod_run = _import_script("pie_run_test")
        with _patch_unreal():
            _ensure_fresh_helpers()
            mod2 = _import_script("pie_run_test")
            result = mod2.pie_run_test(filter="DccMcp.Smoke")
            assert result["success"] is True
            job_id = result.get("context", {}).get("job_id")
            assert job_id is not None
            assert job_id.startswith("pie_automation_test_")

    def test_poll_test_missing_job_id(self):
        """Returns error without job_id."""
        _ensure_fresh_helpers()
        mod = _import_script("pie_poll_test")
        result = mod.pie_poll_test(job_id="")
        assert result["success"] is False

    def test_poll_test_not_found(self):
        """Returns error for unknown job_id."""
        _ensure_fresh_helpers()
        mod = _import_script("pie_poll_test")
        result = mod.pie_poll_test(job_id="nonexistent_job")
        assert result["success"] is False

    def test_poll_test_found(self):
        """Returns status for an existing job."""
        _ensure_fresh_helpers()
        with _patch_unreal():
            _ensure_fresh_helpers()
            mod_run = _import_script("pie_run_test")
            mod_poll = _import_script("pie_poll_test")
            run_result = mod_run.pie_run_test(filter="DccMcp.Smoke")
            job_id = run_result["context"]["job_id"]
            poll_result = mod_poll.pie_poll_test(job_id=job_id)
            assert poll_result["success"] is True
            assert poll_result["context"]["job_id"] == job_id

    def test_cancel_job_missing_job_id(self):
        """Returns error without job_id."""
        _ensure_fresh_helpers()
        mod = _import_script("pie_cancel_job")
        result = mod.pie_cancel_job(job_id="")
        assert result["success"] is False

    def test_cancel_job_not_found(self):
        """Returns error for unknown job_id."""
        _ensure_fresh_helpers()
        mod = _import_script("pie_cancel_job")
        result = mod.pie_cancel_job(job_id="nonexistent_job")
        assert result["success"] is False

    def test_full_job_lifecycle(self):
        """Create → poll → cancel lifecycle."""
        _ensure_fresh_helpers()
        with _patch_unreal():
            _ensure_fresh_helpers()
            mod_run = _import_script("pie_run_test")
            mod_poll = _import_script("pie_poll_test")
            mod_cancel = _import_script("pie_cancel_job")

            # 1. Queue
            run_result = mod_run.pie_run_test(filter="DccMcp.Smoke")
            assert run_result["success"] is True
            job_id = run_result["context"]["job_id"]

            # 2. Poll
            poll_result = mod_poll.pie_poll_test(job_id=job_id)
            assert poll_result["success"] is True
            assert poll_result["context"]["status"] in ("queued", "running")

            # 3. Cancel
            cancel_result = mod_cancel.pie_cancel_job(job_id=job_id)
            assert cancel_result["success"] is True
            assert cancel_result["context"]["status"] == "cancelled"

            # 4. Cancel again (idempotent)
            cancel_result2 = mod_cancel.pie_cancel_job(job_id=job_id)
            assert cancel_result2["success"] is True


# ---------------------------------------------------------------------------
# Tests: pie_capture_screenshot
# ---------------------------------------------------------------------------


class TestPieCaptureScreenshot:
    """Tests for pie_capture_screenshot.py."""

    def test_import(self):
        """Module imports."""
        mod = _import_script("pie_capture_screenshot")
        assert mod is not None

    def test_default_path(self):
        """_default_screenshot_path returns a reasonable path."""
        mod = _import_script("pie_capture_screenshot")
        path = mod._default_screenshot_path()
        assert "pie_" in path
        assert path.endswith(".png")

    def test_ensure_dir(self):
        """_ensure_dir creates parent directory."""
        import tempfile

        mod = _import_script("pie_capture_screenshot")
        with tempfile.TemporaryDirectory() as tmpdir:
            test_path = os.path.join(tmpdir, "sub", "test.png")
            result = mod._ensure_dir(test_path)
            assert os.path.isdir(os.path.dirname(result))

    def test_capture_screenshot_without_ue(self):
        """Returns error or success dict without UE."""
        mod = _import_script("pie_capture_screenshot")
        result = mod.pie_capture_screenshot(filepath="")
        assert result is not None
        assert "success" in result


# ---------------------------------------------------------------------------
# Tests: SKILL.md and tools.yaml existence
# ---------------------------------------------------------------------------


class TestSkillMetadata:
    """Verify SKILL.md and tools.yaml exist and are well-formed."""

    def test_skill_md_exists(self):
        """SKILL.md exists in the skill directory."""
        skill_dir = Path(_PIE_SCRIPTS_DIR).parent
        assert (skill_dir / "SKILL.md").is_file()

    def test_tools_yaml_exists(self):
        """tools.yaml exists and lists all 8 tools."""
        import yaml

        skill_dir = Path(_PIE_SCRIPTS_DIR).parent
        tools_path = skill_dir / "tools.yaml"
        assert tools_path.is_file()

        with open(tools_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        assert "tools" in data
        assert len(data["tools"]) == 8

        tool_names = [t["name"] for t in data["tools"]]
        expected = [
            "pie_control",
            "pie_inject_input",
            "pie_capture_screenshot",
            "pie_snapshot_log",
            "pie_get_status",
            "pie_run_test",
            "pie_poll_test",
            "pie_cancel_job",
        ]
        assert tool_names == expected

    def test_all_scripts_exist(self):
        """Every source_file in tools.yaml points to an existing script."""
        import yaml

        skill_dir = Path(_PIE_SCRIPTS_DIR).parent
        with open(skill_dir / "tools.yaml", "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

        for tool in data["tools"]:
            source = tool["source_file"]
            assert (skill_dir / source).is_file(), "Missing source file: {}".format(source)
