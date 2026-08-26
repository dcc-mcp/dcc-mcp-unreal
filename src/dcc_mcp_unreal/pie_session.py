"""Shared Play-In-Editor session and runtime actor helpers.

The active game world is the authoritative PIE signal. Unreal's
``is_in_play_in_editor`` flag can lag behind world creation during transitions,
so callers should not implement independent guards around that flag.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


class PieSessionUnavailableError(RuntimeError):
    """A transient failure to resolve the active PIE game world."""

    code = "pie_session_unavailable"
    retryable = True


@dataclass(frozen=True)
class PieContext:
    """Objects shared by tools operating on the active PIE session."""

    unreal: Any
    world: Any
    controller: Any
    pawn: Any


def _unreal_module(unreal: Any = None):
    if unreal is not None:
        return unreal
    from dcc_mcp_unreal.api import require_unreal

    return require_unreal()


def get_pie_world(unreal: Any = None) -> Optional[Any]:
    """Return the active PIE game world, or ``None`` when no world exists."""
    unreal = _unreal_module(unreal)
    get_subsystem = getattr(unreal, "get_editor_subsystem", None)
    editor_class = getattr(unreal, "UnrealEditorSubsystem", None)
    if callable(get_subsystem) and editor_class is not None:
        try:
            editor = get_subsystem(editor_class)
            get_game_world = getattr(editor, "get_game_world", None)
            if callable(get_game_world):
                return get_game_world()
        except Exception:
            pass

    editor_level_library = getattr(unreal, "EditorLevelLibrary", None)
    get_game_world = getattr(editor_level_library, "get_game_world", None)
    if callable(get_game_world):
        try:
            return get_game_world()
        except Exception:
            pass
    return None


def is_pie_active(unreal: Any = None) -> bool:
    """Return whether an active PIE game world can be resolved."""
    return get_pie_world(unreal) is not None


def require_pie_context(unreal: Any = None) -> PieContext:
    """Resolve the shared PIE world, controller, and pawn contract."""
    unreal = _unreal_module(unreal)
    world = get_pie_world(unreal)
    if world is None:
        raise PieSessionUnavailableError("No active PIE game world is available")

    gameplay = getattr(unreal, "GameplayStatics", None)
    get_controller = getattr(gameplay, "get_player_controller", None)
    get_pawn = getattr(gameplay, "get_player_pawn", None)
    controller = get_controller(world, 0) if callable(get_controller) else None
    pawn = get_pawn(world, 0) if callable(get_pawn) else None
    if controller is None or pawn is None:
        raise PieSessionUnavailableError("The active PIE player controller or pawn is unavailable")
    return PieContext(unreal=unreal, world=world, controller=controller, pawn=pawn)


def get_pie_actors(unreal: Any = None, world: Any = None) -> list[Any]:
    """Return actors from the active PIE world, or an empty list."""
    unreal = _unreal_module(unreal)
    world = world if world is not None else get_pie_world(unreal)
    if world is None:
        return []

    gameplay = getattr(unreal, "GameplayStatics", None)
    actor_class = getattr(unreal, "Actor", None)
    get_all = getattr(gameplay, "get_all_actors_of_class", None)
    if not callable(get_all) or actor_class is None:
        return []
    try:
        return list(get_all(world, actor_class))
    except Exception:
        return []


def find_pie_actor(actor_name: str, unreal: Any = None) -> Optional[Any]:
    """Find an exact actor label or object name in the active PIE world."""
    if not actor_name:
        return None
    unreal = _unreal_module(unreal)
    for actor in get_pie_actors(unreal):
        if actor is None:
            continue
        try:
            if actor.get_name() == actor_name:
                return actor
        except Exception:
            pass
        try:
            if actor.get_actor_label() == actor_name:
                return actor
        except Exception:
            pass
    return None


def pie_session_error(exc: PieSessionUnavailableError, message: str = "PIE session is temporarily unavailable") -> dict:
    """Return the standard machine-readable result for a transient PIE outage."""
    from dcc_mcp_unreal.api import unreal_error

    return unreal_error(
        message,
        exc.code,
        prompt="Retry after Unreal finishes the PIE world transition.",
        possible_solutions=[
            "Retry the same operation after a short delay",
            "Use unreal_pie__get_status to confirm that the PIE world is ready",
        ],
        retryable=exc.retryable,
        reason=str(exc),
    )


__all__ = [
    "PieContext",
    "PieSessionUnavailableError",
    "find_pie_actor",
    "get_pie_actors",
    "get_pie_world",
    "is_pie_active",
    "pie_session_error",
    "require_pie_context",
]
