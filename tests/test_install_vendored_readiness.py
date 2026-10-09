"""Installed plugin imports stay bound to their verified payload destination."""

import argparse

import pytest

from dcc_mcp_unreal import install_cli
from tests.test_install_cli import _bound_readiness


@pytest.mark.parametrize("vendored", [False, True])
def test_readiness_checks_exact_installed_module_origins(tmp_path, vendored):
    context = {
        "instance_id": "11111111-1111-1111-1111-111111111111",
        "editor_path": tmp_path / "Engine/UnrealEditor.exe",
        "project_file": tmp_path / "Project/Test.uproject",
        "plugin_root": tmp_path / "Project/Plugins/DccMcpUnreal",
        "engine_version": "5.7.4",
        "runtime": {
            "core_version": install_cli.MIN_CORE_VERSION,
            "adapter_origin": str(tmp_path / "runtime/dcc_mcp_unreal/__init__.py"),
            "core_origin": str(tmp_path / "runtime/dcc_mcp_core/__init__.py"),
            "plugin_payload": {"snapshot": {"manifest": []}},
        },
    }
    readiness = _bound_readiness(context)
    identity = readiness["probe"]["result"]["context"]["install_identity"]
    if vendored:
        for field, module in (("adapter_origin", "dcc_mcp_unreal"), ("core_origin", "dcc_mcp_core")):
            relative = f"python/{module}/__init__.py"
            context["runtime"]["plugin_payload"]["snapshot"]["manifest"].append(
                {"path": relative, "type": "file"}
            )
            identity[field] = str(context["plugin_root"] / relative)
    accepted, reason = install_cli._readiness_identity(argparse.Namespace(), context, {}, readiness)
    assert accepted == identity and reason is None
    for field in ("adapter_origin", "core_origin"):
        original = identity[field]
        identity[field] = str(tmp_path / "foreign" / field)
        accepted, reason = install_cli._readiness_identity(argparse.Namespace(), context, {}, readiness)
        assert accepted is None and field in reason
        if vendored:
            identity[field] = context["runtime"][field]
            accepted, reason = install_cli._readiness_identity(argparse.Namespace(), context, {}, readiness)
            assert accepted is None and field in reason
        identity[field] = original
