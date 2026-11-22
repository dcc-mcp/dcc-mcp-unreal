import pytest

from dcc_mcp_unreal.asset_handoff import AssetHandoffError, plan_handoff, verify_handoff


def _graph():
    return {
        "/Plugin/Materials/MI_Mud": ["/Plugin/Materials/M_Mud", "/Plugin/Textures/T_Mud"],
        "/Plugin/Materials/M_Mud": ["/Plugin/Textures/T_Mud"],
        "/Plugin/Textures/T_Mud": [],
    }


def test_plan_is_incremental_and_deterministic():
    plan = plan_handoff(
        ["/Plugin/Materials/MI_Mud"],
        _graph(),
        source_root="/Plugin",
        destination_root="/Game/Localized",
        baseline=["/Plugin/Materials/M_Mud"],
    )
    assert plan["status"] == "planned"
    assert plan["shared"] == ["/Plugin/Materials/M_Mud"]
    assert [item["destination"] for item in plan["copy"]] == [
        "/Game/Localized/Materials/MI_Mud",
        "/Game/Localized/Textures/T_Mud",
    ]
    assert plan["overwrite_allowed"] is False


def test_missing_dependencies_are_separated_from_baseline_missing_references():
    graph = {
        "/Plugin/Materials/MI_Mud": ["/Plugin/Textures/T_Mud", "/Game/Legacy/Missing"],
        "/Plugin/Textures/T_Mud": [],
    }
    plan = plan_handoff(
        ["/Plugin/Materials/MI_Mud"],
        graph,
        source_root="/Plugin",
        destination_root="/Game/Localized",
        baseline=["/Game/Legacy/Missing"],
    )
    assert plan["missing_dependencies"] == []
    assert plan["preexisting_missing_dependencies"] == ["/Game/Legacy/Missing"]


def test_verification_reports_remaining_plugin_dependencies():
    plan = plan_handoff(
        ["/Plugin/Materials/MI_Mud"],
        _graph(),
        source_root="/Plugin",
        destination_root="/Game/Localized",
    )
    verification = verify_handoff(
        plan,
        observed_dependencies={
            "/Game/Localized/Materials/MI_Mud": ["/Plugin/Materials/M_Mud", "/Plugin/Textures/T_Mud"],
            "/Plugin/Materials/M_Mud": ["/Plugin/Textures/T_Mud"],
            "/Plugin/Textures/T_Mud": [],
        },
    )
    assert verification["status"] == "failed"
    assert verification["remaining_source_dependencies"] == [
        "/Plugin/Materials/M_Mud",
        "/Plugin/Textures/T_Mud",
    ]


def test_invalid_roots_and_cross_root_dependencies_fail_closed():
    with pytest.raises(AssetHandoffError):
        plan_handoff(["/Plugin/Materials/MI_Mud.MI_Mud"], _graph(), source_root="/Plugin", destination_root="/Game")
    with pytest.raises(AssetHandoffError, match="inside source_root"):
        plan_handoff(
            ["/Game/Other/Asset"],
            {"/Game/Other/Asset": []},
            source_root="/Plugin",
            destination_root="/Game/Localized",
        )
