"""Regression tests for truthful project-specific mutation results."""

from __future__ import annotations

from dcc_mcp_unreal import verified_effect_result

WAVE_FIELDS = (
    "door_index",
    "current_wave",
    "count_current_wave",
    "num_current_wave",
    "hidden_enemy_count",
)


def test_unchanged_wave_recovery_state_fails_the_postcondition():
    state = {
        "door_index": 1,
        "current_wave": 2,
        "count_current_wave": 4,
        "num_current_wave": 4,
        "hidden_enemy_count": 1,
    }

    result = verified_effect_result(
        operation="advance wave after counter soft-lock",
        before=state,
        after=dict(state),
        required_fields=WAVE_FIELDS,
    )

    assert result["success"] is False
    assert result["context"]["outcome"] == "no_effect"
    assert result["context"]["effect_observed"] is False
    assert result["context"]["changed_fields"] == []
    assert result["context"]["error_code"] == "postcondition_not_met"
    assert result["context"]["retryable"] is False
    assert result["context"]["before"] == state
    assert result["context"]["after"] == state


def test_changed_required_field_reports_a_verified_effect():
    before = {"current_wave": 2, "hidden_enemy_count": 1}
    after = {"current_wave": 3, "hidden_enemy_count": 1}

    result = verified_effect_result(
        operation="advance wave",
        before=before,
        after=after,
        required_fields=("current_wave", "hidden_enemy_count"),
    )

    assert result["success"] is True
    assert result["context"]["outcome"] == "changed"
    assert result["context"]["effect_observed"] is True
    assert result["context"]["changed_fields"] == ["current_wave"]
    assert result["context"]["unchanged_fields"] == ["hidden_enemy_count"]


def test_missing_required_observation_fails_closed():
    result = verified_effect_result(
        operation="advance wave",
        before={"current_wave": 2},
        after={},
        required_fields=("current_wave",),
    )

    assert result["success"] is False
    assert result["context"]["outcome"] == "unobservable"
    assert result["context"]["effect_observed"] is False
    assert result["context"]["error_code"] == "postcondition_unobservable"
    assert result["context"]["missing_after"] == ["current_wave"]
    assert result["context"]["retryable"] is True


def test_invalid_or_unbounded_verification_contract_fails_closed():
    cases = [
        {"before": {"wave": 1}, "after": {"wave": 2}, "required_fields": ()},
        {"before": {"wave": {"nested": 1}}, "after": {"wave": 2}, "required_fields": ("wave",)},
        {
            "before": {f"field_{index}": index for index in range(65)},
            "after": {f"field_{index}": index for index in range(65)},
            "required_fields": tuple(f"field_{index}" for index in range(65)),
        },
    ]

    for case in cases:
        result = verified_effect_result(operation="recover state", **case)
        assert result["success"] is False
        assert result["context"]["outcome"] == "unobservable"
        assert result["context"]["error_code"] == "invalid_postcondition_contract"
