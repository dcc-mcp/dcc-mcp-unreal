"""Repository-local safety guards for `run:` blocks in the release workflow.

This file is **not** part of the shared kit. `tests/test_release_workflow_integrity.py`
is the byte-identical kit copy and only binds the workflow to an approved digest; it
deliberately carries no repository-specific policy. These assertions are the ones we
own here, and they stop two regressions from coming back:

* `${{ }}` inside a `run:` block. An Actions expression is expanded by the runner
  *before* the shell parses the script, so an attacker-influenced value such as a
  `workflow_dispatch` input becomes literal shell source. Passing the same value
  through `env:` and reading it as `"$VAR"` keeps it as data.

* An un-delimited `GITHUB_ENV` write. GitHub's env-file parser turns

      ASSET=one
      INJECTED=yes

  into two entries whenever the value contains a newline. Writing the
  `NAME<<DELIMITER` marker into the file instead keeps the newline inside the value.

  Note what does **not** help: a shell heredoc (`cat >> "$GITHUB_ENV" <<EOF`) bounds
  the shell command, not the env-file record. It produces byte-identical output to a
  plain `echo`, so it defends nothing. Only the marker reaching the file counts, which
  is why the end-to-end test below is the authority here and the static checks are
  only a tripwire.

PyYAML is requested through `pytest.importorskip`, matching the kit copy: a test
environment without PyYAML skips this module instead of failing collection. PyYAML is
a declared dev dependency (`pyyaml>=5.0`), so in CI every assertion below runs.
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, Iterator, List, Tuple

import pytest

yaml = pytest.importorskip("yaml", reason="the release workflow run-safety guards need PyYAML")

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"

# The step whose GITHUB_ENV write carries a workflow_dispatch-supplied value.
ARCHIVE_STEP = "Archive standalone"

# An Actions expression, as the runner recognises it: `${{ ... }}`, non-greedy so two
# expressions on one line are reported as two hits rather than one spanning range.
EXPRESSION = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)

# `$GITHUB_ENV` or `${GITHUB_ENV}`, with or without surrounding quotes.
GITHUB_ENV_TARGET = r"\"?(?:\$\{GITHUB_ENV\}|\$GITHUB_ENV)\"?"

# One statement that appends to GITHUB_ENV. `payload` is everything before the
# redirection, i.e. the text that lands in the env file.
GITHUB_ENV_WRITE = re.compile(r"(?P<payload>.*?)>>\s*" + GITHUB_ENV_TARGET)

# `echo "NAME=value" >> "$GITHUB_ENV"`: the payload is a complete assignment, so a
# value containing a newline appends further entries.
GITHUB_ENV_ASSIGNMENT = re.compile(r"""^\s*echo\s+["']?\w+=""")

# `NAME<<DELIMITER` being written to the env file, which opens a delimited record.
GITHUB_ENV_MARKER = re.compile(r"\w+<<")

# `upload-artifact` reads its `path:` as a newline-separated glob list, so the tag is
# held to a charset that cannot smuggle a second pattern or a path separator.
SAFE_TAG_CHARSET = "A-Za-z0-9._+-"
TAG_CHARSET_GUARD = re.compile(r"case \"\$RELEASE_TAG\" in")
ARCHIVE_NAME_ASSIGNMENT = 'base="dcc-mcp-unreal-${RELEASE_TAG}-${ASSET_SUFFIX}"'

CLEAN_RUN_BLOCK = "echo nothing to see here\n"

# A `run:` block that interpolates an Actions expression directly into shell source.
INTERPOLATED_RUN_BLOCK = 'echo "tag=${{ github.event.inputs.tag_name }}"\n'

# A `run:` block that appends an untrusted value to GITHUB_ENV on a single line.
UNQUOTED_ENV_RUN_BLOCK = 'echo "ASSET=${base}.zip" >> "$GITHUB_ENV"\n'

# The delimited form, i.e. the shape the workflow is required to use.
DELIMITED_ENV_RUN_BLOCK = (
    'asset="dcc-mcp-unreal-v0.0.0-linux-X64.zip"\n'
    'delimiter="ASSET_EOF_$$_${RANDOM}${RANDOM}"\n'
    'echo "ASSET<<$delimiter" >> "$GITHUB_ENV"\n'
    'printf \'%s\\n\' "$asset" >> "$GITHUB_ENV"\n'
    'echo "$delimiter" >> "$GITHUB_ENV"\n'
)

WORKFLOW_WITH_RUN_BLOCK = """name: Release
on:
  push:
    branches: [main]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: |
{block}"""

# A tag carrying a newline and a second assignment, as a crafted workflow_dispatch
# `tag_name` could supply. `INJECTED` must never become an entry of its own.
CRAFTED_TAG = "v0.0.0\nINJECTED=yes"


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def _run_blocks(document: Any, path: str = "root") -> Iterator[Tuple[str, str]]:
    """Yield ``(location, script)`` for every `run:` block anywhere in the document."""
    if isinstance(document, dict):
        for key, value in document.items():
            child = "{}.{}".format(path, key)
            if key == "run":
                if not isinstance(value, str):
                    raise AssertionError("{} must be a string, got {}".format(child, type(value).__name__))
                yield child, value
            else:
                for found in _run_blocks(value, child):
                    yield found
    elif isinstance(document, list):
        for index, value in enumerate(document):
            for found in _run_blocks(value, "{}[{}]".format(path, index)):
                yield found


def _offending(document: Any, pattern: Any) -> List[str]:
    """Return `location: matched text` for every `run:` block matching `pattern`."""
    hits = []
    for location, script in _run_blocks(document):
        for match in pattern.finditer(script):
            hits.append("{}: {!r}".format(location, match.group(0)))
    return hits


def _workflow(run_block: str) -> str:
    indented = "".join("          {}\n".format(line) for line in run_block.splitlines())
    return WORKFLOW_WITH_RUN_BLOCK.format(block=indented)


def _run_block_in(run_block: str) -> str:
    """Return the single `run:` block of a generated single-step workflow."""
    return list(_run_blocks(yaml.safe_load(_workflow(run_block))))[0][1]


def _release_workflow() -> Any:
    return yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))


def _step_run_block(document: Any, step_name: str) -> str:
    """Return the `run:` block of the named step, whichever job holds it."""
    for job in document["jobs"].values():
        for step in job.get("steps", []):
            if step.get("name") == step_name and "run" in step:
                return step["run"]
    raise AssertionError("no run: block found for step {!r}".format(step_name))


# ---------------------------------------------------------------------------
# GITHUB_ENV helpers
# ---------------------------------------------------------------------------


def _env_writes(script: str) -> List[str]:
    """Return the payload of every statement in `script` that appends to GITHUB_ENV."""
    payloads = []
    for line in script.splitlines():
        match = GITHUB_ENV_WRITE.search(line)
        if match:
            payloads.append(match.group("payload"))
    return payloads


def _undelimited_assignments(script: str) -> List[str]:
    """Return `echo NAME=value` payloads written to GITHUB_ENV without a marker."""
    return [
        payload
        for payload in _env_writes(script)
        if GITHUB_ENV_ASSIGNMENT.search(payload) and not GITHUB_ENV_MARKER.search(payload)
    ]


def _opens_a_delimited_record(script: str) -> bool:
    return any(GITHUB_ENV_MARKER.search(payload) for payload in _env_writes(script))


def parse_github_env(raw: str) -> Dict[str, str]:
    """Parse a GITHUB_ENV file the way the Actions runner does.

    A line `NAME<<DELIMITER` opens a multi-line value that ends at a line equal to
    DELIMITER; any other `NAME=value` line is a single entry. This is the behaviour
    the whole guard rests on, so it is implemented here rather than assumed.
    """
    entries: Dict[str, str] = {}
    lines = raw.split("\n")
    index = 0
    while index < len(lines):
        line = lines[index].rstrip("\r")
        marker = re.match(r"^(\w+)<<(.*)$", line)
        if marker:
            name, delimiter = marker.group(1), marker.group(2)
            body = []
            index += 1
            while index < len(lines) and lines[index].rstrip("\r") != delimiter:
                body.append(lines[index].rstrip("\r"))
                index += 1
            entries[name] = "\n".join(body)
        elif "=" in line:
            name, _, value = line.partition("=")
            entries[name] = value
        index += 1
    return entries


# ---------------------------------------------------------------------------
# The workflow itself
# ---------------------------------------------------------------------------


def test_release_workflow_exists_and_parses() -> None:
    """A guard that silently reads nothing would pass while asserting nothing."""
    assert RELEASE_WORKFLOW.is_file(), "missing workflow under test: {}".format(RELEASE_WORKFLOW)
    document = _release_workflow()
    assert isinstance(document, dict), "the release workflow must be a YAML mapping"
    assert document.get("jobs"), "the release workflow must define jobs"


def test_release_workflow_has_run_blocks_to_guard() -> None:
    assert list(_run_blocks(_release_workflow())), "no run: block found, so the guards below are vacuous"


def test_no_actions_expression_is_interpolated_into_a_run_block() -> None:
    hits = _offending(_release_workflow(), EXPRESSION)

    assert not hits, "\n".join(
        [
            "run: blocks must not contain Actions expressions (${{ ... }}).",
            "They are expanded before the shell parses the script, so a dispatch input",
            'becomes shell source. Pass the value through env: and read it as "$VAR".',
            "",
        ]
        + hits
    )


def test_no_undelimited_github_env_assignment() -> None:
    document = _release_workflow()
    offenders = [
        "{}: {!r}".format(location, payload)
        for location, script in _run_blocks(document)
        for payload in _undelimited_assignments(script)
    ]

    assert not offenders, "\n".join(
        [
            'run: blocks must not write `echo "NAME=$VALUE" >> "$GITHUB_ENV"`.',
            "A value containing a newline then appends further entries. Write the",
            "`NAME<<DELIMITER` marker into the env file instead.",
            "",
        ]
        + offenders
    )


def test_the_release_tag_is_checked_before_it_reaches_the_archive_name() -> None:
    """The other half of the newline defence, and the only one that reaches `path:`.

    The delimiter write keeps newlines inside the ASSET value by design, and
    `upload-artifact` reads its `path:` as a newline-separated glob list. So the value
    must be constrained to a safe filename charset before it is allowed to become an
    archive name at all; the delimiter alone cannot stop that step from matching the
    wrong files.
    """
    script = _step_run_block(_release_workflow(), ARCHIVE_STEP)

    assert TAG_CHARSET_GUARD.search(script), (
        "the archive step must reject a RELEASE_TAG outside {!r} before building the archive name".format(
            SAFE_TAG_CHARSET
        )
    )
    # The check has to come first: validating after the archive exists is too late.
    assert script.index(ARCHIVE_NAME_ASSIGNMENT) > TAG_CHARSET_GUARD.search(script).start()
    assert "exit 1" in script


def test_every_github_env_write_opens_a_delimited_record() -> None:
    """Companion to the check above: every write that exists is delimited.

    Without this the assignment guard could be satisfied by deleting the write
    altogether, which would silently drop the ASSET output the next step reads.
    """
    document = _release_workflow()
    writes = [(location, script) for location, script in _run_blocks(document) if "GITHUB_ENV" in script]

    assert writes, "no run: block writes GITHUB_ENV, so the guards above are vacuous"

    undelimited = [location for location, script in writes if not _opens_a_delimited_record(script)]

    assert not undelimited, "GITHUB_ENV written without a NAME<<DELIMITER marker at: " + ", ".join(undelimited)


# ---------------------------------------------------------------------------
# End-to-end: the semantic authority for the GITHUB_ENV guard
# ---------------------------------------------------------------------------

_E2E_REASON = "the end-to-end proof needs bash and a filesystem that allows newlines in filenames"


def _run_under_bash(script: str, workdir: pathlib.Path, env: Dict[str, str]) -> Tuple[int, Dict[str, str], str]:
    """Run `script` under bash; return its exit code, parsed env entries and stderr."""
    script_path = workdir / "step.sh"
    script_path.write_bytes(script.replace("\r\n", "\n").encode("utf-8"))
    env_path = workdir / "github_env"
    env_path.write_bytes(b"")

    environment = {"PATH": os.environ.get("PATH", ""), "GITHUB_ENV": env_path.name}
    environment.update(env)
    result = subprocess.run(
        [shutil.which("bash"), script_path.name],
        cwd=str(workdir),
        env={**environment, "GITHUB_ENV": env_path.name},
        capture_output=True,
    )
    entries = parse_github_env(env_path.read_text(encoding="utf-8"))
    return result.returncode, entries, result.stderr.decode("utf-8", "replace")


def _run_archive_step(tmp_path: pathlib.Path, tag: str) -> Tuple[int, Dict[str, str], str]:
    (tmp_path / "dist" / "standalone").mkdir(parents=True)
    (tmp_path / "dist" / "standalone" / "server").write_text("binary", encoding="utf-8")
    return _run_under_bash(
        _step_run_block(_release_workflow(), ARCHIVE_STEP),
        tmp_path,
        {"RELEASE_TAG": tag, "ASSET_SUFFIX": "linux-X64", "RUNNER_OS_NAME": "Linux"},
    )


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None, reason=_E2E_REASON)
def test_a_valid_tag_still_produces_exactly_one_asset_entry(tmp_path) -> None:
    """The archive step keeps working for the tags it is meant to receive."""
    code, entries, stderr = _run_archive_step(tmp_path, "v0.3.7")

    assert code == 0, stderr
    assert list(entries) == ["ASSET"], entries
    assert entries["ASSET"] == "dcc-mcp-unreal-v0.3.7-linux-X64.tar.gz"


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None, reason=_E2E_REASON)
def test_a_tag_outside_the_safe_charset_is_rejected_before_any_write(tmp_path) -> None:
    """The guard the P2 finding asked for, proven by running the real step.

    `upload-artifact` reads `path:` as a newline-separated glob list, so a tag
    carrying a newline would upload whatever the extra lines match. The step must
    refuse the tag instead of building an archive or writing ASSET at all.
    """
    for index, tag in enumerate((CRAFTED_TAG, "v0\npyproject.toml", "release/v1.0.0", "../escape", "", "v1;rm -rf /")):
        # One scratch tree per tag: the assertion is that nothing is created at all.
        scratch = tmp_path / "case{}".format(index)
        scratch.mkdir()

        code, entries, _ = _run_archive_step(scratch, tag)

        assert code != 0, "the step accepted the unsafe tag {!r}".format(tag)
        assert "ASSET" not in entries, "the step wrote ASSET for the unsafe tag {!r}".format(tag)
        assert not list(scratch.glob("*.tar.gz")), "the step archived the unsafe tag {!r}".format(tag)


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None, reason=_E2E_REASON)
def test_the_end_to_end_proof_distinguishes_delimited_from_plain_writes(tmp_path) -> None:
    """Teeth for the test above: it must fail for the un-delimited form.

    Without this the end-to-end test could pass for a reason unrelated to the
    delimiter, which is exactly how a shell heredoc slipped through.
    """
    setup = 'base="dcc-mcp-unreal-{}-linux-X64"\n'.format(CRAFTED_TAG)
    plain = setup + 'echo "ASSET=${base}.tar.gz" >> "$GITHUB_ENV"\n'
    delimited = (
        setup
        + 'asset="${base}.tar.gz"\n'
        + 'echo "ASSET<<ASSET_EOF" >> "$GITHUB_ENV"\n'
        + 'printf \'%s\\n\' "$asset" >> "$GITHUB_ENV"\n'
        + 'echo "ASSET_EOF" >> "$GITHUB_ENV"\n'
    )
    # The shell heredoc that looks like a fix but is not: it must behave like `plain`.
    heredoc = (
        setup + 'asset="${base}.tar.gz"\n' + 'cat >> "$GITHUB_ENV" <<ASSET_EOF\n' + "ASSET=${asset}\n" + "ASSET_EOF\n"
    )

    _, plain_entries, _ = _run_under_bash(plain, tmp_path, {})
    _, delimited_entries, _ = _run_under_bash(delimited, tmp_path, {})
    _, heredoc_entries, _ = _run_under_bash(heredoc, tmp_path, {})

    assert "INJECTED" in plain_entries
    assert "INJECTED" in heredoc_entries, "a shell heredoc is not a delimiter: it leaks like a plain echo"
    assert list(delimited_entries) == ["ASSET"]
    assert "INJECTED" not in delimited_entries


# ---------------------------------------------------------------------------
# Teeth for the static rules
# ---------------------------------------------------------------------------


def test_the_interpolation_guard_fires_on_a_real_expression() -> None:
    assert _run_block_in(CLEAN_RUN_BLOCK) == CLEAN_RUN_BLOCK, "fixture setup broke"
    assert _run_block_in(INTERPOLATED_RUN_BLOCK) == INTERPOLATED_RUN_BLOCK, "fixture setup broke"

    clean = _offending(yaml.safe_load(_workflow(CLEAN_RUN_BLOCK)), EXPRESSION)
    interpolated = _offending(yaml.safe_load(_workflow(INTERPOLATED_RUN_BLOCK)), EXPRESSION)

    assert clean == []
    assert len(interpolated) == 1
    assert "${{ github.event.inputs.tag_name }}" in interpolated[0]


def test_the_github_env_guard_fires_on_an_undelimited_assignment() -> None:
    clean = _undelimited_assignments(CLEAN_RUN_BLOCK)
    appended = _undelimited_assignments(UNQUOTED_ENV_RUN_BLOCK)
    delimited = _undelimited_assignments(DELIMITED_ENV_RUN_BLOCK)

    assert clean == []
    assert len(appended) == 1
    assert delimited == []


def test_the_delimited_form_opens_a_record_and_the_old_form_does_not() -> None:
    assert _opens_a_delimited_record(DELIMITED_ENV_RUN_BLOCK)
    assert not _opens_a_delimited_record(UNQUOTED_ENV_RUN_BLOCK)
    assert not _opens_a_delimited_record(CLEAN_RUN_BLOCK)


def test_a_shell_heredoc_is_not_accepted_as_a_delimited_write() -> None:
    """Regression anchor for the mistake this guard was written to prevent.

    `cat >> "$GITHUB_ENV" <<EOF` never puts a marker in the env file, so it must not
    satisfy the delimiter rule.
    """
    heredoc = (
        'asset="dcc-mcp-unreal-v0.0.0-linux-X64.zip"\ncat >> "$GITHUB_ENV" <<ASSET_EOF\nASSET=${asset}\nASSET_EOF\n'
    )

    assert not _opens_a_delimited_record(heredoc)


def test_parse_github_env_matches_the_documented_behaviour() -> None:
    """The parser the end-to-end assertions rest on, pinned against the spec."""
    assert parse_github_env("A=1\nB=2\n") == {"A": "1", "B": "2"}
    assert parse_github_env("A<<EOF\nline1\nline2\nEOF\nB=3\n") == {"A": "line1\nline2", "B": "3"}
    # An un-delimited value with a newline splits into a second entry.
    assert parse_github_env("A=one\nB=two\n") == {"A": "one", "B": "two"}
