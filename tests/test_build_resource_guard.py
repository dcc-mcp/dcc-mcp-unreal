from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

BUILD_SCRIPT = Path(__file__).resolve().parents[1] / "packaging" / "build_distributable.py"
ORIGINAL_CONFIG = (
    b"<Configuration><WindowsPlatform><CompilerVersion>14.36</CompilerVersion></WindowsPlatform></Configuration>"
)
USER_EDIT = (
    b"<Configuration><WindowsPlatform><CompilerVersion>user-edit</CompilerVersion></WindowsPlatform></Configuration>"
)

# These helpers only call the config guard; they never execute a build command.
HELPER_SOURCE = r"""
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

script, sandbox_arg, config_arg, state_arg, mode, timeout_arg, clear_arg = sys.argv[1:]
sandbox = Path(sandbox_arg).resolve()
config = Path(config_arg).resolve()
state = Path(state_arg).resolve()
assert sandbox in config.parents and sandbox in state.parents
spec = importlib.util.spec_from_file_location("guard_under_test", script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
# APPDATA alone is insufficient on Windows: the real resolver uses shell32.
module.ubt_user_config_path = lambda: config
backup = config.with_suffix(".xml.dcc-mcp-backup")

def publish(name, data):
    pending = state / (name + ".pending")
    pending.write_text(json.dumps(data), encoding="utf-8")
    os.replace(pending, state / name)

try:
    publish("attempting.json", {"pid": os.getpid()})
    with module.temporarily_clear_legacy_ubt_user_config(
        sandbox / "unused-work", clear=clear_arg == "1", timeout=float(timeout_arg)
    ):
        publish("entered.json", {
            "pid": os.getpid(),
            "config": config.read_bytes().hex() if config.exists() else None,
            "backup": backup.read_bytes().hex() if backup.exists() else None,
        })
        deadline = time.monotonic() + 10
        while not (state / "release").exists():
            if time.monotonic() >= deadline:
                raise RuntimeError("test helper release timed out")
            time.sleep(0.01)
        if mode == "runtime-error":
            raise RuntimeError("simulated build failure")
        if mode == "keyboard-interrupt":
            raise KeyboardInterrupt("simulated cancellation")
        if mode == "system-exit":
            raise SystemExit(17)
except BaseException as exc:
    publish("finished.json", {"error": type(exc).__name__, "message": str(exc)})
    raise
else:
    publish("finished.json", {"error": None})
"""


class GuardProcess:
    def __init__(self, process, state):
        self.process = process
        self.state = state

    def token(self, name, timeout=8):
        path = self.state / name
        deadline = time.monotonic() + timeout
        while True:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (FileNotFoundError, PermissionError):
                # Windows may briefly deny opening a file while its rename completes.
                pass
            if self.process.poll() is not None and not path.exists():
                stdout, stderr = self.process.communicate(timeout=1)
                raise AssertionError(f"helper exited {self.process.returncode} before {name}: {stdout!r}; {stderr!r}")
            if time.monotonic() >= deadline:
                raise AssertionError(f"helper did not publish {name}")
            time.sleep(0.01)

    def release(self):
        (self.state / "release").touch()

    def finish(self, expected_error=None):
        stdout, stderr = self.process.communicate(timeout=8)
        result = json.loads((self.state / "finished.json").read_text(encoding="utf-8"))
        assert result["error"] == expected_error, (result, stdout, stderr)
        if expected_error is None:
            assert self.process.returncode == 0, (stdout, stderr)
        else:
            assert self.process.returncode != 0, (stdout, stderr)
        return result


@pytest.fixture
def guard_processes(tmp_path):
    helper = tmp_path / "guard_helper.py"
    helper.write_text(HELPER_SOURCE, encoding="utf-8")
    config = tmp_path / "user-config" / "BuildConfiguration.xml"
    config.parent.mkdir()
    config.write_bytes(ORIGINAL_CONFIG)
    children = []

    def start(mode, timeout=5, clear=None):
        if clear is None:
            clear = mode != "reader"
        state = tmp_path / f"helper-{len(children)}"
        state.mkdir()
        env = os.environ.copy()
        env["APPDATA"] = str(tmp_path / "unused-appdata")
        # Windows venv launchers spawn a second process; own the real stdlib-only helper directly.
        helper_python = getattr(sys, "_base_executable", sys.executable) if os.name == "nt" else sys.executable
        process = subprocess.Popen(
            [
                helper_python,
                "-I",
                "-B",
                str(helper),
                str(BUILD_SCRIPT),
                str(tmp_path),
                str(config),
                str(state),
                mode,
                str(timeout),
                "1" if clear else "0",
            ],
            cwd=str(tmp_path),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        child = GuardProcess(process, state)
        children.append(child)
        assert child.token("attempting.json")["pid"] == process.pid
        return child

    try:
        yield config, start
    finally:
        # Release and reap only Popen children created by this fixture, even on assertion failure.
        for child in children:
            child.release()
        forced = []
        for child in children:
            try:
                child.process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                forced.append(child.process.pid)
                child.process.terminate()
                try:
                    child.process.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    child.process.kill()
                    child.process.communicate(timeout=3)
        assert not forced, f"owned test helpers failed to finish cooperatively: {forced}"


def _transaction_paths(config):
    return config.with_suffix(".xml.dcc-mcp-backup"), config.with_suffix(".xml.dcc-mcp-new")


def _assert_cleared(config, observation):
    assert bytes.fromhex(observation["config"]) == config.read_bytes()
    assert config.read_bytes() != ORIGINAL_CONFIG
    assert b"CompilerVersion" not in config.read_bytes()
    assert bytes.fromhex(observation["backup"]) == ORIGINAL_CONFIG


def _assert_restored(config):
    backup, pending = _transaction_paths(config)
    assert config.read_bytes() == ORIGINAL_CONFIG
    assert not backup.exists()
    assert not pending.exists()
    assert not config.with_suffix(".xml.dcc-mcp-active").exists()


@pytest.mark.parametrize("second_mode", ["writer", "reader"])
def test_legacy_writer_serializes_other_writers_and_modern_readers(guard_processes, second_mode):
    config, start = guard_processes
    first = start("writer")
    _assert_cleared(config, first.token("entered.json"))
    backup, pending = _transaction_paths(config)
    held_config = config.read_bytes()
    active = config.with_suffix(".xml.dcc-mcp-active")
    held_marker = active.read_bytes()
    assert held_marker
    second = start(second_mode)

    # Both helpers have acknowledged their attempt while the first still owns the lock.
    deadline = time.monotonic() + 0.25
    while time.monotonic() < deadline:
        assert not (second.state / "entered.json").exists()
        assert second.process.poll() is None
        assert config.read_bytes() == held_config
        assert backup.read_bytes() == ORIGINAL_CONFIG
        assert active.read_bytes() == held_marker
        assert not pending.exists()
        time.sleep(0.01)

    first.release()
    first.finish()
    observation = second.token("entered.json")
    if second_mode == "writer":
        _assert_cleared(config, observation)
    else:
        assert bytes.fromhex(observation["config"]) == ORIGINAL_CONFIG
        assert observation["backup"] is None
    second.release()
    second.finish()
    _assert_restored(config)


@pytest.mark.parametrize("waiting_mode", ["writer", "reader"])
def test_lock_timeout_preserves_live_transaction(guard_processes, waiting_mode):
    config, start = guard_processes
    owner = start("writer")
    owner.token("entered.json")
    backup, pending = _transaction_paths(config)
    active = config.with_suffix(".xml.dcc-mcp-active")
    original_transaction = (config.read_bytes(), backup.read_bytes(), active.read_bytes())

    waiter = start(waiting_mode, timeout=0.2)
    result = waiter.finish("TimeoutError")
    assert "Timed out waiting for UBT user config lock" in result["message"]
    assert not (waiter.state / "entered.json").exists()
    assert owner.process.poll() is None
    assert (config.read_bytes(), backup.read_bytes(), active.read_bytes()) == original_transaction
    assert not pending.exists()

    owner.release()
    owner.finish()
    _assert_restored(config)


def test_ordinary_build_failure_restores_original_config(guard_processes):
    config, start = guard_processes
    child = start("runtime-error")
    _assert_cleared(config, child.token("entered.json"))
    child.release()
    result = child.finish("RuntimeError")
    assert result["message"] == "simulated build failure"
    _assert_restored(config)


@pytest.mark.parametrize("mode", ["keyboard-interrupt", "system-exit", "terminate"])
@pytest.mark.parametrize("role", ["writer", "reader", "absent-config"])
def test_cancellation_keeps_recovery_evidence_and_next_reader_refuses(guard_processes, mode, role):
    config, start = guard_processes
    if role == "absent-config":
        config.unlink()
    owner = start(mode, clear=role != "reader")
    observation = owner.token("entered.json")
    backup, pending = _transaction_paths(config)
    active = config.with_suffix(".xml.dcc-mcp-active")
    if role == "writer":
        _assert_cleared(config, observation)
        assert backup.read_bytes() == ORIGINAL_CONFIG
    else:
        assert observation["config"] == (ORIGINAL_CONFIG.hex() if role == "reader" else None)
        assert observation["backup"] is None
    interrupted_config = config.read_bytes() if config.exists() else None
    interrupted_marker = active.read_bytes()
    assert interrupted_marker
    if mode == "terminate":
        # Terminate only this test's owned Python helper, with no child build process.
        owner.process.terminate()
        owner.process.communicate(timeout=3)
        assert owner.process.returncode != 0
        assert not (owner.state / "finished.json").exists()
    else:
        owner.release()
        owner.finish({"keyboard-interrupt": "KeyboardInterrupt", "system-exit": "SystemExit"}[mode])

    assert (config.read_bytes() if config.exists() else None) == interrupted_config
    assert (backup.read_bytes() if backup.exists() else None) == (ORIGINAL_CONFIG if role == "writer" else None)
    assert active.read_bytes() == interrupted_marker
    assert not pending.exists()
    reader = start("reader")
    result = reader.finish("RuntimeError")
    assert "Unfinished UBT build; stop its UAT children" in result["message"]
    assert not (reader.state / "entered.json").exists()
    assert (config.read_bytes() if config.exists() else None) == interrupted_config
    assert (backup.read_bytes() if backup.exists() else None) == (ORIGINAL_CONFIG if role == "writer" else None)
    assert active.read_bytes() == interrupted_marker


@pytest.mark.parametrize("role", ["reader", "absent-config"])
def test_unmodified_config_invocations_remove_active_marker_on_success(guard_processes, role):
    config, start = guard_processes
    if role == "absent-config":
        config.unlink()
    child = start("reader" if role == "reader" else "writer")
    observation = child.token("entered.json")
    active = config.with_suffix(".xml.dcc-mcp-active")
    assert active.read_bytes()
    assert observation["config"] == (ORIGINAL_CONFIG.hex() if role == "reader" else None)
    assert observation["backup"] is None
    child.release()
    child.finish()
    assert not active.exists()
    if role == "reader":
        _assert_restored(config)
    else:
        assert not config.exists()
        assert not any(path.exists() for path in _transaction_paths(config))


def test_unexpected_user_edit_is_never_overwritten(guard_processes):
    config, start = guard_processes
    owner = start("writer")
    owner.token("entered.json")
    config.write_bytes(USER_EDIT)
    owner.release()
    result = owner.finish("RuntimeError")
    backup, pending = _transaction_paths(config)
    assert "UBT config changed during build" in result["message"]
    assert config.read_bytes() == USER_EDIT
    assert backup.read_bytes() == ORIGINAL_CONFIG
    assert not pending.exists()
    active = config.with_suffix(".xml.dcc-mcp-active")
    interrupted_marker = active.read_bytes()

    reader = start("reader")
    assert "Unfinished UBT build; stop its UAT children" in reader.finish("RuntimeError")["message"]
    assert not (reader.state / "entered.json").exists()
    assert config.read_bytes() == USER_EDIT
    assert backup.read_bytes() == ORIGINAL_CONFIG
    assert active.read_bytes() == interrupted_marker
