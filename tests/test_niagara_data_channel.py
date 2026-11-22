import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src/dcc_mcp_unreal/skills/unreal-niagara/scripts/create_data_channel.py"
TOOLS = ROOT / "src/dcc_mcp_unreal/skills/unreal-niagara/tools.yaml"


def _module():
    spec = importlib.util.spec_from_file_location("create_data_channel", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_field_contract_rejects_duplicate_names_and_unknown_type_indices():
    module = _module()
    with pytest.raises(ValueError, match="unique"):
        module._validate_fields(
            [{"name": "Position", "type_registry_index": 0}, {"name": "position", "type_registry_index": 1}]
        )
    with pytest.raises(ValueError, match="65535"):
        module._validate_fields([{"name": "Position", "type_registry_index": 65536}])


def test_field_text_keeps_the_host_type_registry_index_explicit():
    module = _module()
    assert module._field_text({"name": "Position", "type_registry_index": 0}) == (
        '(Version=026F3C6F492337AD9DB0C5A846F7C0A6,Name="Position",TypeDefHandle=(RegisteredTypeIndex=0))'
    )


def test_tool_schema_requires_explicit_type_registry_indices():
    tool = next(
        item for item in yaml.safe_load(TOOLS.read_text())["tools"] if item["name"] == "create_niagara_data_channel"
    )
    properties = tool["input_schema"]["properties"]["fields"]["items"]["properties"]
    assert set(tool["input_schema"]["required"]) == {"channel_name", "fields"}
    assert set(properties) == {"name", "type_registry_index"}
