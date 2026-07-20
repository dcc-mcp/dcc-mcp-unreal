"""Custom skill script runner that auto-discovers @skill_entry decorated functions.

When a skill script omits the boilerplate ``main()`` and
``if __name__ == "__main__":`` block, this runner detects any function
decorated with ``@skill_entry`` (via the ``_is_skill_entry`` sentinel
attribute) and promotes it as the ``main`` entry point automatically.

This eliminates ~8 lines of boilerplate per script without requiring any
change to the dcc-mcp-core runtime.
"""

from __future__ import annotations

import importlib.machinery
import logging
from pathlib import Path
from typing import Any, Callable, Mapping

from dcc_mcp_core._server.inprocess_executor import run_skill_script as _core_run_skill_script

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Auto-main injection via exec_module wrapper
# ---------------------------------------------------------------------------

_original_exec_module = importlib.machinery.SourceFileLoader.exec_module
_auto_main_active = False


def _patched_exec_module(self: importlib.machinery.SourceFileLoader, module: object) -> None:
    """Wrapped exec_module that auto-injects ``main`` for @skill_entry scripts."""
    _original_exec_module(self, module)
    if not _auto_main_active:
        return
    if hasattr(module, "main"):
        return
    entry = _discover_skill_entry(module)
    if entry is not None:
        module.main = entry  # type: ignore[attr-defined]


def _enable_auto_main() -> None:
    """Activate auto-main injection for subsequent module loads."""
    global _auto_main_active
    _auto_main_active = True
    importlib.machinery.SourceFileLoader.exec_module = _patched_exec_module  # type: ignore[method-assign]


def _disable_auto_main() -> None:
    """Deactivate auto-main injection."""
    global _auto_main_active
    _auto_main_active = False
    importlib.machinery.SourceFileLoader.exec_module = _original_exec_module  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _discover_skill_entry(module: object) -> Callable[..., Any] | None:
    """Find the first ``@skill_entry`` decorated function on *module*.

    Returns ``None`` when no decorated function is found, signalling the
    caller to fall back to its normal error path.
    """
    for name in dir(module):
        if name.startswith("_"):
            continue
        obj = getattr(module, name, None)
        if callable(obj) and getattr(obj, "_is_skill_entry", False):
            return obj
    return None


def run_skill_script(
    script_path: str,
    params: Mapping[str, Any],
    *,
    package_owner: str | None = None,
    admission_check: Callable[[], bool] | None = None,
) -> Any:
    """Execute a skill script, auto-discovering ``main`` when omitted.

    Wraps ``dcc_mcp_core._server.inprocess_executor.run_skill_script``
    so existing scripts with explicit ``main()`` work unchanged. When a
    script has only a ``@skill_entry`` decorated function (no module-level
    ``main``), this runner temporarily wraps ``SourceFileLoader.exec_module``
    to auto-inject ``main`` during the core's module loading.

    Skill authors can now write::

        from dcc_mcp_core.skill import skill_entry, skill_success

        @skill_entry
        def my_tool(**kwargs) -> dict:
            import unreal
            return skill_success("done")

    instead of also writing the 8-line ``main()`` + ``__main__`` block.
    """
    path = Path(script_path).resolve()

    # Fast path: if the script file doesn't exist, let the core raise.
    if not path.is_file():
        return _core_run_skill_script(
            script_path,
            params,
            package_owner=package_owner,
            admission_check=admission_check,
        )

    # If the script has an explicit ``def main(`` already, no injection needed.
    source = path.read_text(encoding="utf-8")
    if _has_explicit_main(source):
        return _core_run_skill_script(
            script_path,
            params,
            package_owner=package_owner,
            admission_check=admission_check,
        )

    # Enable auto-main injection just for this call.
    _enable_auto_main()
    try:
        return _core_run_skill_script(
            script_path,
            params,
            package_owner=package_owner,
            admission_check=admission_check,
        )
    finally:
        _disable_auto_main()


def _has_explicit_main(source: str) -> bool:
    """Return ``True`` when *source* contains an explicit ``def main``.

    The check is intentionally simple — it looks for ``def main(`` at the
    start of a line (allowing leading whitespace for indented definitions).
    A false-positive falls back to the safe core path (explicit ``main`` is
    just used as-is).
    """
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("def main("):
            return True
    return False
