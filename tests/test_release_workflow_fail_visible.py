"""Contract tests for the fail-closed release finalization workflow."""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="the release workflow guards need PyYAML")

ROOT = Path(__file__).resolve().parents[1]
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def _workflow() -> dict:
    return yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))


def _ancestors(jobs: dict, name: str) -> set[str]:
    direct = jobs[name].get("needs", [])
    if isinstance(direct, str):
        direct = [direct]
    result = set(direct)
    for dependency in direct:
        result.update(_ancestors(jobs, dependency))
    return result


def test_finalizer_is_the_last_fail_closed_job() -> None:
    jobs = _workflow()["jobs"]

    assert list(jobs)[-1] == "finalize-release"
    assert {"prepare-release", "build", "build-unreal-plugin", "standalone", "publish"} <= _ancestors(
        jobs, "finalize-release"
    )

    condition = jobs["finalize-release"]["if"]
    assert "always()" in condition
    for producer in ("build", "build-unreal-plugin", "standalone"):
        assert "needs.{}.result == 'success'".format(producer) in condition
    assert "needs.publish.result == 'success'" in condition
    assert "needs.prepare-release.outputs.mode == 'recovery'" in condition


def test_release_please_does_not_publish_a_release_before_assets_are_verified() -> None:
    jobs = _workflow()["jobs"]
    release_step = next(
        step for step in jobs["release-please"]["steps"] if "release-please-action" in step.get("uses", "")
    )

    assert release_step["with"]["skip-github-release"] is True
    assert "gh release create" not in "\n".join(
        str(step.get("run", ""))
        for name, job in jobs.items()
        if name != "finalize-release"
        for step in job.get("steps", [])
    )


def test_publish_is_independent_of_the_self_hosted_unreal_runner() -> None:
    publish = _workflow()["jobs"]["publish"]
    needs = publish["needs"]

    assert "build" in needs
    assert "build-unreal-plugin" not in needs
    assert "needs.prepare-release.outputs.publish_pypi == 'true'" in publish["if"]


def test_manual_recovery_uses_the_tagged_commit_and_skips_pypi() -> None:
    jobs = _workflow()["jobs"]
    resolve = next(step for step in jobs["prepare-release"]["steps"] if step.get("name") == "Resolve immutable release source")
    plugin_inputs = jobs["build-unreal-plugin"]["with"]

    assert "resolve-source" in resolve["run"]
    assert resolve["env"]["REQUESTED_TAG"] == "${{ github.event.inputs.tag_name || '' }}"
    assert "needs.prepare-release.outputs.publish_pypi == 'true'" in jobs["publish"]["if"]
    assert "needs.publish.result == 'skipped'" in jobs["finalize-release"]["if"]
    assert plugin_inputs["source_sha"] == "${{ needs.prepare-release.outputs.source_sha }}"
    assert plugin_inputs["release_tag"] == "${{ needs.prepare-release.outputs.tag_name }}"
    assert plugin_inputs["require_existing_tag"] == "${{ needs.prepare-release.outputs.mode == 'recovery' }}"


def test_finalizer_verifies_and_uploads_without_clobbering_existing_assets() -> None:
    steps = _workflow()["jobs"]["finalize-release"]["steps"]
    commands = "\n".join(str(step.get("run", "")) for step in steps)

    assert "verify-plugin-archive" in commands
    assert "Expected six Unreal matrix archives" in commands
    assert "plan-assets" in commands
    assert "gh release upload" in commands
    assert "--clobber" not in commands
    assert "gh release edit" in commands
    assert "--draft=false" in commands


def test_release_workflow_has_no_tag_or_release_event_trigger() -> None:
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    trigger_section = text.split("workflow_dispatch:", 1)[0]

    assert 'tags: ["v*"]' not in trigger_section
    assert "  release:" not in trigger_section
