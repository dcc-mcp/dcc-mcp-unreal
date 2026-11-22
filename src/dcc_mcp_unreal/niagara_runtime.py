"""Runtime evidence contract for Niagara Data Channel qualification."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


class NiagaraRuntimeEvidenceError(ValueError):
    """Raised when runtime evidence is incomplete or contradictory."""


def validate_runtime_evidence(
    channel_path: str,
    routing: str,
    visibility: Sequence[str],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(channel_path, str) or not channel_path.startswith("/Game/"):
        raise NiagaraRuntimeEvidenceError("channel_path must be a /Game package path")
    if routing not in {"global", "islands"}:
        raise NiagaraRuntimeEvidenceError("routing must be global or islands")
    if isinstance(visibility, (str, bytes)) or not isinstance(visibility, Sequence) or not visibility:
        raise NiagaraRuntimeEvidenceError("visibility must contain one or more channels")
    allowed = {"blueprint", "niagara_cpu", "niagara_gpu"}
    if any(value not in allowed for value in visibility) or len(set(visibility)) != len(visibility):
        raise NiagaraRuntimeEvidenceError("visibility contains an unknown or duplicate channel")
    if not isinstance(evidence, Mapping):
        raise NiagaraRuntimeEvidenceError("evidence must be an object")
    required = {
        "writer_observed",
        "reader_observed",
        "delayed_visibility_observed",
        "frame_order_observed",
        "unsubscribe_observed",
        "pie_restart_observed",
        "world_teardown_observed",
    }
    missing = sorted(required - set(evidence))
    if missing:
        raise NiagaraRuntimeEvidenceError(f"missing runtime evidence: {', '.join(missing)}")
    if any(type(evidence[field]) is not bool for field in required):
        raise NiagaraRuntimeEvidenceError("runtime evidence fields must be booleans")
    gpu_requested = "niagara_gpu" in visibility
    gpu_verified = evidence.get("gpu_visibility_observed", False)
    if type(gpu_verified) is not bool:
        raise NiagaraRuntimeEvidenceError("gpu_visibility_observed must be boolean")
    if gpu_requested and not gpu_verified:
        status = "partial_gpu_unverified"
    elif all(evidence[field] for field in required):
        status = "qualified"
    else:
        status = "runtime_unverified"
    return {
        "schema": "dcc-mcp-unreal.niagara-runtime-evidence.v1",
        "status": status,
        "channel_path": channel_path,
        "routing": routing,
        "visibility": list(visibility),
        "gpu_requested": gpu_requested,
        "gpu_verified": gpu_verified,
        "evidence": {field: bool(evidence[field]) for field in sorted(required)},
        "execution_verified": status == "qualified",
        "teardown_verified": bool(evidence["world_teardown_observed"]),
    }
