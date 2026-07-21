"""Tests for dcc_mcp_unreal.skill_runner."""

from __future__ import annotations

import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_script(dir_path: Path, name: str, source: str) -> Path:
    """Write a Python script to *dir_path* and return its absolute path."""
    path = dir_path / name
    path.write_text(source, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# _has_explicit_main
# ---------------------------------------------------------------------------


def test_has_explicit_main_detects_def_main():
    from dcc_mcp_unreal.skill_runner import _has_explicit_main

    assert _has_explicit_main("def main(**kwargs) -> dict:\n    return func(**kwargs)")
    assert _has_explicit_main("  def main(**kwargs) -> dict:\n    return func(**kwargs)")
    assert _has_explicit_main("def main() -> dict:\n    return {}")


def test_has_explicit_main_false_when_no_main():
    from dcc_mcp_unreal.skill_runner import _has_explicit_main

    assert _has_explicit_main("@skill_entry\ndef my_tool(**kwargs):\n    return skill_success('ok')") is False
    assert _has_explicit_main("def helper():\n    pass") is False


# ---------------------------------------------------------------------------
# _discover_skill_entry
# ---------------------------------------------------------------------------


def test_discover_skill_entry_finds_decorated_function():
    from dcc_mcp_core.skill import skill_entry

    from dcc_mcp_unreal.skill_runner import _discover_skill_entry

    @skill_entry
    def my_tool(**kwargs):
        pass

    fake_module = type(sys)("fake_skill")
    fake_module.__dict__["my_tool"] = my_tool

    result = _discover_skill_entry(fake_module)
    assert result is not None
    assert getattr(result, "_is_skill_entry", False) is True


def test_discover_skill_entry_skips_private_names():
    from dcc_mcp_core.skill import skill_entry

    from dcc_mcp_unreal.skill_runner import _discover_skill_entry

    @skill_entry
    def _private_tool(**kwargs):
        pass

    fake_module = type(sys)("fake_skill")
    fake_module.__dict__["_private_tool"] = _private_tool

    assert _discover_skill_entry(fake_module) is None


def test_discover_skill_entry_returns_none_when_no_entry():
    from dcc_mcp_unreal.skill_runner import _discover_skill_entry

    fake_module = type(sys)("fake_skill")
    fake_module.__dict__["not_a_tool"] = lambda: None

    assert _discover_skill_entry(fake_module) is None


# ---------------------------------------------------------------------------
# run_skill_script — explicit main (backward compatibility)
# ---------------------------------------------------------------------------


def test_run_script_with_explicit_main():
    """Scripts with explicit main() work unchanged."""
    from dcc_mcp_unreal.skill_runner import run_skill_script

    with tempfile.TemporaryDirectory() as tmpdir:
        script = _write_script(
            Path(tmpdir),
            "explicit_main.py",
            textwrap.dedent("""\
            from dcc_mcp_core.skill import skill_entry, skill_success

            @skill_entry
            def my_tool(name: str = "world", **kwargs) -> dict:
                return skill_success(f"hello {name}", name=name)

            def main(**kwargs) -> dict:
                return my_tool(**kwargs)

            if __name__ == "__main__":
                from dcc_mcp_core.skill import run_main
                run_main(main)
            """),
        )

        result = run_skill_script(str(script), {"name": "unreal"})
        assert result["success"] is True
        assert result["context"]["name"] == "unreal"


# ---------------------------------------------------------------------------
# run_skill_script — auto-discover main (plugin-style, no main())
# ---------------------------------------------------------------------------


def test_run_script_without_main_discovers_entry():
    """When no main() is present, the runner auto-discovers @skill_entry."""
    from dcc_mcp_unreal.skill_runner import run_skill_script

    with tempfile.TemporaryDirectory() as tmpdir:
        # Also create a mock unreal module to satisfy lazy imports
        mock_unreal = type(sys)("unreal")
        mock_unreal.__dict__["log"] = lambda msg: None
        sys.modules["unreal"] = mock_unreal
        try:
            script = _write_script(
                Path(tmpdir),
                "no_main.py",
                textwrap.dedent("""\
                from dcc_mcp_core.skill import skill_entry, skill_success

                @skill_entry
                def get_version(**kwargs) -> dict:
                    return skill_success("5.5", version="5.5")
                """),
            )

            result = run_skill_script(str(script), {})
            assert result["success"] is True
            assert result["context"]["version"] == "5.5"
        finally:
            sys.modules.pop("unreal", None)


def test_run_script_without_main_errors_on_module():
    """When @skill_entry raises an exception, it's caught."""
    from dcc_mcp_unreal.skill_runner import run_skill_script

    with tempfile.TemporaryDirectory() as tmpdir:
        script = _write_script(
            Path(tmpdir),
            "error_script.py",
            textwrap.dedent("""\
            from dcc_mcp_core.skill import skill_entry, skill_error

            @skill_entry
            def broken_tool(**kwargs) -> dict:
                return skill_error("failed", "test error")
            """),
        )

        result = run_skill_script(str(script), {})
        assert result["success"] is False
        assert result["error"] == "test error"


def test_run_script_delegates_to_core_for_missing_file():
    """Missing files are handled by the core runner."""
    from dcc_mcp_unreal.skill_runner import run_skill_script

    with pytest.raises(FileNotFoundError, match="nonexistent"):
        run_skill_script("/nonexistent/path.py", {})


def test_run_script_delegates_to_core_when_neither_main_nor_entry():
    """When a script has no main and no @skill_entry, core errors out."""
    from dcc_mcp_unreal.skill_runner import run_skill_script

    with tempfile.TemporaryDirectory() as tmpdir:
        script = _write_script(
            Path(tmpdir),
            "no_entry.py",
            textwrap.dedent("""\
            x = 1
            """),
        )

        with pytest.raises(AttributeError, match=r"does not expose"):
            run_skill_script(str(script), {})


# ---------------------------------------------------------------------------
# run_skill_script — custom runner passed to HostExecutionBridge
# ---------------------------------------------------------------------------


def test_host_execution_bridge_accepts_custom_runner():
    """The custom runner can be wired into HostExecutionBridge."""
    from dcc_mcp_core import HostExecutionBridge

    from dcc_mcp_unreal.skill_runner import run_skill_script as custom_runner

    bridge = HostExecutionBridge(runner=custom_runner)
    assert bridge.runner is custom_runner

    executor = bridge.as_inprocess_executor()
    assert callable(executor)


def test_inprocess_executor_uses_custom_runner_for_script_without_main():
    """End-to-end: bridge executor → custom runner → auto-discover main."""
    from dcc_mcp_core import HostExecutionBridge

    from dcc_mcp_unreal.skill_runner import run_skill_script as custom_runner

    bridge = HostExecutionBridge(runner=custom_runner)
    executor = bridge.as_inprocess_executor()

    with tempfile.TemporaryDirectory() as tmpdir:
        mock_unreal = type(sys)("unreal")
        mock_unreal.__dict__["log"] = lambda msg: None
        sys.modules["unreal"] = mock_unreal
        try:
            script = _write_script(
                Path(tmpdir),
                "simple_getter.py",
                textwrap.dedent("""\
                from dcc_mcp_core.skill import skill_entry, skill_success

                @skill_entry
                def engine_info(**kwargs) -> dict:
                    return skill_success("UE 5.5", engine="Unreal Engine 5.5")
                """),
            )

            result = executor(str(script), {})
            assert result["success"] is True
            assert result["context"]["engine"] == "Unreal Engine 5.5"
        finally:
            sys.modules.pop("unreal", None)


# ---------------------------------------------------------------------------
# Server integration
# ---------------------------------------------------------------------------


def test_make_execution_bridge_uses_custom_runner():
    """_make_execution_bridge wires the custom skill runner."""
    from dcc_mcp_unreal.server import _make_execution_bridge
    from dcc_mcp_unreal.skill_runner import run_skill_script as custom_runner

    dispatcher, bridge = _make_execution_bridge(timeout_secs=5.0)
    assert bridge.runner is custom_runner
    dispatcher.close()
