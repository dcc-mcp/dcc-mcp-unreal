import importlib.util
from pathlib import Path

import pytest

from dcc_mcp_unreal.project_config import (
    patch_console_variables,
    read_console_variables,
    requested_keys,
    validate_settings,
)


def test_project_config_path_discovers_embedded_plugin_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import dcc_mcp_unreal.project_config as project_config

    module_file = tmp_path / "Plugins" / "DccMcpUnreal" / "python" / "dcc_mcp_unreal" / "project_config.py"
    (tmp_path / "Config").mkdir()
    (tmp_path / "Config" / "DefaultEngine.ini").write_text("", encoding="utf-8")
    monkeypatch.setattr(project_config, "__file__", str(module_file))

    assert project_config.project_config_path() == tmp_path / "Config" / "DefaultEngine.ini"


def test_patch_console_variables_preserves_other_sections_and_creates_backup(tmp_path: Path):
    path = tmp_path / "Config" / "DefaultEngine.ini"
    path.parent.mkdir()
    path.write_text(
        "[ConsoleVariables]\nr.LumenScene.SurfaceCache.AtlasSize=4096\n\n[Other]\nKeep=1\n", encoding="utf-8"
    )

    result = patch_console_variables(path, {"r.LumenScene.SurfaceCache.AtlasSize": 8192})

    assert result["changed"] == {"r.LumenScene.SurfaceCache.AtlasSize": 8192}
    assert read_console_variables(path)["r.LumenScene.SurfaceCache.AtlasSize"] == "8192"
    assert "Keep=1" in path.read_text(encoding="utf-8")
    assert path.with_suffix(".ini.bak").exists()


def test_validate_settings_rejects_unknown_keys_and_invalid_atlas():
    with pytest.raises(ValueError, match="Unsupported renderer setting"):
        validate_settings({"r.Unknown": 1})
    with pytest.raises(ValueError, match="power of two"):
        validate_settings({"r.LumenScene.SurfaceCache.AtlasSize": 5000})


def test_patch_is_idempotent(tmp_path: Path):
    path = tmp_path / "DefaultEngine.ini"
    first = patch_console_variables(path, {"r.Nanite": 1})
    second = patch_console_variables(path, {"r.Nanite": 1})

    assert first["changed"] == {"r.Nanite": 1}
    assert second["changed"] == {}


def test_default_selection_ignores_unallowlisted_console_variables():
    values = {"r.Nanite": "1", "r.UnrelatedProjectSetting": "1"}

    assert requested_keys(values, None) == ["r.Nanite"]
    assert requested_keys(values, ["r.UnrelatedProjectSetting"]) == ["r.UnrelatedProjectSetting"]


def test_skill_handlers_publish_explicit_mcp_parameters():
    from dcc_mcp_core.schema import tool_spec_from_callable

    script = (
        Path(__file__).parents[1] / "src/dcc_mcp_unreal/skills/unreal-project-config/scripts/apply_project_config.py"
    )
    spec = importlib.util.spec_from_file_location("unreal_project_config_apply", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    schema = tool_spec_from_callable(module.apply_project_config).input_schema

    assert set(schema["properties"]) == {"settings"}
    assert schema["properties"]["settings"]["anyOf"][0]["additionalProperties"] == {"type": "number"}
