"""A release that is missing assets must end red, not green.

`publish` in `release.yml` deliberately does **not** depend on
`build-unreal-plugin`: the PyPI upload must not be blocked by the availability
of the self-hosted Unreal runner. `attach-release-assets` on the other hand
*requires* `needs.build-unreal-plugin.result == 'success'`, so when the runner
is down or one of the five `build-uplugin` lanes fails, the attach job is
**skipped** — and GitHub counts a skip as neither failure nor error. The run
used to end green while the public tag carried no assets at all, and the only
way a consumer could notice was by comparing against PyPI by hand.

`release-summary` is the closing bracket. This module pins the two halves of
that contract:

* the shape — the summary job needs every release job, runs even when they
  failed or were skipped, and `publish` never gains the dependency that would
  chain PyPI to the Unreal runner;
* the behaviour — the summary script exits non-zero for a failed *or skipped*
  producer, and exits zero on every path that legitimately skips a job.

The behavioural half is proven by running the real `run:` block under bash with
`needs.*.result` values supplied through the environment, because a static check
cannot tell "fails on skip" from a regex that happens to match. Those cases are
skipped where bash is unavailable; the shape assertions run everywhere.

This file is **not** part of the shared kit (`tests/test_release_workflow_integrity.py`
is the byte-identical copy and carries no repository-specific policy). PyYAML is
requested through `pytest.importorskip`, matching the kit copy, so a test
environment without PyYAML skips this module instead of failing collection.
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import sys
from typing import Any, Dict

import pytest

yaml = pytest.importorskip("yaml", reason="the release workflow fail-visible guards need PyYAML")

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"

SUMMARY_JOB = "release-summary"

# Every job that produces or publishes part of a release. The summary must need
# all of them, so a failure or skip in any one of them is visible.
RELEASE_JOBS = (
    "release-please",
    "build",
    "build-unreal-plugin",
    "standalone",
    "publish",
    "attach-release-assets",
)

# The jobs that own an artifact and must therefore succeed in every release run.
# `release-please` and `publish` are deliberately absent: both are legitimately
# skipped for a manual dispatch with an explicit tag.
REQUIRED_JOBS = ("build", "build-unreal-plugin", "standalone", "attach-release-assets")

# An Actions expression, as the runner recognises it: `${{ ... }}`, non-greedy so
# two expressions on one line are reported as two hits rather than one range.
EXPRESSION = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)

# A script that only treats an explicit `failure` as fatal. It is what the guard
# looks like without the skip rule, and it is the reason the end-to-end tests
# below assert on a real skip instead of a real failure.
IGNORES_SKIPS = 'test "$RESULT_BUILD_UNREAL_PLUGIN" = failure && exit 1\nexit 0\n'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _release_workflow() -> Any:
    return yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))


def _job(name: str) -> Dict[str, Any]:
    job = _release_workflow()["jobs"][name]
    assert isinstance(job, dict), "job {!r} must be a mapping".format(name)
    return job


def _summary_script() -> str:
    """Return the single `run:` block of the summary job."""
    blocks = [step["run"] for step in _job(SUMMARY_JOB).get("steps", []) if "run" in step]
    assert len(blocks) == 1, "the summary job must hold exactly one run: block, found {}".format(len(blocks))
    return blocks[0]


def _result_env(name: str) -> str:
    """The env var `needs.<name>.result` is passed to the summary script as."""
    return "RESULT_{}".format(name.upper().replace("-", "_"))


def _green_env(**overrides: str) -> Dict[str, str]:
    """A fully green release-please run, with individual results overridden."""
    env = {_result_env(job): "success" for job in RELEASE_JOBS}
    env.update({"RELEASE_CREATED": "true", "RELEASE_TAG": "v0.3.9"})
    env.update(overrides)
    return env


def _run_under_bash(script: str, workdir: pathlib.Path, env: Dict[str, str]) -> "subprocess.CompletedProcess[str]":
    path = workdir / "summary.sh"
    path.write_bytes(script.replace("\r\n", "\n").encode("utf-8"))
    return subprocess.run(
        [shutil.which("bash"), path.name],
        cwd=str(workdir),
        env={**{key: value for key, value in env.items()}, "PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
    )


def _summary(tmp_path: pathlib.Path, **overrides: str) -> "subprocess.CompletedProcess[str]":
    return _run_under_bash(_summary_script(), tmp_path, _green_env(**overrides))


# ---------------------------------------------------------------------------
# The shape of the guard
# ---------------------------------------------------------------------------


def test_release_workflow_is_guarded_by_a_summary_job() -> None:
    """A guard that reads a job which does not exist would pass while asserting nothing."""
    assert RELEASE_WORKFLOW.is_file(), "missing workflow under test: {}".format(RELEASE_WORKFLOW)
    jobs = _release_workflow()["jobs"]
    assert jobs, "the release workflow must define jobs"
    assert SUMMARY_JOB in jobs, "no {!r} job: a skipped attach step still ends the run green".format(SUMMARY_JOB)


def test_the_summary_is_the_last_job() -> None:
    """It has to close the run: a summary that others depend on cannot see their result."""
    assert list(_release_workflow()["jobs"])[-1] == SUMMARY_JOB


def test_the_summary_needs_every_release_job() -> None:
    needs = _job(SUMMARY_JOB)["needs"]
    assert sorted(needs) == sorted(RELEASE_JOBS), "the summary must need every release job, got {}".format(needs)


def test_the_summary_runs_when_an_upstream_job_failed_or_was_skipped() -> None:
    """Without `always()` a failed or skipped producer skips the summary too, and the run ends green."""
    condition = _job(SUMMARY_JOB)["if"]
    assert "always()" in condition, "the summary must opt out of the implicit success() gate"


def test_the_summary_stays_quiet_outside_a_release_run() -> None:
    """A push to `main` that cuts no release skips every job; the summary must skip too."""
    condition = _job(SUMMARY_JOB)["if"]
    assert "needs.release-please.outputs.release_created == 'true'" in condition


def test_publish_is_not_chained_to_the_unreal_runner() -> None:
    """The forbidden fix: `needs: build-unreal-plugin` on `publish` would block PyPI on runner availability."""
    needs = _job("publish").get("needs", [])
    assert "build-unreal-plugin" not in needs, "publish must not depend on build-unreal-plugin; see the summary job"
    assert "build" in needs, "publish must still wait for the wheel it uploads"


def test_attach_still_gates_on_the_unreal_build() -> None:
    """The other half of the asymmetry, and the reason a skip is possible at all."""
    condition = _job("attach-release-assets")["if"]
    assert "needs.build-unreal-plugin.result == 'success'" in condition


def test_every_job_result_reaches_the_script_through_env() -> None:
    """Results must be data, not shell source: an expression inside `run:` is expanded before the shell parses it."""
    env = _job(SUMMARY_JOB)["env"]
    for job in RELEASE_JOBS:
        key = _result_env(job)
        assert key in env, "missing {} for job {!r}".format(key, job)
        expected = "$" + "{{ needs." + job + ".result }}"
        assert env[key] == expected, "{} must carry {}, got {}".format(key, expected, env[key])


def test_no_actions_expression_is_interpolated_into_the_summary_script() -> None:
    hits = EXPRESSION.findall(_summary_script())
    assert not hits, "run: blocks must take workflow data through env:, found: {}".format(hits)


def test_the_summary_script_exits_non_zero_when_it_finds_a_gap() -> None:
    """A report that prints the missing assets but exits 0 would not turn the run red."""
    script = _summary_script()
    assert re.search(r"^\s*exit 1\s*$", script, re.MULTILINE), "the summary must exit non-zero on a missing asset"


# ---------------------------------------------------------------------------
# The behaviour of the guard
# ---------------------------------------------------------------------------

_E2E_REASON = "the end-to-end proof needs bash; the shape assertions above run everywhere"


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None, reason=_E2E_REASON)
def test_a_fully_green_release_passes(tmp_path) -> None:
    result = _summary(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "complete" in result.stdout


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None, reason=_E2E_REASON)
def test_a_skipped_attach_step_fails_the_run(tmp_path) -> None:
    """The reported defect: the Unreal lanes fail, attach is skipped, PyPI already has the version."""
    result = _summary(tmp_path, RESULT_BUILD_UNREAL_PLUGIN="failure", RESULT_ATTACH_RELEASE_ASSETS="skipped")

    assert result.returncode != 0, "a skipped attach step must fail the run, got:\n{}".format(result.stdout)
    assert "attach-release-assets" in result.stdout
    assert "install-standalone.ps1" in result.stdout, "the summary must name the assets that are missing"


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None, reason=_E2E_REASON)
def test_an_unavailable_unreal_runner_fails_the_run(tmp_path) -> None:
    """A job that never ran has an empty result, not `failure`: the silent case this job exists for."""
    result = _summary(tmp_path, RESULT_BUILD_UNREAL_PLUGIN="", RESULT_ATTACH_RELEASE_ASSETS="skipped")

    assert result.returncode != 0, "an empty needs result must fail the run, got:\n{}".format(result.stdout)
    assert "build-unreal-plugin" in result.stdout
    for ue_version in ("5.5", "5.7", "5.8", "4.18", "4.26"):
        assert "ue{}-win64.zip".format(ue_version) in result.stdout, "the summary must list every Unreal lane"


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None, reason=_E2E_REASON)
def test_every_required_job_is_actually_required(tmp_path) -> None:
    """Teeth for the list above: each producer must be checked individually.

    Without this, dropping a job from the summary script would leave the run
    green for exactly the asset that job owns.
    """
    for job in REQUIRED_JOBS:
        scratch = tmp_path / job.replace("-", "_")
        scratch.mkdir()
        for state in ("failure", "skipped", ""):
            result = _summary(scratch, **{_result_env(job): state})
            assert result.returncode != 0, "{!r} with result {!r} must fail the run".format(job, state)
            assert job in result.stdout


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None, reason=_E2E_REASON)
def test_a_failed_publish_fails_the_run(tmp_path) -> None:
    """PyPI is part of the release: a tag that reached GitHub but not PyPI is not published."""
    result = _summary(tmp_path, RESULT_PUBLISH="failure", RESULT_ATTACH_RELEASE_ASSETS="skipped")

    assert result.returncode != 0, result.stdout
    assert "publish" in result.stdout


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None, reason=_E2E_REASON)
def test_a_manual_dispatch_with_an_explicit_tag_still_passes(tmp_path) -> None:
    """The path that legitimately skips release-please and publish must stay green."""
    env = _green_env(RESULT_RELEASE_PLEASE="skipped", RESULT_PUBLISH="skipped", RELEASE_CREATED="")
    result = _run_under_bash(_summary_script(), tmp_path, env)

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None, reason=_E2E_REASON)
def test_a_failed_release_please_fails_the_run(tmp_path) -> None:
    """Skipped is fine for release-please, failed is not: without it there is no tag to attach to."""
    result = _summary(tmp_path, RESULT_RELEASE_PLEASE="failure", RESULT_ATTACH_RELEASE_ASSETS="skipped")

    assert result.returncode != 0, result.stdout
    assert "release-please" in result.stdout


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None, reason=_E2E_REASON)
def test_ignoring_skips_is_not_enough(tmp_path) -> None:
    """The teeth for the skip cases: a failure-only check passes on the very defect this guards."""
    env = _green_env(RESULT_BUILD_UNREAL_PLUGIN="skipped", RESULT_ATTACH_RELEASE_ASSETS="skipped")

    naive = _run_under_bash(IGNORES_SKIPS, tmp_path, env)
    assert naive.returncode == 0, "the naive script must pass, otherwise the comparison proves nothing"

    real = _run_under_bash(_summary_script(), tmp_path, env)
    assert real.returncode != 0, "the summary must catch the skip the naive script lets through"


# ---------------------------------------------------------------------------
# Teeth for the static rules
# ---------------------------------------------------------------------------


def test_the_expression_guard_fires_on_a_real_expression() -> None:
    assert EXPRESSION.findall("echo clean") == []
    assert EXPRESSION.findall('echo "${{ needs.build.result }}"') == ["${{ needs.build.result }}"]


def test_the_result_env_names_cover_every_release_job() -> None:
    """A renamed job must not silently leave its result unwired."""
    names = {_result_env(job) for job in RELEASE_JOBS}
    assert len(names) == len(RELEASE_JOBS), "two release jobs map to the same env var name"
    assert all(re.match(r"^RESULT_[A-Z0-9_]+$", name) for name in names)


def test_the_green_fixture_really_is_green() -> None:
    """Every override in the behavioural tests is a delta from a passing run."""
    env = _green_env()
    assert all(value == "success" for key, value in env.items() if key.startswith("RESULT_"))
    assert env["RELEASE_CREATED"] == "true"
