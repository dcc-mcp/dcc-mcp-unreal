"""Bounded, project-configurable telemetry for Unreal PIE observations."""

from __future__ import annotations

import math
from typing import Any

COMBAT_ACTIONS = frozenset(
    {
        "attack_primary",
        "attack_secondary",
        "melee",
        "explosive",
        "skill",
        "attack_primary_entity",
        "attack_secondary_entity",
        "melee_entity",
        "explosive_entity",
        "skill_entity",
    }
)

DEFAULT_TELEMETRY_ALIASES = {
    "health": ["health", "Health", "CurrentHealth"],
    "max_health": ["max_health", "MaxHealth", "HealthMax"],
    "magazine": ["magazine", "Magazine", "CurrentAmmo", "AmmoInMagazine", "MagazineAmmo"],
    "reserve_ammo": ["reserve_ammo", "ReserveAmmo", "AmmoReserve"],
    "skill_cooldown_remaining": ["skill_cooldown_remaining", "SkillCooldownRemaining"],
    "ability_cooldown_remaining": ["ability_cooldown_remaining", "AbilityCooldownRemaining", "CooldownRemaining"],
}


def normalize_telemetry_aliases(value: Any) -> dict[str, list[str]]:
    """Merge bounded project aliases over the built-in combat fields."""
    aliases = {key: list(names) for key, names in DEFAULT_TELEMETRY_ALIASES.items()}
    if value is None:
        return aliases
    if not isinstance(value, dict):
        raise ValueError("telemetry_aliases must be an object")
    if len(value) > 24:
        raise ValueError("telemetry_aliases cannot contain more than 24 fields")
    for raw_key, raw_names in value.items():
        key = _safe_name(raw_key, "telemetry alias keys")
        if not isinstance(raw_names, list):
            raise ValueError("each telemetry alias must be an array of property names")
        if not 1 <= len(raw_names) <= 8:
            raise ValueError("each telemetry alias must provide between one and eight property names")
        names = []
        for raw_name in raw_names:
            name = _safe_name(raw_name, "telemetry property names")
            if name not in names:
                names.append(name)
        if not names:
            raise ValueError("each telemetry alias must provide at least one property name")
        aliases[key] = names
    return aliases


def read_actor_telemetry(unreal: Any, actor: Any, aliases: dict[str, list[str]]) -> dict[str, Any]:
    """Read the first scalar match for each alias from an actor or component."""
    owners = [actor]
    component_class = getattr(unreal, "ActorComponent", None)
    get_components = getattr(actor, "get_components_by_class", None)
    if component_class is not None and callable(get_components):
        try:
            owners.extend(item for item in list(get_components(component_class))[:24] if item is not None)
        except Exception:
            pass

    result = {}
    for key, names in aliases.items():
        value = _first_scalar_property(owners, names)
        if value is not None:
            result[key] = value
    return result


def build_action_availability(telemetry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Derive readiness for canonical ``*_cooldown_remaining`` fields."""
    result = {}
    suffix = "_cooldown_remaining"
    for field, value in telemetry.items():
        if not field.endswith(suffix) or isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        remaining = max(0.0, float(value))
        result[field[: -len(suffix)]] = {
            "ready": remaining <= 0.0,
            "remaining_seconds": remaining,
        }
    return dict(sorted(result.items()))


def telemetry_deltas(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    """Return changed canonical telemetry fields for persistent actors."""
    snapshots = [("player", before["player"], after["player"])]
    after_entities = {item["name"]: item for item in after["entities"]}
    snapshots.extend(
        ("entity", item, after_entities[item["name"]]) for item in before["entities"] if item["name"] in after_entities
    )
    deltas = []
    for scope, left, right in snapshots:
        left_values = left.get("telemetry", {})
        right_values = right.get("telemetry", {})
        for field in sorted(set(left_values).intersection(right_values)):
            old = left_values[field]
            new = right_values[field]
            if old == new:
                continue
            item = {
                "scope": scope,
                "actor": left["name"],
                "field": field,
                "before": old,
                "after": new,
            }
            if _is_number(old) and _is_number(new):
                item["delta"] = float(new) - float(old)
            deltas.append(item)
    return deltas


def combat_feedback(
    action: dict[str, Any],
    after: dict[str, Any],
    deltas: list[dict[str, Any]],
) -> dict[str, Any]:
    """Derive explicitly observational damage feedback from health deltas."""
    player_name = action["before"]["player"]["name"]
    health_deltas = [
        item
        for item in deltas
        if item["scope"] == "entity" and item["field"] == "health" and float(item.get("delta", 0.0)) < 0.0
    ]
    damage_events = [
        {
            "source": player_name,
            "target": item["actor"],
            "amount": -float(item["delta"]),
            "time_seconds": float(after["time_seconds"]),
            "observed": True,
        }
        for item in health_deltas
    ]
    target_name = action["target"]["name"] if action.get("target") else None
    target_before = next((item for item in action["before"]["entities"] if item["name"] == target_name), None)
    target_after = next((item for item in after["entities"] if item["name"] == target_name), None)
    health_observed = bool(
        target_before
        and target_after
        and "health" in target_before.get("telemetry", {})
        and "health" in target_after.get("telemetry", {})
    )
    target_damage = sum(item["amount"] for item in damage_events if item["target"] == target_name)
    return {
        "damage_events": damage_events,
        "combat_feedback": {
            "observed_hit": target_damage > 0.0 if health_observed else None,
            "damage_dealt": target_damage if health_observed else None,
            "target": target_name,
        },
    }


def _safe_name(value: Any, field: str) -> str:
    name = str(value).strip()
    if not name or len(name) > 64 or not name.isascii() or not name.replace("_", "").isalnum():
        raise ValueError("{} must contain only letters, numbers, and underscores".format(field))
    return name


def _first_scalar_property(owners: list[Any], names: list[str]):
    for owner in owners:
        for name in names:
            try:
                value = owner.get_editor_property(name)
            except Exception:
                continue
            if value is None:
                continue
            if isinstance(value, float) and not math.isfinite(value):
                continue
            if isinstance(value, (bool, int, float, str)):
                return value
    return None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


__all__ = [
    "COMBAT_ACTIONS",
    "DEFAULT_TELEMETRY_ALIASES",
    "build_action_availability",
    "combat_feedback",
    "normalize_telemetry_aliases",
    "read_actor_telemetry",
    "telemetry_deltas",
]
