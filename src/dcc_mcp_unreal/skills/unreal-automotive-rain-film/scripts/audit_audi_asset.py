"""Audit Epic's official Automotive Configurator Audi A5 assembly."""

from __future__ import annotations

from _automotive_common import audit_actor, dispatch_or_error, find_actor
from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


def _audit_audi_asset(actor_name: str) -> dict:
    import unreal

    actor = find_actor(unreal, actor_name)
    if actor is None:
        return skill_error(
            "The Audi actor was not found in the current level",
            actor_name,
            possible_solutions=["Load /Game/CarConfigurator/CarConfigurator_Main first."],
        )
    audit = audit_actor(unreal, actor)
    return skill_success(
        "Audited the official Automotive Configurator Audi assembly.",
        prompt="Use build_audi_rain_film to create the dedicated cinematic level.",
        **audit,
    )


@skill_entry
def audit_audi_asset(actor_name: str = "BP_AudiA5", **kwargs) -> dict:
    return dispatch_or_error(_audit_audi_asset, actor_name, timeout_hint_secs=45)


def main(**kwargs) -> dict:
    return audit_audi_asset(**kwargs)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
