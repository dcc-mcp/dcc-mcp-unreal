"""Tests for Unreal level skill scripts."""

from __future__ import annotations

import importlib.util
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def test_save_level_uses_ue58_save_packages_signature():
    package = SimpleNamespace(get_name=lambda: "/Game/Materials/M_Road")
    loading_and_saving = SimpleNamespace(
        get_dirty_content_packages=lambda: [package],
        save_packages=MagicMock(),
    )
    unreal = SimpleNamespace(
        EditorLevelLibrary=SimpleNamespace(
            get_editor_world=lambda: SimpleNamespace(get_name=lambda: "PCG_City_Showcase"),
            save_current_level=lambda: True,
        ),
        EditorLoadingAndSavingUtils=loading_and_saving,
    )
    script = "src/dcc_mcp_unreal/skills/unreal-level/scripts/save_level.py"
    spec = importlib.util.spec_from_file_location("_test_save_level", script)
    module = importlib.util.module_from_spec(spec)

    with patch.dict(sys.modules, {"unreal": unreal}):
        spec.loader.exec_module(module)
        result = module.save_level(save_all_dirty=True)

    assert result["success"] is True
    loading_and_saving.save_packages.assert_called_once_with([package], True)
