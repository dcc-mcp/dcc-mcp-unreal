from pathlib import Path

import pytest

from dcc_mcp_unreal.compatibility import parse_unreal_version, resolve_unreal_runtime, unreal_compatibility


@pytest.mark.parametrize(
    ("version", "expected"),
    [("4.18.3", (4, 18)), ("5.8.0-55116800+++UE5+Release-5.8", (5, 8))],
)
def test_parse_unreal_version(version, expected):
    assert parse_unreal_version(version) == expected


def test_ue418_reports_native_baseline_without_python():
    compatibility = unreal_compatibility("4.18", has_embedded_python=False)
    assert compatibility["supported"] is True
    assert compatibility["integration_tier"] == "native-baseline"
    assert compatibility["official_mcp_bridge"] is False


def test_ue426_auto_runtime_uses_the_standalone_sidecar():
    assert resolve_unreal_runtime("4.26.2", "auto") == "sidecar"


def test_unreal_startup_uses_the_shared_runtime_resolution():
    startup = (Path(__file__).parents[1] / "unreal" / "plugin" / "Content" / "Python" / "init_unreal.py").read_text(
        encoding="utf-8"
    )

    assert "resolve_unreal_runtime" in startup
    assert "SystemLibrary.get_engine_version()" in startup


def test_ue58_can_compose_dcc_and_epic_mcp():
    compatibility = unreal_compatibility("5.8", has_embedded_python=True, has_official_mcp=True)
    assert compatibility["integration_tier"] == "dcc-mcp-plus-epic"
    assert compatibility["official_mcp_bridge"] is True
