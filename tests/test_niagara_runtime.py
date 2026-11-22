import pytest

from dcc_mcp_unreal.niagara_runtime import NiagaraRuntimeEvidenceError, validate_runtime_evidence


def _evidence(**overrides):
    result = {
        "writer_observed": True,
        "reader_observed": True,
        "delayed_visibility_observed": True,
        "frame_order_observed": True,
        "unsubscribe_observed": True,
        "pie_restart_observed": True,
        "world_teardown_observed": True,
        "gpu_visibility_observed": True,
    }
    result.update(overrides)
    return result


def test_runtime_evidence_requires_delayed_visibility_and_teardown():
    result = validate_runtime_evidence("/Game/VFX/NDC", "global", ["blueprint", "niagara_cpu"], _evidence())
    assert result["status"] == "qualified"
    assert result["execution_verified"] is True
    with pytest.raises(NiagaraRuntimeEvidenceError, match="missing runtime evidence"):
        validate_runtime_evidence("/Game/VFX/NDC", "global", ["niagara_cpu"], {})


def test_gpu_path_is_reported_as_partial_until_its_own_observation_exists():
    result = validate_runtime_evidence(
        "/Game/VFX/NDC", "islands", ["niagara_cpu", "niagara_gpu"], _evidence(gpu_visibility_observed=False)
    )
    assert result["status"] == "partial_gpu_unverified"
    assert result["execution_verified"] is False
