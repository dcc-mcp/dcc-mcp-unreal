from pathlib import Path

from dcc_mcp_unreal.native_discovery import NATIVE_TOOL_SPECS


def test_native_discovery_only_advertises_cpp_bridge_actions() -> None:
    source = (
        Path(__file__).parents[1]
        / "unreal"
        / "plugin"
        / "Source"
        / "DccMcpUnreal"
        / "Private"
        / "DccMcpUnrealModule.cpp"
    ).read_text(encoding="utf-8")

    advertised = {spec["name"] for spec in NATIVE_TOOL_SPECS}
    implemented = {
        line.split('TEXT("', 1)[1].split('")', 1)[0]
        for line in source.splitlines()
        if 'if (Action == TEXT("unreal_' in line
    }

    assert advertised == implemented


def test_native_discovery_marks_read_tools() -> None:
    by_name = {spec["name"]: spec for spec in NATIVE_TOOL_SPECS}

    assert by_name["unreal_actors__list_actors"]["read_only"] is True
    assert by_name["unreal_level__get_level_info"]["read_only"] is True
    assert by_name["unreal_assets__list_assets"]["read_only"] is True
    assert by_name["unreal_actors__delete_actor"]["destructive"] is True
