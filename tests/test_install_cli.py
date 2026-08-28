from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.9/3.10 CI
    import tomli as tomllib

import dcc_mcp_core
import pytest
from jsonschema import Draft202012Validator

from dcc_mcp_unreal import install_cli

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "tests" / "fixtures" / "adapter-install-sop-v1.schema.json"
CORE_2320_SCHEMA_SHA256 = "3ca25788439917b4d4c0617230a762f9797756b5b54f45c8c4149f975b90f904"


def _assert_sop_v1(result: dict) -> None:
    assert {
        "schema_version",
        "status",
        "dcc_type",
        "adapter_version",
        "core_version",
        "steps",
        "next_steps",
        "receipt_path",
        "verify",
    } <= result.keys()
    assert result["schema_version"] == 1
    assert result["status"] in {"planned", "running", "ok", "failed", "partial", "requires_restart"}
    assert set(result["verify"]) >= {"directly_usable", "failure_stage", "failure_reason"}
    for next_step in result["next_steps"]:
        assert set(next_step) >= {"id", "description", "why"}
        assert ("command" in next_step) ^ ("file_edit" in next_step)
    schema_bytes = SCHEMA_PATH.read_bytes()
    assert hashlib.sha256(schema_bytes).hexdigest() == CORE_2320_SCHEMA_SHA256
    schema = json.loads(schema_bytes)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(result)


def _cli_env() -> dict[str, str]:
    env = os.environ.copy()
    source = str(REPO_ROOT / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = source if not existing else source + os.pathsep + existing
    return env


def _run_cli(
    tmp_path: Path,
    *arguments: str,
    env_overrides: Optional[dict[str, str]] = None,
) -> subprocess.CompletedProcess[str]:
    env = _cli_env()
    env.update(env_overrides or {})
    return subprocess.run(
        [sys.executable, "-m", "dcc_mcp_unreal.install_cli", *arguments],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def _sop_diagnostic_text(value: object, args: object, limit: int) -> str:
    # OSError renders filenames with repr-escaped backslashes on Windows.
    text = str(value or "").replace("\\\\", "\\").replace("\\", "/")
    roots = [(str(REPO_ROOT).replace("\\", "/"), "<source>")]
    for attribute, label in (("project", "<project>"), ("dcc_path", "<engine>"), ("python", "<python>")):
        root = str(getattr(args, attribute, "") or "").replace("\\", "/")
        if attribute in {"project", "python"}:
            root = root.rsplit("/", 1)[0] if "/" in root else ""
        if root:
            roots.append((root, label))
    for root, label in sorted(roots, key=lambda item: len(item[0]), reverse=True):
        text = re.sub(re.escape(root) + r"(?=/|$|['\"])", label, text, flags=re.IGNORECASE)
    text = re.sub(r"https?://\S+", "<url>", text, flags=re.IGNORECASE)
    text = re.sub(r"(['\"])(?:[A-Za-z]:/|/)[^'\"\r\n]*\1", "'<path>'", text)
    text = re.sub(r"(?<![\w>])(?:[A-Za-z]:/|/)[^\r\n,;]+", "<path>", text)
    text = re.sub(
        r"\b((?:[\w-]*[_-])?(?:password|passwd|secret|token|api[_-]?key|authorization))\s*[:=]\s*('[^']*'|\"[^\"]*\"|(?:(?:Bearer|Basic)\s+)?[^\s,;]+)",
        r"\1=<redacted>",
        text,
        flags=re.IGNORECASE,
    )
    if len(text) > limit:
        text = text[: limit // 2] + "...<truncated>..." + text[-limit // 2 :]
    return text


def _publish_path_state(path: Path, label: str) -> dict:
    state = {"path": label}
    try:
        info = path.lstat()
        state.update(
            exists=True,
            device=info.st_dev,
            inode=info.st_ino,
            mode=info.st_mode,
            attributes=getattr(info, "st_file_attributes", None),
            reparse_tag=getattr(info, "st_reparse_tag", None),
            links=info.st_nlink,
        )
    except FileNotFoundError:
        state["exists"] = False
    except BaseException:
        state["probe"] = "unknown"
    return state


def _publish_acl(path: Path, project: Path) -> dict:
    if sys.platform != "win32":
        return {"status": "unknown", "reason": "scoped_acl_probe_unavailable"}
    try:
        for candidate in (path, path.parent, project):
            if candidate.lstat().st_file_attributes & 0x400:
                return {"status": "unknown", "reason": "reparse_path"}
        result = subprocess.run(["icacls", str(path)], capture_output=True, text=True, timeout=2, check=False)
        if result.returncode:
            return {"status": "unknown", "reason": "acl_query_failed"}
        # Retain permission flags only, never account names or filesystem paths.
        allowed = {
            "I",
            "OI",
            "CI",
            "IO",
            "NP",
            "F",
            "M",
            "RX",
            "R",
            "W",
            "D",
            "N",
            "DE",
            "RC",
            "WDAC",
            "WO",
            "S",
            "AS",
            "MA",
            "GR",
            "GW",
            "GE",
            "GA",
            "RD",
            "WD",
            "AD",
            "REA",
            "WEA",
            "X",
            "DC",
            "RA",
            "WA",
        }
        flags = re.findall(r"\([A-Z,]+\)", result.stdout[:4096])
        return {
            "status": "observed",
            "permission_flags": [flag for flag in flags if set(flag[1:-1].split(",")) <= allowed][:32],
            "truncated": len(result.stdout) > 4096,
        }
    except BaseException:
        return {"status": "unknown", "reason": "acl_query_unavailable"}


@contextmanager
def _observe_publish_failures(args: object):
    failures = []
    project_value = getattr(args, "project", None)
    if not project_value or not Path(project_value).is_absolute():
        yield failures
        return
    project = Path(project_value).parent
    parent = project / "Plugins"
    original = install_cli.os.replace

    def observed(source, destination, *positional, **keywords):
        try:
            src, dst = Path(source), Path(destination)
            scoped = (
                src.parent == parent
                and re.fullmatch(r"\.DccMcpUnreal\.staging-[0-9a-f]{32}", src.name)
                and dst == parent / "DccMcpUnreal"
            )
        except BaseException:
            scoped = False
        if not scoped:
            return original(source, destination, *positional, **keywords)
        paths = ((src, "staging"), (dst, "plugin"), (parent, "parent"))
        try:
            before = [_publish_path_state(path, label) for path, label in paths]
        except BaseException:
            before = {"status": "unknown", "reason": "metadata_probe_failed"}
        try:
            return original(source, destination, *positional, **keywords)
        except BaseException as primary:
            try:
                record = {
                    "operation": "staging_to_plugin",
                    "errno": getattr(primary, "errno", None),
                    "winerror": getattr(primary, "winerror", None),
                    "before": before,
                    "after": [_publish_path_state(path, label) for path, label in paths],
                    "acl": [_publish_acl(path, project) for path, _label in paths],
                    "holder": {"status": "unknown", "reason": "no_safe_scoped_holder_query"},
                }
                if len(json.dumps(record, ensure_ascii=True)) > 4096:
                    record = {"status": "unknown", "reason": "diagnostic_size_limit"}
                if not failures:
                    failures.append(record)
            except BaseException:
                if not failures:
                    failures.append({"status": "unknown", "reason": "diagnostic_probe_failed"})
            raise

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(install_cli.os, "replace", observed)
        yield failures


def _execute_expect(args: object, expected_exit: int) -> dict:
    with _observe_publish_failures(args) as publish_failures:
        exit_code, result = install_cli._execute(args)
    if exit_code != expected_exit:
        verify = result.get("verify") or {}
        diagnostic = {"expected_exit": expected_exit, "actual_exit": exit_code}
        for field, value, limit in (
            ("operation", getattr(args, "verb", ""), 64),
            ("status", result.get("status"), 64),
            ("failure_stage", verify.get("failure_stage"), 64),
            ("failure_reason", verify.get("failure_reason"), 768),
        ):
            diagnostic[field] = _sop_diagnostic_text(value, args, limit)
        if publish_failures:
            diagnostic["publish_failure"] = publish_failures[0]
        # Explicit string exception avoids pytest's truncated safe repr of a dict.
        raise AssertionError("INSTALL_SOP_DIAGNOSTIC " + json.dumps(diagnostic, sort_keys=True))
    return result


@pytest.fixture(autouse=True)
def _isolate_external_lock_inspection(monkeypatch) -> None:
    monkeypatch.setattr(install_cli, "_inspect_locks", lambda _path: None)


def test_execute_expectation_reports_the_lifecycle_result(monkeypatch) -> None:
    monkeypatch.setattr(
        install_cli,
        "_execute",
        lambda _args: (50, {"verify": {"failure_reason": "locked synthetic path"}}),
    )

    with pytest.raises(AssertionError, match="locked synthetic path"):
        _execute_expect(object(), 40)


def test_publish_observer_preserves_once_only_failure(monkeypatch, tmp_path: Path) -> None:
    parent = tmp_path / "Sample" / "Plugins"
    source = parent / (".DccMcpUnreal.staging-" + "a" * 32)
    source.mkdir(parents=True)
    destination = parent / "DccMcpUnreal"
    error = PermissionError(13, "PRIVATE_ERROR_SECRET", str(source))
    calls = []

    def replace(src, dst):
        calls.append((src, dst))
        raise error

    monkeypatch.setattr(install_cli.os, "replace", replace)
    args = SimpleNamespace(project=str(parent.parent / "Sample.uproject"))
    with pytest.raises(PermissionError) as caught:
        with _observe_publish_failures(args) as failures:
            install_cli.os.replace(source, destination)
    assert caught.value is error and calls == [(source, destination)]
    assert len(failures) == 1 and failures[0]["errno"] == 13
    assert failures[0]["before"][1]["exists"] is False
    assert failures[0]["after"][0]["inode"] == source.stat().st_ino
    assert "PRIVATE_ERROR_SECRET" not in json.dumps(failures)
    assert str(tmp_path) not in json.dumps(failures)


@pytest.mark.parametrize("probe", ["metadata", "acl"])
def test_publish_observer_probe_failure_preserves_primary(monkeypatch, tmp_path: Path, probe: str) -> None:
    parent = tmp_path / "Plugins"
    source = parent / (".DccMcpUnreal.staging-" + "b" * 32)
    source.mkdir(parents=True)
    destination = parent / "DccMcpUnreal"
    primary = PermissionError(13, "PRIVATE_SECRET")
    calls = []

    def replace(src, dst):
        calls.append((src, dst))
        raise primary

    def broken_probe(*_args):
        raise KeyboardInterrupt("PRIVATE_PROBE_SECRET")

    monkeypatch.setattr(install_cli.os, "replace", replace)
    monkeypatch.setitem(globals(), "_publish_path_state" if probe == "metadata" else "_publish_acl", broken_probe)
    with pytest.raises(PermissionError) as caught:
        with _observe_publish_failures(SimpleNamespace(project=str(tmp_path / "Sample.uproject"))) as failures:
            install_cli.os.replace(source, destination)
    assert caught.value is primary and calls == [(source, destination)]
    assert install_cli.os.replace is replace
    assert failures == [{"status": "unknown", "reason": "diagnostic_probe_failed"}]


def test_publish_observer_success_and_foreign_calls_are_not_retried(monkeypatch, tmp_path: Path) -> None:
    parent = tmp_path / "Plugins"
    source = parent / (".DccMcpUnreal.staging-" + "c" * 32)
    destination = parent / "DccMcpUnreal"
    marker = object()
    calls = []

    def replace(*args, **kwargs):
        calls.append((args, kwargs))
        return marker

    def forbidden_acl(*_args):
        pytest.fail("Success must not query ACLs")

    monkeypatch.setattr(install_cli.os, "replace", replace)
    monkeypatch.setitem(globals(), "_publish_acl", forbidden_acl)
    with _observe_publish_failures(SimpleNamespace(project=str(tmp_path / "Sample.uproject"))) as failures:
        assert install_cli.os.replace(source, destination) is marker
        assert install_cli.os.replace("foreign-source", "foreign-destination", src_dir_fd=17) is marker
    assert failures == []
    assert calls == [((source, destination), {}), (("foreign-source", "foreign-destination"), {"src_dir_fd": 17})]
    assert install_cli.os.replace is replace


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL output contract")
def test_publish_acl_is_private_and_bounded(monkeypatch, tmp_path: Path) -> None:
    calls = []

    def query(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="PRIVATE_OWNER:(PASSWORD)(I)(OI)(CI)(F)\n" * 1000)

    monkeypatch.setattr(subprocess, "run", query)
    result = _publish_acl(tmp_path, tmp_path)
    encoded = json.dumps(result)
    assert "PRIVATE_OWNER" not in encoded and "PASSWORD" not in encoded
    assert len(result["permission_flags"]) <= 32 and len(encoded) < 1024
    assert result["truncated"] is True
    assert len(calls) == 1 and calls[0][0] == ["icacls", str(tmp_path)]
    assert calls[0][1]["timeout"] == 2


def test_publish_observer_mismatch_retains_primary_result(monkeypatch, tmp_path: Path) -> None:
    parent = tmp_path / "Plugins"
    source = parent / (".DccMcpUnreal.staging-" + "d" * 32)
    source.mkdir(parents=True)
    destination = parent / "DccMcpUnreal"
    primary = PermissionError(13, "PRIVATE_SECRET", str(source))
    result = {
        "status": "requires_restart",
        "verify": {"failure_stage": "install", "failure_reason": "primary sentinel"},
    }
    before_result = json.dumps(result)
    calls = []

    def replace(src, dst):
        calls.append((src, dst))
        raise primary

    def execute(_args):
        with pytest.raises(PermissionError) as caught:
            install_cli.os.replace(source, destination)
        assert caught.value is primary
        return 50, result

    monkeypatch.setattr(install_cli.os, "replace", replace)
    monkeypatch.setattr(install_cli, "_execute", execute)
    with pytest.raises(AssertionError) as caught:
        _execute_expect(SimpleNamespace(verb="install", project=str(tmp_path / "Sample.uproject")), 40)
    encoded = str(caught.value).removeprefix("INSTALL_SOP_DIAGNOSTIC ")
    diagnostic = json.loads(encoded)
    assert diagnostic["expected_exit"] == 40 and diagnostic["actual_exit"] == 50
    assert diagnostic["failure_reason"] == "primary sentinel"
    assert diagnostic["publish_failure"]["errno"] == 13
    assert calls == [(source, destination)] and json.dumps(result) == before_result
    assert "PRIVATE_SECRET" not in encoded and str(tmp_path) not in encoded and len(encoded) < 8192


def test_publish_observer_oversized_probe_keeps_exception(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "Plugins" / (".DccMcpUnreal.staging-" + "e" * 32)
    destination = source.parent / "DccMcpUnreal"
    primary = PermissionError(13, "PRIMARY_PRIVATE_SECRET")
    calls = []

    def replace(src, dst):
        calls.append((src, dst))
        raise primary

    monkeypatch.setattr(install_cli.os, "replace", replace)
    monkeypatch.setitem(globals(), "_publish_path_state", lambda *_args: {"unexpected": "PRIVATE_PROBE_SECRET" * 10000})
    with pytest.raises(PermissionError) as caught:
        with _observe_publish_failures(SimpleNamespace(project=str(tmp_path / "Sample.uproject"))) as failures:
            install_cli.os.replace(source, destination)
    assert caught.value is primary and calls == [(source, destination)]
    assert failures == [{"status": "unknown", "reason": "diagnostic_size_limit"}]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL output contract")
@pytest.mark.parametrize("mode", ["reparse", "query_error", "interrupted"])
def test_publish_acl_absence_is_unknown(monkeypatch, tmp_path: Path, mode: str) -> None:
    calls = []

    def query(*_args, **_kwargs):
        calls.append(True)
        if mode == "interrupted":
            raise KeyboardInterrupt("PRIVATE_PROBE_SECRET")
        return SimpleNamespace(returncode=5, stdout="PRIVATE_ACCOUNT")

    monkeypatch.setattr(subprocess, "run", query)
    if mode == "reparse":
        monkeypatch.setattr(Path, "lstat", lambda _path: SimpleNamespace(st_file_attributes=0x400))
    result = _publish_acl(tmp_path, tmp_path)
    assert result["status"] == "unknown" and "PRIVATE" not in json.dumps(result)
    assert len(calls) == (0 if mode == "reparse" else 1)


@pytest.mark.parametrize("oversized,windows_path", [(False, False), (False, True), (True, True)])
def test_execute_expectation_survives_pytest_reporting(tmp_path: Path, oversized: bool, windows_path: bool) -> None:
    fixture_root = tmp_path / "reporter"
    fixture_root.mkdir()
    config = fixture_root / "pytest.ini"
    config.write_text(f'[pytest]\npythonpath = "{(REPO_ROOT / "tests").as_posix()}"\n', encoding="utf-8")
    (tmp_path / "conftest.py").write_text("raise RuntimeError('UNRELATED_ANCESTOR_COLLECTED')\n", encoding="utf-8")
    (fixture_root / "test_unrelated.py").write_text(
        "raise RuntimeError('UNRELATED_FILE_COLLECTED')\n", encoding="utf-8"
    )
    private_root = "C:/Users/PRIVATE_OWNER/Workspace/Sample"
    reason = (
        "A loaded Unreal plugin artifact requires restart: [WinError 5] Access is denied: "
        f"'{private_root}/Plugins/.DccMcpUnreal.staging-123/Content/Python/DIAG_PATH_SENTINEL.py'"
    )
    if windows_path:
        filename = (private_root + "/Plugins/.DccMcpUnreal.staging-123/Content/Python/DIAG_PATH_SENTINEL.py").replace(
            "/", "\\"
        )
        reason = "A loaded Unreal plugin artifact requires restart: " + str(
            PermissionError(13, "Access is denied", filename)
        )
    if oversized:
        reason = (
            "os.replace password='INNER_SECRET' authorization=Bearer AUTH_SECRET; SERVICE_API_KEY=INLINE_API_SECRET; "
            "unknown 'C:/Users/OTHER_OWNER/private/file.dll'; '/home/POSIX_OWNER/private'; "
            "'//PRIVATE_SERVER/share/file'; https://URL_USER:URL_PASSWORD@example.test/?token=URL_TOKEN; "
            + "bounded padding " * 1000
            + reason
        )
    result = {
        "schema_version": 1,
        "status": "requires_restart",
        "dcc_type": "unreal",
        "adapter_version": "0.3.4",
        "core_version": "0.20.21",
        "steps": [{"id": "copy", "message": "unrelated payload " * 100}] * 50,
        "credentials": {"password": "DO_NOT_PRINT_CREDENTIAL"},
        "environment": {"PRIVATE_ENV": "DO_NOT_PRINT_ENV"},
        "verify": {"directly_usable": False, "failure_stage": "install", "failure_reason": reason},
    }
    data = fixture_root / "report.json"
    data.write_text(
        json.dumps(
            {
                "args": {"verb": "install", "project": private_root + "/Sample.uproject"},
                "result": result,
                "helper_origin": str(Path(__file__).resolve()),
            }
        ),
        encoding="utf-8",
    )
    child = fixture_root / "test_report.py"
    child.write_text(
        "import json\nfrom pathlib import Path\nfrom types import SimpleNamespace\n"
        "from test_install_cli import _execute_expect, install_cli, __file__ as helper_origin\n\n"
        "def test_mismatch(monkeypatch):\n"
        "    data = json.loads(Path(__file__).with_name('report.json').read_text(encoding='utf-8'))\n"
        "    assert Path(helper_origin).resolve() == Path(data['helper_origin']).resolve()\n"
        "    monkeypatch.setattr(install_cli, '_execute', lambda args: (50, data['result']))\n"
        "    _execute_expect(SimpleNamespace(**data['args']), 0)\n",
        encoding="utf-8",
    )
    env = _cli_env()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(REPO_ROOT / "tests") + os.pathsep + env["PYTHONPATH"]
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(child),
            "-c",
            str(config),
            "--rootdir",
            str(fixture_root),
            "--confcutdir",
            str(fixture_root),
            "-o",
            "addopts=",
            "-q",
            "--tb=short",
            "--color=no",
            "-p",
            "no:cacheprovider",
        ],
        cwd=fixture_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    (tmp_path / "stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (tmp_path / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
    (tmp_path / "exit.json").write_text(json.dumps({"exit_code": completed.returncode}), encoding="utf-8")
    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert re.search(r"\b1 failed in ", completed.stdout)
    assert " passed" not in completed.stdout and "UNRELATED_" not in completed.stdout + completed.stderr
    assert "DIAG_PATH_SENTINEL.py" in completed.stdout
    marker = "INSTALL_SOP_DIAGNOSTIC "
    line = next(
        line.split(marker, 1)[1] for line in completed.stdout.splitlines() if line.startswith("E ") and marker in line
    )
    diagnostic = json.loads(line)
    assert diagnostic["expected_exit"] == 0 and diagnostic["actual_exit"] == 50
    assert diagnostic["operation"] == "install"
    assert diagnostic["status"] == "requires_restart" and diagnostic["failure_stage"] == "install"
    assert "<project>/Plugins/" in diagnostic["failure_reason"]
    assert ("Errno 13" if windows_path else "WinError 5") in diagnostic["failure_reason"]
    assert len(line) <= 8192
    if oversized:
        assert "<truncated>" in diagnostic["failure_reason"] and "os.replace" in diagnostic["failure_reason"]
    for hidden in (
        "PRIVATE_OWNER",
        "DO_NOT_PRINT_CREDENTIAL",
        "DO_NOT_PRINT_ENV",
        "INNER_SECRET",
        "AUTH_SECRET",
        "INLINE_API_SECRET",
        "OTHER_OWNER",
        "POSIX_OWNER",
        "PRIVATE_SERVER",
        "URL_PASSWORD",
        "URL_TOKEN",
    ):
        assert hidden not in completed.stdout + completed.stderr


@pytest.mark.parametrize("expected_exit", [0, 40, 50])
def test_execute_expectation_returns_unchanged_expected_result(monkeypatch, capsys, expected_exit: int) -> None:
    result = {
        "status": {0: "ok", 40: "failed", 50: "requires_restart"}[expected_exit],
        "verify": {"failure_reason": "kept verbatim"},
    }
    calls = []
    args = object()

    def execute(actual_args):
        calls.append(actual_args)
        return expected_exit, result

    monkeypatch.setattr(install_cli, "_execute", execute)
    assert _execute_expect(args, expected_exit) is result
    assert calls == [args] and result["verify"]["failure_reason"] == "kept verbatim"
    assert capsys.readouterr() == ("", "")


def test_lifecycle_unit_boundary_does_not_use_external_lock_inspection(monkeypatch, tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    common = [
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--timeout",
        "0",
    ]
    install_args = install_cli._parser().parse_args(["install", *common, "--yes"])
    _execute_expect(install_args, 40)
    receipt_path = project.parent / ".dcc-mcp" / "receipts" / "unreal.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["adapter_version"] = "0.2.9"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    def fail_external_inspection(_path: Path) -> dict:
        raise AssertionError("external Windows lock inspection escaped the unit boundary")

    monkeypatch.setattr(dcc_mcp_core, "inspect_install_root", fail_external_inspection)
    upgrade_args = install_cli._parser().parse_args(["upgrade", *common, "--yes"])

    _execute_expect(upgrade_args, 40)


def test_upgrade_preserves_restart_semantics_for_an_injected_plugin_lock(monkeypatch, tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    common = [
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--timeout",
        "0",
    ]
    install_args = install_cli._parser().parse_args(["install", *common, "--yes"])
    _execute_expect(install_args, 40)
    receipt_path = project.parent / ".dcc-mcp" / "receipts" / "unreal.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["adapter_version"] = "0.2.9"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(install_cli, "_inspect_locks", lambda _path: "DccMcpUnreal.dll")
    upgrade_args = install_cli._parser().parse_args(["upgrade", *common, "--yes"])

    result = _execute_expect(upgrade_args, 50)

    assert result["status"] == "requires_restart"
    assert "DccMcpUnreal.dll" in result["verify"]["failure_reason"]


def _synthetic_host(tmp_path: Path) -> tuple[Path, Path]:
    engine = tmp_path / "UE_5.7"
    build_version = engine / "Engine" / "Build" / "Build.version"
    build_version.parent.mkdir(parents=True)
    build_version.write_text(
        json.dumps({"MajorVersion": 5, "MinorVersion": 7, "PatchVersion": 0}),
        encoding="utf-8",
    )
    project = tmp_path / "Sample" / "Sample.uproject"
    project.parent.mkdir()
    project.write_text(json.dumps({"FileVersion": 3, "EngineAssociation": "5.7"}), encoding="utf-8")
    if sys.platform == "win32":
        editor = engine / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
    elif sys.platform == "darwin":
        editor = engine / "Engine" / "Binaries" / "Mac" / "UnrealEditor.app" / "Contents" / "MacOS" / "UnrealEditor"
    else:
        editor = engine / "Engine" / "Binaries" / "Linux" / "UnrealEditor"
    editor.parent.mkdir(parents=True)
    shutil.copyfile(sys.executable, editor)
    return engine, project


def test_install_dry_run_emits_sop_plan_without_writing(tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "dcc_mcp_unreal.install_cli",
            "install",
            "--json",
            "--dry-run",
            "--dcc-path",
            str(engine),
            "--python",
            sys.executable,
            "--project",
            str(project),
        ],
        cwd=tmp_path,
        env=_cli_env(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    _assert_sop_v1(result)
    assert result["schema_version"] == 1
    assert result["status"] == "planned"
    assert result["dcc_type"] == "unreal"
    assert result["host"]["version"] == "5.7.0"
    assert result["install_state"] == "fresh"
    assert result["verify"]["directly_usable"] is False
    assert result["next_steps"] == [
        {
            "id": "execute-install",
            "description": "Execute the validated Unreal install plan.",
            "command": [
                "dcc-mcp-unreal",
                "install",
                "--json",
                "--yes",
                "--dcc-path",
                str(engine.resolve()),
                "--python",
                str(Path(sys.executable).resolve()),
                "--project",
                str(project.resolve()),
            ],
            "why": "The plan is valid but dry-run never mutates the project.",
        }
    ]
    assert not (project.parent / "Plugins" / "DccMcpUnreal").exists()
    assert not (project.parent / ".dcc-mcp" / "receipts" / "unreal.json").exists()


def test_receipt_driven_lifecycle_round_trip_preserves_project(tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    original_project = project.read_text(encoding="utf-8")
    common = (
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--timeout",
        "0",
    )

    installed = _run_cli(tmp_path, "install", *common, "--yes")

    assert installed.returncode == 40, installed.stderr
    install_result = json.loads(installed.stdout)
    assert install_result["verify"]["failure_stage"] == "readiness"
    plugin_root = project.parent / "Plugins" / "DccMcpUnreal"
    receipt = project.parent / ".dcc-mcp" / "receipts" / "unreal.json"
    assert (plugin_root / "DccMcpUnreal.uplugin").is_file()
    receipt_data = json.loads(receipt.read_text(encoding="utf-8"))
    assert receipt_data["adapter_version"] == install_result["adapter_version"]
    assert receipt_data["plugin_root"] == str(plugin_root.resolve())
    project_data = json.loads(project.read_text(encoding="utf-8"))
    assert {"Name": "DccMcpUnreal", "Enabled": True} in project_data["Plugins"]

    previous_receipt = receipt.read_bytes()
    installed_again = _run_cli(tmp_path, "install", *common, "--yes")
    assert installed_again.returncode == 40, installed_again.stderr
    assert receipt.read_bytes() == previous_receipt

    status = _run_cli(tmp_path, "status", *common)
    assert status.returncode == 0, status.stderr
    assert json.loads(status.stdout)["install_state"] == "current"

    removed = _run_cli(tmp_path, "uninstall", *common, "--yes")
    assert removed.returncode == 0, removed.stderr
    assert not plugin_root.exists()
    assert not receipt.exists()
    assert json.loads(project.read_text(encoding="utf-8")) == json.loads(original_project)

    removed_again = _run_cli(tmp_path, "uninstall", *common, "--yes")
    assert removed_again.returncode == 0, removed_again.stderr
    assert json.loads(removed_again.stdout)["install_state"] == "absent"


def test_install_discovers_host_without_dcc_path_override(tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)

    planned = _run_cli(
        tmp_path,
        "install",
        "--json",
        "--dry-run",
        "--project",
        str(project),
        env_overrides={"UE_ROOT": str(engine), "DCC_MCP_INSTALL_PYTHON": sys.executable},
    )

    assert planned.returncode == 0, planned.stderr
    result = json.loads(planned.stdout)
    assert result["host"] == {
        "path": str(engine.resolve()),
        "version": "5.7.0",
        "source": "environment",
    }
    assert result["target_python"]["source"] == "environment"


def test_uninstall_fails_closed_when_project_enablement_changed(tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    common = (
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--timeout",
        "0",
    )
    assert _run_cli(tmp_path, "install", *common, "--yes").returncode == 40
    project_data = json.loads(project.read_text(encoding="utf-8"))
    project_data["Plugins"][0]["Enabled"] = False
    project.write_text(json.dumps(project_data), encoding="utf-8")

    removed = _run_cli(tmp_path, "uninstall", *common, "--yes")

    assert removed.returncode == 30, removed.stderr
    result = json.loads(removed.stdout)
    assert result["verify"]["failure_stage"] == "uninstall"
    assert (project.parent / "Plugins" / "DccMcpUnreal").is_dir()
    assert (project.parent / ".dcc-mcp" / "receipts" / "unreal.json").is_file()
    assert json.loads(project.read_text(encoding="utf-8"))["Plugins"][0]["Enabled"] is False


def test_wheel_configuration_ships_the_installable_plugin_payload() -> None:
    configuration = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    force_include = configuration["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert force_include == {"unreal/plugin": "dcc_mcp_unreal/_plugin"}


def test_partial_status_has_one_machine_executable_recovery_step(tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    (project.parent / "Plugins" / "DccMcpUnreal").mkdir(parents=True)

    status = _run_cli(
        tmp_path,
        "status",
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--timeout",
        "0",
    )

    assert status.returncode == 10, status.stderr
    result = json.loads(status.stdout)
    assert result["status"] == "partial"
    assert len(result["next_steps"]) == 1
    assert result["next_steps"][0]["command"][0:2] == ["dcc-mcp-unreal", "status"]


def test_dry_run_wins_over_yes_for_uninstall(tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    common = (
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
    )
    assert _run_cli(tmp_path, "install", *common, "--yes").returncode == 40
    plugin_root = project.parent / "Plugins" / "DccMcpUnreal"
    receipt = project.parent / ".dcc-mcp" / "receipts" / "unreal.json"

    planned = _run_cli(tmp_path, "uninstall", *common, "--yes", "--dry-run")

    assert planned.returncode == 0, planned.stderr
    assert json.loads(planned.stdout)["status"] == "planned"
    assert plugin_root.is_dir()
    assert receipt.is_file()


def test_preflight_rejects_project_engine_mismatch(tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    project.write_text(
        json.dumps({"FileVersion": 3, "EngineAssociation": "5.6"}),
        encoding="utf-8",
    )

    planned = _run_cli(
        tmp_path,
        "install",
        "--json",
        "--dry-run",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
    )

    assert planned.returncode == 10, planned.stderr
    result = json.loads(planned.stdout)
    assert result["verify"]["failure_stage"] == "preflight"
    assert "EngineAssociation 5.6" in result["verify"]["failure_reason"]


def test_uninstall_classifies_windows_style_plugin_lock(monkeypatch, tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    common = [
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--timeout",
        "0",
    ]
    install_args = install_cli._parser().parse_args(["install", *common, "--yes"])
    _execute_expect(install_args, 40)
    plugin_root = project.parent / "Plugins" / "DccMcpUnreal"
    real_replace = install_cli.os.replace

    def locked_replace(source, destination):
        if Path(source) == plugin_root:
            raise PermissionError("plugin binary is loaded")
        return real_replace(source, destination)

    monkeypatch.setattr(install_cli.os, "replace", locked_replace)
    uninstall_args = install_cli._parser().parse_args(["uninstall", *common, "--yes"])

    exit_code, result = install_cli._execute(uninstall_args)

    assert exit_code == 50
    assert result["status"] == "requires_restart"
    assert result["verify"]["failure_stage"] == "uninstall"
    assert plugin_root.is_dir()


def test_failed_upgrade_receipt_commit_restores_previous_install(monkeypatch, tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    common = [
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--timeout",
        "0",
    ]
    install_args = install_cli._parser().parse_args(["install", *common, "--yes"])
    _execute_expect(install_args, 40)
    plugin_root = project.parent / "Plugins" / "DccMcpUnreal"
    receipt_path = project.parent / ".dcc-mcp" / "receipts" / "unreal.json"
    previous_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    previous_receipt["adapter_version"] = "0.2.9"
    receipt_path.write_text(json.dumps(previous_receipt), encoding="utf-8")
    previous_files = install_cli._file_manifest(plugin_root)
    previous_project = project.read_bytes()
    previous_receipt_bytes = receipt_path.read_bytes()

    def fail_receipt(*_args, **_kwargs):
        raise OSError("injected receipt commit failure")

    monkeypatch.setattr(install_cli, "_write_receipt", fail_receipt)
    upgrade_args = install_cli._parser().parse_args(["upgrade", *common, "--yes"])

    exit_code, result = install_cli._execute(upgrade_args)

    assert exit_code == 30
    assert result["verify"]["failure_stage"] == "install"
    assert install_cli._file_manifest(plugin_root) == previous_files
    assert project.read_bytes() == previous_project
    assert receipt_path.read_bytes() == previous_receipt_bytes


def test_target_runtime_rejects_core_below_floor(monkeypatch, tmp_path: Path) -> None:
    python_path = tmp_path / "python"
    python_path.touch()
    completed = {
        "success": True,
        "returncode": 0,
        "stdout": json.dumps(
            {
                "python_version": "3.12.0",
                "adapter_version": install_cli.__version__,
                "core_version": "0.19.99",
            }
        ),
        "stderr": "",
        "truncated": False,
    }
    monkeypatch.setattr(install_cli, "_run_bounded_probe", lambda *_args, **_kwargs: completed)

    with pytest.raises(ValueError, match=r"0\.20\.13\+"):
        install_cli._target_runtime(python_path)


def test_lifecycle_cli_rejects_core_below_floor(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(install_cli, "_core_version", lambda: "0.19.99")
    args = install_cli._parser().parse_args(
        ["status", "--json", "--dcc-path", str(tmp_path), "--python", sys.executable]
    )

    context, failure = install_cli._preflight(args)

    assert context is None
    assert failure is not None
    exit_code, result = failure
    assert exit_code == 10
    assert "0.20.13+" in result["verify"]["failure_reason"]


def test_verify_reports_directly_usable_only_after_typed_probe(monkeypatch, tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    common = [
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--instance-id",
        "11111111-1111-1111-1111-111111111111",
        "--timeout",
        "0",
    ]
    install_args = install_cli._parser().parse_args(["install", *common, "--yes"])
    context = install_cli._resolve_context(install_args)
    monkeypatch.setattr(
        dcc_mcp_core,
        "wait_for_sidecar_ready",
        lambda **kwargs: _bound_readiness(context),
    )

    exit_code, result = install_cli._execute(install_args)

    assert exit_code == 0, result
    _assert_sop_v1(result)
    assert result["verify"] == {
        "directly_usable": True,
        "failure_stage": None,
        "failure_reason": None,
    }


def test_readiness_failure_returns_exact_editor_launch_step(tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    if sys.platform == "win32":
        editor = engine / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
    elif sys.platform == "darwin":
        editor = engine / "Engine" / "Binaries" / "Mac" / "UnrealEditor.app" / "Contents" / "MacOS" / "UnrealEditor"
    else:
        editor = engine / "Engine" / "Binaries" / "Linux" / "UnrealEditor"
    editor.parent.mkdir(parents=True, exist_ok=True)
    editor.touch()
    common = [
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--timeout",
        "0",
    ]
    install_args = install_cli._parser().parse_args(["install", *common, "--yes"])

    exit_code, result = install_cli._execute(install_args)

    assert exit_code == 40, result
    assert result["verify"]["failure_stage"] == "readiness"
    assert result["next_steps"] == [
        {
            "id": "launch-unreal-editor",
            "description": "Launch the selected Unreal Editor project so its DCC MCP plugin can become ready.",
            "command": [str(editor.resolve()), str(project.resolve())],
            "why": "The installed plugin passed static checks, but no typed Unreal readiness probe succeeded.",
        }
    ]


def test_install_rejects_payload_version_mismatch_before_commit(monkeypatch, tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "DccMcpUnreal.uplugin").write_text(
        json.dumps({"FileVersion": 3, "VersionName": "0.2.0"}),
        encoding="utf-8",
    )
    runtime = {
        "python_executable": str(Path(sys.executable).resolve()),
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "adapter_version": install_cli.__version__,
        "core_version": install_cli.MIN_CORE_VERSION,
        "adapter_origin": str(payload.parent / "dcc_mcp_unreal" / "__init__.py"),
        "core_origin": str(payload.parent / "dcc_mcp_core" / "__init__.py"),
        "adapter_distribution_root": str(payload.parent),
        "core_distribution_root": str(payload.parent),
        "plugin_payload": {"root": str(payload), "provenance": "wheel", "ownership_root": str(payload)},
    }
    monkeypatch.setattr(install_cli, "_target_runtime", lambda _python: runtime)
    args = install_cli._parser().parse_args(
        [
            "install",
            "--json",
            "--yes",
            "--dcc-path",
            str(engine),
            "--python",
            sys.executable,
            "--project",
            str(project),
        ]
    )

    exit_code, result = install_cli._execute(args)

    assert exit_code == 20
    assert result["verify"]["failure_stage"] == "acquire"
    assert not (project.parent / "Plugins" / "DccMcpUnreal").exists()
    assert not (project.parent / ".dcc-mcp" / "receipts" / "unreal.json").exists()


def test_install_copies_only_the_target_distribution_payload(monkeypatch, tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    target_payload = tmp_path / "target-distribution" / "dcc_mcp_unreal" / "_plugin"
    invoker_payload = tmp_path / "invoker-checkout" / "unreal" / "plugin"
    for payload, marker in ((target_payload, "target"), (invoker_payload, "invoker")):
        payload.mkdir(parents=True)
        (payload / "DccMcpUnreal.uplugin").write_text(
            json.dumps({"FileVersion": 3, "VersionName": install_cli.__version__}),
            encoding="utf-8",
        )
        (payload / "payload-owner.txt").write_text(marker, encoding="utf-8")
    runtime = {
        "python_executable": str(Path(sys.executable).resolve()),
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "adapter_version": install_cli.__version__,
        "core_version": install_cli.MIN_CORE_VERSION,
        "adapter_origin": str(target_payload.parent / "__init__.py"),
        "core_origin": str(tmp_path / "target-distribution" / "dcc_mcp_core" / "__init__.py"),
        "adapter_distribution_root": str(tmp_path / "target-distribution"),
        "core_distribution_root": str(tmp_path / "target-distribution"),
        "plugin_payload": {"root": str(target_payload), "provenance": "wheel"},
    }
    monkeypatch.setattr(install_cli, "_target_runtime", lambda _python: runtime)
    invoker_module = invoker_payload.parents[1] / "src" / "dcc_mcp_unreal" / "install_cli.py"
    invoker_module.parent.mkdir(parents=True)
    invoker_module.write_text("# independent invoking CLI\n", encoding="utf-8")
    monkeypatch.setattr(install_cli, "__file__", str(invoker_module))
    args = install_cli._parser().parse_args(
        [
            "install",
            "--json",
            "--yes",
            "--dcc-path",
            str(engine),
            "--python",
            sys.executable,
            "--project",
            str(project),
            "--timeout",
            "0",
        ]
    )

    exit_code, result = install_cli._execute(args)

    assert exit_code == install_cli.INSTALL_EXIT_VERIFY
    assert result["verify"]["failure_stage"] == "readiness"
    installed = project.parent / "Plugins" / "DccMcpUnreal"
    assert (installed / "payload-owner.txt").read_text(encoding="utf-8") == "target"


def test_install_rejects_same_path_payload_replacement_after_preflight(monkeypatch, tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    payload = tmp_path / "target-distribution" / "dcc_mcp_unreal" / "_plugin"
    replacement = tmp_path / "independent-replacement"
    for root in (payload, replacement):
        root.mkdir(parents=True)
        (root / "DccMcpUnreal.uplugin").write_text(
            json.dumps({"FileVersion": 3, "VersionName": install_cli.__version__}),
            encoding="utf-8",
        )
        (root / "same-bytes.txt").write_text("identical\n", encoding="utf-8")
    runtime = {
        "python_executable": str(Path(sys.executable).resolve()),
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "adapter_version": install_cli.__version__,
        "core_version": install_cli.MIN_CORE_VERSION,
        "adapter_origin": str(payload.parent / "__init__.py"),
        "core_origin": str(tmp_path / "target-distribution" / "dcc_mcp_core" / "__init__.py"),
        "adapter_distribution_root": str(tmp_path / "target-distribution"),
        "core_distribution_root": str(tmp_path / "target-distribution"),
        "plugin_payload": {"root": str(payload), "provenance": "wheel"},
    }
    monkeypatch.setattr(install_cli, "_target_runtime", lambda _python: runtime)
    inspect_state = install_cli._inspect_state
    replaced = False

    def replace_before_state(context: dict) -> tuple[str, Optional[dict], Optional[str]]:
        nonlocal replaced
        if not replaced:
            preserved = payload.parent / "_validated-moved"
            payload.rename(preserved)
            replacement.rename(payload)
            replaced = True
        return inspect_state(context)

    monkeypatch.setattr(install_cli, "_inspect_state", replace_before_state)
    args = install_cli._parser().parse_args(
        [
            "install",
            "--json",
            "--yes",
            "--dcc-path",
            str(engine),
            "--python",
            sys.executable,
            "--project",
            str(project),
            "--timeout",
            "0",
        ]
    )

    exit_code, result = install_cli._execute(args)

    assert exit_code == install_cli.INSTALL_EXIT_ACQUIRE
    assert result["verify"]["failure_stage"] == "acquire"
    assert not (project.parent / "Plugins" / "DccMcpUnreal").exists()
    assert not (project.parent / ".dcc-mcp" / "receipts" / "unreal.json").exists()


def test_install_rejects_same_path_source_module_replacement_after_preflight(monkeypatch, tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    source_root = tmp_path / "source"
    origin = source_root / "src" / "dcc_mcp_unreal" / "__init__.py"
    payload = source_root / "unreal" / "plugin"
    origin.parent.mkdir(parents=True)
    payload.mkdir(parents=True)
    origin.write_text("# identical source\n", encoding="utf-8")
    replacement = tmp_path / "replacement.py"
    replacement.write_bytes(origin.read_bytes())
    (payload / "DccMcpUnreal.uplugin").write_text(
        json.dumps({"FileVersion": 3, "VersionName": install_cli.__version__}), encoding="utf-8"
    )
    runtime = {
        "python_executable": str(Path(sys.executable).resolve()),
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "adapter_version": install_cli.__version__,
        "core_version": install_cli.MIN_CORE_VERSION,
        "adapter_origin": str(origin),
        "core_origin": str(tmp_path / "site-packages" / "dcc_mcp_core" / "__init__.py"),
        "adapter_distribution_root": str(tmp_path / "site-packages"),
        "core_distribution_root": str(tmp_path / "site-packages"),
        "plugin_payload": {
            "root": str(payload),
            "provenance": "source-checkout",
            "ownership_root": str(source_root),
        },
    }
    monkeypatch.setattr(install_cli, "_target_runtime", lambda _python: runtime)
    inspect_state = install_cli._inspect_state
    replaced = False

    def replace_before_state(context: dict) -> tuple[str, Optional[dict], Optional[str]]:
        nonlocal replaced
        if not replaced:
            preserved = source_root / "original-moved.py"
            origin.rename(preserved)
            replacement.rename(origin)
            replaced = True
        return inspect_state(context)

    monkeypatch.setattr(install_cli, "_inspect_state", replace_before_state)
    args = install_cli._parser().parse_args(
        [
            "install",
            "--json",
            "--yes",
            "--dcc-path",
            str(engine),
            "--python",
            sys.executable,
            "--project",
            str(project),
            "--timeout",
            "0",
        ]
    )

    exit_code, result = install_cli._execute(args)

    assert exit_code == install_cli.INSTALL_EXIT_ACQUIRE
    assert result["verify"]["failure_stage"] == "acquire"
    assert not (project.parent / "Plugins" / "DccMcpUnreal").exists()


def test_install_rejects_payload_drift_during_staging(monkeypatch, tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    payload = tmp_path / "target-distribution" / "dcc_mcp_unreal" / "_plugin"
    payload.mkdir(parents=True)
    descriptor = payload / "DccMcpUnreal.uplugin"
    descriptor.write_text(json.dumps({"FileVersion": 3, "VersionName": install_cli.__version__}), encoding="utf-8")
    runtime = {
        "python_executable": str(Path(sys.executable).resolve()),
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "adapter_version": install_cli.__version__,
        "core_version": install_cli.MIN_CORE_VERSION,
        "adapter_origin": str(payload.parent / "__init__.py"),
        "core_origin": str(tmp_path / "target-distribution" / "dcc_mcp_core" / "__init__.py"),
        "adapter_distribution_root": str(tmp_path / "target-distribution"),
        "core_distribution_root": str(tmp_path / "target-distribution"),
        "plugin_payload": {"root": str(payload), "provenance": "wheel", "ownership_root": str(payload)},
    }
    monkeypatch.setattr(install_cli, "_target_runtime", lambda _python: runtime)
    copy2 = install_cli.shutil.copy2

    def copy_then_drift(source: Path, destination: Path) -> str:
        result = copy2(source, destination)
        descriptor.write_text("tampered after copy\n", encoding="utf-8")
        return result

    monkeypatch.setattr(install_cli.shutil, "copy2", copy_then_drift)
    args = install_cli._parser().parse_args(
        [
            "install",
            "--json",
            "--yes",
            "--dcc-path",
            str(engine),
            "--python",
            sys.executable,
            "--project",
            str(project),
            "--timeout",
            "0",
        ]
    )

    exit_code, result = install_cli._execute(args)

    assert exit_code == install_cli.INSTALL_EXIT_ACQUIRE
    assert result["verify"]["failure_stage"] == "acquire"
    assert not (project.parent / "Plugins" / "DccMcpUnreal").exists()


def test_root_install_runbook_has_required_sop_sections_and_catalog_handoff() -> None:
    runbook = (REPO_ROOT / "install.md").read_text(encoding="utf-8")

    for section in (
        "## Requirements",
        "## Supported versions",
        "## Agent quick path",
        "## Manual path",
        "## Verify",
        "## Upgrade",
        "## Uninstall",
        "## Troubleshooting",
    ):
        assert section in runbook
    assert "Windows" in runbook and "macOS" in runbook and "Linux" in runbook
    assert "https://raw.githubusercontent.com/dcc-mcp/dcc-mcp-unreal/main/install.md" in runbook


def test_repair_refuses_unreceipted_files_inside_plugin_root(tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    common = (
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--timeout",
        "0",
    )
    assert _run_cli(tmp_path, "install", *common, "--yes").returncode == 40
    user_file = project.parent / "Plugins" / "DccMcpUnreal" / "StudioOwned.txt"
    user_file.write_text("preserve me", encoding="utf-8")

    repaired = _run_cli(tmp_path, "install", *common, "--yes")

    assert repaired.returncode == 10, repaired.stderr
    result = json.loads(repaired.stdout)
    assert result["install_state"] == "partial"
    assert "unreceipted" in result["verify"]["failure_reason"]
    assert user_file.read_text(encoding="utf-8") == "preserve me"


@pytest.mark.parametrize(
    "value",
    (
        "0.20.13rc1",
        "garbage0.20.13",
        "0.20.13suffix",
        " 0.20.13",
        "0.20",
        "0.20.13.1",
        "0." + "9" * 5000 + ".1",
    ),
)
def test_versions_are_bounded_canonical_finals(value: str) -> None:
    with pytest.raises(ValueError, match="canonical"):
        install_cli._version_tuple(value)


def test_zero_byte_editor_is_not_a_usable_host(tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    editor = install_cli._editor_executable(engine)
    assert editor is not None
    editor.write_bytes(b"")
    args = install_cli._parser().parse_args(
        [
            "status",
            "--json",
            "--dcc-path",
            str(engine),
            "--python",
            sys.executable,
            "--project",
            str(project),
        ]
    )

    context, failure = install_cli._preflight(args)

    assert context is None
    assert failure is not None
    assert failure[0] == 10
    assert "editor" in failure[1]["verify"]["failure_reason"].lower()


def test_manifest_owns_directories_and_rejects_unexpected_empty_directory(tmp_path: Path) -> None:
    root = tmp_path / "plugin"
    (root / "Content" / "Python").mkdir(parents=True)
    (root / "Content" / "Python" / "init_unreal.py").write_text("pass\n", encoding="utf-8")
    manifest = install_cli._file_manifest(root)
    assert {item["type"] for item in manifest} == {"directory", "file"}
    receipt = {"ownership": manifest}
    assert install_cli._manifest_matches(root, receipt)[:2] == (True, "")

    (root / "StudioOwnedEmpty").mkdir()
    matches, reason, has_unreceipted = install_cli._manifest_matches(root, receipt)

    assert matches is False
    assert has_unreceipted is True
    assert "unreceipted" in reason


def test_target_runtime_rejects_shadow_module_outside_distribution(monkeypatch, tmp_path: Path) -> None:
    python_path = tmp_path / "python"
    python_path.touch()
    site = tmp_path / "site-packages"
    shadow_origin = tmp_path / "shadow" / "dcc_mcp_unreal" / "__init__.py"
    core_origin = site / "dcc_mcp_core" / "__init__.py"
    shadow_origin.parent.mkdir(parents=True)
    core_origin.parent.mkdir(parents=True)
    shadow_origin.write_text("# shadow\n", encoding="utf-8")
    core_origin.write_text("# core\n", encoding="utf-8")
    completed = {
        "success": True,
        "returncode": 0,
        "stdout": json.dumps(
            {
                "python_executable": str(python_path.resolve()),
                "python_version": "3.12.0",
                "adapter": {
                    "name": "dcc-mcp-unreal",
                    "version": install_cli.__version__,
                    "module_version": install_cli.__version__,
                    "origin": str(shadow_origin.resolve()),
                    "distribution_root": str(site.resolve()),
                    "records": [
                        {
                            "path": "dcc_mcp_unreal/__init__.py",
                            "hash": "sha256="
                            + base64.urlsafe_b64encode(hashlib.sha256(shadow_origin.read_bytes()).digest())
                            .decode("ascii")
                            .rstrip("="),
                            "size": shadow_origin.stat().st_size,
                        }
                    ],
                    "direct_url": None,
                },
                "core": {
                    "name": "dcc-mcp-core",
                    "version": install_cli.MIN_CORE_VERSION,
                    "module_version": None,
                    "origin": str(core_origin.resolve()),
                    "distribution_root": str(site.resolve()),
                    "records": [
                        {
                            "path": "dcc_mcp_core/__init__.py",
                            "hash": "sha256="
                            + base64.urlsafe_b64encode(hashlib.sha256(core_origin.read_bytes()).digest())
                            .decode("ascii")
                            .rstrip("="),
                            "size": core_origin.stat().st_size,
                        }
                    ],
                    "direct_url": None,
                },
            }
        ),
        "stderr": "",
        "truncated": False,
    }
    commands: list[list[str]] = []

    def capture_probe(command: list[str]) -> dict:
        commands.append(command)
        return completed

    monkeypatch.setattr(install_cli, "_run_bounded_probe", capture_probe)

    with pytest.raises(ValueError, match="origin"):
        install_cli._target_runtime(python_path)

    assert commands[0][1:3] == ["-I", "-c"]
    assert commands[0][-1] == ""
    assert "from dcc_mcp_unreal.install_cli" not in commands[0][3]


def test_target_runtime_does_not_execute_a_shadowed_probe(monkeypatch, tmp_path: Path) -> None:
    legitimate_report = install_cli._runtime_probe()
    forged_source = tmp_path / "forged-source"
    forged_origin = forged_source / "src" / "dcc_mcp_unreal" / "__init__.py"
    forged_payload = forged_source / "unreal" / "plugin"
    forged_site = tmp_path / "forged-site-packages"
    forged_origin.parent.mkdir(parents=True)
    forged_payload.mkdir(parents=True)
    forged_site.mkdir()
    forged_origin.write_text("# forged source\n", encoding="utf-8")
    (forged_payload / "DccMcpUnreal.uplugin").write_text(
        json.dumps({"FileVersion": 3, "VersionName": install_cli.__version__}), encoding="utf-8"
    )
    (forged_payload / "attacker-controlled.py").write_text("raise SystemExit('payload ran')\n", encoding="utf-8")
    legitimate_report["adapter"] = {
        "name": "dcc-mcp-unreal",
        "version": install_cli.__version__,
        "module_version": install_cli.__version__,
        "origin": str(forged_origin),
        "distribution_root": str(forged_site),
        "records": [],
        "payload_records": [],
        "direct_url": {"url": forged_source.as_uri(), "dir_info": {}},
    }
    encoded = base64.b64encode(json.dumps(legitimate_report).encode("utf-8")).decode("ascii")

    shadow_package = tmp_path / "shadow" / "dcc_mcp_unreal"
    shadow_package.mkdir(parents=True)
    (shadow_package / "__init__.py").write_text("# shadow package\n", encoding="utf-8")
    marker = tmp_path / "shadow-probe-ran.txt"
    stdlib_marker = tmp_path / "shadow-stdlib-ran.txt"
    (shadow_package.parent / "json.py").write_text(
        f"open({str(stdlib_marker)!r}, 'w', encoding='utf-8').write('shadow stdlib executed')\n",
        encoding="utf-8",
    )
    (shadow_package / "install_cli.py").write_text(
        "import base64, json\n"
        f"MARKER = {str(marker)!r}\n"
        f"REPORT = {encoded!r}\n"
        "def _runtime_probe():\n"
        "    open(MARKER, 'w', encoding='utf-8').write('shadow executed')\n"
        "    return json.loads(base64.b64decode(REPORT))\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(shadow_package.parent)
    accepted = install_cli._target_runtime(Path(sys.executable))

    assert not marker.exists()
    assert not stdlib_marker.exists()
    assert accepted["adapter_origin"] != str(forged_origin)
    assert accepted["plugin_payload"]["root"] != str(forged_payload)


def _distribution_identity(
    origin: Path,
    root: Path,
    *,
    record: Optional[str] = None,
    direct_url: Optional[dict] = None,
    name: str = "dcc-mcp-unreal",
    version: str = install_cli.__version__,
) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    records = []
    if record is not None:
        digest = base64.urlsafe_b64encode(hashlib.sha256(origin.read_bytes()).digest()).decode("ascii").rstrip("=")
        records.append({"path": record, "hash": f"sha256={digest}", "size": origin.stat().st_size})
    return {
        "name": name,
        "version": version,
        "module_version": install_cli.__version__,
        "origin": str(origin.absolute()),
        "distribution_root": str(root.absolute()),
        "records": records,
        "direct_url": direct_url,
    }


def _runtime_probe_result(python_path: Path, adapter: dict, core: dict) -> dict:
    return {
        "success": True,
        "returncode": 0,
        "stdout": json.dumps(
            {
                "python_executable": str(python_path.resolve()),
                "python_version": "3.12.0",
                "cache_tag": sys.implementation.cache_tag,
                "adapter": adapter,
                "core": core,
            }
        ),
        "stderr": "",
        "truncated": False,
    }


@pytest.fixture(scope="module")
def install_sop_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("install-sop-wheel")
    completed = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(output)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    return next(output.glob("dcc_mcp_unreal-*.whl"))


@pytest.mark.parametrize(
    ("owned_path", "alias"),
    (
        ("dcc_mcp_unreal/__init__.py", "dcc_mcp_unreal/./__init__.py"),
        ("dcc_mcp_unreal/__init__.py", "dcc_mcp_unreal\\__init__.py"),
        ("dcc_mcp_unreal/__init__.py", "DCC_MCP_UNREAL/__init__.py"),
        (
            "dcc_mcp_unreal/_plugin/DccMcpUnreal.uplugin",
            "dcc_mcp_unreal/_plugin/./DccMcpUnreal.uplugin",
        ),
        (
            "dcc_mcp_unreal/_plugin/DccMcpUnreal.uplugin",
            "dcc_mcp_unreal\\_plugin\\DccMcpUnreal.uplugin",
        ),
        (
            "dcc_mcp_unreal/_plugin/DccMcpUnreal.uplugin",
            "dcc_mcp_unreal/_PLUGIN/DccMcpUnreal.uplugin",
        ),
    ),
)
def test_installed_wheel_rejects_noncanonical_record_aliases(
    tmp_path: Path, install_sop_wheel: Path, owned_path: str, alias: str
) -> None:
    wheel = tmp_path / install_sop_wheel.name
    shutil.copy2(install_sop_wheel, wheel)
    target = tmp_path / "target"
    install_python = sys.executable
    pip_available = (
        subprocess.run(
            [install_python, "-m", "pip", "--version"], check=False, capture_output=True, text=True
        ).returncode
        == 0
    )
    if pip_available:
        installer = [install_python, "-m", "pip"]
    else:
        uv = shutil.which("uv")
        assert uv is not None, "the test interpreter needs pip or uv for isolated wheel installation"
        installer = [uv, "pip"]
    install_environment = os.environ.copy()
    install_environment["UV_LINK_MODE"] = "copy"
    installed = subprocess.run(
        [*installer, "install", "--no-deps", "--target", str(target), str(wheel)],
        cwd=tmp_path,
        env=install_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert installed.returncode == 0, installed.stderr
    installed_record = next(target.glob("dcc_mcp_unreal-*.dist-info/RECORD"))
    installed_rows = list(csv.reader(io.StringIO(installed_record.read_text(encoding="utf-8"))))
    matching = [row for row in installed_rows if row[0] == owned_path]
    assert len(matching) == 1
    matching[0][0] = alias
    rendered = io.StringIO(newline="")
    csv.writer(rendered, lineterminator="\n").writerows(installed_rows)
    with installed_record.open("w", encoding="utf-8", newline="") as stream:
        stream.write(rendered.getvalue())
    installed_rows = list(csv.reader(io.StringIO(installed_record.read_text(encoding="utf-8"))))
    assert any(row[0] == alias for row in installed_rows)
    assert not any(row[0] == owned_path for row in installed_rows)
    core_site = Path(dcc_mcp_core.__file__).resolve().parents[1]
    probe = (
        f"import sys; sys.path[:0] = [{str(target)!r}, {str(core_site)!r}]; "
        "from pathlib import Path; "
        "from dcc_mcp_unreal.install_cli import _runtime_probe, _validate_target_runtime_probe; "
        "_validate_target_runtime_probe(_runtime_probe(), Path(sys.executable))"
    )
    probed = subprocess.run(
        [install_python, "-c", probe],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert probed.returncode != 0
    assert "RECORD" in probed.stderr


@pytest.mark.parametrize("editable", (True, False, None))
def test_distribution_identity_accepts_owned_local_source_checkout(tmp_path: Path, editable: Optional[bool]) -> None:
    source_root = tmp_path / "source"
    origin = source_root / "src" / "dcc_mcp_unreal" / "__init__.py"
    origin.parent.mkdir(parents=True)
    origin.write_text("# package\n", encoding="utf-8")
    dir_info = {} if editable is None else {"editable": editable}
    identity = _distribution_identity(
        origin,
        tmp_path / "site-packages",
        direct_url={"url": source_root.as_uri(), "dir_info": dir_info},
    )

    assert install_cli._owned_module_origin(identity, "dcc-mcp-unreal", "dcc_mcp_unreal") == str(origin.absolute())


def test_distribution_identity_accepts_installed_wheel_record(tmp_path: Path) -> None:
    site = tmp_path / "site-packages"
    origin = site / "dcc_mcp_unreal" / "__init__.py"
    origin.parent.mkdir(parents=True)
    origin.write_text("# package\n", encoding="utf-8")
    identity = _distribution_identity(origin, site, record="dcc_mcp_unreal/__init__.py")

    assert install_cli._owned_module_origin(identity, "dcc-mcp-unreal", "dcc_mcp_unreal") == str(origin.absolute())


@pytest.mark.parametrize(
    "record_name",
    (
        "/dcc_mcp_unreal/__init__.py",
        "C:/dcc_mcp_unreal/__init__.py",
        "//server/share/dcc_mcp_unreal/__init__.py",
        "dcc_mcp_unreal//__init__.py",
        "dcc_mcp_unreal/../dcc_mcp_unreal/__init__.py",
        "./dcc_mcp_unreal/__init__.py",
    ),
)
def test_distribution_identity_rejects_noncanonical_record_names(tmp_path: Path, record_name: str) -> None:
    site = tmp_path / "site-packages"
    origin = site / "dcc_mcp_unreal" / "__init__.py"
    origin.parent.mkdir(parents=True)
    origin.write_text("# package\n", encoding="utf-8")
    identity = _distribution_identity(origin, site, record=record_name)

    with pytest.raises(ValueError, match="RECORD"):
        install_cli._owned_module_origin(identity, "dcc-mcp-unreal", "dcc_mcp_unreal")


def test_distribution_identity_rejects_missing_wheel_record(tmp_path: Path) -> None:
    site = tmp_path / "site-packages"
    origin = site / "dcc_mcp_unreal" / "__init__.py"
    origin.parent.mkdir(parents=True)
    origin.write_text("# package\n", encoding="utf-8")
    identity = _distribution_identity(origin, site)

    with pytest.raises(ValueError, match="RECORD"):
        install_cli._owned_module_origin(identity, "dcc-mcp-unreal", "dcc_mcp_unreal")


def test_target_runtime_rejects_duplicate_matching_wheel_records(monkeypatch, tmp_path: Path) -> None:
    python_path = tmp_path / "python"
    python_path.touch()
    site = tmp_path / "site-packages"
    adapter_origin = site / "dcc_mcp_unreal" / "__init__.py"
    core_origin = site / "dcc_mcp_core" / "__init__.py"
    adapter_origin.parent.mkdir(parents=True)
    core_origin.parent.mkdir(parents=True)
    adapter_origin.write_text("# tampered adapter\n", encoding="utf-8")
    core_origin.write_text("# core\n", encoding="utf-8")
    adapter = _distribution_identity(adapter_origin, site, record="dcc_mcp_unreal/__init__.py")
    adapter["records"] = [
        {
            "path": "dcc_mcp_unreal/__init__.py",
            "hash": "sha256=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "size": 1,
        },
        {"path": "dcc_mcp_unreal/./__init__.py", "hash": None, "size": None},
    ]
    core = _distribution_identity(
        core_origin,
        site,
        record="dcc_mcp_core/__init__.py",
        name="dcc-mcp-core",
        version=install_cli.MIN_CORE_VERSION,
    )
    core["module_version"] = None
    monkeypatch.setattr(
        install_cli,
        "_run_bounded_probe",
        lambda *_args, **_kwargs: _runtime_probe_result(python_path, adapter, core),
    )

    with pytest.raises(ValueError, match="RECORD"):
        install_cli._target_runtime(python_path)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("record_size", None),
        ("record_hash", None),
        ("record_hash", ""),
        ("record_size", 1),
        ("record_hash", "sha256=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"),
    ),
)
def test_distribution_identity_rejects_record_metadata_mismatch(tmp_path: Path, field: str, value: object) -> None:
    site = tmp_path / "site-packages"
    origin = site / "dcc_mcp_unreal" / "__init__.py"
    origin.parent.mkdir(parents=True)
    origin.write_text("# package\n", encoding="utf-8")
    identity = _distribution_identity(origin, site, record="dcc_mcp_unreal/__init__.py")
    identity["records"][0][field.removeprefix("record_")] = value

    with pytest.raises(ValueError, match="metadata"):
        install_cli._owned_module_origin(identity, "dcc-mcp-unreal", "dcc_mcp_unreal")


@pytest.mark.parametrize("case", ("missing", "duplicate", "empty-hash", "empty-size", "forged-hash", "forged-size"))
def test_target_payload_rejects_invalid_wheel_records(tmp_path: Path, case: str) -> None:
    site = tmp_path / "site-packages"
    payload = site / "dcc_mcp_unreal" / "_plugin"
    payload.mkdir(parents=True)
    descriptor = payload / "DccMcpUnreal.uplugin"
    descriptor.write_text(json.dumps({"FileVersion": 3, "VersionName": install_cli.__version__}), encoding="utf-8")
    relative = descriptor.relative_to(site).as_posix()
    digest = base64.urlsafe_b64encode(hashlib.sha256(descriptor.read_bytes()).digest()).decode("ascii").rstrip("=")
    valid = {
        "located": str(descriptor.absolute()),
        "path": relative,
        "hash": f"sha256={digest}",
        "size": descriptor.stat().st_size,
    }
    records = [dict(valid)]
    if case == "missing":
        records = []
    elif case == "duplicate":
        duplicate = dict(valid)
        duplicate["path"] = "dcc_mcp_unreal/_plugin/./DccMcpUnreal.uplugin"
        records.append(duplicate)
    elif case == "empty-hash":
        records[0]["hash"] = None
    elif case == "empty-size":
        records[0]["size"] = None
    elif case == "forged-hash":
        records[0]["hash"] = "sha256=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    else:
        records[0]["size"] += 1
    runtime = {
        "adapter_origin": str(site / "dcc_mcp_unreal" / "__init__.py"),
        "adapter_distribution_root": str(site),
        "plugin_payload": {
            "root": str(payload),
            "provenance": "wheel",
            "ownership_root": str(site),
            "cache_tag": sys.implementation.cache_tag,
            "records": records,
        },
    }

    with pytest.raises(ValueError, match="RECORD|metadata"):
        install_cli._bind_target_payload(runtime)


@pytest.mark.parametrize("optimization", ("", ".opt-1", ".opt-2"))
def test_target_payload_excludes_generated_bytecode_with_empty_records(tmp_path: Path, optimization: str) -> None:
    site = tmp_path / "site-packages"
    payload = site / "dcc_mcp_unreal" / "_plugin"
    descriptor = payload / "DccMcpUnreal.uplugin"
    source = payload / "Content" / "Python" / "init_unreal.py"
    generated = (
        payload / "Content" / "Python" / "__pycache__" / f"init_unreal.{sys.implementation.cache_tag}{optimization}.pyc"
    )
    generated.parent.mkdir(parents=True)
    descriptor.parent.mkdir(parents=True, exist_ok=True)
    descriptor.write_text(json.dumps({"FileVersion": 3, "VersionName": install_cli.__version__}), encoding="utf-8")
    source.write_text("# generated at install time\n", encoding="utf-8")
    generated.write_bytes(b"generated bytecode")
    descriptor_digest = (
        base64.urlsafe_b64encode(hashlib.sha256(descriptor.read_bytes()).digest()).decode("ascii").rstrip("=")
    )
    source_digest = base64.urlsafe_b64encode(hashlib.sha256(source.read_bytes()).digest()).decode("ascii").rstrip("=")
    runtime = {
        "adapter_origin": str(site / "dcc_mcp_unreal" / "__init__.py"),
        "adapter_distribution_root": str(site),
        "plugin_payload": {
            "root": str(payload),
            "provenance": "wheel",
            "ownership_root": str(site),
            "records": [
                {
                    "located": str(descriptor.absolute()),
                    "path": descriptor.relative_to(site).as_posix(),
                    "hash": f"sha256={descriptor_digest}",
                    "size": descriptor.stat().st_size,
                },
                {
                    "located": str(source.absolute()),
                    "path": source.relative_to(site).as_posix(),
                    "hash": f"sha256={source_digest}",
                    "size": source.stat().st_size,
                },
                {
                    "located": str(generated.absolute()),
                    "path": generated.relative_to(site).as_posix(),
                    "hash": None,
                    "size": None,
                },
            ],
            "cache_tag": sys.implementation.cache_tag,
        },
    }

    bound = install_cli._bind_target_payload(runtime)

    paths = {item["path"] for item in bound["plugin_payload"]["snapshot"]["manifest"]}
    assert "Content/Python/__pycache__" not in paths
    assert not any(path.endswith(".pyc") for path in paths)


@pytest.mark.parametrize("case", ("unowned", "unrecorded", "nonexistent", "duplicate", "alternate-optimization"))
def test_target_payload_rejects_unowned_bytecode_record(tmp_path: Path, case: str) -> None:
    site = tmp_path / "site-packages"
    payload = site / "dcc_mcp_unreal" / "_plugin"
    descriptor = payload / "DccMcpUnreal.uplugin"
    source = payload / "Content" / "Python" / "init_unreal.py"
    generated_name = {
        "unowned": "unrelated.pyc",
        "unrecorded": "unrelated.pyc",
        "nonexistent": f"init_unreal.{sys.implementation.cache_tag}.pyc",
        "duplicate": f"init_unreal.{sys.implementation.cache_tag}.pyc",
        "alternate-optimization": f"init_unreal.{sys.implementation.cache_tag}.opt-debug.pyc",
    }[case]
    generated = payload / "Content" / "Python" / "__pycache__" / generated_name
    generated.parent.mkdir(parents=True)
    descriptor.parent.mkdir(parents=True, exist_ok=True)
    descriptor.write_text(json.dumps({"FileVersion": 3, "VersionName": install_cli.__version__}), encoding="utf-8")
    source.write_text("# authenticated source\n", encoding="utf-8")
    if case != "nonexistent":
        generated.write_bytes(b"unowned bytecode")
    descriptor_digest = (
        base64.urlsafe_b64encode(hashlib.sha256(descriptor.read_bytes()).digest()).decode("ascii").rstrip("=")
    )
    source_digest = base64.urlsafe_b64encode(hashlib.sha256(source.read_bytes()).digest()).decode("ascii").rstrip("=")
    generated_record = {
        "located": str(generated.absolute()),
        "path": generated.relative_to(site).as_posix(),
        "hash": None,
        "size": None,
    }
    runtime = {
        "adapter_origin": str(site / "dcc_mcp_unreal" / "__init__.py"),
        "adapter_distribution_root": str(site),
        "plugin_payload": {
            "root": str(payload),
            "provenance": "wheel",
            "ownership_root": str(site),
            "cache_tag": sys.implementation.cache_tag,
            "records": [
                {
                    "located": str(descriptor.absolute()),
                    "path": descriptor.relative_to(site).as_posix(),
                    "hash": f"sha256={descriptor_digest}",
                    "size": descriptor.stat().st_size,
                },
                {
                    "located": str(source.absolute()),
                    "path": source.relative_to(site).as_posix(),
                    "hash": f"sha256={source_digest}",
                    "size": source.stat().st_size,
                },
                *([] if case == "unrecorded" else [generated_record]),
                *([dict(generated_record)] if case == "duplicate" else []),
            ],
        },
    }

    with pytest.raises(ValueError, match="RECORD|bytecode"):
        install_cli._bind_target_payload(runtime)


def test_target_runtime_accepts_the_active_distribution_context() -> None:
    runtime = install_cli._target_runtime(Path(sys.executable))

    assert runtime["adapter_version"] == install_cli.__version__
    assert Path(runtime["adapter_origin"]).name == "__init__.py"
    assert Path(runtime["core_origin"]).name == "__init__.py"


def test_distribution_identity_rejects_same_bytes_from_independent_source(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    owned = source_root / "src" / "dcc_mcp_unreal" / "__init__.py"
    replacement = tmp_path / "replacement" / "src" / "dcc_mcp_unreal" / "__init__.py"
    owned.parent.mkdir(parents=True)
    replacement.parent.mkdir(parents=True)
    owned.write_text("# identical\n", encoding="utf-8")
    replacement.write_bytes(owned.read_bytes())
    identity = _distribution_identity(
        replacement,
        tmp_path / "site-packages",
        direct_url={"url": source_root.as_uri(), "dir_info": {}},
    )

    with pytest.raises(ValueError, match="owned"):
        install_cli._owned_module_origin(identity, "dcc-mcp-unreal", "dcc_mcp_unreal")


def test_distribution_identity_rejects_symlinked_source_package(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    payload = tmp_path / "payload" / "dcc_mcp_unreal"
    payload.mkdir(parents=True)
    (payload / "__init__.py").write_text("# package\n", encoding="utf-8")
    package_link = source_root / "src" / "dcc_mcp_unreal"
    package_link.parent.mkdir(parents=True)
    if sys.platform == "win32":
        linked = subprocess.run(
            ["cmd", "/d", "/c", "mklink", "/J", str(package_link), str(payload)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert linked.returncode == 0, linked.stderr or linked.stdout
    else:
        os.symlink(payload, package_link, target_is_directory=True)
    origin = package_link / "__init__.py"
    identity = _distribution_identity(
        origin,
        tmp_path / "site-packages",
        direct_url={"url": source_root.as_uri(), "dir_info": {}},
    )

    with pytest.raises(ValueError, match="link|reparse"):
        install_cli._owned_module_origin(identity, "dcc-mcp-unreal", "dcc_mcp_unreal")


def test_distribution_identity_rejects_hardlinked_module(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    origin = source_root / "src" / "dcc_mcp_unreal" / "__init__.py"
    independent = tmp_path / "independent.py"
    origin.parent.mkdir(parents=True)
    independent.write_text("# package\n", encoding="utf-8")
    os.link(independent, origin)
    identity = _distribution_identity(
        origin,
        tmp_path / "site-packages",
        direct_url={"url": source_root.as_uri(), "dir_info": {}},
    )

    with pytest.raises(ValueError, match="link"):
        install_cli._owned_module_origin(identity, "dcc-mcp-unreal", "dcc_mcp_unreal")


def test_target_payload_rejects_reparse_directory(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    payload = source_root / "unreal" / "plugin"
    external = tmp_path / "external-content"
    payload.mkdir(parents=True)
    external.mkdir()
    (payload / "DccMcpUnreal.uplugin").write_text(
        json.dumps({"FileVersion": 3, "VersionName": install_cli.__version__}), encoding="utf-8"
    )
    linked = payload / "Content"
    if sys.platform == "win32":
        created = subprocess.run(
            ["cmd", "/d", "/c", "mklink", "/J", str(linked), str(external)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert created.returncode == 0, created.stderr or created.stdout
    else:
        os.symlink(external, linked, target_is_directory=True)
    runtime = {
        "adapter_origin": str(source_root / "src" / "dcc_mcp_unreal" / "__init__.py"),
        "adapter_distribution_root": str(tmp_path / "site-packages"),
        "plugin_payload": {
            "root": str(payload),
            "provenance": "source-checkout",
            "ownership_root": str(source_root),
        },
    }
    origin = Path(runtime["adapter_origin"])
    origin.parent.mkdir(parents=True)
    origin.write_text("# package\n", encoding="utf-8")

    with pytest.raises(ValueError, match="link|reparse"):
        install_cli._bind_target_payload(runtime)


def test_target_payload_rejects_hardlinked_file(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    payload = source_root / "unreal" / "plugin"
    origin = source_root / "src" / "dcc_mcp_unreal" / "__init__.py"
    payload.mkdir(parents=True)
    origin.parent.mkdir(parents=True)
    origin.write_text("# package\n", encoding="utf-8")
    independent = tmp_path / "independent.uplugin"
    independent.write_text(json.dumps({"FileVersion": 3, "VersionName": install_cli.__version__}), encoding="utf-8")
    os.link(independent, payload / "DccMcpUnreal.uplugin")
    runtime = {
        "adapter_origin": str(origin),
        "adapter_distribution_root": str(tmp_path / "site-packages"),
        "plugin_payload": {
            "root": str(payload),
            "provenance": "source-checkout",
            "ownership_root": str(source_root),
        },
    }

    with pytest.raises(ValueError, match="hardlink"):
        install_cli._bind_target_payload(runtime)


@pytest.mark.parametrize(
    ("field", "value"),
    (("name", "foreign-distribution"), ("version", "0.0.1")),
)
def test_distribution_identity_rejects_mismatched_product_metadata(tmp_path: Path, field: str, value: str) -> None:
    source_root = tmp_path / "source"
    origin = source_root / "src" / "dcc_mcp_unreal" / "__init__.py"
    origin.parent.mkdir(parents=True)
    origin.write_text("# package\n", encoding="utf-8")
    identity = _distribution_identity(
        origin,
        tmp_path / "site-packages",
        direct_url={"url": source_root.as_uri(), "dir_info": {}},
    )
    identity[field] = value

    with pytest.raises(ValueError, match="identity|version"):
        install_cli._owned_module_origin(identity, "dcc-mcp-unreal", "dcc_mcp_unreal")


@pytest.mark.parametrize("editable", (0, 1, "true", {}, []))
def test_distribution_identity_rejects_malformed_source_metadata(tmp_path: Path, editable: object) -> None:
    source_root = tmp_path / "source"
    origin = source_root / "src" / "dcc_mcp_unreal" / "__init__.py"
    origin.parent.mkdir(parents=True)
    origin.write_text("# package\n", encoding="utf-8")
    identity = _distribution_identity(
        origin,
        tmp_path / "site-packages",
        direct_url={"url": source_root.as_uri(), "dir_info": {"editable": editable}},
    )

    with pytest.raises(ValueError, match="owned"):
        install_cli._owned_module_origin(identity, "dcc-mcp-unreal", "dcc_mcp_unreal")


def _bound_readiness(context: dict, *, instance_id: str = "11111111-1111-1111-1111-111111111111") -> dict:
    identity = {
        "instance_id": instance_id,
        "host_pid": 4242,
        "process_start_token": "unreal-start-token",
        "editor_executable": str(context["editor_path"]),
        "project_file": str(context["project_file"]),
        "plugin_root": str(context["plugin_root"]),
        "engine_version": context["engine_version"],
        "adapter_version": install_cli.__version__,
        "core_version": context["runtime"]["core_version"],
        "adapter_origin": context["runtime"]["adapter_origin"],
        "core_origin": context["runtime"]["core_origin"],
    }
    return {
        "success": True,
        "ready": True,
        "entry": {"instance_id": instance_id, "parent_pid": 4242},
        "probe": {"success": True, "result": {"success": True, "context": {"install_identity": identity}}},
    }


def _isolated_source_runtime(tmp_path: Path) -> tuple[dict, Path, Path]:
    active = install_cli._target_runtime(Path(sys.executable))
    source_root = tmp_path / "isolated-source"
    origin = source_root / "src" / "dcc_mcp_unreal" / "__init__.py"
    payload = source_root / "unreal" / "plugin"
    origin.parent.mkdir(parents=True)
    shutil.copy2(active["adapter_origin"], origin)
    shutil.copytree(active["plugin_payload"]["root"], payload)
    runtime = dict(active)
    runtime["adapter_origin"] = str(origin.absolute())
    runtime["adapter_distribution_root"] = str((tmp_path / "site-packages").absolute())
    runtime.pop("adapter_source_identity", None)
    runtime.pop("adapter_module_identity", None)
    runtime["plugin_payload"] = {
        "root": str(payload.absolute()),
        "provenance": "source-checkout",
        "ownership_root": str(source_root.absolute()),
    }
    return install_cli._bind_target_payload(runtime), origin, payload


@pytest.mark.parametrize(
    ("drift_axis", "ready"),
    (
        ("source", True),
        ("payload", False),
        ("installed-plugin", True),
        ("project", False),
        ("receipt", True),
        ("backup", False),
    ),
)
def test_pending_resolution_preserves_evidence_when_bound_identity_drifts_during_wait(
    monkeypatch, tmp_path: Path, drift_axis: str, ready: bool
) -> None:
    runtime, origin, payload = _isolated_source_runtime(tmp_path)
    monkeypatch.setattr(install_cli, "_target_runtime", lambda _python: runtime)
    engine, project = _synthetic_host(tmp_path)
    common = [
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--timeout",
        "0",
    ]
    install_args = install_cli._parser().parse_args(["install", *common, "--yes"])
    _execute_expect(install_args, 40)
    context = install_cli._resolve_context(install_args)
    receipt_path = context["receipt_path"]
    prior = json.loads(receipt_path.read_text(encoding="utf-8"))
    prior["adapter_version"] = "0.2.9"
    receipt_path.write_text(json.dumps(prior), encoding="utf-8")
    upgrade_args = install_cli._parser().parse_args(["upgrade", *common, "--yes"])
    assert install_cli._execute(upgrade_args)[0] == 40
    pending = json.loads(receipt_path.read_text(encoding="utf-8"))
    backup = Path(pending["transaction"]["backup_plugin"])
    pending_receipt = receipt_path.read_bytes()
    backup_manifest = install_cli._file_manifest(backup)
    verify_args = install_cli._parser().parse_args(
        [
            "verify",
            *common,
            "--instance-id",
            "11111111-1111-1111-1111-111111111111",
        ]
    )
    verify_context = install_cli._resolve_context(verify_args)
    mutated_receipt: list[bytes] = []

    def drift_during_wait(**_kwargs: object) -> dict:
        targets = {
            "source": origin,
            "payload": payload / "DccMcpUnreal.uplugin",
            "installed-plugin": verify_context["plugin_root"] / "DccMcpUnreal.uplugin",
            "project": project,
            "receipt": receipt_path,
            "backup": backup / "DccMcpUnreal.uplugin",
        }
        target = targets[drift_axis]
        target.write_bytes(target.read_bytes() + b" \n")
        if drift_axis == "receipt":
            mutated_receipt.append(receipt_path.read_bytes())
        if ready:
            return _bound_readiness(verify_context)
        return {"success": False, "ready": False, "message": "injected readiness failure"}

    monkeypatch.setattr(dcc_mcp_core, "wait_for_sidecar_ready", drift_during_wait)

    exit_code, result = install_cli._execute(verify_args)

    assert exit_code == 30
    assert result["verify"]["failure_stage"] == "verify"
    assert "changed" in result["verify"]["failure_reason"]
    assert receipt_path.read_bytes() == (mutated_receipt[0] if mutated_receipt else pending_receipt)
    assert backup.is_dir()
    if drift_axis != "backup":
        assert install_cli._file_manifest(backup) == backup_manifest


def test_upgrade_source_drift_before_backup_preserves_prior_install(monkeypatch, tmp_path: Path) -> None:
    runtime, _origin, payload = _isolated_source_runtime(tmp_path)
    monkeypatch.setattr(install_cli, "_target_runtime", lambda _python: runtime)
    engine, project = _synthetic_host(tmp_path)
    common = [
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--timeout",
        "0",
    ]
    install_args = install_cli._parser().parse_args(["install", *common, "--yes"])
    _execute_expect(install_args, 40)
    context = install_cli._resolve_context(install_args)
    plugin_root = context["plugin_root"]
    receipt_path = context["receipt_path"]
    prior = json.loads(receipt_path.read_text(encoding="utf-8"))
    prior["adapter_version"] = "0.2.9"
    receipt_path.write_text(json.dumps(prior), encoding="utf-8")
    prior_plugin = install_cli._file_manifest(plugin_root)
    prior_project = project.read_bytes()
    prior_receipt = receipt_path.read_bytes()
    real_copy = install_cli.shutil.copy2
    drifted = False

    def copy_then_drift(source: Path, destination: Path) -> str:
        nonlocal drifted
        result = real_copy(source, destination)
        if not drifted:
            descriptor = payload / "DccMcpUnreal.uplugin"
            descriptor.write_bytes(descriptor.read_bytes() + b" \n")
            drifted = True
        return result

    monkeypatch.setattr(install_cli.shutil, "copy2", copy_then_drift)
    upgrade_args = install_cli._parser().parse_args(["upgrade", *common, "--yes"])

    exit_code, result = install_cli._execute(upgrade_args)

    assert exit_code == 20
    assert result["verify"]["failure_stage"] == "acquire"
    assert install_cli._file_manifest(plugin_root) == prior_plugin
    assert project.read_bytes() == prior_project
    assert receipt_path.read_bytes() == prior_receipt
    assert not list(plugin_root.parent.glob(".DccMcpUnreal.*-*"))


@pytest.mark.parametrize("install_state", ("fresh", "upgrade"))
@pytest.mark.parametrize(
    ("failure_window", "expected_exit", "expected_stage"),
    (
        ("recapture", 20, "acquire"),
        ("staging", 20, "acquire"),
        ("publish-after-backup", 30, "install"),
    ),
)
def test_install_failure_window_preserves_only_preexisting_state(
    monkeypatch,
    tmp_path: Path,
    install_state: str,
    failure_window: str,
    expected_exit: int,
    expected_stage: str,
) -> None:
    runtime, _origin, payload = _isolated_source_runtime(tmp_path)
    monkeypatch.setattr(install_cli, "_target_runtime", lambda _python: runtime)
    engine, project = _synthetic_host(tmp_path)
    common = [
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--timeout",
        "0",
    ]
    install_args = install_cli._parser().parse_args(["install", *common, "--yes"])
    context = install_cli._resolve_context(install_args)
    plugin_root = context["plugin_root"]
    receipt_path = context["receipt_path"]
    if install_state == "upgrade":
        _execute_expect(install_args, 40)
        prior = json.loads(receipt_path.read_text(encoding="utf-8"))
        prior["adapter_version"] = "0.2.9"
        receipt_path.write_text(json.dumps(prior), encoding="utf-8")
        operation_args = install_cli._parser().parse_args(["upgrade", *common, "--yes"])
    else:
        operation_args = install_args
    prior_plugin = install_cli._file_manifest(plugin_root)
    prior_project = project.read_bytes()
    prior_receipt = receipt_path.read_bytes() if receipt_path.is_file() else None
    drifted = False

    if failure_window == "recapture":
        inspect_state = install_cli._inspect_state

        def drift_after_state(context_value: dict) -> tuple[str, Optional[dict], Optional[str]]:
            nonlocal drifted
            result = inspect_state(context_value)
            if not drifted:
                descriptor = payload / "DccMcpUnreal.uplugin"
                descriptor.write_bytes(descriptor.read_bytes() + b" \n")
                drifted = True
            return result

        monkeypatch.setattr(install_cli, "_inspect_state", drift_after_state)
    elif failure_window == "staging":
        real_copy = install_cli.shutil.copy2

        def copy_then_drift(source: Path, destination: Path) -> str:
            nonlocal drifted
            result = real_copy(source, destination)
            if not drifted:
                descriptor = payload / "DccMcpUnreal.uplugin"
                descriptor.write_bytes(descriptor.read_bytes() + b" \n")
                drifted = True
            return result

        monkeypatch.setattr(install_cli.shutil, "copy2", copy_then_drift)
    else:
        real_replace = install_cli.os.replace

        def fail_new_publish(source: Path, destination: Path) -> None:
            if Path(source).name.startswith(".DccMcpUnreal.staging-") and Path(destination) == plugin_root:
                raise OSError("injected publish failure")
            real_replace(source, destination)

        monkeypatch.setattr(install_cli.os, "replace", fail_new_publish)

    exit_code, result = install_cli._execute(operation_args)

    assert exit_code == expected_exit
    assert result["verify"]["failure_stage"] == expected_stage
    assert install_cli._file_manifest(plugin_root) == prior_plugin
    assert project.read_bytes() == prior_project
    assert (receipt_path.read_bytes() if receipt_path.is_file() else None) == prior_receipt
    assert not list(plugin_root.parent.glob(".DccMcpUnreal.*-*"))


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("instance_id", "22222222-2222-2222-2222-222222222222"),
        ("host_pid", 5151),
        ("process_start_token", "bad"),
        ("editor_executable", "foreign-editor"),
        ("project_file", "foreign-project"),
        ("plugin_root", "foreign-plugin"),
        ("engine_version", "5.6.0"),
        ("adapter_version", "0.0.1"),
        ("core_version", "0.0.1"),
        ("adapter_origin", "foreign-adapter"),
        ("core_origin", "foreign-core"),
    ),
)
def test_readiness_identity_rejects_each_foreign_runtime_axis(tmp_path: Path, field: str, replacement: object) -> None:
    engine, project = _synthetic_host(tmp_path)
    args = install_cli._parser().parse_args(
        [
            "verify",
            "--dcc-path",
            str(engine),
            "--python",
            sys.executable,
            "--project",
            str(project),
            "--instance-id",
            "11111111-1111-1111-1111-111111111111",
        ]
    )
    context = install_cli._resolve_context(args)
    readiness = _bound_readiness(context)
    readiness["probe"]["result"]["context"]["install_identity"][field] = replacement

    identity, reason = install_cli._readiness_identity(
        args,
        context,
        {"instance_selector": context["instance_id"], "runtime_identity": None},
        readiness,
    )

    assert identity is None
    assert reason is not None
    assert field in reason


def test_receipted_process_token_rejects_pid_reuse(tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    args = install_cli._parser().parse_args(
        [
            "verify",
            "--dcc-path",
            str(engine),
            "--python",
            sys.executable,
            "--project",
            str(project),
            "--instance-id",
            "11111111-1111-1111-1111-111111111111",
        ]
    )
    context = install_cli._resolve_context(args)
    readiness = _bound_readiness(context)
    previous = dict(readiness["probe"]["result"]["context"]["install_identity"])
    readiness["probe"]["result"]["context"]["install_identity"]["process_start_token"] = "replacement-start-token"

    identity, reason = install_cli._readiness_identity(
        args,
        context,
        {"instance_selector": context["instance_id"], "runtime_identity": previous},
        readiness,
    )

    assert identity is None
    assert reason == "typed readiness identity changed from the receipted editor process"


def test_verify_rejects_foreign_project_instance(monkeypatch, tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    common = [
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--instance-id",
        "11111111-1111-1111-1111-111111111111",
        "--timeout",
        "0",
    ]
    args = install_cli._parser().parse_args(["install", *common, "--yes"])
    context = install_cli._resolve_context(args)
    readiness = _bound_readiness(context)
    readiness["probe"]["result"]["context"]["install_identity"]["project_file"] = str(
        (tmp_path / "Foreign.uproject").resolve()
    )
    monkeypatch.setattr(dcc_mcp_core, "wait_for_sidecar_ready", lambda **_kwargs: readiness)

    exit_code, result = install_cli._execute(args)

    assert exit_code == 40, result
    assert result["verify"]["directly_usable"] is False
    assert "project_file" in result["verify"]["failure_reason"]
    assert not (project.parent / "Plugins" / "DccMcpUnreal").exists()
    assert not (project.parent / ".dcc-mcp" / "receipts" / "unreal.json").exists()


@pytest.mark.parametrize(
    ("verb", "extra", "expected_exit"),
    (
        ("install", ["--dry-run"], 0),
        ("status", [], 0),
        ("verify", [], 40),
        ("uninstall", ["--yes"], 0),
        ("upgrade", ["--dry-run"], 0),
    ),
)
def test_all_public_verbs_validate_against_core_draft_schema(
    tmp_path: Path, verb: str, extra: list[str], expected_exit: int
) -> None:
    engine, project = _synthetic_host(tmp_path)
    args = install_cli._parser().parse_args(
        [
            verb,
            "--json",
            "--dcc-path",
            str(engine),
            "--python",
            sys.executable,
            "--project",
            str(project),
            "--timeout",
            "0",
            *extra,
        ]
    )

    exit_code, result = install_cli._execute(args)

    assert exit_code == expected_exit
    _assert_sop_v1(result)


def test_upgrade_keeps_prior_install_until_bound_verify_succeeds(monkeypatch, tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    common = [
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--instance-id",
        "11111111-1111-1111-1111-111111111111",
        "--timeout",
        "0",
    ]
    install_args = install_cli._parser().parse_args(["install", *common, "--yes"])
    context = install_cli._resolve_context(install_args)
    monkeypatch.setattr(dcc_mcp_core, "wait_for_sidecar_ready", lambda **_kwargs: _bound_readiness(context))
    _execute_expect(install_args, 0)
    plugin_root = context["plugin_root"]
    receipt_path = context["receipt_path"]
    prior_files = install_cli._file_manifest(plugin_root)
    prior_project = project.read_bytes()
    prior_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    prior_receipt["adapter_version"] = "0.2.9"
    receipt_path.write_text(json.dumps(prior_receipt), encoding="utf-8")
    prior_receipt_bytes = receipt_path.read_bytes()
    foreign = _bound_readiness(context)
    foreign["probe"]["result"]["context"]["install_identity"]["plugin_root"] = str(
        (tmp_path / "ForeignPlugin").resolve()
    )
    monkeypatch.setattr(dcc_mcp_core, "wait_for_sidecar_ready", lambda **_kwargs: foreign)
    upgrade_args = install_cli._parser().parse_args(["upgrade", *common, "--yes"])

    exit_code, result = install_cli._execute(upgrade_args)

    assert exit_code == 40, result
    assert "plugin_root" in result["verify"]["failure_reason"]
    assert install_cli._file_manifest(plugin_root) == prior_files
    assert project.read_bytes() == prior_project
    assert receipt_path.read_bytes() == prior_receipt_bytes
    assert not list(plugin_root.parent.glob(".DccMcpUnreal.*-*"))


def test_upgrade_without_live_selector_keeps_rollback_until_later_bound_verify(monkeypatch, tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    common = [
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--timeout",
        "0",
    ]
    install_args = install_cli._parser().parse_args(["install", *common, "--yes"])
    _execute_expect(install_args, 40)
    context = install_cli._resolve_context(install_args)
    plugin_root = context["plugin_root"]
    receipt_path = context["receipt_path"]
    prior_files = install_cli._file_manifest(plugin_root)
    prior_project = project.read_bytes()
    prior_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    prior_receipt["adapter_version"] = "0.2.9"
    receipt_path.write_text(json.dumps(prior_receipt), encoding="utf-8")
    prior_receipt_bytes = receipt_path.read_bytes()

    upgrade_args = install_cli._parser().parse_args(["upgrade", *common, "--yes"])
    _execute_expect(upgrade_args, 40)
    pending_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert pending_receipt["transaction"]["state"] == "awaiting-bound-verify"
    assert Path(pending_receipt["transaction"]["backup_plugin"]).is_dir()
    status_args = install_cli._parser().parse_args(["status", *common])
    status_code, status_result = install_cli._execute(status_args)
    uninstall_args = install_cli._parser().parse_args(["uninstall", *common, "--yes"])
    uninstall_code, uninstall_result = install_cli._execute(uninstall_args)

    assert status_code == 0
    assert status_result["verify"]["failure_stage"] == "readiness"
    assert status_result["next_steps"][0]["id"] == "launch-unreal-editor"
    assert uninstall_code == 10
    assert "awaiting exact-instance" in uninstall_result["verify"]["failure_reason"]
    assert Path(pending_receipt["transaction"]["backup_plugin"]).is_dir()

    verify_args = install_cli._parser().parse_args(
        [
            "verify",
            *common,
            "--instance-id",
            "11111111-1111-1111-1111-111111111111",
        ]
    )
    verify_context = install_cli._resolve_context(verify_args)
    foreign = _bound_readiness(verify_context)
    foreign["probe"]["result"]["context"]["install_identity"]["project_file"] = str(
        (tmp_path / "Foreign.uproject").resolve()
    )
    monkeypatch.setattr(dcc_mcp_core, "wait_for_sidecar_ready", lambda **_kwargs: foreign)

    exit_code, result = install_cli._execute(verify_args)

    assert exit_code == 40, result
    assert "project_file" in result["verify"]["failure_reason"]
    assert install_cli._file_manifest(plugin_root) == prior_files
    assert project.read_bytes() == prior_project
    assert receipt_path.read_bytes() == prior_receipt_bytes
    assert not list(plugin_root.parent.glob(".DccMcpUnreal.*-*"))


def test_uninstall_delete_failure_restores_every_owned_byte(monkeypatch, tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    common = [
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--instance-id",
        "11111111-1111-1111-1111-111111111111",
        "--timeout",
        "0",
    ]
    install_args = install_cli._parser().parse_args(["install", *common, "--yes"])
    context = install_cli._resolve_context(install_args)
    monkeypatch.setattr(dcc_mcp_core, "wait_for_sidecar_ready", lambda **_kwargs: _bound_readiness(context))
    _execute_expect(install_args, 0)
    plugin_root = context["plugin_root"]
    receipt_path = context["receipt_path"]
    prior_files = install_cli._file_manifest(plugin_root)
    prior_project = project.read_bytes()
    prior_receipt = receipt_path.read_bytes()
    real_remove = install_cli._remove_tree

    def fail_quarantine(path: Path) -> None:
        if ".uninstall-" in path.name:
            victim = next(item for item in path.rglob("*") if item.is_file())
            victim.unlink()
            raise OSError("injected partial quarantine delete")
        real_remove(path)

    monkeypatch.setattr(install_cli, "_remove_tree", fail_quarantine)
    uninstall_args = install_cli._parser().parse_args(["uninstall", *common, "--yes"])

    exit_code, result = install_cli._execute(uninstall_args)

    assert exit_code == 30
    assert result["verify"]["failure_stage"] == "uninstall"
    assert install_cli._file_manifest(plugin_root) == prior_files
    assert project.read_bytes() == prior_project
    assert receipt_path.read_bytes() == prior_receipt
