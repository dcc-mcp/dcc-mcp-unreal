"""Static candidate installation must not probe an arbitrary running Editor."""

import sys

import dcc_mcp_core

from dcc_mcp_unreal import install_cli
from tests.test_install_cli import _synthetic_host


def test_unbound_install_and_verify_preserve_receipt_without_host_probe(monkeypatch, tmp_path):
    engine, project = _synthetic_host(tmp_path)
    common = ["--json", "--dcc-path", str(engine), "--python", sys.executable, "--project", str(project)]

    def reject_unselected_probe(**kwargs):
        raise AssertionError("No instance was selected; an existing Editor must not be probed")

    monkeypatch.setattr(dcc_mcp_core, "wait_for_sidecar_ready", reject_unselected_probe)
    code, result = install_cli._execute(install_cli._parser().parse_args(["install", *common, "--yes"]))
    assert code == install_cli.INSTALL_EXIT_VERIFY
    assert result["verify"]["directly_usable"] is False
    assert "--instance-id" in result["verify"]["failure_reason"]
    receipt = project.parent / ".dcc-mcp/receipts/unreal.json"
    original_receipt = receipt.read_bytes()
    assert (project.parent / "Plugins/DccMcpUnreal/DccMcpUnreal.uplugin").is_file()
    code, result = install_cli._execute(install_cli._parser().parse_args(["verify", *common]))
    assert code == install_cli.INSTALL_EXIT_VERIFY
    assert receipt.read_bytes() == original_receipt
    assert result["verify"]["failure_stage"] == "readiness"
