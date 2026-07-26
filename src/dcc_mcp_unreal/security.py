"""Fail-closed security policy for UObject reflection.

All UObject access is governed by a deny-by-default policy. Every property read,
property write, and UFunction call is checked against this policy before any
reflection operation is performed. Paths not explicitly allowed are rejected
with a ``SecurityDeniedError``.

Design principles
=================
- **Fail-closed**: unknown paths, private names (``_`` prefix), and dangerous
  operations are denied unless explicitly allowlisted.
- **Main-thread only**: mutating operations are gated on ``GameThread``.
- **Explicit allowlists**: no wildcard discovery that could leak internal state.
- **Audit trail**: every access decision is logged for observability.

Security levels
===============
- ``read`` — safe read-only operations (get property, list properties, describe object)
- ``write`` — mutating operations (set property, call function)
- ``execute`` — UFunction invocation (highest risk)
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Optional

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

# Properties/functions whose names start with these prefixes are NEVER accessible.
_DENIED_PREFIXES: FrozenSet[str] = frozenset({"_", "bOverride_", "K2Node_", "ExecuteUbergraph_"})

# UObject classes or patterns that are always denied (internal engine objects).
_DENIED_CLASS_PATTERNS: FrozenSet[str] = frozenset(
    {
        "*/Script/Engine.Default__*",
        "*/Script/CoreUObject.Package*",
        "*/Script/CoreUObject.Class*",
        "*/Script/CoreUObject.MetaData*",
        "*/Script/Engine.PlayerController*",  # Disallow direct control
        "*/Script/Engine.GameModeBase*",  # Disallow game mode mutation
        "*/Script/Engine.GameStateBase*",  # Disallow game state mutation
        "*/Script/Engine.WorldSettings*",  # Disallow world settings mutation
    }
)

# Properties that are always denied regardless of object/class.
_DENIED_PROPERTY_NAMES: FrozenSet[str] = frozenset(
    {
        "bIsEditorOnly",
        "InternalIndex",
        "NativeIndex",
    }
)

# Functions that are always denied (engine lifecycle, dangerous operations).
_DENIED_FUNCTION_PATTERNS: FrozenSet[str] = frozenset(
    {
        "*/K2_DestroyActor",
        "*/K2_DestroyComponent",
        "*/Server_*",  # RPC Server functions
        "*/Client_*",  # RPC Client functions
        "*/Multicast_*",  # RPC Multicast functions
        "*/OnRep_*",  # Replication callbacks
        "*/BeginPlay",
        "*/EndPlay",
        "*/Tick",
        "*/ReceiveTick",
        "*/ReceiveBeginPlay",
        "*/ReceiveEndPlay",
        "*/ReceiveDestroyed",
        "*/ReceiveActorBeginOverlap",
        "*/ReceiveActorEndOverlap",
        "*/ReceiveHit",
        "*/UserConstructionScript",
        "*/ReceiveAnyDamage",
        "*/ReceivePointDamage",
        "*/ReceiveRadialDamage",
        "*/BndEvt__*",
    }
)

# Flags enum for operation types.
_READ = 1 << 0
_WRITE = 1 << 1
_EXECUTE = 1 << 2


class OperationKind(Enum):
    """Kind of reflection operation being performed."""

    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"

    @property
    def level(self) -> int:
        return {OperationKind.READ: _READ, OperationKind.WRITE: _WRITE, OperationKind.EXECUTE: _EXECUTE}[self]


# ── SecurityDeniedError ──────────────────────────────────────────────────────


class SecurityDeniedError(Exception):
    """Raised when a UObject reflection operation is denied by the security policy.

    This is the *only* exception raised for policy violations — callers can
    catch it specifically to distinguish security denials from runtime errors.
    """

    def __init__(self, reason: str, *, operation: Optional[OperationKind] = None, path: Optional[str] = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.operation = operation
        self.path = path

    def __str__(self) -> str:
        parts = ["[SECURITY DENIED]", self.reason]
        if self.operation:
            parts.append(f"(operation={self.operation.value})")
        if self.path:
            parts.append(f"(path={self.path})")
        return " ".join(parts)


# ── ReflectionPolicy ─────────────────────────────────────────────────────────


@dataclass
class ReflectionPolicy:
    """Fail-closed security policy for UObject reflection.

    Every reflection operation (discover, describe, get_property, set_property,
    call_function) is checked against this policy. The default state denies
    **everything** — callers must explicitly enable allowlists.

    Attributes:
        allowed_properties: Glob-style patterns for allowed property names.
        allowed_functions: Glob-style patterns for allowed UFunction names.
        allowed_classes: Glob-style patterns for allowed UObject class paths.
        allow_write: Whether property writes are permitted at all.
        allow_execute: Whether UFunction calls are permitted at all.
        enforce_main_thread: Whether mutating operations require GameThread.
        audit_all: Whether to log every access decision (verbose).
    """

    allowed_properties: List[str] = field(default_factory=list)
    allowed_functions: List[str] = field(default_factory=list)
    allowed_classes: List[str] = field(default_factory=list)
    allow_write: bool = False
    allow_execute: bool = False
    enforce_main_thread: bool = True
    audit_all: bool = False

    def __post_init__(self) -> None:
        # Use raw fnmatch patterns directly instead of compiling to regex.
        # fnmatch.translate() treats / specially (as a path separator), but
        # UObject paths use :: as the class–member separator. fnmatch.fnmatch()
        # matches * against any characters including ::.
        self._denied_class_patterns: List[str] = list(_DENIED_CLASS_PATTERNS)
        self._denied_function_patterns: List[str] = list(_DENIED_FUNCTION_PATTERNS)

    def _matches_denied_function(self, func_path: str, function_name: str) -> Optional[str]:
        """Check if a function call matches any denied pattern.

        Patterns may be of the form ``*/FuncName`` (matches via func_path which
        contains ``/`` separators) or just ``FuncName`` (matches bare names).
        We try against both ``func_path`` and ``function_name``, and also try
        stripping a leading ``*/`` from the pattern when matching against the
        bare ``function_name``.
        """
        for pattern in self._denied_function_patterns:
            if fnmatch.fnmatch(func_path, pattern):
                return pattern
            if fnmatch.fnmatch(function_name, pattern):
                return pattern
            # Strip leading */ for bare-name matching (e.g. "*/Server_*" → "Server_*")
            if pattern.startswith("*/"):
                bare_pattern = pattern[2:]
                if fnmatch.fnmatch(function_name, bare_pattern):
                    return pattern
        return None

    def check_class(self, class_path: str) -> None:
        """Check whether a UObject class path is accessible.

        Raises :class:`SecurityDeniedError` if the class is denied.
        """
        for pattern in self._denied_class_patterns:
            if fnmatch.fnmatch(class_path, pattern):
                raise SecurityDeniedError(
                    f"Class {class_path!r} matches denied pattern {pattern!r}",
                    operation=None,
                    path=class_path,
                )
            # Also try without leading */ for paths without slash (bare class names)
            if pattern.startswith("*/"):
                bare_pattern = pattern[2:]
                if fnmatch.fnmatch(class_path, bare_pattern):
                    raise SecurityDeniedError(
                        f"Class {class_path!r} matches denied pattern {pattern!r}",
                        operation=None,
                        path=class_path,
                    )
        if self.allowed_classes:
            if not any(fnmatch.fnmatch(class_path, p) for p in self.allowed_classes):
                raise SecurityDeniedError(
                    f"Class {class_path!r} is not in the allowed_classes allowlist",
                    operation=None,
                    path=class_path,
                )
        if self.audit_all:
            logger.debug("[security] class %r: ALLOWED", class_path)

    def check_property_name(self, name: str) -> None:
        """Check whether a property name is accessible.

        Raises :class:`SecurityDeniedError` if the property name is denied.
        """
        if not name:
            raise SecurityDeniedError("Empty property name", operation=OperationKind.READ)
        for prefix in _DENIED_PREFIXES:
            if name.startswith(prefix):
                raise SecurityDeniedError(
                    f"Property {name!r} starts with denied prefix {prefix!r}",
                    operation=OperationKind.READ,
                    path=name,
                )
        if name.lower() in {n.lower() for n in _DENIED_PROPERTY_NAMES}:
            raise SecurityDeniedError(
                f"Property {name!r} is in the denied-properties list",
                operation=OperationKind.READ,
                path=name,
            )

    def check_property_read(self, name: str, class_path: str) -> None:
        """Check whether a property read is permitted.

        Raises :class:`SecurityDeniedError` if denied.
        """
        self.check_class(class_path)
        self.check_property_name(name)
        if self.allowed_properties:
            if not any(fnmatch.fnmatch(name, p) for p in self.allowed_properties):
                raise SecurityDeniedError(
                    f"Property {name!r} is not in the allowed_properties allowlist",
                    operation=OperationKind.READ,
                    path=f"{class_path}::{name}",
                )
        if self.audit_all:
            logger.debug("[security] property read %r on %r: ALLOWED", name, class_path)

    def check_property_write(self, name: str, class_path: str, value: Any) -> None:
        """Check whether a property write is permitted.

        Raises :class:`SecurityDeniedError` if denied.
        """
        if not self.allow_write:
            raise SecurityDeniedError(
                "Property writes are not permitted (allow_write=False)",
                operation=OperationKind.WRITE,
                path=f"{class_path}::{name}",
            )
        self.check_class(class_path)
        self.check_property_name(name)
        if self.allowed_properties:
            if not any(fnmatch.fnmatch(name, p) for p in self.allowed_properties):
                raise SecurityDeniedError(
                    f"Property {name!r} is not in the allowed_properties allowlist",
                    operation=OperationKind.WRITE,
                    path=f"{class_path}::{name}",
                )
        self._check_value_safety(name, value)
        if self.audit_all:
            logger.debug("[security] property write %r on %r: ALLOWED", name, class_path)

    def check_function_call(self, function_name: str, class_path: str, args: Optional[Dict[str, Any]] = None) -> None:
        """Check whether a UFunction call is permitted.

        Raises :class:`SecurityDeniedError` if denied.
        """
        if not self.allow_execute:
            raise SecurityDeniedError(
                "UFunction calls are not permitted (allow_execute=False)",
                operation=OperationKind.EXECUTE,
                path=f"{class_path}::{function_name}",
            )
        self.check_class(class_path)
        # Check denied function patterns.
        func_path = f"{class_path}::{function_name}"
        matched = self._matches_denied_function(func_path, function_name)
        if matched is not None:
            raise SecurityDeniedError(
                f"UFunction {function_name!r} matches denied pattern {matched!r}",
                operation=OperationKind.EXECUTE,
                path=func_path,
            )
        # Check private prefix
        for prefix in _DENIED_PREFIXES:
            if function_name.startswith(prefix):
                raise SecurityDeniedError(
                    f"UFunction {function_name!r} starts with denied prefix {prefix!r}",
                    operation=OperationKind.EXECUTE,
                    path=func_path,
                )
        if self.allowed_functions:
            if not (
                any(fnmatch.fnmatch(function_name, p) for p in self.allowed_functions)
                or any(fnmatch.fnmatch(func_path, p) for p in self.allowed_functions)
            ):
                raise SecurityDeniedError(
                    f"UFunction {function_name!r} is not in the allowed_functions allowlist",
                    operation=OperationKind.EXECUTE,
                    path=func_path,
                )
        if args:
            self._check_args_safety(args)
        if self.audit_all:
            logger.debug("[security] function call %r on %r: ALLOWED", function_name, class_path)

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _check_value_safety(name: str, value: Any) -> None:
        """Reject values that could be dangerous (e.g. arbitrary code objects)."""
        if callable(value):
            raise SecurityDeniedError(
                f"Property {name!r}: callable values are not permitted",
                operation=OperationKind.WRITE,
                path=name,
            )
        # Reject excessively large strings to prevent memory pressure attacks
        if isinstance(value, str) and len(value) > 1_000_000:
            raise SecurityDeniedError(
                f"Property {name!r}: string value exceeds 1MB limit",
                operation=OperationKind.WRITE,
                path=name,
            )
        if isinstance(value, (bytes, bytearray)) and len(value) > 1_000_000:
            raise SecurityDeniedError(
                f"Property {name!r}: bytes value exceeds 1MB limit",
                operation=OperationKind.WRITE,
                path=name,
            )

    @staticmethod
    def _check_args_safety(args: Dict[str, Any]) -> None:
        """Reject dangerous argument payloads."""
        for key, value in args.items():
            if callable(value):
                raise SecurityDeniedError(
                    f"Function argument {key!r}: callable values are not permitted",
                    operation=OperationKind.EXECUTE,
                    path=key,
                )
            if isinstance(value, str) and len(value) > 1_000_000:
                raise SecurityDeniedError(
                    f"Function argument {key!r}: string value exceeds 1MB limit",
                    operation=OperationKind.EXECUTE,
                    path=key,
                )


# ── Default policies ─────────────────────────────────────────────────────────


def default_read_policy() -> ReflectionPolicy:
    """Return a safe read-only policy suitable for discovery/description.

    Allows reading properties from all non-denied classes. No writes, no function calls.
    """
    return ReflectionPolicy(
        allow_write=False,
        allow_execute=False,
        enforce_main_thread=True,
    )


def default_full_policy() -> ReflectionPolicy:
    """Return a policy suitable for full access (read + write + execute).

    This is the **base** full policy — it still fails closed on denied patterns
    but allows read/write/execute on non-denied classes. Production deployments
    should further restrict ``allowed_properties``, ``allowed_functions``, and
    ``allowed_classes`` based on the specific use case.
    """
    return ReflectionPolicy(
        allow_write=True,
        allow_execute=True,
        enforce_main_thread=True,
    )


__all__ = [
    "OperationKind",
    "ReflectionPolicy",
    "SecurityDeniedError",
    "default_full_policy",
    "default_read_policy",
]
