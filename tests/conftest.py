"""pytest configuration — prevent the project's unreal/ plugin directory from
being imported as a Python namespace package during testing.

The project has a top-level ``unreal/`` directory (Unreal Engine plugin
scaffolding).  When the project root is on ``sys.path``, Python treats
``unreal/`` as a namespace package, causing ``import unreal`` to succeed even
when the real Unreal Engine Python API is not available.

This conftest removes the project root from ``sys.path`` and removes any
pre-cached namespace package so that the ``unreal`` availability helpers
accurately reflect the "not inside Unreal Engine" condition.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Remove project root from sys.path at collection time
# ---------------------------------------------------------------------------

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)


def _remove_project_root_from_syspath() -> None:
    """Remove the project root so ``import unreal`` finds no namespace package."""
    paths_to_remove = [
        p for p in sys.path
        if p and os.path.normcase(os.path.realpath(p)) == os.path.normcase(os.path.realpath(_PROJECT_ROOT))
    ]
    for p in paths_to_remove:
        sys.path.remove(p)

    # Also evict any already-cached namespace package for 'unreal'
    mod = sys.modules.get("unreal")
    if mod is not None:
        spec = getattr(mod, "__spec__", None)
        is_namespace = spec is not None and spec.origin is None
        if is_namespace:
            del sys.modules["unreal"]


_remove_project_root_from_syspath()
