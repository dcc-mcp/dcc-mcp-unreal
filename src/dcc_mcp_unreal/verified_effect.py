"""Fail-closed postcondition results for project-specific Unreal mutations.

Project Skills can invoke arbitrary gameplay events, but dispatching an event
does not prove that the requested gameplay state changed.  This module turns a
bounded pair of observations into the standard DCC-MCP action-result envelope.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, Dict, Optional, Tuple

from dcc_mcp_unreal.api import unreal_error, unreal_success

_MAX_FIELDS = 64
_MAX_FIELD_LENGTH = 128
_MAX_OPERATION_LENGTH = 120
_MAX_STRING_VALUE_LENGTH = 4096


def _invalid_reason(
    operation: object,
    before: object,
    after: object,
    required_fields: object,
) -> Optional[str]:
    if not isinstance(operation, str) or not operation.strip() or len(operation) > _MAX_OPERATION_LENGTH:
        return "operation must be a non-empty string of at most 120 characters"
    if not isinstance(before, Mapping) or not isinstance(after, Mapping):
        return "before and after must be mappings"
    if isinstance(required_fields, (str, bytes)) or not isinstance(required_fields, Sequence):
        return "required_fields must be a sequence of field names"
    if not required_fields or len(required_fields) > _MAX_FIELDS:
        return "required_fields must contain between 1 and 64 field names"
    if any(not isinstance(field, str) or not field or len(field) > _MAX_FIELD_LENGTH for field in required_fields):
        return "required field names must be non-empty strings of at most 128 characters"
    if len(set(required_fields)) != len(required_fields):
        return "required field names must be unique"
    for snapshot_name, snapshot in (("before", before), ("after", after)):
        for field in required_fields:
            if field in snapshot and not _is_json_scalar(snapshot[field]):
                return f"{snapshot_name}.{field} must be a bounded JSON scalar"
    return None


def _is_json_scalar(value: object) -> bool:
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return isinstance(value, str) and len(value) <= _MAX_STRING_VALUE_LENGTH


def _same_scalar(left: object, right: object) -> bool:
    """Compare JSON scalars without treating ``True`` and ``1`` as equal."""

    return type(left) is type(right) and left == right


def _observed_snapshot(snapshot: Mapping[str, object], fields: Sequence[str]) -> Dict[str, object]:
    return {field: snapshot[field] for field in fields if field in snapshot}


def verified_effect_result(
    *,
    operation: str,
    before: Mapping[str, object],
    after: Mapping[str, object],
    required_fields: Sequence[str],
) -> Dict[str, Any]:
    """Return success only when a required observed field changed.

    The helper is intended for project-local mutation and recovery tools.  It
    deliberately requires named fields so event dispatch cannot be mistaken
    for a verified effect and an empty observation cannot pass accidentally.
    Results use the adapter's standard action-result envelope.
    """

    invalid_reason = _invalid_reason(operation, before, after, required_fields)
    if invalid_reason is not None:
        return unreal_error(
            "Postcondition contract is invalid",
            invalid_reason,
            error_code="invalid_postcondition_contract",
            outcome="unobservable",
            effect_observed=False,
            verification_required=True,
            retryable=False,
        )

    fields: Tuple[str, ...] = tuple(required_fields)
    missing_before = [field for field in fields if field not in before]
    missing_after = [field for field in fields if field not in after]
    before_snapshot = _observed_snapshot(before, fields)
    after_snapshot = _observed_snapshot(after, fields)
    common_context = {
        "operation": operation,
        "verification_required": True,
        "required_fields": list(fields),
        "before": before_snapshot,
        "after": after_snapshot,
    }

    if missing_before or missing_after:
        return unreal_error(
            f"Could not verify the effect of {operation}",
            "One or more required postcondition fields were not observed both before and after the operation.",
            error_code="postcondition_unobservable",
            outcome="unobservable",
            effect_observed=False,
            missing_before=missing_before,
            missing_after=missing_after,
            retryable=True,
            **common_context,
        )

    changed_fields = [field for field in fields if not _same_scalar(before[field], after[field])]
    unchanged_fields = [field for field in fields if field not in changed_fields]
    comparison_context = {
        "changed_fields": changed_fields,
        "unchanged_fields": unchanged_fields,
        **common_context,
    }

    if not changed_fields:
        return unreal_error(
            f"{operation} produced no observed state change",
            "The event may have been dispatched, but every required postcondition field remained unchanged.",
            error_code="postcondition_not_met",
            outcome="no_effect",
            effect_observed=False,
            retryable=False,
            **comparison_context,
        )

    return unreal_success(
        f"Verified the effect of {operation}",
        outcome="changed",
        effect_observed=True,
        retryable=False,
        **comparison_context,
    )
