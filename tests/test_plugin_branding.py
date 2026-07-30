import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DESCRIPTOR = ROOT / "unreal" / "plugin" / "DccMcpUnreal.uplugin"
PLUGIN_ICON = ROOT / "unreal" / "plugin" / "Resources" / "Icon128.png"


def test_plugin_browser_branding_uses_the_official_site_and_icon_contract() -> None:
    descriptor = json.loads(PLUGIN_DESCRIPTOR.read_text(encoding="utf-8"))
    icon = PLUGIN_ICON.read_bytes()

    assert descriptor["CreatedByURL"] == "https://dcc-mcp.github.io/"
    assert descriptor["DocsURL"] == ("https://dcc-mcp.github.io/ecosystem#dcc-and-creative-application-adapters")
    assert icon[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", icon[16:24]) == (128, 128)
