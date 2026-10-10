"""Native packaging contracts; fake UAT bytes are never native behavior evidence."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location("_test_" + name, ROOT / "packaging" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_project(root, name):
    root.mkdir(parents=True)
    (root / "README.md").write_text("fixture\n", encoding="utf-8")
    (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
    package = root / "src" / name.replace("-", "_")
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("# fixture package\n", encoding="utf-8")
    (package / "__version__.py").write_text('__version__ = "0.99.0"\n', encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n'
        '[project]\nname = "' + name + '"\nversion = "0.99.0"\nreadme = "README.md"\n'
        '[tool.hatch.build.targets.wheel]\npackages = ["src/' + name.replace("-", "_") + '"]\n',
        encoding="utf-8",
    )
    return root


@pytest.fixture
def native_fixture(tmp_path, monkeypatch):
    module = load_script("build_distributable")
    repo = make_project(tmp_path / "repo", "dcc-mcp-unreal")
    with (repo / "pyproject.toml").open("a", encoding="utf-8") as handle:
        handle.write('[tool.hatch.build.targets.wheel.force-include]\n"unreal/plugin" = "dcc_mcp_unreal/_plugin"\n')
    plugin = repo / "unreal" / "plugin"
    (plugin / "Source").mkdir(parents=True)
    (plugin / "Source" / "Module.cpp").write_text("// fresh source\n", encoding="utf-8")
    (plugin / "Content" / "Python").mkdir(parents=True)
    (plugin / "Content" / "Python" / "init_unreal.py").write_text("# fixture bootstrap\n", encoding="utf-8")
    (plugin / "DccMcpUnreal.uplugin").write_text(json.dumps({"VersionName": "0.99.0", "Modules": []}), encoding="utf-8")
    (repo / "packaging").mkdir()
    for name in ("build_plugin.py", "post_install.py"):
        shutil.copy2(ROOT / "packaging" / name, repo / "packaging" / name)
    engine = tmp_path / "engine"
    (engine / "Engine" / "Build" / "BatchFiles").mkdir(parents=True)
    (engine / "Engine" / "Build" / "BatchFiles" / "RunUAT.bat").write_text("fake only", encoding="utf-8")
    (engine / "Engine" / "Build" / "Build.version").write_text(
        json.dumps({"MajorVersion": 5, "MinorVersion": 7}), encoding="utf-8"
    )
    (engine / "Engine" / "Binaries" / "Win64").mkdir(parents=True)
    (engine / "Engine" / "Binaries" / "Win64" / "UnrealEditor.modules").write_text(
        json.dumps({"BuildId": "fixture-engine"}), encoding="utf-8"
    )
    monkeypatch.setattr(module, "REPO_ROOT", repo)
    monkeypatch.setattr(module, "PLUGIN_SOURCE", plugin / "DccMcpUnreal.uplugin")
    return module, repo, plugin, engine


def fake_uat(plugin, output, build_id="fixture-engine"):
    shutil.copytree(plugin, output)
    binaries = output / "Binaries" / "Win64"
    binaries.mkdir(parents=True)
    (binaries / "UnrealEditor-DccMcpUnreal.dll").write_bytes(b"new fake DLL from this fake UAT invocation")
    (binaries / "UnrealEditor.modules").write_text(
        json.dumps({"BuildId": build_id, "Modules": {"DccMcpUnreal": "UnrealEditor-DccMcpUnreal.dll"}}),
        encoding="utf-8",
    )


@pytest.mark.skipif(sys.platform != "win32", reason="native output and pip acceptance target Win64")
@pytest.mark.parametrize("include_license", [True, False], ids=["with-license", "without-license"])
def test_native_mode_builds_and_vendors_exact_new_wheel(native_fixture, tmp_path, monkeypatch, include_license):
    """Real offline pip/Hatch build+vendoring around a fake UAT tree."""
    pytest.importorskip("hatchling")
    pytest.importorskip("pip")
    module, repo, plugin, engine = native_fixture
    if not include_license:
        (repo / "LICENSE").unlink()
    core = make_project(tmp_path / "core", "dcc-mcp-core")
    events = []

    def uat(args, output):
        events.append("uat")
        fake_uat(plugin, output)

    real_payload = module.build_python_payload

    def payload(args, output, adapter_wheel=None):
        events.append("native-wheel-vendor" if adapter_wheel else "bootstrap-vendor")
        real_payload(args, output, adapter_wheel)

    monkeypatch.setattr(module, "build_precompiled_plugin", uat)
    monkeypatch.setattr(module, "build_python_payload", payload)
    monkeypatch.setenv("PIP_NO_INDEX", "1")
    # pip's negative option parser: zero disables build isolation.
    monkeypatch.setenv("PIP_NO_BUILD_ISOLATION", "0")
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_distributable.py",
            "--mode",
            "native",
            "--ue-root",
            str(engine),
            "--python",
            sys.executable,
            "--use-local-core",
            "--core-root",
            str(core),
        ],
    )
    locked = module.native_source_lock()
    assert ("LICENSE" in locked["metadata"]) == include_license
    module.main()

    assert events == ["uat", "bootstrap-vendor", "native-wheel-vendor"]
    work = repo / "dist" / "_uplugin_work"
    manifest = json.loads((repo / "dist" / "package" / "native-wheel-build.json").read_text(encoding="utf-8"))
    wheel = Path(manifest["wheel"])
    staged_plugin = work / "wheel-payload" / "DccMcpUnreal"
    final_plugin = repo / "dist" / "package" / "DccMcpUnreal"
    module.verify_native_wheel(wheel, staged_plugin)
    assert module.native_source_lock() == locked
    assert (work / "native-wheel-source" / "LICENSE").exists() == include_license
    assert manifest["native"]["engine_build_id"] == "fixture-engine"
    assert manifest["native"]["dll_sha256"] == module.tree_hashes(final_plugin)[manifest["native"]["dll"]]
    assert module.tree_hashes(final_plugin / "python" / "dcc_mcp_unreal" / "_plugin") == module.tree_hashes(
        staged_plugin
    )
    assert (staged_plugin / "python" / "dcc_mcp_core" / "__init__.py").is_file()
    bootstrap_plugin = staged_plugin / "python" / "dcc_mcp_unreal" / "_plugin"
    assert not (bootstrap_plugin / "python").exists()
    assert not (bootstrap_plugin / "Binaries").exists()
    with zipfile.ZipFile(wheel) as archive:
        assert "Root-Is-Purelib: false" in archive.read("dcc_mcp_unreal-0.99.0.dist-info/WHEEL").decode()
        members = {name: archive.read(name) for name in archive.namelist()}
    # Deliberately corrupt only a test artifact to prove RECORD rejection.
    tampered = tmp_path / "tampered-test-wheel.whl"
    with zipfile.ZipFile(tampered, "w") as archive:
        for name, content in members.items():
            if name.endswith("UnrealEditor-DccMcpUnreal.dll"):
                content += b"tampered"
            archive.writestr(name, content)
    with pytest.raises(RuntimeError, match="RECORD hash mismatch"):
        module.verify_native_wheel(tampered, staged_plugin)
    assert list((repo / "dist").glob("DccMcpUnreal-*-ue5.7-win64.zip"))


def test_source_change_during_uat_stops_before_vendoring(native_fixture, monkeypatch):
    module, repo, plugin, engine = native_fixture

    def uat(args, output):
        fake_uat(plugin, output)
        (repo / "src" / "dcc_mcp_unreal" / "__init__.py").write_text("# changed\n", encoding="utf-8")

    monkeypatch.setattr(module, "build_precompiled_plugin", uat)
    monkeypatch.setattr(module, "build_python_payload", lambda *args: pytest.fail("must stop before pip"))
    monkeypatch.setattr(sys, "argv", ["build_distributable.py", "--mode", "native", "--ue-root", str(engine)])
    with pytest.raises(RuntimeError, match="source changed during UAT"):
        module.main()


def test_optional_license_appearing_after_source_lock_is_rejected(native_fixture, monkeypatch):
    module, repo, plugin, engine = native_fixture
    (repo / "LICENSE").unlink()

    def uat(args, output):
        fake_uat(plugin, output)
        (repo / "LICENSE").write_text("new input after freeze\n", encoding="utf-8")

    monkeypatch.setattr(module, "build_precompiled_plugin", uat)
    monkeypatch.setattr(module, "build_python_payload", lambda *args: pytest.fail("must stop before pip"))
    monkeypatch.setattr(sys, "argv", ["build_distributable.py", "--mode", "native", "--ue-root", str(engine)])
    with pytest.raises(RuntimeError, match="source changed during UAT"):
        module.main()


@pytest.mark.parametrize("name", ["pyproject.toml", "README.md"])
def test_wheel_metadata_remains_required(native_fixture, name):
    module, repo, _, _ = native_fixture
    (repo / name).unlink()
    with pytest.raises(FileNotFoundError):
        module.native_source_lock()


@pytest.mark.parametrize("change", ["source", "build-id", "missing-dll"])
def test_native_output_requires_locked_source_engine_and_dll(native_fixture, change):
    module, repo, plugin, engine = native_fixture
    locked = module.native_source_lock()
    output = repo / "dist" / "fake-uat"
    fake_uat(plugin, output, "wrong-engine" if change == "build-id" else "fixture-engine")
    if change == "source":
        (output / "Source" / "Module.cpp").write_text("// stale\n", encoding="utf-8")
    elif change == "missing-dll":
        (output / "Binaries" / "Win64" / "UnrealEditor-DccMcpUnreal.dll").unlink()
    with pytest.raises(RuntimeError):
        module.validate_native_output(SimpleNamespace(ue_root=engine), output, locked)


@pytest.mark.parametrize("mode", ["source", "python-only"])
def test_non_native_modes_keep_existing_flow(native_fixture, monkeypatch, mode):
    module, repo, plugin, engine = native_fixture
    calls = []

    def payload(args, output):
        calls.append(args.mode)
        shutil.copytree(plugin, output)

    monkeypatch.setattr(module, "build_python_payload", payload)
    monkeypatch.setattr(module, "build_precompiled_plugin", lambda *args: pytest.fail("non-native must not run UAT"))
    monkeypatch.setattr(
        module, "build_native_wheel", lambda *args: pytest.fail("non-native must not build native wheel")
    )
    monkeypatch.setattr(module, "verify", lambda *args: None)
    monkeypatch.setattr(sys, "argv", ["build_distributable.py", "--mode", mode, "--ue-root", str(engine)])
    module.main()
    assert calls == [mode]
    assert not (repo / "dist" / "package" / "native-wheels").exists()


def test_source_change_during_wheel_build_rejected(native_fixture, monkeypatch):
    module, repo, plugin, engine = native_fixture
    locked = module.native_source_lock()
    payload = repo / "dist" / "bootstrap"
    shutil.copytree(plugin, payload)
    adapter = payload / "python" / "dcc_mcp_unreal"
    shutil.copytree(repo / "src" / "dcc_mcp_unreal", adapter)
    shutil.copytree(plugin, adapter / "_plugin")
    work = repo / "dist" / "work"
    work.mkdir()

    def build(command):
        output = repo / "dist" / "out" / "native-wheels" / "dcc_mcp_unreal-0.99.0-py3-none-win_amd64.whl"
        output.write_bytes(b"not consumed: source guard rejects first")
        (repo / "src" / "dcc_mcp_unreal" / "__init__.py").write_text("# changed during pip\n", encoding="utf-8")

    monkeypatch.setattr(module, "run", build)
    with pytest.raises(RuntimeError, match="build source changed"):
        module.build_native_wheel(
            SimpleNamespace(work_dir=work, out_dir=repo / "dist" / "out", ue_root=engine, python=None), payload, locked
        )


@pytest.mark.parametrize("name", ["python", "Binaries", "Intermediate"])
def test_native_canonical_source_rejects_previously_packaged_input(native_fixture, name):
    module, _, plugin, _ = native_fixture
    (plugin / name).mkdir()
    with pytest.raises(RuntimeError, match="canonical source"):
        module.native_source_lock()


def test_adapter_wheel_is_pip_input_and_default_still_uses_source(tmp_path, monkeypatch):
    module = load_script("build_plugin")
    calls = []
    monkeypatch.setattr(module, "run", lambda command: calls.append(command))
    wheel = tmp_path / "dcc_mcp_unreal-new.whl"
    wheel.write_bytes(b"not installed: command contract only")
    options = dict(core_spec="unused", core_wheel=None, core_root=tmp_path, use_local_core=False, skip_core=True)
    module.install_python_payload(Path(sys.executable), tmp_path / "with-wheel", adapter_wheel=wheel, **options)
    module.install_python_payload(Path(sys.executable), tmp_path / "with-source", **options)
    assert calls[0][-1] == str(wheel)
    assert calls[1][-1] == str(module.REPO_ROOT)
    assert "--no-deps" in calls[0]


@pytest.mark.parametrize("limit", [None, 2])
@pytest.mark.parametrize("previous", [None, '-NoUBA -MaxParallelActions=1 -Log="path with spaces"'])
@pytest.mark.parametrize("fails", [False, True])
def test_optional_parallel_actions_reach_ubt_and_restore_environment(
    native_fixture, monkeypatch, limit, previous, fails
):
    module, repo, _, engine = native_fixture
    calls = []
    if previous is None:
        monkeypatch.delenv("UBT_EXTRA_ARGS", raising=False)
    else:
        monkeypatch.setenv("UBT_EXTRA_ARGS", previous)

    def uat(command, **kwargs):
        calls.append((command, kwargs.get("env", os.environ).get("UBT_EXTRA_ARGS")))
        if fails:
            raise subprocess.CalledProcessError(7, command)

    monkeypatch.setattr(module.subprocess, "run", uat)
    monkeypatch.setattr(module, "_check_msvc_toolchain", lambda *args: None)
    args = SimpleNamespace(
        ue_root=engine, vctoolchain_version="14.36", patched_headers_dir="", max_parallel_actions=limit
    )
    if fails:
        with pytest.raises(subprocess.CalledProcessError) as caught:
            module.build_precompiled_plugin(args, repo / "dist" / "uat")
        assert caught.value.returncode == 7
    else:
        module.build_precompiled_plugin(args, repo / "dist" / "uat")
    command, inherited = calls[0]
    expected = previous if limit is None else "-MaxParallelActions=2" + (" " + previous if previous else "")
    assert inherited == expected
    assert os.environ.get("UBT_EXTRA_ARGS") == previous
    assert "-VCToolchainVersion=14.36" in command[-1]
    assert any("-MaxParallelActions=2" in part for part in command) == (limit is not None)


@pytest.mark.parametrize("value", ["0", "-1", "abc"])
def test_parallel_limit_rejects_invalid_values(value, monkeypatch):
    module = load_script("build_distributable")
    with pytest.raises((ValueError, SystemExit)):
        # argparse.ArgumentTypeError derives from Exception, not ValueError;
        # exercise the actual command-line parser for the complete contract.
        monkeypatch.setattr(sys, "argv", ["build_distributable.py", "--max-parallel-actions", value])
        module.main()
