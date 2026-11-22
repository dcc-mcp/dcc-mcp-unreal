from pathlib import Path

import pytest

from dcc_mcp_unreal.acceptance_fixtures import FixtureCatalogError, inspect_local_fixture, load_catalog

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "docs/official-acceptance-fixtures.json"


def test_catalog_records_provenance_and_rights_without_acquiring_assets():
    catalog = load_catalog(CATALOG)
    assert catalog["policy"]["acquisition"] == "manual-only"
    assert {entry["rights_status"] for entry in catalog["fixtures"]} == {"reference-only", "authorized-local"}


def test_authorized_local_fixture_is_available():
    catalog = load_catalog(CATALOG)
    entry = next(item for item in catalog["fixtures"] if item["id"] == "synthetic-channel-contract")
    result = inspect_local_fixture(entry, ROOT)
    assert result["status"] == "available"
    assert result["missing"] == []


def test_reference_only_fixture_cannot_be_used_as_a_local_pass():
    catalog = load_catalog(CATALOG)
    entry = next(item for item in catalog["fixtures"] if item["id"] == "niagara-examples-channel-effects")
    assert inspect_local_fixture(entry, ROOT)["status"] == "rights-blocked"


def test_local_fixture_paths_cannot_escape_project_root():
    entry = {
        "id": "escape",
        "rights_status": "authorized-local",
        "local_paths": ["../../outside.json"],
    }
    with pytest.raises(FixtureCatalogError, match="escapes"):
        inspect_local_fixture(entry, ROOT)
