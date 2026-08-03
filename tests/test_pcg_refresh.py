"""Tests for the Unreal PCG refresh skill."""

from __future__ import annotations

import importlib.util
import sys
from types import SimpleNamespace
from unittest.mock import patch


def test_refresh_pcg_rebuilds_matching_components():
    calls = []

    class PCGComponent:
        def rebuild_generated(self):
            calls.append("rebuild")

    component = PCGComponent()
    actor = SimpleNamespace(
        get_name=lambda: "RoadPCG",
        get_components_by_class=lambda cls: [component] if cls is PCGComponent else [],
    )
    unreal = SimpleNamespace(
        PCGComponent=PCGComponent,
        EditorLevelLibrary=SimpleNamespace(
            get_editor_world=lambda: SimpleNamespace(get_name=lambda: "City"),
            get_all_level_actors=lambda: [actor],
        ),
    )
    script = "src/dcc_mcp_unreal/skills/unreal-pcg/scripts/refresh_pcg.py"
    spec = importlib.util.spec_from_file_location("_test_refresh_pcg", script)
    module = importlib.util.module_from_spec(spec)

    with patch.dict(sys.modules, {"unreal": unreal}):
        spec.loader.exec_module(module)
        result = module.refresh_pcg(actor_name="RoadPCG")

    assert calls == ["rebuild"]
    assert result["success"] is True
    assert result["context"]["refreshed"] == [{"actor_name": "RoadPCG", "method": "rebuild_generated"}]
