from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "src" / "dcc_mcp_unreal" / "skills" / "unreal-fab-assets" / "scripts"


def load_helper():
    spec = importlib.util.spec_from_file_location("_test_unreal_fab", SCRIPTS / "_fab.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeLibrary:
    def __init__(self, authenticated=False):
        self.authenticated = authenticated
        self.login_calls = 0
        self.opened_urls = []

    def get_fab_session_status_json(self):
        return (
            '{"plugin_available":true,"authenticated":%s,'
            '"engine_version":"5.8","plugin_version":"0.0.13"}' % str(self.authenticated).lower()
        )

    def request_fab_login(self):
        self.login_calls += 1
        return True

    def open_fab_listing(self, url):
        self.opened_urls.append(url)
        return True


def test_inspect_session_never_returns_token():
    helper = load_helper()
    status = helper.inspect_session(FakeLibrary(authenticated=True))
    assert status == {
        "plugin_available": True,
        "authenticated": True,
        "engine_version": "5.8",
        "plugin_version": "0.0.13",
    }
    assert "token" not in repr(status).lower()


def test_login_and_listing_use_official_fab_api():
    helper = load_helper()
    library = FakeLibrary()
    helper.request_login(library)
    url = helper.open_listing(library, "a4882b5e-cfad-4830-a3dd-46a6c31a79b2")
    assert library.login_calls == 1
    assert library.opened_urls == [url]
    assert url == "https://fab.com/plugins/ue5/listings/a4882b5e-cfad-4830-a3dd-46a6c31a79b2"


def test_listing_id_must_be_uuid():
    helper = load_helper()
    with pytest.raises(ValueError):
        helper.listing_url("https://evil.example/listing")


def test_fab_skill_contract_validates():
    from dcc_mcp_core import validate_skill

    skill_dir = SCRIPTS.parent
    report = validate_skill(str(skill_dir))
    assert not report.has_errors, report
    skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    tools_text = (skill_dir / "tools.yaml").read_text(encoding="utf-8")
    depends_text = (skill_dir / "metadata" / "depends.md").read_text(encoding="utf-8")
    assert 'depends: ["ui-control", "unreal-assets"]' in skill_text
    assert "ui-control" in depends_text
    assert "ui_control__snapshot" in tools_text
    assert "app-ui" not in skill_text
    assert "app-ui" not in depends_text
    assert "app_ui__" not in tools_text
