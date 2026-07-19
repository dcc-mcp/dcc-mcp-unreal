"""Prepare the constrained official-Fab acquisition workflow."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def prepare_free_asset_acquisition(
    query: str = "",
    engine_version: str = "5.8",
    destination_path: str = "/Game/Fab",
    required_traits=None,
    rejected_traits=None,
    **kwargs,
) -> dict:
    query = query.strip()
    destination_path = destination_path.strip()
    if not query:
        return skill_error("Missing required parameter: 'query'", "query must not be empty")
    if not destination_path.startswith("/Game"):
        return skill_error(
            "Invalid destination_path",
            "destination_path must be a Content Browser path under /Game",
        )

    required_traits = [str(value).strip() for value in (required_traits or []) if str(value).strip()]
    rejected_traits = [str(value).strip() for value in (rejected_traits or []) if str(value).strip()]

    return skill_success(
        "Prepared the official Fab acquisition and verification workflow.",
        prompt="Open the scoped Unreal Fab window with app_ui__snapshot; stop at authentication or EULA boundaries.",
        query=query,
        engine_version=engine_version.strip() or "5.8",
        destination_path=destination_path,
        filters={"price": "free", "format": "unreal-engine", "compatible_engine": True},
        required_listing_fields=[
            "title",
            "publisher",
            "source_url",
            "license",
            "supported_engine_versions",
        ],
        next_tool="app_ui__snapshot",
        verification_tools=[
            "unreal_assets__list_assets",
            "unreal_assets__get_asset_info",
        ],
        visual_gate={
            "required_traits": required_traits,
            "rejected_traits": rejected_traits,
        },
    )


def main(**kwargs) -> dict:
    return prepare_free_asset_acquisition(**kwargs)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
