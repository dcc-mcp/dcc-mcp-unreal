"""Repository-local safety guards for `run:` blocks in the release workflow.

This file is **not** part of the shared kit. `tests/test_release_workflow_integrity.py`
is the byte-identical kit copy and only binds the workflow to an approved digest; it
deliberately carries no repository-specific policy. These assertions are the ones we
own here, and they exist to stop two regressions from coming back:

* `${{ }}` inside a `run:` block. An Actions expression is expanded by the runner
  *before* the shell parses the script, so an attacker-influenced value such as a
  `workflow_dispatch` input becomes literal shell source. Passing the same value
  through `env:` and reading it as `"$VAR"` keeps it as data.

* A single-line `echo "NAME=$VALUE" >> "$GITHUB_ENV"`. A value containing a newline
  appends extra `GITHUB_ENV` entries. The delimiter form
  (`NAME<<EOF` / value / `EOF`) bounds the value, so a newline inside it stays part
  of the value instead of starting a new entry.

Both guards are fail-closed: they walk the parsed document rather than grepping, so
they cover `run:` blocks anywhere in the structure, including ones added later to a
new job, a composite step, or a reusable-workflow call.

PyYAML is requested through `pytest.importorskip`, matching the kit copy: a test
environment without PyYAML skips this module instead of failing collection. PyYAML is
a declared dev dependency (`pyyaml>=5.0`), so in CI every assertion below runs.
"""

from __future__ import annotations

import pathlib
import re
from typing import Any, Iterator, List, Tuple

import pytest

yaml = pytest.importorskip("yaml", reason="the release workflow run-safety guards need PyYAML")

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"

# An Actions expression, as the runner recognises it: `${{ ... }}`, non-greedy so two
# expressions on one line are reported as two hits rather than one spanning range.
EXPRESSION = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)

# `$GITHUB_ENV` or `${GITHUB_ENV}`, with or without surrounding quotes.
GITHUB_ENV_TARGET = r"\"?(?:\$\{GITHUB_ENV\}|\$GITHUB_ENV)\"?"

# `echo ... >> "$GITHUB_ENV"` on a single line, i.e. the un-delimited append form.
# Any quoting of the echoed text matches.
GITHUB_ENV_APPEND = re.compile(r"(?:^|\n)\s*echo\s+[^\n]*>>\s*" + GITHUB_ENV_TARGET)

# The form this repository requires instead: one heredoc statement that opens the
# delimiter and writes the value in a single step, e.g. `cat >> "$GITHUB_ENV" <<EOF`.
# The echo-per-line spelling GitHub also documents is deliberately not accepted: it is
# safe only as a complete opening/value/terminator triple, which no per-line rule can
# verify, so this repository standardises on the single-statement form.
GITHUB_ENV_HEREDOC = re.compile(r">>\s*" + GITHUB_ENV_TARGET + r"\s*<<\s*\w+")

CLEAN_RUN_BLOCK = "echo nothing to see here\n"

# A `run:` block that interpolates an Actions expression directly into shell source.
INTERPOLATED_RUN_BLOCK = 'echo "tag=${{ github.event.inputs.tag_name }}"\n'

# A `run:` block that appends an untrusted value to GITHUB_ENV on a single line.
UNQUOTED_ENV_RUN_BLOCK = 'echo "ASSET=${base}.zip" >> "$GITHUB_ENV"\n'

# The form the release workflow is required to use.
REQUIRED_ENV_RUN_BLOCK = (
    'asset="dcc-mcp-unreal-v0.0.0-linux-X64.zip"\ncat >> "$GITHUB_ENV" <<ASSET_EOF\nASSET=${asset}\nASSET_EOF\n'
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


def _uses_heredoc_form(script: str) -> bool:
    return bool(GITHUB_ENV_HEREDOC.search(script))


def _workflow(run_block: str) -> str:
    indented = "".join("          {}\n".format(line) for line in run_block.splitlines())
    return WORKFLOW_WITH_RUN_BLOCK.format(block=indented)


def _run_block_in(run_block: str) -> str:
    """Return the single `run:` block of a generated single-step workflow."""
    return list(_run_blocks(yaml.safe_load(_workflow(run_block))))[0][1]


def _release_workflow() -> Any:
    return yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))


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


def test_no_single_line_github_env_append() -> None:
    hits = _offending(_release_workflow(), GITHUB_ENV_APPEND)

    assert not hits, "\n".join(
        [
            'run: blocks must write GITHUB_ENV with one heredoc (cat >> "$GITHUB_ENV" <<EOF).',
            "A single-line echo lets a value containing a newline append extra entries.",
            "",
        ]
        + hits
    )


def test_every_github_env_write_uses_the_heredoc_form() -> None:
    """Companion to the check above: every write that exists is delimited.

    Without this the append guard could be satisfied by deleting the write
    altogether, which would silently drop the ASSET output the next step reads.
    """
    writes = [(location, script) for location, script in _run_blocks(_release_workflow()) if "GITHUB_ENV" in script]

    assert writes, "no run: block writes GITHUB_ENV, so the append guard above is vacuous"

    undelimited = [location for location, script in writes if not _uses_heredoc_form(script)]

    assert not undelimited, "GITHUB_ENV written without a delimiter at: " + ", ".join(undelimited)


def test_the_interpolation_guard_fires_on_a_real_expression() -> None:
    """Proof the guard is not vacuous: an interpolated block must be caught."""
    assert _run_block_in(CLEAN_RUN_BLOCK) == CLEAN_RUN_BLOCK, "fixture setup broke"
    assert _run_block_in(INTERPOLATED_RUN_BLOCK) == INTERPOLATED_RUN_BLOCK, "fixture setup broke"

    clean = _offending(yaml.safe_load(_workflow(CLEAN_RUN_BLOCK)), EXPRESSION)
    interpolated = _offending(yaml.safe_load(_workflow(INTERPOLATED_RUN_BLOCK)), EXPRESSION)

    assert clean == []
    assert len(interpolated) == 1
    assert "${{ github.event.inputs.tag_name }}" in interpolated[0]


def test_the_github_env_guard_fires_on_a_single_line_append() -> None:
    """Proof the guard is not vacuous: an un-delimited append must be caught."""
    clean = _offending(yaml.safe_load(_workflow(CLEAN_RUN_BLOCK)), GITHUB_ENV_APPEND)
    appended = _offending(yaml.safe_load(_workflow(UNQUOTED_ENV_RUN_BLOCK)), GITHUB_ENV_APPEND)

    assert clean == []
    assert len(appended) == 1


def test_the_required_heredoc_form_passes_both_github_env_guards() -> None:
    """The form the workflow uses must satisfy the guard that enforces it."""
    document = yaml.safe_load(_workflow(REQUIRED_ENV_RUN_BLOCK))

    assert _offending(document, GITHUB_ENV_APPEND) == []
    assert _uses_heredoc_form(REQUIRED_ENV_RUN_BLOCK)


def test_the_echo_per_line_form_is_rejected_by_policy() -> None:
    """The other documented spelling is refused, so the policy stays one statement.

    Its safety depends on the opening, value and terminator lines all being present,
    which a per-line rule cannot verify, so it is not accepted here.
    """
    echo_form = (
        'echo "ASSET<<ASSET_EOF" >> "$GITHUB_ENV"\n'
        'echo "${asset}" >> "$GITHUB_ENV"\n'
        'echo "ASSET_EOF" >> "$GITHUB_ENV"\n'
    )

    assert _offending(yaml.safe_load(_workflow(echo_form)), GITHUB_ENV_APPEND)
    assert not _uses_heredoc_form(echo_form)
