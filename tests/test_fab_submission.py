from __future__ import annotations

import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "packaging/build_fab_submission.py"
SPEC = importlib.util.spec_from_file_location("fab_submission", SCRIPT)
assert SPEC and SPEC.loader
fab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fab)


@pytest.fixture
def source(tmp_path):
    plugin = tmp_path / "unreal/plugin"
    files = {
        "Config/FilterPlugin.ini": "[FilterPlugin]\n",
        "Content/Python/init_unreal.py": "# bootstrap\n",
        "Resources/Icon128.png": "icon",
        "Source/DccMcpUnreal/DccMcpUnreal.Build.cs": "// module\n",
        "Source/DccMcpUnreal/Private/Module.cpp": "// source\n",
        "DccMcpUnreal.uplugin": json.dumps(
            {
                "VersionName": "1.2.3",
                "Modules": [{"Name": "DccMcpUnreal", "Type": "Editor"}],
                "Plugins": [{"Name": "PythonScriptPlugin", "Enabled": True, "Optional": True}],
            }
        ),
    }
    for relative, content in files.items():
        target = plugin / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    adapter = tmp_path / "src/dcc_mcp_unreal"
    adapter.mkdir(parents=True)
    (adapter / "__init__.py").write_text("# adapter\n")
    documentation = tmp_path / "packaging/fab"
    documentation.mkdir(parents=True)
    (documentation / "README.txt").write_text("Instructions\n")
    (documentation / "License.txt").write_text("MIT License\n")
    return tmp_path


def release(tmp_path, extra=None, version="1.2.3"):
    path = tmp_path / "release.zip"
    with zipfile.ZipFile(path, "w") as archive:
        files = {
            "DccMcpUnreal/DccMcpUnreal.uplugin": json.dumps({"VersionName": version}),
            "DccMcpUnreal/python/dcc_mcp_core/__init__.py": "# dependency",
            "DccMcpUnreal/python/dcc_mcp_core/_core.pyd": "native extension",
            "DccMcpUnreal/python/dcc_mcp_core-1.0.dist-info/licenses/LICENSE": "MIT License",
            "DccMcpUnreal/python/dcc_mcp_core-1.0.dist-info/direct_url.json": "private build path",
            "DccMcpUnreal/python/dcc_mcp_unreal/_plugin/DccMcpUnreal.uplugin": "{}",
            "DccMcpUnreal/python/bin/launcher.exe": "launcher",
            "DccMcpUnreal/Binaries/Win64/Editor.dll": "binary",
            "DccMcpUnreal/Intermediate/Build/temp.lib": "intermediate",
            "DccMcpUnreal/BUILD_INFO.txt": "private build path",
        }
        files.update(extra or {})
        for name, content in files.items():
            member = zipfile.ZipInfo()
            member.filename = name
            archive.writestr(member, content)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_submission_keeps_one_source_plugin_with_loadable_python_locations(source, tmp_path):
    payload, digest = release(tmp_path)
    result = fab.build_submission(payload, digest, tmp_path / "out", source)
    with zipfile.ZipFile(result) as archive:
        names = archive.namelist()
        assert len([name for name in names if name.endswith(".uplugin")]) == 1
        assert "DccMcpUnreal/Content/Python/dcc_mcp_unreal/__init__.py" in names
        assert "DccMcpUnreal/Content/Python/Lib/site-packages/dcc_mcp_core/_core.pyd" in names
        assert "DccMcpUnreal/Source/DccMcpUnreal/Private/Module.cpp" in names
        assert not any("/Intermediate/" in name or "/Binaries/" in name or "/_plugin/" in name for name in names)
        assert not any(name.endswith((".exe", "direct_url.json", "BUILD_INFO.txt")) for name in names)
        assert all("/Content/Python/" in name for name in names if name.endswith(".py"))
        descriptor = json.loads(archive.read("DccMcpUnreal/DccMcpUnreal.uplugin"))
        assert descriptor["Plugins"][0]["Optional"] is False
        assert "EngineVersion" not in descriptor
        assert descriptor["SupportedTargetPlatforms"] == ["Win64"]
        assert b"/Content/Python/..." in archive.read("DccMcpUnreal/Config/FilterPlugin.ini")
        manifest = json.loads(archive.read("DccMcpUnreal/Documentation/BuildManifest.json"))
        assert manifest["files"] == len(names)
    assert (
        json.loads(result.with_suffix(".json").read_text())["submission_sha256"]
        == hashlib.sha256(result.read_bytes()).hexdigest()
    )


@pytest.mark.parametrize(
    "member",
    [
        "DccMcpUnreal/../escape.py",
        "/absolute.py",
        "DccMcpUnreal/python/C:/escape.py",
        "DccMcpUnreal\\python\\escape.py",
    ],
)
def test_submission_rejects_unsafe_archive_paths(source, tmp_path, member):
    payload, digest = release(tmp_path, {member: "unsafe"})
    with pytest.raises(ValueError, match="Unsafe release member"):
        fab.build_submission(payload, digest, tmp_path / "out", source)
    assert not list((tmp_path / "out").glob("*-fab-source-win64.zip"))


def test_submission_rejects_a_tampered_release_before_staging(source, tmp_path):
    payload, _ = release(tmp_path)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        fab.build_submission(payload, "0" * 64, tmp_path / "out", source)
    assert not (tmp_path / "out").exists()


def test_submission_rejects_a_payload_from_a_different_release(source, tmp_path):
    payload, digest = release(tmp_path, version="1.2.4")
    with pytest.raises(ValueError, match="versions differ"):
        fab.build_submission(payload, digest, tmp_path / "out", source)


def test_submission_refuses_to_replace_a_reviewed_archive(source, tmp_path):
    payload, digest = release(tmp_path)
    result = fab.build_submission(payload, digest, tmp_path / "out", source)
    original = result.read_bytes()
    with pytest.raises(FileExistsError, match="Refusing to replace"):
        fab.build_submission(payload, digest, tmp_path / "out", source)
    assert result.read_bytes() == original


def test_submission_write_failure_leaves_no_partial_archive_and_can_retry(source, tmp_path, monkeypatch):
    payload, digest = release(tmp_path)
    output = tmp_path / "out"
    write = zipfile.ZipFile.writestr
    writes = []

    def fail_after_first_member(archive, *args, **kwargs):
        if writes:
            raise OSError("injected archive write failure")
        writes.append(True)
        return write(archive, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(zipfile.ZipFile, "writestr", fail_after_first_member)
        with pytest.raises(OSError, match="injected archive write failure"):
            fab.build_submission(payload, digest, output, source)
    assert list(output.iterdir()) == []
    assert fab.build_submission(payload, digest, output, source).is_file()


def test_submission_publication_race_preserves_the_other_complete_archive(source, tmp_path, monkeypatch):
    payload, digest = release(tmp_path)
    output = tmp_path / "out"
    link = fab.os.link
    competing = b"already reviewed submission"

    def publish_race(staged, destination):
        with zipfile.ZipFile(staged) as archive:
            assert archive.testzip() is None
        destination.write_bytes(competing)
        return link(staged, destination)

    monkeypatch.setattr(fab.os, "link", publish_race)
    with pytest.raises(FileExistsError):
        fab.build_submission(payload, digest, output, source)
    remaining = list(output.iterdir())
    assert len(remaining) == 1
    assert remaining[0].read_bytes() == competing
