"""dcc_mcp_unreal.api — High-level Unreal Engine skill authoring helpers.

Mirrors dcc_mcp_maya.api but for Unreal Engine's Python API (unreal module).

Key helpers
-----------
``unreal_success(message, **context)``
    Build a success ActionResultModel dict.

``unreal_error(message, error, **context)``
    Build an error ActionResultModel dict.

``unreal_from_exception(exc, message=None, **context)``
    Build an error dict from a live exception with full traceback.

``require_unreal()``
    Import and return the ``unreal`` module; raises ``UnrealNotAvailableError``
    if not running inside Unreal Engine.

``with_unreal(func)``
    Decorator that handles ImportError and Exception automatically.

Typical usage in a skill script::

    from dcc_mcp_unreal.api import unreal_success, unreal_error

    def spawn_actor(actor_class: str = "/Script/Engine.StaticMeshActor", **kwargs) -> dict:
        try:
            import unreal
            loc = unreal.Vector(0, 0, 0)
            actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
                unreal.load_class(None, actor_class), loc
            )
            return unreal_success(
                f"Spawned {actor.get_name()}",
                actor_name=actor.get_name(),
                actor_class=actor_class,
            )
        except ImportError:
            return unreal_error("Unreal Engine not available", "ImportError: unreal module not found")
        except Exception as exc:
            return unreal_from_exception(exc, "Failed to spawn actor")
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable, List, Optional, TypeVar

logger = logging.getLogger(__name__)

_F = TypeVar("_F", bound=Callable[..., Any])


class UnrealNotAvailableError(ImportError):
    """Raised when the ``unreal`` module is not available.

    This happens when the skill script is executed outside Unreal Engine
    (e.g. during testing or in a standalone Python environment).
    """


def is_unreal_available() -> bool:
    """Return True if the ``unreal`` module can be imported."""
    try:
        import unreal  # noqa: F401

        return True
    except ImportError:
        return False


def require_unreal():
    """Import and return the ``unreal`` module.

    Raises:
        UnrealNotAvailableError: If not running inside Unreal Engine.
    """
    try:
        import unreal

        return unreal
    except ImportError as exc:
        raise UnrealNotAvailableError(
            "The 'unreal' module is not available. "
            "Ensure Unreal Engine is running with the Python Editor Script Plugin enabled."
        ) from exc


def get_unreal():
    """Return the ``unreal`` module or None if not available."""
    try:
        import unreal

        return unreal
    except ImportError:
        return None


def unreal_success(message: str, *, prompt: Optional[str] = None, **context: Any) -> dict:
    """Build a success result dict compatible with ActionResultModel.

    Args:
        message: Human-readable summary of what was accomplished.
        prompt: Optional hint for the agent's next action.
        **context: Arbitrary key/value pairs (actor names, object counts, paths).

    Returns:
        dict: ActionResultModel-compatible success dict.
    """
    try:
        from dcc_mcp_core import success_result

        arm = success_result(message, prompt=prompt, **context)
        return arm.to_dict()
    except ImportError:
        from dcc_mcp_core.skill import skill_success

        return skill_success(message, prompt=prompt, **context)


def unreal_error(
    message: str,
    error: str,
    *,
    prompt: Optional[str] = None,
    possible_solutions: Optional[List[str]] = None,
    **context: Any,
) -> dict:
    """Build a failure result dict compatible with ActionResultModel.

    Args:
        message: User-facing description of what went wrong.
        error: Technical error string (exception repr, error code).
        prompt: Optional recovery hint.
        possible_solutions: Optional list of actionable suggestions.
        **context: Additional context key/value pairs.
    """
    try:
        from dcc_mcp_core import error_result

        arm = error_result(message, error=error, prompt=prompt, possible_solutions=possible_solutions, **context)
        return arm.to_dict()
    except ImportError:
        from dcc_mcp_core.skill import skill_error

        return skill_error(message, error, prompt=prompt, possible_solutions=possible_solutions, **context)


def unreal_from_exception(
    exc: BaseException,
    message: Optional[str] = None,
    *,
    prompt: Optional[str] = None,
    include_traceback: bool = True,
    **context: Any,
) -> dict:
    """Build a failure result dict from a caught exception.

    Args:
        exc: The caught exception.
        message: Optional custom user-facing message.
        prompt: Optional recovery hint.
        include_traceback: Whether to include the formatted traceback.
        **context: Additional context key/value pairs.
    """
    try:
        from dcc_mcp_core import from_exception

        error_str = repr(exc)
        arm = from_exception(error_str, message=message, prompt=prompt, include_traceback=include_traceback, **context)
        return arm.to_dict()
    except ImportError:
        from dcc_mcp_core.skill import skill_exception

        return skill_exception(exc, message=message, prompt=prompt, include_traceback=include_traceback, **context)


def with_unreal(func: _F) -> _F:
    """Decorator: wrap a skill function with standard Unreal error handling.

    Catches:
    - ``ImportError`` / ``UnrealNotAvailableError``: Unreal Engine not running
    - ``Exception``: Any other error during execution

    Usage::

        @with_unreal
        def list_actors(**kwargs) -> dict:
            import unreal
            actors = unreal.EditorLevelLibrary.get_all_level_actors()
            return unreal_success(f"Found {len(actors)} actors", count=len(actors))

        def main(**kwargs):
            return list_actors(**kwargs)
    """

    @functools.wraps(func)
    def wrapper(**kwargs: Any) -> dict:
        try:
            return func(**kwargs)
        except (ImportError, UnrealNotAvailableError) as exc:
            return unreal_error(
                "Unreal Engine is not available in this environment",
                repr(exc),
                prompt="Ensure Unreal Engine is running with the Python Editor Script Plugin enabled.",
                possible_solutions=[
                    "Enable 'Python Editor Script Plugin' in Unreal Engine plugins",
                    "Start Unreal Engine before launching the MCP server",
                ],
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Skill execution failed: %s", func.__name__)
            return unreal_from_exception(exc)

    return wrapper  # type: ignore[return-value]
