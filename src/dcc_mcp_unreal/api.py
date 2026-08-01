"""dcc_mcp_unreal.api — High-level Unreal Engine skill authoring helpers.

This module provides a clean, unified interface for Unreal skill developers.
Instead of repeating the same boilerplate in every script, import from here::

    from dcc_mcp_unreal.api import unreal_success, unreal_error, unreal_from_exception

Key helpers
-----------
``unreal_success(message, **context)``
    Build a success result dict backed by ``dcc_mcp_core.skill.skill_success``.

``unreal_error(message, error, **context)``
    Build an error ActionResultModel dict.

``unreal_warning(message, warning, **context)``
    Build a success dict with a non-fatal warning note.

``unreal_from_exception(exc, message, **context)``
    Build an error ActionResultModel dict from a live exception, including the
    full traceback.  Prefer this over ``unreal_error("...", str(exc))``.

``require_unreal()``
    Import and return the ``unreal`` module; raises ``UnrealNotAvailableError``
    if not running inside Unreal Engine.

``with_unreal(func)``
    Decorator that wraps the entire function body in the standard
    try/ImportError/Exception pattern:

        @with_unreal
        def list_actors(**kwargs) -> dict:
            import unreal
            ...

    * ``ImportError`` / ``UnrealNotAvailableError``  → ``unreal_error("Unreal not available", ...)``
    * Any other ``Exception``  → ``unreal_from_exception(exc, ...)``

Typical usage in a skill script::

    from dcc_mcp_unreal.api import unreal_success, unreal_error, unreal_from_exception

    import logging
    logger = logging.getLogger(__name__)

    def list_actors(**kwargs) -> dict:
        try:
            import unreal
            actors = unreal.EditorLevelLibrary.get_all_level_actors()
            return unreal_success("Found actors", count=len(actors))
        except ImportError:
            return unreal_error("Unreal Engine not available", "ImportError: unreal module not found")
        except Exception as exc:
            logger.exception("list_actors failed")
            return unreal_from_exception(exc, "Failed to list actors")

Or with the decorator (even simpler)::

    from dcc_mcp_unreal.api import with_unreal, unreal_success

    @with_unreal
    def list_actors(**kwargs) -> dict:
        import unreal
        actors = unreal.EditorLevelLibrary.get_all_level_actors()
        return unreal_success("Found actors", count=len(actors))
"""

# Import future modules
from __future__ import annotations

# Import built-in modules
import functools
import logging
from typing import Any, Callable, Dict, List, Optional, TypeVar

logger = logging.getLogger(__name__)

_F = TypeVar("_F", bound=Callable[..., Any])

# Sentinel used by require_param to detect "no default provided"
_SENTINEL = object()

# ---------------------------------------------------------------------------
# Unreal availability helpers
# ---------------------------------------------------------------------------


class UnrealNotAvailableError(ImportError):
    """Raised when the ``unreal`` module is not available.

    This happens when the skill script is executed outside Unreal Engine
    (e.g. during testing or in a standalone Python environment).
    """


def is_unreal_available() -> bool:
    """Return ``True`` if the real Unreal Engine ``unreal`` module is available.

    Returns ``False`` when running outside Unreal Engine, including when the
    project's own ``unreal/`` directory is on ``sys.path`` and Python resolves
    it as a namespace package (which has no real UE API).
    """
    try:
        import unreal  # noqa: F401
    except ImportError:
        return False

    # A real unreal module always exposes top-level engine symbols.
    # A namespace package from the project's unreal/ directory does not.
    import unreal as _ue  # noqa: PLC0415

    return hasattr(_ue, "log") and hasattr(_ue, "EditorLevelLibrary")


def require_unreal():
    """Import and return the ``unreal`` module.

    Raises:
        UnrealNotAvailableError: If not running inside Unreal Engine, or if
            the ``unreal`` name resolves to a namespace package rather than
            the real Unreal Engine Python API.

    Example::

        ue = require_unreal()
        actors = ue.EditorLevelLibrary.get_all_level_actors()
    """
    try:
        import unreal
    except ImportError as exc:
        raise UnrealNotAvailableError(
            "The 'unreal' module is not available. "
            "Ensure Unreal Engine is running with the Python Editor Script Plugin enabled."
        ) from exc

    # Guard against the project's own unreal/ directory being resolved as a
    # namespace package (which lacks the real UE API).
    if not (hasattr(unreal, "log") and hasattr(unreal, "EditorLevelLibrary")):
        raise UnrealNotAvailableError(
            "The 'unreal' module was found but does not expose Unreal Engine API symbols. "
            "Ensure you are running inside Unreal Engine with the Python Editor Script Plugin enabled."
        )
    return unreal


def get_unreal():
    """Return the ``unreal`` module or ``None`` if not available.

    Unlike :func:`require_unreal`, this never raises; it returns ``None``
    when Unreal is not available or the module is a namespace package.

    Example::

        ue = get_unreal()
        if ue is not None:
            print(ue.SystemLibrary.get_engine_version())
    """
    try:
        import unreal

        if not (hasattr(unreal, "log") and hasattr(unreal, "EditorLevelLibrary")):
            return None
        return unreal
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Core result helpers
# ---------------------------------------------------------------------------


def unreal_success(message: str, prompt: Optional[str] = None, **context: Any) -> Dict[str, Any]:
    """Return a success ActionResultModel as a plain dict.

    Thin wrapper around ``dcc_mcp_core.skill.skill_success`` so skill scripts
    do not need to import from two packages.

    Args:
        message: Human-readable success message.
        prompt: Optional follow-up hint shown to the AI agent.
        **context: Arbitrary key/value pairs stored in ``result["context"]``.

    Returns:
        Serialised ``ActionResultModel`` dict (``success=True``).

    Example::

        return unreal_success("Spawned actor", actor_name="SM_Cube_1", actor_class="/Engine/StaticMesh")
    """
    from dcc_mcp_core.skill import skill_success  # noqa: PLC0415

    return skill_success(message, prompt=prompt, **context)


def unreal_error(
    message: str,
    error: str = "",
    prompt: Optional[str] = None,
    possible_solutions: Optional[List[str]] = None,
    **context: Any,
) -> Dict[str, Any]:
    """Return an error ActionResultModel as a plain dict.

    Args:
        message: Short human-readable description of what went wrong.
        error: Detailed error string (e.g. exception message).
        prompt: Optional follow-up hint shown to the AI agent.
        possible_solutions: List of actionable fix suggestions shown to the agent.
        **context: Arbitrary key/value pairs stored in ``result["context"]``.

    Returns:
        Serialised ``ActionResultModel`` dict (``success=False``).

    Example::

        return unreal_error(
            "Actor not found",
            f"No actor named '{name}' in the current level",
            possible_solutions=["Use list_actors to see available actors", "Check actor name spelling"],
        )
    """
    from dcc_mcp_core.skill import skill_error  # noqa: PLC0415

    return skill_error(
        message,
        error,
        prompt=prompt,
        possible_solutions=possible_solutions,
        **context,
    )


def unreal_warning(message: str, warning: str = "", prompt: Optional[str] = None, **context: Any) -> Dict[str, Any]:
    """Return a success ActionResultModel dict with a warning note.

    The result is a *success* (``success=True``) but includes a ``warning``
    key in the context to inform the AI agent of a non-fatal issue.

    Args:
        message: Human-readable success message.
        warning: Short description of the non-fatal warning.
        prompt: Optional follow-up hint shown to the AI agent.
        **context: Arbitrary key/value pairs stored in ``result["context"]``.

    Returns:
        Serialised ``ActionResultModel`` dict (``success=True``, with
        ``context["warning"]`` set).

    Example::

        return unreal_warning(
            "Actor spawned with default material",
            warning="Requested material asset not found, used default",
            prompt="Check the material asset path with list_assets.",
            actor_name="SM_Cube_1",
        )
    """
    from dcc_mcp_core.skill import skill_warning  # noqa: PLC0415

    return skill_warning(message, warning=warning, prompt=prompt, **context)


def unreal_from_exception(
    exc: BaseException,
    message: str = "Unreal operation failed",
    prompt: Optional[str] = None,
    possible_solutions: Optional[List[str]] = None,
    include_traceback: bool = True,
    **context: Any,
) -> Dict[str, Any]:
    """Return an error ActionResultModel from a live exception.

    Unlike ``unreal_error("...", str(exc))``, this captures the full traceback
    and passes it to the agent for richer diagnostics.

    Args:
        exc: The caught exception.
        message: Short description of the failed operation.
        prompt: Optional follow-up hint shown to the AI agent.
        possible_solutions: List of actionable fix suggestions.
        include_traceback: Whether to include the full Python traceback in
            the error detail (default ``True``).
        **context: Arbitrary key/value pairs stored in ``result["context"]``.

    Returns:
        Serialised ``ActionResultModel`` dict (``success=False``).

    Example::

        except Exception as exc:
            logger.exception("spawn_actor failed")
            return unreal_from_exception(exc, "Failed to spawn actor")
    """
    from dcc_mcp_core.skill import skill_exception  # noqa: PLC0415

    return skill_exception(
        exc,
        message=message,
        prompt=prompt,
        include_traceback=include_traceback,
        possible_solutions=possible_solutions,
        **context,
    )


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------

_UNREAL_NOT_AVAILABLE_MSG = "Unreal Engine not available"
_UNREAL_NOT_AVAILABLE_DETAIL = "The 'unreal' module could not be imported"
_UNREAL_NOT_AVAILABLE_SOLUTIONS = [
    "Enable 'Python Editor Script Plugin' in Unreal Engine plugins",
    "Run this skill inside Unreal Engine (not in a standalone Python process)",
    "Ensure Unreal Engine is properly installed and the Python plugin is active",
]


def with_unreal(func: _F) -> _F:
    """Decorator that wraps a skill function with the standard Unreal error pattern.

    The decorated function is called normally.  Any exception is caught and
    converted to an ``ActionResultModel`` error dict:

    * ``ImportError`` / ``UnrealNotAvailableError``  → ``unreal_error("Unreal Engine not available", ...)``
    * Any other ``Exception``  → ``unreal_from_exception(exc, ...)``

    The wrapped function's name is used in the auto-generated error message.

    Example::

        from dcc_mcp_unreal.api import with_unreal, unreal_success

        @with_unreal
        def list_actors(**kwargs) -> dict:
            import unreal
            actors = unreal.EditorLevelLibrary.get_all_level_actors()
            return unreal_success(f"Found {len(actors)} actors", count=len(actors))

    .. note::
        The decorator does **not** log exceptions itself.  Add a
        ``logger.exception(...)`` call before ``return unreal_from_exception``
        if you need structured logging.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> dict:
        try:
            return func(*args, **kwargs)
        except (ImportError, UnrealNotAvailableError):
            return unreal_error(
                _UNREAL_NOT_AVAILABLE_MSG,
                _UNREAL_NOT_AVAILABLE_DETAIL,
                possible_solutions=_UNREAL_NOT_AVAILABLE_SOLUTIONS,
            )
        except Exception as exc:
            logger.exception("%s failed", func.__name__)
            return unreal_from_exception(
                exc,
                message="Failed to execute {}".format(func.__name__),
            )

    return wrapper  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Parameter helpers
# ---------------------------------------------------------------------------


class MissingParamError(ValueError):
    """Raised by :func:`require_param` when a required parameter is absent."""


def require_param(params: Any, key: str, default: Any = _SENTINEL) -> Any:
    """Extract a required (or defaulted) parameter from a *params* dict.

    Args:
        params: The ``params`` dict received by the skill ``run`` function.
        key: The parameter name to look up.
        default: If provided, return this value when *key* is absent.  When
            omitted the function raises :class:`MissingParamError`.

    Returns:
        The value associated with *key*, or *default* if supplied.

    Raises:
        MissingParamError: When *key* is absent and no *default* was given.

    Example::

        actor_name = require_param(params, "actor_name")         # raises if missing
        radius = require_param(params, "radius", 100.0)          # returns 100.0 if absent
    """
    if key in params:
        return params[key]
    if default is not _SENTINEL:
        return default
    raise MissingParamError("Required parameter '{}' is missing".format(key))


def missing_param_error(key: str, **context: Any) -> dict:
    """Return a pre-built error dict for a missing required parameter.

    Convenience wrapper so skill scripts can do::

        if "actor_name" not in params:
            return missing_param_error("actor_name")

    Args:
        key: The name of the missing parameter.
        **context: Extra context forwarded to :func:`unreal_error`.

    Returns:
        Serialised ``ActionResultModel`` dict (``success=False``).
    """
    return unreal_error(
        "Missing required parameter: '{}'".format(key),
        "The parameter '{}' must be provided".format(key),
        possible_solutions=["Pass '{}' in the params dict".format(key)],
        **context,
    )


def require_any_param(params: Any, *keys: str) -> Any:
    """Return the value of the first key found in *params*.

    Useful when a skill accepts several mutually-exclusive parameter names
    that map to the same concept (e.g. ``name`` vs ``actor_name``).

    Args:
        params: The ``params`` dict received by the skill ``run`` function.
        *keys: One or more parameter names to search for, in order.

    Returns:
        The value associated with the first matching key.

    Raises:
        MissingParamError: When **none** of the supplied keys exist in *params*.

    Example::

        actor = require_any_param(params, "actor_name", "name", "object_name")
    """
    for key in keys:
        if key in params:
            return params[key]
    raise MissingParamError("At least one of {} is required".format(", ".join("'{}'".format(k) for k in keys)))


def get_param_list(params: Any, key: str, default: Any = None) -> List[Any]:
    """Extract a list parameter, coercing a bare string to a one-element list.

    Many Unreal skills accept either a single actor name or a list of names.
    This helper normalises both forms so the skill body only needs to handle lists.

    Args:
        params: The ``params`` dict received by the skill ``run`` function.
        key: The parameter name to look up.
        default: Value to return when *key* is absent.  Defaults to ``[]``.

    Returns:
        A list.  If the value is already a list it is returned as-is; if it
        is a string it is wrapped in ``[value]``; otherwise it is cast with
        ``list(value)``.

    Example::

        actor_names = get_param_list(params, "actor_names")   # [] if absent
        tags = get_param_list(params, "tags", [])             # [] if absent
    """
    if default is None:
        default = []
    value = params.get(key, default)
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [value]
    try:
        return list(value)
    except TypeError:
        return [value]


# ---------------------------------------------------------------------------
# Name and context helpers
# ---------------------------------------------------------------------------


def ensure_valid_name(name: Any, param: str = "name") -> Optional[Dict[str, Any]]:
    """Return an error dict if *name* is falsy or whitespace-only, else ``None``.

    Designed to guard skill functions that require a non-empty actor/asset name::

        err = ensure_valid_name(actor_name, "actor_name")
        if err:
            return err

    Args:
        name: The value to validate (typically a ``str``).
        param: The parameter name used in the error message.

    Returns:
        ``None`` when *name* is a non-empty string, otherwise a serialised
        error dict.
    """
    if not name or (isinstance(name, str) and not name.strip()):
        return unreal_error(
            "Invalid '{}': name must not be empty".format(param),
            "'{}' received an empty or whitespace-only value".format(param),
            possible_solutions=[
                "Pass a non-empty string for '{}'".format(param),
            ],
        )
    return None


def build_context_dict(**kwargs: Any) -> Dict[str, Any]:
    """Return a dict of *kwargs* with ``None``-valued keys removed.

    Reduces ``if value is not None`` boilerplate in skill return statements::

        return unreal_success("Done", prompt="...", **build_context_dict(
            actor_name=name,
            location=location,   # may be None
        ))

    Args:
        **kwargs: Arbitrary key/value pairs.

    Returns:
        A new dict containing only entries whose value is not ``None``.
    """
    return {k: v for k, v in kwargs.items() if v is not None}


# ---------------------------------------------------------------------------
# Unreal data model helpers
# ---------------------------------------------------------------------------


def vector_to_list(vector: Any) -> List[float]:
    """Convert an ``unreal.Vector`` to a ``[x, y, z]`` float list.

    Args:
        vector: An ``unreal.Vector`` instance.

    Returns:
        ``[x, y, z]`` as Python floats.

    Example::

        loc = actor.get_actor_location()
        return unreal_success("Got location", location=vector_to_list(loc))
    """
    return [float(vector.x), float(vector.y), float(vector.z)]


def rotator_to_list(rotator: Any) -> List[float]:
    """Convert an ``unreal.Rotator`` to a ``[pitch, yaw, roll]`` float list.

    Args:
        rotator: An ``unreal.Rotator`` instance.

    Returns:
        ``[pitch, yaw, roll]`` as Python floats.

    Example::

        rot = actor.get_actor_rotation()
        return unreal_success("Got rotation", rotation=rotator_to_list(rot))
    """
    return [float(rotator.pitch), float(rotator.yaw), float(rotator.roll)]


def actor_to_dict(actor: Any) -> Dict[str, Any]:
    """Build a serialisable dict from an ``unreal.Actor`` instance.

    Extracts the actor's name, class path, world-space location, rotation,
    and scale.  All spatial values are converted to Python float lists.

    Args:
        actor: An ``unreal.Actor`` instance from the current level.

    Returns:
        Dict with keys: ``name``, ``class``, ``location``, ``rotation``,
        ``scale``.

    Example::

        actors = unreal.EditorLevelLibrary.get_all_level_actors()
        actor_list = [actor_to_dict(a) for a in actors]
        return unreal_success("Listed actors", actors=actor_list, count=len(actor_list))
    """
    try:
        location = vector_to_list(actor.get_actor_location())
    except Exception:
        location = [0.0, 0.0, 0.0]

    try:
        rotation = rotator_to_list(actor.get_actor_rotation())
    except Exception:
        rotation = [0.0, 0.0, 0.0]

    try:
        scale = vector_to_list(actor.get_actor_scale3d())
    except Exception:
        scale = [1.0, 1.0, 1.0]

    try:
        class_path = actor.get_class().get_path_name()
    except Exception:
        class_path = ""

    return {
        "name": actor.get_name(),
        "class": class_path,
        "location": location,
        "rotation": rotation,
        "scale": scale,
    }


def find_level_actor(actor_name: str) -> Optional[Any]:
    """Return the first current-level actor matching an exact label or object name.

    UE 5.8 removed ``EditorLevelLibrary.find_actor_by_label_in_level``. Prefer
    ``EditorActorSubsystem`` and retain the older list API only as a fallback
    for supported UE 5.0-era hosts.
    """
    if not actor_name:
        return None

    unreal = require_unreal()
    actors = []
    get_subsystem = getattr(unreal, "get_editor_subsystem", None)
    subsystem_class = getattr(unreal, "EditorActorSubsystem", None)
    if callable(get_subsystem) and subsystem_class is not None:
        subsystem = get_subsystem(subsystem_class)
        if subsystem is not None:
            actors = list(subsystem.get_all_level_actors())

    if not actors:
        editor_level_library = getattr(unreal, "EditorLevelLibrary", None)
        get_all = getattr(editor_level_library, "get_all_level_actors", None)
        if callable(get_all):
            actors = list(get_all())

    for actor in actors:
        if actor.get_actor_label() == actor_name or actor.get_name() == actor_name:
            return actor
    return None


# ---------------------------------------------------------------------------
# Convenience re-exports so callers only need one import
# ---------------------------------------------------------------------------

__all__ = [
    # Availability helpers
    "UnrealNotAvailableError",
    "is_unreal_available",
    "require_unreal",
    "get_unreal",
    # Core result helpers
    "unreal_success",
    "unreal_error",
    "unreal_warning",
    "unreal_from_exception",
    # Decorator
    "with_unreal",
    # Parameter helpers
    "require_param",
    "require_any_param",
    "get_param_list",
    "missing_param_error",
    "MissingParamError",
    # Name and context helpers
    "ensure_valid_name",
    "build_context_dict",
    # Unreal data model helpers
    "vector_to_list",
    "rotator_to_list",
    "actor_to_dict",
    "find_level_actor",
    # DCC capabilities
    "unreal_capabilities",
]

# Import unreal_capabilities here so it is accessible as dcc_mcp_unreal.api.unreal_capabilities
from dcc_mcp_unreal.capabilities import unreal_capabilities  # noqa: E402, F401
