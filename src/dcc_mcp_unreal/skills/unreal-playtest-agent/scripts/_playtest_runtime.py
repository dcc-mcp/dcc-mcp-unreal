"""Process-scoped runtime for structured PIE playtest episodes."""

from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from collections import Counter
from typing import Any, Optional

import dcc_mcp_unreal as _adapter_package
from dcc_mcp_unreal.pie_session import require_pie_context
from dcc_mcp_unreal.playtest_telemetry import (
    COMBAT_ACTIONS,
    build_action_availability,
    combat_feedback,
    normalize_telemetry_aliases,
    read_actor_telemetry,
    telemetry_deltas,
)

if not hasattr(_adapter_package, "_playtest_episode_registry"):
    _adapter_package._playtest_episode_registry = {}  # type: ignore[attr-defined]
_EPISODES: dict[str, dict[str, Any]] = _adapter_package._playtest_episode_registry  # type: ignore[attr-defined]


_ACTION_KEYS = {
    "interact": "F",
    "attack_primary": "LeftMouseButton",
    "attack_secondary": "RightMouseButton",
    "melee": "V",
    "explosive": "Q",
    "skill": "E",
    "reload": "R",
    "jump": "SpaceBar",
}
_MOVE_KEYS = {
    "forward": "W",
    "backward": "S",
    "left": "A",
    "right": "D",
}
_TARGET_ACTIONS = {
    "navigate_to_entity",
    "face_entity",
    "attack_primary_entity",
    "attack_secondary_entity",
    "melee_entity",
    "explosive_entity",
    "skill_entity",
}
_NAVIGATION_ACTIONS = {"navigate_to_entity", "navigate_to_location"}
_MOVEMENT_ACTIONS = _NAVIGATION_ACTIONS | {"move_relative"}
_OBJECT_IDENTITIES: dict[int, tuple[Any, str]] = {}
_DISTANCE_UNIT = "centimeters"
_DURATION_UNIT = "seconds"
_RELATIVE_MOVEMENT_MAX_SPEED_CM_PER_SECOND = 10_000.0
_RELATIVE_MOVEMENT_BASE_SLACK_CM = 500.0
_RELATIVE_DIRECTION_MIN_ALIGNMENT = math.sqrt(0.5)


def _unreal():
    import unreal  # noqa: PLC0415

    return unreal


def _pie_context():
    context = require_pie_context(_unreal())
    return context.unreal, context.world, context.controller, context.pawn


def _class_name(value: Any) -> str:
    unreal_class = value.get_class() if value is not None else None
    return str(unreal_class.get_name()) if unreal_class is not None else ""


def _actor_name(actor: Any) -> str:
    return str(actor.get_name())


def _object_path(value: Any) -> Optional[str]:
    get_path_name = getattr(value, "get_path_name", None)
    try:
        raw_path = get_path_name() if callable(get_path_name) else None
    except Exception:
        return None
    normalized = str(raw_path).strip() if raw_path else ""
    return normalized or None


def _object_token(value: Any) -> str:
    """Return a process-stable token tied to this exact live wrapper object."""

    key = id(value)
    existing = _OBJECT_IDENTITIES.get(key)
    if existing is not None and existing[0] is value:
        return existing[1]
    token = uuid.uuid4().hex
    _OBJECT_IDENTITIES[key] = (value, token)
    return token


def _redacted_object_identity(value: Any) -> dict[str, Any]:
    raw_path = _object_path(value)
    if raw_path is None:
        return {"identity": None, "object_path_hash": None}
    path_digest = hashlib.sha256(raw_path.encode("utf-8")).hexdigest()
    exact_source = "{}\0{}".format(raw_path, _object_token(value))
    exact_digest = hashlib.sha256(exact_source.encode("utf-8")).hexdigest()
    return {
        "identity": "sha256:" + exact_digest,
        "object_path_hash": "sha256:" + path_digest,
    }


def _actor_identity(actor: Any, observed_player: Any) -> dict[str, Any]:
    """Return exact-object and path digests without exposing the raw object path."""

    redacted = _redacted_object_identity(actor)
    return {
        "name": _actor_name(actor),
        "class": _class_name(actor),
        **redacted,
        "is_observed_player": actor is observed_player,
    }


def _context_component_identity(value: Any, kind: str) -> dict[str, Any]:
    redacted = _redacted_object_identity(value)
    if redacted["identity"] is None:
        raise RuntimeError("The PIE {} has no trustworthy exact object path".format(kind))
    get_name = getattr(value, "get_name", None)
    return {
        "name": str(get_name()) if callable(get_name) else "",
        "class": _class_name(value) if callable(getattr(value, "get_class", None)) else "",
        **redacted,
    }


def _runtime_binding(context: tuple[Any, Any, Any, Any]) -> dict[str, Any]:
    _unreal_value, world, controller, player = context
    world_identity = _context_component_identity(world, "world")
    controller_identity = _context_component_identity(controller, "controller")
    player_identity = _context_component_identity(player, "player pawn")
    session_source = "\0".join(
        (
            str(world_identity["identity"]),
            str(controller_identity["identity"]),
            str(player_identity["identity"]),
        )
    )
    return {
        "session_identity": "sha256:" + hashlib.sha256(session_source.encode("utf-8")).hexdigest(),
        "world": world_identity,
        "controller": controller_identity,
        "player": player_identity,
        "_world_ref": world,
        "_controller_ref": controller,
        "_player_ref": player,
    }


def _public_runtime_binding(binding: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_identity": binding["session_identity"],
        "world": dict(binding["world"]),
        "controller": dict(binding["controller"]),
        "player": dict(binding["player"]),
    }


def _context_change_reason(binding: dict[str, Any], context: tuple[Any, Any, Any, Any]) -> Optional[str]:
    _unreal_value, world, controller, player = context
    if world is not binding["_world_ref"]:
        return "world_changed"
    if controller is not binding["_controller_ref"]:
        return "controller_changed"
    if player is not binding["_player_ref"]:
        return "possession_changed"
    get_pawn = getattr(controller, "get_pawn", None)
    try:
        possessed = get_pawn() if callable(get_pawn) else None
    except Exception:
        possessed = None
    if possessed is None:
        return "possession_lost"
    if possessed is not player:
        return "possession_changed"
    return None


def _observation_change_reason(binding: dict[str, Any], observation: dict[str, Any]) -> Optional[str]:
    if observation.get("world") != binding["world"]["name"]:
        return "world_changed"
    observed_binding = observation.get("runtime", {}).get("session")
    if not isinstance(observed_binding, dict):
        return "observation_identity_mismatch"
    if observed_binding.get("session_identity") != binding["session_identity"]:
        return "session_changed"
    for component in ("world", "controller", "player"):
        observed = observed_binding.get(component)
        if not isinstance(observed, dict) or observed.get("identity") != binding[component]["identity"]:
            return "observation_identity_mismatch"
    possessed = observation.get("runtime", {}).get("possessed")
    if not isinstance(possessed, dict) or possessed.get("identity") is None:
        return "possession_unconfirmed"
    if possessed.get("identity") != binding["player"]["identity"]:
        return "possession_changed"
    if not possessed.get("is_observed_player", False):
        return "possession_mismatch"
    return None


def _require_bound_context(binding: dict[str, Any], context: tuple[Any, Any, Any, Any]) -> None:
    reason = _context_change_reason(binding, context)
    if reason is not None:
        raise RuntimeError("The bound PIE session changed before input delivery: {}".format(reason))


def _vector(value: Any) -> dict[str, float]:
    return {"x": float(value.x), "y": float(value.y), "z": float(value.z)}


def _rotator(value: Any) -> dict[str, float]:
    return {"pitch": float(value.pitch), "yaw": float(value.yaw), "roll": float(value.roll)}


def _distance(left: Any, right: Any) -> float:
    delta = left - right
    return float(math.sqrt(float(delta.x) ** 2 + float(delta.y) ** 2 + float(delta.z) ** 2))


def _target_location(unreal: Any, value: Any):
    if not isinstance(value, dict) or any(axis not in value for axis in ("x", "y", "z")):
        raise ValueError("target_location must explicitly provide x, y, and z")
    try:
        coordinates = [float(value[axis]) for axis in ("x", "y", "z")]
    except (TypeError, ValueError) as exc:
        raise ValueError("target_location coordinates must be numbers") from exc
    if any(not math.isfinite(item) or abs(item) > 1_000_000.0 for item in coordinates):
        raise ValueError("target_location coordinates must be finite and within world bounds")
    return unreal.Vector(*coordinates)


def _actor_tags(actor: Any) -> list[str]:
    try:
        return [str(tag) for tag in actor.get_editor_property("tags")]
    except Exception:
        return []


def _actor_hidden(actor: Any) -> bool:
    method = getattr(actor, "is_hidden", None)
    if callable(method):
        try:
            return bool(method())
        except Exception:
            pass
    for property_name in ("bHidden", "hidden"):
        try:
            return bool(actor.get_editor_property(property_name))
        except Exception:
            continue
    return False


def _json_scalar(value: Any):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if hasattr(value, "x") and hasattr(value, "y") and hasattr(value, "z"):
        return _vector(value)
    if hasattr(value, "pitch") and hasattr(value, "yaw") and hasattr(value, "roll"):
        return _rotator(value)
    return None


def _attributes(actor: Any, names: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in names[:24]:
        if not name or not str(name).replace("_", "").isalnum():
            continue
        try:
            value = actor.get_editor_property(str(name))
        except Exception:
            continue
        encoded = _json_scalar(value)
        if encoded is not None:
            result[str(name)] = encoded
    return result


def _components(unreal: Any, actor: Any, attribute_names: list[str]) -> list[dict[str, Any]]:
    component_class = getattr(unreal, "ActorComponent", None)
    getter = getattr(actor, "get_components_by_class", None)
    if component_class is None or not callable(getter):
        return []
    try:
        components = list(getter(component_class))
    except Exception:
        return []
    return [
        {
            "name": _actor_name(component),
            "class": _class_name(component),
            "attributes": _attributes(component, attribute_names),
        }
        for component in components[:24]
        if component is not None
    ]


def _entity(
    unreal: Any,
    actor: Any,
    player_location: Any,
    attribute_names: list[str],
    telemetry_aliases: dict[str, list[str]],
    *,
    include_components: bool = False,
) -> dict[str, Any]:
    location = actor.get_actor_location()
    velocity = None
    velocity_getter = getattr(actor, "get_velocity", None)
    if callable(velocity_getter):
        try:
            velocity = _vector(velocity_getter())
        except Exception:
            velocity = None
    result = {
        "name": _actor_name(actor),
        "class": _class_name(actor),
        "hidden": _actor_hidden(actor),
        "location": _vector(location),
        "rotation": _rotator(actor.get_actor_rotation()),
        "velocity": velocity,
        "distance_to_player": _distance(location, player_location),
        "tags": _actor_tags(actor),
        "attributes": _attributes(actor, attribute_names),
        "telemetry": read_actor_telemetry(unreal, actor, telemetry_aliases),
    }
    if include_components:
        result["components"] = _components(unreal, actor, attribute_names)
    return result


def _line_of_sight(controller: Any, actor: Any):
    method = getattr(controller, "line_of_sight_to", None)
    if not callable(method):
        return None
    try:
        return bool(method(actor))
    except Exception:
        return None


def _line_of_fire(unreal: Any, controller: Any, player: Any, actor: Any):
    trace = getattr(getattr(unreal, "SystemLibrary", None), "line_trace_single", None)
    view_point = getattr(controller, "get_player_view_point", None)
    if not callable(trace) or not callable(view_point):
        return None
    try:
        start, _rotation = view_point()
        end = actor.get_actor_location()
        hit = trace(
            player,
            start,
            end,
            unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
            True,
            [player],
            unreal.DrawDebugTrace.NONE,
            True,
        )
        if hit is None:
            return True
        blocking = bool(hit.get_editor_property("blocking_hit"))
        hit_actor = hit.get_editor_property("hit_actor")
        return not blocking or hit_actor is actor or _actor_name(hit_actor) == _actor_name(actor)
    except Exception:
        return None


def _contains_any(value: str, needles: list[str]) -> bool:
    folded = value.casefold()
    return any(str(needle).casefold() in folded for needle in needles if needle)


def _matches(actor: Any, selectors: dict[str, Any], pawn_ids: set[int]) -> bool:
    if _actor_hidden(actor) and not selectors.get("include_hidden", False):
        return False
    class_name = _class_name(actor)
    if _contains_any(class_name, selectors.get("exclude_class_contains", [])):
        return False
    if selectors.get("include_pawns", True) and id(actor) in pawn_ids:
        return True
    actor_name = _actor_name(actor)
    if _contains_any(actor_name, selectors.get("name_contains", [])):
        return True
    if _contains_any(class_name, selectors.get("class_contains", [])):
        return True
    requested_tags = {str(item).casefold() for item in selectors.get("tags", []) if item}
    actor_tags = {item.casefold() for item in _actor_tags(actor)}
    return bool(requested_tags and requested_tags.intersection(actor_tags))


def _call_bool(value: Any, method_name: str):
    method = getattr(value, method_name, None)
    if not callable(method):
        return None
    try:
        return bool(method())
    except Exception:
        return None


def _runtime_state(
    unreal: Any,
    world: Any,
    controller: Any,
    player: Any,
    binding: dict[str, Any],
) -> dict[str, Any]:
    game_mode = None
    get_game_mode = getattr(unreal.GameplayStatics, "get_game_mode", None)
    if callable(get_game_mode):
        try:
            game_mode = get_game_mode(world)
        except Exception:
            game_mode = None

    default_pawn_class = ""
    if game_mode is not None:
        try:
            configured_pawn_class = game_mode.get_editor_property("default_pawn_class")
            get_name = getattr(configured_pawn_class, "get_name", None)
            default_pawn_class = str(get_name()) if callable(get_name) else str(configured_pawn_class or "")
        except Exception:
            default_pawn_class = ""

    player_start_count = None
    player_start_class = getattr(unreal, "PlayerStart", None)
    if player_start_class is not None:
        try:
            player_start_count = len(unreal.GameplayStatics.get_all_actors_of_class(world, player_start_class))
        except Exception:
            player_start_count = None

    possessed_pawn = None
    get_pawn = getattr(controller, "get_pawn", None)
    if callable(get_pawn):
        try:
            possessed_pawn = get_pawn()
        except Exception:
            possessed_pawn = None

    widgets = []
    widget_library = getattr(unreal, "WidgetBlueprintLibrary", None)
    user_widget_class = getattr(unreal, "UserWidget", None)
    get_widgets = getattr(widget_library, "get_all_widgets_of_class", None)
    if callable(get_widgets) and user_widget_class is not None:
        try:
            active_widgets = list(get_widgets(world, user_widget_class, False))
        except Exception:
            active_widgets = []
        for widget in active_widgets[:32]:
            if widget is None:
                continue
            visibility = None
            get_visibility = getattr(widget, "get_visibility", None)
            if callable(get_visibility):
                try:
                    visibility = str(get_visibility())
                except Exception:
                    visibility = None
            widgets.append(
                {
                    "name": _actor_name(widget),
                    "class": _class_name(widget),
                    "visibility": visibility,
                    "in_viewport": _call_bool(widget, "is_in_viewport"),
                    "enabled": _call_bool(widget, "get_is_enabled"),
                }
            )
        widgets.sort(key=lambda item: (item["class"], item["name"]))

    player_class = _class_name(player)
    return {
        "session": _public_runtime_binding(binding),
        "game_mode_class": _class_name(game_mode),
        "default_pawn_class": default_pawn_class,
        "player_start_count": player_start_count,
        "controller_class": _class_name(controller),
        "pawn_class": player_class,
        "possessed": _actor_identity(possessed_pawn, player) if possessed_pawn is not None else None,
        "spectating": "spectator" in player_class.casefold(),
        "active_widget_count": len(widgets),
        "active_widgets": widgets,
    }


def _observation_hash(observation: dict[str, Any]) -> str:
    payload = json.dumps(observation, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def observe(selectors: dict[str, Any]) -> dict[str, Any]:
    unreal, world, controller, player = _pie_context()
    binding = _runtime_binding((unreal, world, controller, player))
    player_location = player.get_actor_location()
    pawns = list(unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Pawn))
    pawn_ids = {id(item) for item in pawns if item is not player}
    candidates = list(pawns)
    if selectors.get("class_contains") or selectors.get("name_contains") or selectors.get("tags"):
        candidates.extend(unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor))

    unique: dict[str, Any] = {}
    for actor in candidates:
        if actor is None or actor is player or not _matches(actor, selectors, pawn_ids):
            continue
        unique.setdefault(_actor_name(actor), actor)

    max_distance = float(selectors.get("max_distance", 0) or 0)
    attribute_names = list(selectors.get("attribute_names", []))[:24]
    telemetry_aliases = normalize_telemetry_aliases(selectors.get("telemetry_aliases"))
    include_components = bool(selectors.get("include_components", False))
    entities = []
    for actor in unique.values():
        item = _entity(
            unreal,
            actor,
            player_location,
            attribute_names,
            telemetry_aliases,
            include_components=include_components,
        )
        item["line_of_sight"] = _line_of_sight(controller, actor)
        item["line_of_fire"] = _line_of_fire(unreal, controller, player, actor)
        entities.append(item)
    if max_distance > 0:
        entities = [item for item in entities if item["distance_to_player"] <= max_distance]
    entities.sort(key=lambda item: (item["distance_to_player"], item["name"]))
    entities = entities[: int(selectors.get("max_entities", 64))]

    player_state = _entity(
        unreal,
        player,
        player_location,
        attribute_names,
        telemetry_aliases,
        include_components=include_components,
    )
    rotation_getter = getattr(controller, "get_control_rotation", None)
    if callable(rotation_getter):
        player_state["control_rotation"] = _rotator(rotation_getter())

    action_availability = build_action_availability(player_state["telemetry"])

    observation = {
        "schema": "dcc-mcp-playtest-observation-v1",
        "world": str(world.get_name()),
        "time_seconds": float(unreal.GameplayStatics.get_time_seconds(world)),
        "runtime": _runtime_state(unreal, world, controller, player, binding),
        "player": player_state,
        "action_availability": action_availability,
        "entity_count": len(entities),
        "entity_classes": dict(sorted(Counter(item["class"] for item in entities).items())),
        "entities": entities,
    }
    observation["observation_hash"] = _observation_hash(observation)
    return observation


def _selector_config(**kwargs) -> dict[str, Any]:
    project_telemetry_aliases = kwargs.get("telemetry_aliases")
    normalize_telemetry_aliases(project_telemetry_aliases)
    project_telemetry_aliases = {
        str(key): [str(name) for name in names] for key, names in (project_telemetry_aliases or {}).items()
    }
    return {
        "include_pawns": bool(kwargs.get("include_pawns", True)),
        "include_hidden": bool(kwargs.get("include_hidden", False)),
        "include_components": bool(kwargs.get("include_components", False)),
        "class_contains": [str(item) for item in kwargs.get("class_contains", [])][:16],
        "exclude_class_contains": [str(item) for item in kwargs.get("exclude_class_contains", [])][:16],
        "name_contains": [str(item) for item in kwargs.get("name_contains", [])][:16],
        "tags": [str(item) for item in kwargs.get("tags", [])][:16],
        "attribute_names": [str(item) for item in kwargs.get("attribute_names", [])][:24],
        "telemetry_aliases": project_telemetry_aliases,
        "max_entities": max(1, min(int(kwargs.get("max_entities", 64)), 128)),
        "max_distance": max(0.0, min(float(kwargs.get("max_distance", 0)), 1_000_000.0)),
    }


def start_episode(**kwargs) -> dict[str, Any]:
    selectors = _selector_config(**kwargs)
    context = _pie_context()
    binding = _runtime_binding(context)
    baseline = observe(selectors)
    _require_bound_context(binding, _pie_context())
    observation_reason = _observation_change_reason(binding, baseline)
    if observation_reason is not None:
        raise RuntimeError("The initial PIE observation did not match the bound session: {}".format(observation_reason))
    episode_id = "pie_episode_{}_{}".format(time.strftime("%Y%m%d_%H%M%S"), uuid.uuid4().hex[:8])
    _EPISODES[episode_id] = {
        "episode_id": episode_id,
        "started_at": time.time(),
        "selectors": selectors,
        "baseline_hash": baseline["observation_hash"],
        "runtime_binding": binding,
        "actions": {},
        "trace": [],
    }
    return {
        "episode_id": episode_id,
        "session": _public_runtime_binding(binding),
        "selectors": selectors,
        "observation": baseline,
    }


def get_episode(episode_id: str) -> dict[str, Any]:
    episode = _EPISODES.get(str(episode_id))
    if episode is None:
        raise KeyError("Unknown playtest episode_id: {}".format(episode_id))
    return episode


def observe_episode(episode: dict[str, Any]) -> dict[str, Any]:
    binding = episode["runtime_binding"]
    _require_bound_context(binding, _pie_context())
    observation = observe(episode["selectors"])
    _require_bound_context(binding, _pie_context())
    reason = _observation_change_reason(binding, observation)
    if reason is not None:
        raise RuntimeError("The PIE observation did not match the bound episode: {}".format(reason))
    return observation


def episode_summary(episode: dict[str, Any], include_trace: bool = False) -> dict[str, Any]:
    result = {
        "episode_id": episode["episode_id"],
        "session": _public_runtime_binding(episode["runtime_binding"]),
        "started_at": episode["started_at"],
        "elapsed_seconds": max(0.0, time.time() - episode["started_at"]),
        "selectors": episode["selectors"],
        "baseline_hash": episode["baseline_hash"],
        "action_count": len(episode["actions"]),
        "transition_count": len(episode["trace"]),
        "pending_action_ids": [
            item["action_id"] for item in episode["actions"].values() if item["status"] == "pending"
        ],
    }
    if include_trace:
        result["trace"] = list(episode["trace"])
    return result


def finish_episode(episode_id: str) -> dict[str, Any]:
    episode = get_episode(episode_id)
    after = None
    for action in episode["actions"].values():
        if action["status"] == "pending":
            _release_action_input(action)
            if action["action"] in _NAVIGATION_ACTIONS:
                action["_navigation_cleanup_errors"] = _stop_navigation(binding=episode["runtime_binding"])
    try:
        unreal, _world, _controller, _player = _pie_context()
        after = observe_episode(episode)
    except BaseException:
        pass
    for action in episode["actions"].values():
        if action["status"] == "pending":
            if after is not None:
                _finalize(
                    episode,
                    action,
                    "cancelled",
                    after,
                    cleanup_navigation=False,
                    reason="episode_finished",
                )
            else:
                action["status"] = "cancelled"
                transition = {
                    "action_id": action["action_id"],
                    "action": action["action"],
                    "status": "cancelled",
                    "reason": "episode_finished_after_observation_loss",
                    "elapsed_seconds": max(0.0, time.time() - action["started_at"]),
                    "target": action["target"],
                    "before_hash": action["before"]["observation_hash"],
                    "after_hash": None,
                    "player_location_delta": None,
                    "player_displacement": None,
                    "movement_expected": action["movement_expected"],
                    "min_displacement": action["min_displacement"],
                    "entity_count_delta": None,
                    "telemetry_deltas": [],
                    **_action_contract_fields(action),
                    "before": action["before"],
                    "after": None,
                }
                action["transition"] = transition
                cleanup_errors = _release_action_input(action) + action.get("_navigation_cleanup_errors", [])
                if cleanup_errors:
                    transition["cleanup_errors"] = cleanup_errors
                release = action.get("_release_input")
                if release is not None:
                    transition["input_cleanup"] = dict(release.state)
                episode["trace"].append(transition)
    result = episode_summary(episode, include_trace=True)
    _EPISODES.pop(episode_id, None)
    return result


def _resolve_target(world: Any, player: Any, selector: dict[str, Any]):
    unreal = _unreal()
    requested_tags = {str(item).casefold() for item in selector.get("target_tags", []) if item}
    exact = str(selector.get("target_name", "")).casefold()
    name_contains = str(selector.get("target_name_contains", "")).casefold()
    class_contains = str(selector.get("target_class_contains", "")).casefold()
    exclude_class_contains = [str(item) for item in selector.get("target_exclude_class_contains", [])][:16]
    include_hidden = bool(selector.get("target_include_hidden", False))
    matches = []
    player_location = player.get_actor_location()
    for actor in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
        if actor is None or actor is player:
            continue
        name = _actor_name(actor)
        class_name = _class_name(actor)
        tags = {item.casefold() for item in _actor_tags(actor)}
        if _actor_hidden(actor) and not include_hidden:
            continue
        if _contains_any(class_name, exclude_class_contains):
            continue
        if exact and name.casefold() != exact:
            continue
        if name_contains and name_contains not in name.casefold():
            continue
        if class_contains and class_contains not in class_name.casefold():
            continue
        if requested_tags and not requested_tags.intersection(tags):
            continue
        matches.append((_distance(actor.get_actor_location(), player_location), name, actor))
    if not matches:
        return None
    matches.sort(key=lambda item: (item[0], item[1]))
    return matches[0][2]


class _OwnedKey:
    """One native receiver/key lease; cleanup never replaces the primary result."""

    def __init__(self, unreal: Any, key: str, binding: dict[str, Any]):
        bridge = getattr(unreal, "DccMcpAutomationLibrary", None)
        acquire = getattr(bridge, "acquire_pie_key", None)
        self.press = getattr(bridge, "press_owned_pie_key", None)
        self.release = getattr(bridge, "release_owned_pie_key", None)
        if not all(callable(fn) for fn in (acquire, self.press, self.release)):
            raise RuntimeError("Native owned PIE input is unavailable; update the plugin")
        _require_bound_context(binding, _pie_context())
        self.owner = acquire(binding["_world_ref"], binding["_controller_ref"], key)
        if not self.owner:
            raise RuntimeError("The native PIE input receiver could not be acquired")
        self.register = getattr(unreal, "register_slate_post_tick_callback", None)
        self.unregister = getattr(unreal, "unregister_slate_post_tick_callback", None)
        self.handle = None
        self.errors: list[str] = []
        self.state = {
            "release_attempted": False,
            "release_completed": False,
            "retirement_attempted": False,
            "retirement_completed": False,
        }
        binding.setdefault("_input_owners", []).append(self)

    def __call__(self) -> list[str]:
        try:
            if not self.state["release_attempted"]:
                # Mark before delivery: a cancelled bridge call may already have delivered.
                self.state["release_attempted"] = True
                try:
                    self.state["release_completed"] = bool(self.release(self.owner))
                    if not self.state["release_completed"]:
                        self.errors.append("The owned PIE input receiver could not release its key")
                except BaseException as exc:
                    self.errors.append(str(exc))
        finally:
            if self.handle is not None and not self.state["retirement_completed"]:
                self.state["retirement_attempted"] = True
                try:
                    self.unregister(self.handle)
                    self.state["retirement_completed"] = True
                except BaseException as exc:
                    message = str(exc)
                    if message not in self.errors:
                        self.errors.append(message)
        return list(self.errors)

    def start(self, duration: Optional[float], binding: dict[str, Any]) -> None:
        try:
            _require_bound_context(binding, _pie_context())
            if not self.press(self.owner):
                raise RuntimeError("The native PIE input bridge could not press its owned key")
            if duration == 0:
                errors = self()
                if errors:
                    raise RuntimeError("; ".join(errors))
                return
            if not callable(self.register) or not callable(self.unregister):
                raise RuntimeError("Slate tick callbacks are unavailable for bounded PIE input")
            release_at = time.monotonic() + duration if duration is not None else None

            def on_tick(_delta_seconds: float = 0.0) -> None:
                if self.state["release_attempted"]:
                    self()  # A failed unregister is retriable; key-up is not.
                    return
                try:
                    _require_bound_context(binding, _pie_context())
                    if release_at is None or time.monotonic() < release_at:
                        return
                except BaseException:
                    pass
                self()

            self.handle = self.register(on_tick)
            if self.handle is None:
                raise RuntimeError("Slate callback registration returned no retirement handle")
            if self.state["release_attempted"]:
                self()
        except BaseException:
            self()
            raise


def _tap_key(unreal: Any, key: str, duration: Optional[float], *, binding: dict[str, Any]) -> _OwnedKey:
    owned = _OwnedKey(unreal, key, binding)
    owned.start(duration, binding)
    return owned


def _release_action_input(action: dict[str, Any]) -> list[str]:
    release = action.get("_release_input")
    if callable(release):
        return release()
    return []


def _stop_navigation(
    unreal: Any = None,
    *,
    binding: Optional[dict[str, Any]] = None,
) -> list[str]:
    try:
        bridge = getattr(unreal if unreal is not None else _unreal(), "DccMcpAutomationLibrary", None)
        stop = getattr(bridge, "stop_owned_pie_navigation", None)
        if (
            binding is None
            or not callable(stop)
            or not stop(binding["_world_ref"], binding["_controller_ref"], binding["_player_ref"])
        ):
            return ["The owned PIE navigation receiver could not stop movement"]
    except BaseException as exc:
        return [str(exc)]
    return []


def _face_location(
    unreal: Any, controller: Any, player: Any, target_location: Any, *, include_pitch: bool = True
) -> None:
    start = player.get_actor_location()
    view_point = getattr(controller, "get_player_view_point", None)
    if callable(view_point):
        try:
            start, _rotation = view_point()
        except Exception:
            pass
    delta = target_location - start
    yaw = math.degrees(math.atan2(float(delta.y), float(delta.x)))
    horizontal = math.sqrt(float(delta.x) ** 2 + float(delta.y) ** 2)
    pitch = math.degrees(math.atan2(float(delta.z), horizontal)) if include_pitch else 0.0
    controller.set_control_rotation(unreal.Rotator(roll=0.0, pitch=pitch, yaw=yaw))


def _target_aim_location(target: Any) -> Any:
    get_bounds = getattr(target, "get_actor_bounds", None)
    if callable(get_bounds):
        for arguments in ((False, True), (False, False), ()):
            try:
                origin, extent = get_bounds(*arguments)
            except Exception:
                continue
            values = (
                float(origin.x),
                float(origin.y),
                float(origin.z),
                float(extent.x),
                float(extent.y),
                float(extent.z),
            )
            if all(math.isfinite(value) for value in values) and any(value > 0.0 for value in values[3:]):
                return origin
    return target.get_actor_location()


def _face_target(unreal: Any, controller: Any, player: Any, target: Any, *, include_pitch: bool = True) -> None:
    _face_location(
        unreal,
        controller,
        player,
        _target_aim_location(target),
        include_pitch=include_pitch,
    )


def _start_input_steering(
    unreal: Any,
    controller: Any,
    player: Any,
    target: Any,
    *,
    action: dict[str, Any],
    binding: Optional[dict[str, Any]] = None,
) -> str:
    return _start_input_steering_to_location(
        unreal,
        controller,
        player,
        _target_aim_location(target),
        action=action,
        binding=binding,
    )


def _start_input_steering_to_location(
    unreal: Any,
    controller: Any,
    player: Any,
    target_location: Any,
    *,
    action: dict[str, Any],
    binding: Optional[dict[str, Any]] = None,
) -> str:
    bridge = getattr(unreal, "DccMcpAutomationLibrary", None)
    start = getattr(bridge, "start_pie_input_steering_to_location", None) if bridge is not None else None
    if callable(start) and start(target_location):
        return "native_pawn_movement"
    _face_location(unreal, controller, player, target_location, include_pitch=False)
    action["_release_input"] = _tap_key(
        unreal, "W", max(0.0, action["timeout_seconds"] - (time.time() - action["started_at"])), binding=binding
    )
    return "legacy_key"


def _relative_direction(direction: str, control_yaw_degrees: float) -> dict[str, float]:
    yaw = math.radians(float(control_yaw_degrees))
    forward = (math.cos(yaw), math.sin(yaw))
    right = (-math.sin(yaw), math.cos(yaw))
    vectors = {
        "forward": forward,
        "backward": (-forward[0], -forward[1]),
        "right": right,
        "left": (-right[0], -right[1]),
    }
    x, y = vectors[direction]
    return {"x": float(x), "y": float(y), "z": 0.0}


def _relative_movement_evidence(action: dict[str, Any], after: dict[str, Any], elapsed: float) -> dict[str, Any]:
    delta = _location_delta(action["before"], after)
    displacement = _player_displacement(action["before"], after)
    expected = action["expected_direction"]
    horizontal = math.sqrt(float(delta["x"]) ** 2 + float(delta["y"]) ** 2)
    projection = float(delta["x"]) * float(expected["x"]) + float(delta["y"]) * float(expected["y"])
    alignment = projection / horizontal if horizontal > 0.0 else 0.0
    evidence = {
        "causal_displacement": max(0.0, projection),
        "direction_alignment": float(alignment),
        "expected_direction": dict(expected),
        "max_causal_displacement": action["max_causal_displacement"],
        "movement_proof_window": action["movement_proof_window"],
    }
    if displacement > action["max_causal_displacement"]:
        evidence["causal_reason"] = "movement_exceeds_causal_bound"
    elif displacement >= action["min_displacement"] and (
        alignment < _RELATIVE_DIRECTION_MIN_ALIGNMENT or projection < action["min_displacement"]
    ):
        evidence["causal_reason"] = "movement_direction_mismatch"
    elif displacement >= action["min_displacement"] and elapsed > action["movement_proof_window"]:
        evidence["causal_reason"] = "movement_proof_window_expired"
    elif projection >= action["min_displacement"]:
        evidence["causal_reason"] = None
    else:
        evidence["causal_reason"] = "movement_below_threshold"
    return evidence


def execute_action(episode_id: str, action_name: str, **kwargs) -> dict[str, Any]:
    binding = get_episode(episode_id)["runtime_binding"]
    owners = binding.setdefault("_input_owners", [])
    previous = len(owners)
    try:
        return _execute_action(episode_id, action_name, **kwargs)
    except BaseException:
        for owner in owners[previous:]:
            owner()
        raise


def _execute_action(episode_id: str, action_name: str, **kwargs) -> dict[str, Any]:
    episode = get_episode(episode_id)
    binding = episode["runtime_binding"]
    context = _pie_context()
    _require_bound_context(binding, context)
    unreal, world, controller, player = context
    action_name = str(action_name)
    before = observe(episode["selectors"])
    observation_reason = _observation_change_reason(binding, before)
    if observation_reason is not None:
        raise RuntimeError(
            "The pre-input observation did not match the bound PIE session: {}".format(observation_reason)
        )
    if "expect_movement" in kwargs and not isinstance(kwargs["expect_movement"], bool):
        raise ValueError("expect_movement must be a boolean")
    movement_expected = action_name == "move_relative" if "expect_movement" not in kwargs else kwargs["expect_movement"]
    if ("expect_movement" in kwargs or "min_displacement" in kwargs) and action_name not in _MOVEMENT_ACTIONS:
        raise ValueError("expect_movement and min_displacement are only valid for movement actions")
    try:
        min_displacement = float(kwargs.get("min_displacement", 1.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("min_displacement must be a finite number") from exc
    if not math.isfinite(min_displacement) or not 0.001 <= min_displacement <= 1_000_000.0:
        raise ValueError("min_displacement must be between 0.001 and 1000000")
    try:
        duration = float(kwargs.get("duration", 0.05))
    except (TypeError, ValueError) as exc:
        raise ValueError("duration must be a finite number of seconds") from exc
    if not math.isfinite(duration) or not 0.0 <= duration <= 5.0:
        raise ValueError("duration must be between 0 and 5 seconds")
    if action_name in _MOVEMENT_ACTIONS:
        possessed = before["runtime"].get("possessed")
        if not possessed or not possessed.get("is_observed_player", False):
            raise RuntimeError("The PIE controller has no confirmed possession of the observed player pawn")
    target = None
    location_target = None
    selector = {
        "target_name": kwargs.get("target_name", ""),
        "target_name_contains": kwargs.get("target_name_contains", ""),
        "target_class_contains": kwargs.get("target_class_contains", ""),
        "target_exclude_class_contains": kwargs.get("target_exclude_class_contains", []),
        "target_include_hidden": kwargs.get("target_include_hidden", False),
        "target_tags": kwargs.get("target_tags", []),
    }
    if action_name in _TARGET_ACTIONS:
        if not any(
            (
                selector["target_name"],
                selector["target_name_contains"],
                selector["target_class_contains"],
                selector["target_tags"],
            )
        ):
            raise ValueError("A bounded target selector is required for {}".format(action_name))
        target = _resolve_target(world, player, selector)
        if target is None:
            raise RuntimeError("No PIE entity matched the bounded target selector")
        if _actor_identity(target, player)["identity"] is None:
            raise RuntimeError("The matched PIE target has no trustworthy exact object path")
    elif action_name in {"navigate_to_location", "face_location"}:
        location_target = _target_location(unreal, kwargs.get("target_location"))

    _require_bound_context(binding, _pie_context())
    if target is not None:
        delivery_target = _resolve_target(world, player, selector)
        if delivery_target is not target:
            raise RuntimeError("The exact PIE target changed before input delivery")

    release_input = None
    if action_name == "ensure_player_control":
        runtime_state = before["runtime"]
        if not runtime_state["spectating"]:
            raise RuntimeError("The PIE controller already owns a playable pawn")
        default_pawn_class = str(runtime_state.get("default_pawn_class", ""))
        if not default_pawn_class or "spectator" in default_pawn_class.casefold():
            raise RuntimeError("The active GameMode does not define a non-spectator default pawn")
        game_mode = unreal.GameplayStatics.get_game_mode(world)
        restart_player = getattr(game_mode, "restart_player", None) if game_mode is not None else None
        if not callable(restart_player):
            raise RuntimeError("The active GameMode cannot restart the PIE player")
        restart_player(controller)
    elif action_name == "navigate_to_entity":
        navigation = getattr(unreal, "AIBlueprintHelperLibrary", None)
        navigate = getattr(navigation, "simple_move_to_actor", None) if navigation is not None else None
        if not callable(navigate):
            raise RuntimeError("Exact-object PIE navigation is unavailable")
        navigate(controller, target)
    elif action_name == "navigate_to_location":
        bridge = getattr(unreal, "DccMcpAutomationLibrary", None)
        navigate = getattr(bridge, "navigate_pie_to_location", None) if bridge is not None else None
        if not callable(navigate) or not navigate(location_target):
            raise RuntimeError("The native PIE navigation bridge could not start location navigation")
    elif action_name == "face_entity":
        _face_target(unreal, controller, player, target)
    elif action_name == "face_location":
        _face_location(unreal, controller, player, location_target)
    elif action_name == "attack_primary_entity":
        visibility = _line_of_fire(unreal, controller, player, target)
        if visibility is None:
            visibility = _line_of_sight(controller, target)
        if kwargs.get("require_line_of_sight", True) and visibility is False:
            raise RuntimeError("The target is occluded from the PIE player")
        _face_target(unreal, controller, player, target)
        release_input = _tap_key(unreal, _ACTION_KEYS["attack_primary"], duration, binding=binding)
    elif action_name == "attack_secondary_entity":
        visibility = _line_of_fire(unreal, controller, player, target)
        if visibility is None:
            visibility = _line_of_sight(controller, target)
        if kwargs.get("require_line_of_sight", True) and visibility is False:
            raise RuntimeError("The target is occluded from the PIE player")
        _face_target(unreal, controller, player, target)
        release_input = _tap_key(unreal, _ACTION_KEYS["attack_secondary"], duration, binding=binding)
    elif action_name in {"melee_entity", "explosive_entity", "skill_entity"}:
        _face_target(unreal, controller, player, target)
        semantic_action = action_name.removesuffix("_entity")
        release_input = _tap_key(unreal, _ACTION_KEYS[semantic_action], duration, binding=binding)
    elif action_name == "stop_navigation":
        cleanup_errors = _stop_navigation(unreal, binding=binding)
        if cleanup_errors:
            raise RuntimeError("; ".join(cleanup_errors))
    elif action_name == "move_relative":
        direction = str(kwargs.get("direction", "")).casefold()
        key = _MOVE_KEYS.get(direction)
        if key is None:
            raise ValueError("move_relative direction must be one of: {}".format(", ".join(_MOVE_KEYS)))
        release_input = _tap_key(unreal, key, duration, binding=binding)
    elif action_name in _ACTION_KEYS:
        release_input = _tap_key(unreal, _ACTION_KEYS[action_name], duration, binding=binding)
    elif action_name == "wait":
        pass
    else:
        raise ValueError("Unsupported semantic playtest action: {}".format(action_name))

    now = time.time()
    target_summary = None
    target_distance = None
    if target is not None:
        target_distance = _distance(target.get_actor_location(), player.get_actor_location())
        target_summary = {
            "name": _actor_name(target),
            "class": _class_name(target),
            **_redacted_object_identity(target),
            "location": _vector(target.get_actor_location()),
            "distance_to_player": target_distance,
        }
    elif location_target is not None:
        target_distance = _distance(location_target, player.get_actor_location())
        target_summary = {
            "name": "world_waypoint",
            "class": "Waypoint",
            "location": _vector(location_target),
            "distance_to_player": target_distance,
        }
    action_id = "pie_action_{}".format(uuid.uuid4().hex[:10])
    direction = str(kwargs.get("direction", "")).casefold() if action_name == "move_relative" else None
    control_yaw = float(before["player"].get("control_rotation", {}).get("yaw", 0.0))
    expected_direction = _relative_direction(direction, control_yaw) if direction is not None else None
    stall_seconds = max(0.5, min(float(kwargs.get("stall_seconds", 4)), 30.0))
    record = {
        "action_id": action_id,
        "action": action_name,
        "status": "pending",
        "started_at": now,
        "timeout_seconds": max(0.1, min(float(kwargs.get("timeout_seconds", 30)), 120.0)),
        "stall_seconds": stall_seconds,
        "acceptance_radius": max(10.0, min(float(kwargs.get("acceptance_radius", 125)), 10000.0)),
        "wait_duration": duration,
        "duration": duration,
        "direction": direction,
        "expected_direction": expected_direction,
        "max_causal_displacement": (
            _RELATIVE_MOVEMENT_BASE_SLACK_CM + _RELATIVE_MOVEMENT_MAX_SPEED_CM_PER_SECOND * duration
            if action_name == "move_relative"
            else None
        ),
        "movement_proof_window": duration + max(0.5, min(stall_seconds, 1.0)),
        "target": target_summary,
        "target_selector": dict(selector) if target is not None else None,
        "_target_ref": target,
        "last_distance": target_distance,
        "last_progress_at": now,
        "navigation_driver": "native_pathfinding" if action_name in _NAVIGATION_ACTIONS else None,
        "native_grace_seconds": min(
            1.0,
            max(0.25, max(0.5, min(float(kwargs.get("stall_seconds", 4)), 30.0)) * 0.25),
        ),
        "steering_fallback_started_at": None,
        "steering_backend": None,
        "movement_expected": movement_expected,
        "min_displacement": min_displacement,
        "before": before,
        "session_identity": binding["session_identity"],
        "_release_input": release_input,
        "transition": None,
    }
    episode["actions"][action_id] = record
    return {
        "episode_id": episode_id,
        "action_id": action_id,
        "status": "pending",
        "action": action_name,
        "navigation_driver": record["navigation_driver"],
        "target": target_summary,
        "before_hash": before["observation_hash"],
        "movement_expected": movement_expected,
        "min_displacement": min_displacement,
        "session_identity": binding["session_identity"],
        "distance_unit": _DISTANCE_UNIT,
        "duration": duration,
        "duration_unit": _DURATION_UNIT,
        **({"direction": direction} if direction is not None else {}),
    }


def _location_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, float]:
    left = before["player"]["location"]
    right = after["player"]["location"]
    return {axis: float(right[axis]) - float(left[axis]) for axis in ("x", "y", "z")}


def _player_displacement(before: dict[str, Any], after: dict[str, Any]) -> float:
    delta = _location_delta(before, after)
    return float(math.sqrt(sum(float(delta[axis]) ** 2 for axis in ("x", "y", "z"))))


def _action_contract_fields(action: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "session_identity": action["session_identity"],
        "distance_unit": _DISTANCE_UNIT,
        "duration": action["duration"],
        "duration_unit": _DURATION_UNIT,
    }
    if action.get("direction") is not None:
        fields["direction"] = action["direction"]
        fields["expected_direction"] = dict(action["expected_direction"])
        fields["max_causal_displacement"] = action["max_causal_displacement"]
        fields["movement_proof_window"] = action["movement_proof_window"]
    return fields


def _finalize(
    episode: dict[str, Any],
    action: dict[str, Any],
    status: str,
    after: dict[str, Any],
    *,
    cleanup_navigation: bool = True,
    observation_trusted: bool = True,
    **extra,
):
    cleanup_errors = _release_action_input(action)
    if action["action"] in _NAVIGATION_ACTIONS:
        extra.setdefault("navigation_driver", action["navigation_driver"])
        extra.setdefault("steering_fallback_used", action["steering_fallback_started_at"] is not None)
        extra.setdefault("steering_backend", action["steering_backend"])
        if cleanup_navigation or "_navigation_cleanup_errors" not in action:
            cleanup_errors.extend(
                _stop_navigation(
                    binding=episode["runtime_binding"],
                )
            )
        else:
            cleanup_errors.extend(action["_navigation_cleanup_errors"])
    if cleanup_errors:
        extra["cleanup_errors"] = cleanup_errors
    release = action.get("_release_input")
    if release is not None:
        extra["input_cleanup"] = dict(release.state)
    if cleanup_errors and status == "completed":
        status = "blocked"
        extra["reason"] = "input_cleanup_failed"
    if "blocked_reason" in extra:
        extra.setdefault("reason", extra["blocked_reason"])
    action["status"] = status
    observed_deltas = telemetry_deltas(action["before"], after) if observation_trusted else []
    if observation_trusted and action["action"] in COMBAT_ACTIONS:
        extra.update(combat_feedback(action, after, observed_deltas))
    player_location_delta = _location_delta(action["before"], after) if observation_trusted else None
    transition = {
        "action_id": action["action_id"],
        "action": action["action"],
        "status": status,
        "elapsed_seconds": max(0.0, time.time() - action["started_at"]),
        "target": action["target"],
        "before_hash": action["before"]["observation_hash"],
        "after_hash": after["observation_hash"],
        "player_location_delta": player_location_delta,
        "player_displacement": _player_displacement(action["before"], after) if observation_trusted else None,
        "movement_expected": action["movement_expected"],
        "min_displacement": action["min_displacement"],
        **_action_contract_fields(action),
        "entity_count_delta": (
            int(after["entity_count"]) - int(action["before"]["entity_count"]) if observation_trusted else None
        ),
        "telemetry_deltas": observed_deltas,
        "before": action["before"],
        "after": after,
        **extra,
    }
    action["transition"] = transition
    episode["trace"].append(transition)
    return transition


def _possession_change_reason(action: dict[str, Any], after: dict[str, Any]):
    if action["action"] not in _MOVEMENT_ACTIONS:
        return None
    before_possessed = action["before"]["runtime"].get("possessed")
    after_possessed = after["runtime"].get("possessed")
    if before_possessed is not None and after_possessed is None:
        return "possession_lost"
    if before_possessed is None or after_possessed is None:
        return "possession_unconfirmed"
    if before_possessed.get("identity") != after_possessed.get("identity"):
        return "possession_changed"
    if not after_possessed.get("is_observed_player", False):
        return "possession_mismatch"
    return None


def poll_action(episode_id: str, action_id: str) -> dict[str, Any]:
    episode = get_episode(episode_id)
    try:
        return _poll_action(episode_id, action_id)
    except BaseException:
        # Observation, context loss and cancellation all retire delivered input.
        action = episode["actions"].get(str(action_id))
        if action is not None:
            _release_action_input(action)
        raise


def _poll_action(episode_id: str, action_id: str) -> dict[str, Any]:
    episode = get_episode(episode_id)
    action = episode["actions"].get(str(action_id))
    if action is None:
        raise KeyError("Unknown playtest action_id: {}".format(action_id))
    if action["transition"] is not None:
        return action["transition"]

    context = _pie_context()
    unreal, world, controller, player = context
    context_reason = _context_change_reason(episode["runtime_binding"], context)
    after = observe(episode["selectors"])
    elapsed = max(0.0, time.time() - action["started_at"])
    observation_reason = _observation_change_reason(episode["runtime_binding"], after)
    identity_reason = context_reason or observation_reason
    if identity_reason is not None:
        return _finalize(
            episode,
            action,
            "blocked",
            after,
            reason=identity_reason,
            cleanup_navigation=False,
            observation_trusted=False,
        )
    possession_reason = _possession_change_reason(action, after)
    if possession_reason is not None:
        return _finalize(episode, action, "blocked", after, reason=possession_reason)
    if elapsed >= action["timeout_seconds"]:
        return _finalize(episode, action, "timed_out", after)

    if action["action"] in _NAVIGATION_ACTIONS:
        target = None
        if action["action"] == "navigate_to_entity":
            target = _resolve_target(world, player, action["target_selector"])
            if target is None:
                return _finalize(episode, action, "blocked", after, blocked_reason="target_unavailable")
            target_identity = _actor_identity(target, player)
            if target is not action["_target_ref"] or target_identity["identity"] != action["target"]["identity"]:
                return _finalize(episode, action, "blocked", after, reason="target_changed")
            target_location = target.get_actor_location()
        else:
            target_location = _target_location(unreal, action["target"]["location"])
        distance = _distance(target_location, player.get_actor_location())
        if distance <= action["acceptance_radius"]:
            displacement = _player_displacement(action["before"], after)
            if action["movement_expected"] and displacement < action["min_displacement"]:
                if elapsed >= action["stall_seconds"]:
                    return _finalize(
                        episode,
                        action,
                        "stalled",
                        after,
                        reason="movement_below_threshold",
                        distance_to_target=distance,
                    )
                return {
                    "action_id": action_id,
                    "action": action["action"],
                    "status": "pending",
                    "elapsed_seconds": elapsed,
                    "distance_to_target": distance,
                    "player_displacement": displacement,
                    "movement_expected": True,
                    "min_displacement": action["min_displacement"],
                    **_action_contract_fields(action),
                    "observation": after,
                }
            return _finalize(episode, action, "completed", after, distance_to_target=distance)
        now = time.time()
        if action["last_distance"] is None or distance < float(action["last_distance"]) - 5.0:
            action["last_distance"] = distance
            action["last_progress_at"] = now
        elif (
            action["navigation_driver"] == "native_pathfinding"
            and now - float(action["started_at"]) >= action["native_grace_seconds"]
        ):
            action["steering_backend"] = (
                _start_input_steering(
                    unreal,
                    controller,
                    player,
                    target,
                    action=action,
                    binding=episode["runtime_binding"],
                )
                if target is not None
                else _start_input_steering_to_location(
                    unreal,
                    controller,
                    player,
                    target_location,
                    action=action,
                    binding=episode["runtime_binding"],
                )
            )
            action["navigation_driver"] = "input_steering"
            action["steering_fallback_started_at"] = now
            action["last_progress_at"] = now
        elif now - float(action["last_progress_at"]) >= action["stall_seconds"]:
            return _finalize(
                episode,
                action,
                "blocked",
                after,
                blocked_reason="navigation_stalled",
                distance_to_target=distance,
            )
        if action["navigation_driver"] == "input_steering":
            if target is not None:
                _face_target(unreal, controller, player, target, include_pitch=False)
            else:
                _face_location(unreal, controller, player, target_location, include_pitch=False)
        return {
            "action_id": action_id,
            "action": action["action"],
            "status": "pending",
            "elapsed_seconds": elapsed,
            "distance_to_target": distance,
            "navigation_driver": action["navigation_driver"],
            "steering_fallback_used": action["steering_fallback_started_at"] is not None,
            "steering_backend": action["steering_backend"],
            "movement_expected": action["movement_expected"],
            "min_displacement": action["min_displacement"],
            **_action_contract_fields(action),
            "observation": after,
        }

    completion_delay = action["wait_duration"] if action["action"] == "wait" else max(0.1, action["wait_duration"])
    if elapsed >= completion_delay:
        displacement = _player_displacement(action["before"], after)
        if action["movement_expected"] and action["action"] == "move_relative":
            causal = _relative_movement_evidence(action, after, elapsed)
            causal_reason = causal.pop("causal_reason")
            if causal_reason in {
                "movement_exceeds_causal_bound",
                "movement_direction_mismatch",
                "movement_proof_window_expired",
            }:
                return _finalize(episode, action, "blocked", after, reason=causal_reason, **causal)
            if causal_reason == "movement_below_threshold":
                if elapsed >= action["stall_seconds"]:
                    return _finalize(
                        episode,
                        action,
                        "stalled",
                        after,
                        reason="movement_below_threshold",
                        **causal,
                    )
            else:
                return _finalize(episode, action, "completed", after, **causal)
        elif action["movement_expected"] and displacement < action["min_displacement"]:
            if elapsed >= action["stall_seconds"]:
                return _finalize(
                    episode,
                    action,
                    "stalled",
                    after,
                    reason="movement_below_threshold",
                )
        else:
            return _finalize(episode, action, "completed", after)
    pending = {
        "action_id": action_id,
        "action": action["action"],
        "status": "pending",
        "elapsed_seconds": elapsed,
        "player_displacement": _player_displacement(action["before"], after),
        "movement_expected": action["movement_expected"],
        "min_displacement": action["min_displacement"],
        **_action_contract_fields(action),
        "observation": after,
    }
    if action["action"] == "move_relative":
        causal = _relative_movement_evidence(action, after, elapsed)
        causal.pop("causal_reason", None)
        pending.update(causal)
    return pending
