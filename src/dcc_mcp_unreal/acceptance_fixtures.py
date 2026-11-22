"""Validate optional Unreal acceptance-fixture metadata without acquiring assets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

CATALOG_SCHEMA = "dcc-mcp-unreal.official-acceptance-fixtures.v1"
RIGHTS_STATUSES = {"reference-only", "authorized-local", "unresolved"}
REQUIRED_FIELDS = {
    "id",
    "source_url",
    "publisher",
    "identity",
    "compatible_engine_versions",
    "required_plugins",
    "rights_status",
    "expected_behavior",
}


class FixtureCatalogError(ValueError):
    """Raised when a fixture catalog would make an unsafe or ambiguous claim."""


def load_catalog(path: Path) -> dict[str, Any]:
    """Load and validate a fixture catalog from JSON."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FixtureCatalogError(f"Cannot read fixture catalog: {path}") from exc
    validate_catalog(document)
    return document


def validate_catalog(document: Any) -> None:
    """Validate provenance, rights, and expected-result fields for each entry."""
    if not isinstance(document, dict) or document.get("schema") != CATALOG_SCHEMA:
        raise FixtureCatalogError(f"catalog schema must be {CATALOG_SCHEMA}")
    entries = document.get("fixtures")
    if not isinstance(entries, list) or not entries:
        raise FixtureCatalogError("catalog must contain at least one fixture")

    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or not REQUIRED_FIELDS <= set(entry):
            raise FixtureCatalogError("fixture entries must contain the complete provenance contract")
        fixture_id = entry["id"]
        if not isinstance(fixture_id, str) or not fixture_id or fixture_id in seen:
            raise FixtureCatalogError("fixture ids must be non-empty and unique")
        seen.add(fixture_id)
        source_url = entry["source_url"]
        parsed = urlparse(source_url) if isinstance(source_url, str) else None
        if parsed is None or parsed.scheme != "https" or not parsed.netloc:
            raise FixtureCatalogError(f"fixture {fixture_id} requires an HTTPS source_url")
        if not isinstance(entry["publisher"], str) or not entry["publisher"].strip():
            raise FixtureCatalogError(f"fixture {fixture_id} requires a publisher")
        if not isinstance(entry["identity"], dict) or not entry["identity"].get("name"):
            raise FixtureCatalogError(f"fixture {fixture_id} requires an asset identity")
        if not isinstance(entry["compatible_engine_versions"], list) or not entry["compatible_engine_versions"]:
            raise FixtureCatalogError(f"fixture {fixture_id} requires compatible engine versions")
        if not isinstance(entry["required_plugins"], list):
            raise FixtureCatalogError(f"fixture {fixture_id} requires a plugin list")
        if entry["rights_status"] not in RIGHTS_STATUSES:
            raise FixtureCatalogError(f"fixture {fixture_id} has an invalid rights_status")
        if not isinstance(entry["expected_behavior"], list) or not entry["expected_behavior"]:
            raise FixtureCatalogError(f"fixture {fixture_id} requires expected behavior")
        paths = entry.get("local_paths", [])
        if not isinstance(paths, list) or any(not isinstance(path, str) or Path(path).is_absolute() for path in paths):
            raise FixtureCatalogError(f"fixture {fixture_id} local_paths must be relative")
        if entry["rights_status"] != "authorized-local" and paths:
            raise FixtureCatalogError(f"fixture {fixture_id} cannot expose local paths without authorization")


def inspect_local_fixture(entry: dict[str, Any], project_root: Path) -> dict[str, Any]:
    """Report whether an explicitly authorized local fixture is available.

    This function never downloads, copies, or mutates an asset. A missing file is
    an explicit dependency result and cannot be interpreted as a passing fixture.
    """
    fixture_id = str(entry.get("id", ""))
    if entry.get("rights_status") != "authorized-local":
        return {"id": fixture_id, "status": "rights-blocked", "paths": []}
    paths = [Path(path) for path in entry.get("local_paths", [])]
    resolved = [(project_root / path).resolve() for path in paths]
    root = project_root.resolve()
    if any(root not in path.parents and path != root for path in resolved):
        raise FixtureCatalogError(f"fixture {fixture_id} escapes the project root")
    missing = [str(path.relative_to(root)) for path in resolved if not path.exists()]
    return {
        "id": fixture_id,
        "status": "missing-dependency" if missing else "available",
        "paths": [str(path.relative_to(root)) for path in resolved if path.exists()],
        "missing": missing,
    }
