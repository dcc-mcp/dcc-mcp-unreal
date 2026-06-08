"""Legacy Unreal Editor smoke entry point for DccMcpUnreal.

Run with UnrealEditor-Cmd.exe and ``-ExecutePythonScript``.  The preferred
entry point is the native Automation Test ``DccMcp.Smoke.ServerStarts``; this
wrapper remains useful for older plugin builds or direct script debugging.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _ensure_plugin_python_on_path() -> None:
    script_path = Path(__file__).resolve()
    project_root = script_path.parents[1]
    source_plugin_python = project_root / "unreal" / "plugin" / "Content" / "Python"
    if source_plugin_python.is_dir():
        source_plugin_python_str = str(source_plugin_python)
        if source_plugin_python_str not in sys.path:
            sys.path.insert(0, source_plugin_python_str)

    plugin_python = project_root / "Plugins" / "DccMcpUnreal" / "python"
    if plugin_python.is_dir():
        plugin_python_str = str(plugin_python)
        if plugin_python_str not in sys.path:
            sys.path.insert(0, plugin_python_str)


def main() -> dict:
    _ensure_plugin_python_on_path()
    import dcc_mcp_unreal_automation  # noqa: PLC0415

    return dcc_mcp_unreal_automation.run_smoke(
        result_path=os.environ.get("DCC_MCP_UNREAL_TEST_RESULT", ""),
        raise_on_failure=True,
    )


if __name__ == "__main__":
    main()
