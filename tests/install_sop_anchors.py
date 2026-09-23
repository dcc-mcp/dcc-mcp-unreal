"""Measured byte identity of the Core Install SOP schema, keyed by Core release.

Core republishes the Install SOP schema artifact, so its byte identity is a property of the
Core release rather than a constant of the contract. A single hard-coded digest therefore stops
describing what Core ships as soon as Core publishes a new revision under the same revision id.

This adapter previously validated CLI output against a vendored copy of that schema in
`tests/fixtures/`. Comparing a file against a digest of itself can never fail, so the check was
blind to drift between what this adapter emits and what Core actually publishes. These helpers
measure the artifact the installed Core serves instead, and verify it against the revision
measured for that Core release.

A Core release with no measured row -- newer than `CORE_SCHEMA_ANCHOR_MEASURED_THROUGH`, or older
than the first row -- is accepted without a pinned digest and its observed bytes are reported, so
Core can move forward without breaking this suite.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Tuple


class CoreSchemaAnchor(NamedTuple):
    """Measured byte identity of one published revision of the Core Install SOP schema."""

    size: int
    sha256: str


# Key every measured revision by the first Core release that shipped it and append new rows;
# editing an existing row would silently re-pin a digest that was already published.
#
# The first row starts at 0.20.14 because 0.20.13 -- the floor this adapter declares in
# pyproject.toml -- shipped a 75-byte stub rather than the 4261-byte artifact. Versions below the
# first row deliberately resolve to no anchor, so that stub is never pinned.
#
# Rows whose floor is above `CORE_SCHEMA_ANCHOR_MEASURED_THROUGH` are staged: the bytes are
# recorded as soon as they are known, but the row only goes live once that Core release is
# published and `CORE_SCHEMA_ANCHOR_MEASURED_THROUGH` is raised to it. The `0.20.34` row is the
# `adapter-install-sop-v2` artifact Core `main` already carries.
CORE_SCHEMA_ANCHORS: Tuple[Tuple[Tuple[int, int, int], CoreSchemaAnchor], ...] = (
    ((0, 20, 14), CoreSchemaAnchor(4261, "3ca25788439917b4d4c0617230a762f9797756b5b54f45c8c4149f975b90f904")),
    ((0, 20, 30), CoreSchemaAnchor(4899, "2b3a8a101384a5163c7569c4a2b0de6586c672c5ee291735f94334a33b7d37a0")),
    ((0, 20, 34), CoreSchemaAnchor(4899, "daa5840e07c956d7c9269e5709d6993a3988b905f986c06e7c4c02f5023e9422")),
)

# Highest Core release whose schema bytes were measured into CORE_SCHEMA_ANCHORS.
CORE_SCHEMA_ANCHOR_MEASURED_THROUGH = "0.20.33"


def version_tuple(value: str) -> Optional[Tuple[int, int, int]]:
    """Parse a bounded `major[.minor[.patch]]` release version, or return None."""
    if not isinstance(value, str):
        return None
    parts = value.strip().split(".")
    if not 1 <= len(parts) <= 3:
        return None
    parsed: List[int] = []
    for part in parts:
        if not (part.isascii() and part.isdigit()):
            return None
        parsed.append(int(part))
    while len(parsed) < 3:
        parsed.append(0)
    return (parsed[0], parsed[1], parsed[2])


def core_schema_anchor(core_version: str) -> Optional[CoreSchemaAnchor]:
    """Return the measured schema identity for a Core version, or None when unmeasured.

    Returns `None` for an unparseable version, for a version newer than
    `CORE_SCHEMA_ANCHOR_MEASURED_THROUGH`, and for a version older than the first measured row.
    That last case matters here: this adapter declares a Core floor of 0.20.13, whose schema
    artifact is a stub, so sub-floor versions must degrade rather than pin the stub's bytes.
    """
    parsed = version_tuple(core_version)
    if parsed is None:
        return None
    measured_through = version_tuple(CORE_SCHEMA_ANCHOR_MEASURED_THROUGH)
    if measured_through is not None and parsed > measured_through:
        return None
    anchor: Optional[CoreSchemaAnchor] = None
    for floor, candidate in CORE_SCHEMA_ANCHORS:
        if parsed >= floor:
            anchor = candidate
    return anchor


def installed_core_version() -> Optional[str]:
    """Return the installed Core version, or None when it cannot be determined.

    Prefers the installed distribution's version because that is what the resolver selected and
    therefore what put the schema artifact on disk; falls back to the module attribute.
    """
    try:
        from importlib.metadata import version

        return version("dcc-mcp-core")
    except Exception:
        pass
    try:
        import dcc_mcp_core
    except ImportError:  # pragma: no cover - Core is a hard dependency of this suite
        return None
    value = getattr(dcc_mcp_core, "__version__", None)
    return value if isinstance(value, str) else None


def core_schema_artifact(shared: Mapping[str, Any]) -> Optional[CoreSchemaAnchor]:
    """Measure the schema artifact Core actually serves for `shared`, or return None.

    Core names the artifact by revision (`adapter-install-sop-vN.schema.json`), so the file whose
    parsed document equals `shared` is the one Core loaded. Matching on content rather than on a
    fixed filename keeps this working when Core moves from the v1 artifact to v2.
    """
    from dcc_mcp_core.deployment import install_sop

    schemas = Path(install_sop.__file__).resolve().parent.parent / "schemas"
    for candidate in sorted(schemas.glob("adapter-install-sop-v*.schema.json")):
        raw = candidate.read_bytes()
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            continue
        if document == dict(shared):
            return CoreSchemaAnchor(len(raw), hashlib.sha256(raw).hexdigest())
    return None


def core_schema_report(shared: Mapping[str, Any]) -> Dict[str, Any]:
    """Describe how the installed Core schema is pinned, including the observed bytes."""
    core_version = installed_core_version()
    anchor = core_schema_anchor(core_version or "")
    observed = core_schema_artifact(shared)
    return {
        "status": "pinned" if anchor is not None else "unpinned",
        "core_version": core_version,
        "measured_through": CORE_SCHEMA_ANCHOR_MEASURED_THROUGH,
        "size": anchor.size if anchor is not None else None,
        "sha256": anchor.sha256 if anchor is not None else None,
        "observed_size": observed.size if observed is not None else None,
        "observed_sha256": observed.sha256 if observed is not None else None,
    }


def verified_install_sop_schema() -> Dict[str, Any]:
    """Return the Install SOP schema Core serves, verified against its measured revision.

    Raises `AssertionError` when the artifact cannot be located, or when the installed Core
    release has a measured row that the artifact does not match. A release with no measured row is
    accepted, because rejecting it would strand a working installation on every Core upgrade.
    """
    from dcc_mcp_core.deployment import load_install_sop_schema

    shared = load_install_sop_schema()
    observed = core_schema_artifact(shared)
    assert observed is not None, "Could not locate the Install SOP schema artifact served by Core"
    anchor = core_schema_anchor(installed_core_version() or "")
    if anchor is not None:
        assert observed == anchor, (
            "Core serves Install SOP schema {} bytes / {} but the revision measured for dcc-mcp-core {} "
            "is {} bytes / {}".format(
                observed.size,
                observed.sha256,
                installed_core_version(),
                anchor.size,
                anchor.sha256,
            )
        )
    return dict(shared)
