from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from jsonschema import Draft202012Validator
from test_official_mcp import _load_prepare_module


@pytest.fixture
def setup_project(tmp_path, monkeypatch):
    prepare = _load_prepare_module()
    engine = tmp_path / "Engine"
    plugins = engine / "Plugins"
    project = tmp_path / "Project" / "Example.uproject"
    project.parent.mkdir()
    project.write_bytes(b'\xef\xbb\xbf{\r\n "FileVersion": 3, "Description": "Keep me", "Plugins": []\r\n}\r\n')
    config = project.parent / "Config" / "DefaultEditorPerProjectUserSettings.ini"
    monkeypatch.setattr(
        prepare, "_process_arguments", lambda: [str(engine / "Binaries" / "UnrealEditor"), str(project)]
    )
    for relative in prepare._PLUGIN_RELATIVE_PATHS.values():
        path = plugins / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = {"FileVersion": 3}
        if path.stem == "PCGToolset":
            descriptor["Plugins"] = [{"Name": "PCG", "Enabled": True}]
        path.write_text(json.dumps(descriptor), encoding="utf-8")
    pcg = plugins / "PCG" / "PCG.uplugin"
    pcg.parent.mkdir()
    pcg.write_text('{"FileVersion": 3, "EnabledByDefault": false}', encoding="utf-8")
    return prepare, project, config, plugins


def _assert_no_writes(prepare, monkeypatch):
    def unexpected_write(*args):
        pytest.fail("Preflight failure must not attempt a write")

    monkeypatch.setattr(prepare, "_atomic_write_bytes", unexpected_write)


@pytest.mark.parametrize("port", [1, 8000, 18081, 65535])
def test_server_port_is_read_back_without_claiming_runtime_verification(setup_project, port):
    prepare, project, config, plugins = setup_project
    result = prepare.prepare_official_mcp(server_port=port)
    assert result["success"] is True, result
    context = result["context"]
    assert context["configured_port"] == port
    assert context["configured_endpoint"] == f"http://127.0.0.1:{port}/mcp"
    assert context["configuration_verified"] is True
    assert context["runtime_verified"] is False
    assert f"ServerPortNumber={port}\n".encode() in config.read_bytes()
    assert context["configured_endpoint"] in result["prompt"]


@pytest.mark.parametrize("port", [True, False, "18081", 18081.0, None, 0, -1, 65536, [], {}])
def test_invalid_server_ports_block_before_any_writes(setup_project, monkeypatch, port):
    prepare, project, config, plugins = setup_project
    original = project.read_bytes()
    _assert_no_writes(prepare, monkeypatch)
    result = prepare.prepare_official_mcp(server_port=port)
    assert result["success"] is False
    assert result["error"] == "invalid_server_port"
    assert project.read_bytes() == original
    assert not config.parent.exists()


def test_server_port_schema_matches_runtime_contract():
    prepare = _load_prepare_module()
    tools = yaml.safe_load((Path(prepare.__file__).parents[1] / "tools.yaml").read_text(encoding="utf-8"))["tools"]
    schema = next(tool["input_schema"] for tool in tools if tool["name"] == "prepare_official_mcp")
    validator = Draft202012Validator(schema)
    assert schema["properties"]["server_port"]["default"] == 8000
    for port in (1, 8000, 18081, 65535):
        assert validator.is_valid({"server_port": port})
    for port in (True, False, "18081", None, 0, -1, 65536):
        assert not validator.is_valid({"server_port": port})


def test_port_only_change_requires_restart_and_has_no_global_state_leak(setup_project, monkeypatch):
    prepare, project, config, plugins = setup_project
    assert prepare.prepare_official_mcp()["success"] is True
    original = project.read_bytes()
    for port in (18081, 18082, 8000):
        kwargs = {} if port == 8000 else {"server_port": port}
        result = prepare.prepare_official_mcp(**kwargs)
        assert result["success"] is True
        assert result["context"]["configured_port"] == port
        assert result["context"]["changed_plugins"] == []
        assert result["context"]["config_changed"] is True
        assert result["context"]["restart_required"] is True
        assert project.read_bytes() == original
        with monkeypatch.context() as patch:
            _assert_no_writes(prepare, patch)
            repeated = prepare.prepare_official_mcp(**kwargs)
        assert repeated["success"] is True
        assert repeated["context"]["restart_required"] is False
    assert prepare._AUTOSTART_SETTINGS["ServerPortNumber"] == "8000"


@pytest.mark.parametrize(
    "overrides",
    [
        ["-ModelContextProtocolPort=8000"],
        ["-ModelContextProtocolPort=0"],
        ["-ModelContextProtocolPort=65536"],
        ["-ModelContextProtocolPort="],
        ["-ModelContextProtocolPort=18081.0"],
        ["-ModelContextProtocolPort", "18081"],
        ["--ModelContextProtocolPort=18081"],
        ["-ModelContextProtocolPort=18081"] * 2,
    ],
)
def test_conflicting_or_ambiguous_port_override_blocks_without_writes(setup_project, monkeypatch, overrides):
    prepare, project, config, plugins = setup_project
    arguments = prepare._process_arguments() + overrides
    monkeypatch.setattr(prepare, "_process_arguments", lambda: arguments)
    original = project.read_bytes()
    _assert_no_writes(prepare, monkeypatch)
    result = prepare.prepare_official_mcp(server_port=18081)
    assert result["success"] is False
    assert "ModelContextProtocolPort" in result["error"]
    assert project.read_bytes() == original
    assert not config.parent.exists()


def test_matching_port_override_does_not_claim_runtime_verification(setup_project, monkeypatch):
    prepare, project, config, plugins = setup_project
    arguments = prepare._process_arguments() + ["-modelcontextprotocolport=18081"]
    monkeypatch.setattr(prepare, "_process_arguments", lambda: arguments)
    result = prepare.prepare_official_mcp(server_port=18081)
    assert result["success"] is True
    assert result["context"]["configured_port"] == 18081
    assert result["context"]["runtime_verified"] is False


@pytest.mark.parametrize(
    "arguments",
    [
        ["Editor", "/Projects/ModelContextProtocolPortProbe/Example.uproject"],
        ["Editor", "/Projects/Example.uproject", "-log=/Logs/ModelContextProtocolPortProbe.log"],
    ],
)
def test_port_keyword_in_project_or_log_path_is_not_an_override(arguments):
    prepare = _load_prepare_module()
    prepare._validate_port_override(arguments, 18081)


@pytest.mark.parametrize(
    "argument",
    [
        "-log=/Logs/ModelContextProtocolPort=18081.log",
        "-args=-ModelContextProtocolPort=18081",
        "-notes=ModelContextProtocolPort =18081",
    ],
)
def test_nested_port_assignment_remains_ambiguous(argument):
    prepare = _load_prepare_module()
    with pytest.raises(ValueError, match="ModelContextProtocolPort"):
        prepare._validate_port_override(["Editor", "/Projects/Example.uproject", argument], 18081)


def test_unknown_native_command_line_blocks_before_any_writes(setup_project, monkeypatch):
    prepare, project, config, plugins = setup_project

    def unavailable():
        raise OSError("Native command line unavailable")

    monkeypatch.setattr(prepare, "_process_arguments", unavailable)
    _assert_no_writes(prepare, monkeypatch)
    result = prepare.prepare_official_mcp(server_port=18081)
    assert result["success"] is False
    assert result["error"] == "Native command line unavailable"
    guidance = " ".join(result["context"]["possible_solutions"])
    assert ".uproject" in guidance
    assert "server_port" in guidance and "-ModelContextProtocolPort" in guidance
    assert "unreadable" in guidance and "platform" in guidance
    assert not config.parent.exists()


@pytest.mark.parametrize("command_line", [None, "Editor Project.uproject"])
def test_windows_command_line_failure_never_falls_back_to_python_argv(monkeypatch, command_line):
    prepare = _load_prepare_module()
    monkeypatch.setattr(prepare, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        prepare.ctypes,
        "windll",
        SimpleNamespace(
            shell32=SimpleNamespace(CommandLineToArgvW=lambda *args: None),
            kernel32=SimpleNamespace(GetCommandLineW=lambda: command_line, LocalFree=lambda *args: None),
        ),
        raising=False,
    )
    with pytest.raises(OSError, match="native Editor command line"):
        prepare._process_arguments()


@pytest.mark.parametrize(
    "contents", [b"Editor\0Project.uproject\0-ModelContextProtocolPort=18081\0", b"", b"truncated"]
)
def test_linux_command_line_requires_complete_native_arguments(monkeypatch, contents):
    prepare = _load_prepare_module()
    monkeypatch.setattr(prepare, "os", SimpleNamespace(name="posix", fsdecode=lambda value: value.decode()))
    monkeypatch.setattr(prepare.sys, "platform", "linux")

    def read(path):
        assert path.as_posix() == "/proc/self/cmdline"
        return contents

    monkeypatch.setattr(Path, "read_bytes", read)
    if contents.endswith(b"\0"):
        assert prepare._process_arguments() == ["Editor", "Project.uproject", "-ModelContextProtocolPort=18081"]
    else:
        with pytest.raises(OSError, match="cannot be verified"):
            prepare._process_arguments()


def test_unsupported_native_command_line_reader_fails_closed(monkeypatch):
    prepare = _load_prepare_module()
    monkeypatch.setattr(prepare, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(prepare.sys, "platform", "darwin")
    with pytest.raises(OSError, match="cannot be verified"):
        prepare._process_arguments()


@pytest.mark.parametrize("failure", ["unreadable", "external_edit", "external_delete", "no_write"])
@pytest.mark.parametrize("existing_config", [False, True])
def test_configuration_readback_failure_preserves_external_changes(
    setup_project, monkeypatch, failure, existing_config
):
    prepare, project, config, plugins = setup_project
    original = project.read_bytes()
    config_original = b"; Original config\r\n"
    if existing_config:
        config.parent.mkdir()
        config.write_bytes(config_original)
    actual_write, actual_read = prepare._atomic_write_bytes, prepare._read_optional_bytes
    wrote_config = False
    failed_read = False

    def write(path, contents):
        nonlocal wrote_config
        if path != config or failure != "no_write":
            actual_write(path, contents)
        if path == config:
            wrote_config = True
            if failure == "external_edit":
                path.write_bytes(b"; External editor change\n")
            elif failure == "external_delete":
                path.unlink()

    def read(path):
        nonlocal failed_read
        if path == config and wrote_config and failure == "unreadable" and not failed_read:
            failed_read = True
            raise OSError("Injected readback failure")
        return actual_read(path)

    monkeypatch.setattr(prepare, "_atomic_write_bytes", write)
    monkeypatch.setattr(prepare, "_read_optional_bytes", read)
    result = prepare.prepare_official_mcp(server_port=18081)
    assert result["success"] is False
    assert project.read_bytes() == original
    if failure == "external_edit":
        assert config.read_bytes() == b"; External editor change\n"
        assert result["context"]["rollback_complete"] is False
    elif failure == "external_delete":
        assert not config.exists()
        assert result["context"]["rollback_complete"] is (not existing_config)
    else:
        assert config.read_bytes() == config_original if existing_config else not config.exists()
        assert result["context"]["rollback_complete"] is True


@pytest.mark.parametrize("timing", ["before", "during"])
def test_external_change_before_or_during_transaction_is_not_overwritten(setup_project, monkeypatch, timing):
    prepare, project, config, plugins = setup_project
    original = project.read_bytes()
    write_configuration = prepare._write_configuration
    actual_write = prepare._atomic_write_bytes
    external = b"; External change before transaction\n"
    writes = []

    def external_write():
        config.parent.mkdir()
        config.write_bytes(external)

    def concurrent_write(configuration):
        if timing == "before":
            external_write()
        return write_configuration(configuration)

    def write(path, contents):
        writes.append(path)
        actual_write(path, contents)
        if timing == "during" and len(writes) == 1:
            external_write()

    monkeypatch.setattr(prepare, "_write_configuration", concurrent_write)
    monkeypatch.setattr(prepare, "_atomic_write_bytes", write)
    result = prepare.prepare_official_mcp(server_port=18081)
    assert result["success"] is False
    assert "changed before write" in result["context"]["details"]
    assert project.read_bytes() == original
    assert config.read_bytes() == external
    assert writes == ([] if timing == "before" else [project, project])


def test_unchanged_configuration_is_also_read_back(setup_project, monkeypatch):
    prepare, project, config, plugins = setup_project
    assert prepare.prepare_official_mcp(server_port=18081)["success"] is True
    actual_read = prepare._read_optional_bytes
    config_reads = 0

    def read(path):
        nonlocal config_reads
        if path == config:
            config_reads += 1
            if config_reads == 3:
                raise OSError("Injected unchanged-file readback failure")
        return actual_read(path)

    monkeypatch.setattr(prepare, "_read_optional_bytes", read)
    _assert_no_writes(prepare, monkeypatch)
    result = prepare.prepare_official_mcp(server_port=18081)
    assert result["success"] is False
    assert "unchanged-file readback" in result["context"]["details"]


def test_batch_preflight_read_error_performs_no_writes(tmp_path, monkeypatch):
    prepare = _load_prepare_module()
    project, config = tmp_path / "project", tmp_path / "config"
    writes = []

    def read(path):
        if path == config:
            raise OSError("Unreadable configuration")
        return b"original"

    monkeypatch.setattr(prepare, "_read_optional_bytes", read)
    monkeypatch.setattr(prepare, "_atomic_write_bytes", lambda *args: writes.append(args))
    with pytest.raises(prepare._ConfigurationWriteError, match="Unreadable configuration"):
        prepare._write_configuration([(project, b"original", b"changed"), (config, b"original", b"changed")])
    assert writes == []


@pytest.fixture
def setup_ue_5_8_1_project(setup_project):
    prepare, project, config, plugins = setup_project
    # Dependency declarations observed on UE 5.8.1, CL 56057345 (PC8).
    descriptor = plugins / "Experimental/Toolsets/PCGToolset/PCGToolset.uplugin"
    descriptor.write_text(
        json.dumps(
            {
                "FileVersion": 3,
                "Plugins": [{"Name": "PCG", "Enabled": True}, {"Name": "ToolsetRegistry", "Enabled": True}],
            }
        ),
        encoding="utf-8",
    )
    registry = plugins / "Experimental/ToolsetRegistry/ToolsetRegistry.uplugin"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text('{"FileVersion": 3}', encoding="utf-8")
    return prepare, project, config, plugins


def test_ue_5_8_1_dependencies_are_verified_without_enabling_them_directly(setup_ue_5_8_1_project, monkeypatch):
    prepare, project, config, plugins = setup_ue_5_8_1_project
    result = prepare.prepare_official_mcp(include_pcg_toolset=True)
    assert result["success"] is True, result
    assert result["context"]["required_dependencies"] == ["PCG", "ToolsetRegistry"]
    assert result["context"]["runtime_verified"] is False
    assert result["context"]["restart_required"] is True
    assert [entry["Name"] for entry in json.loads(project.read_bytes())["Plugins"]] == [
        "ModelContextProtocol",
        "EditorToolset",
        "PCGToolset",
    ]
    original_project, original_config = project.read_bytes(), config.read_bytes()
    _assert_no_writes(prepare, monkeypatch)
    repeated = prepare.prepare_official_mcp(include_pcg_toolset=True)
    assert repeated["success"] is True
    assert repeated["context"]["required_dependencies"] == ["PCG", "ToolsetRegistry"]
    assert repeated["context"]["restart_required"] is False
    assert project.read_bytes() == original_project
    assert config.read_bytes() == original_config


@pytest.mark.parametrize("contents", [None, b"broken json", b"[]", b"{}", b'{"FileVersion":true}'])
def test_ue_5_8_1_registry_missing_or_malformed_blocks_without_writes(setup_ue_5_8_1_project, contents, monkeypatch):
    prepare, project, config, plugins = setup_ue_5_8_1_project
    registry = plugins / "Experimental/ToolsetRegistry/ToolsetRegistry.uplugin"
    if contents is None:
        registry.unlink()
    else:
        registry.write_bytes(contents)
    original = project.read_bytes()
    _assert_no_writes(prepare, monkeypatch)
    result = prepare.prepare_official_mcp(include_pcg_toolset=True)
    assert result["success"] is False
    assert project.read_bytes() == original
    assert not config.parent.exists()


def test_explicitly_disabled_registry_is_not_silently_reenabled(setup_ue_5_8_1_project, monkeypatch):
    prepare, project, config, plugins = setup_ue_5_8_1_project
    project.write_text('{"Plugins":[{"Name":"ToolsetRegistry","Enabled":false}]}', encoding="utf-8")
    original = project.read_bytes()
    _assert_no_writes(prepare, monkeypatch)
    result = prepare.prepare_official_mcp(include_pcg_toolset=True)
    assert result["success"] is False
    assert "ToolsetRegistry is explicitly disabled" in result["error"]
    assert project.read_bytes() == original
    assert not config.parent.exists()


def test_undeclared_registry_is_not_required_for_older_descriptors(setup_project):
    prepare, project, config, plugins = setup_project
    registry = plugins / "Experimental/ToolsetRegistry/ToolsetRegistry.uplugin"
    if registry.exists():
        registry.unlink()
    result = prepare.prepare_official_mcp(include_pcg_toolset=True)
    assert result["success"] is True
    assert result["context"]["required_dependencies"] == ["PCG"]


@pytest.mark.parametrize("blocker", ["ambiguous_pcg", "unknown_dependency"])
def test_ue_5_8_1_dependencies_still_fail_closed(setup_ue_5_8_1_project, blocker, monkeypatch):
    prepare, project, config, plugins = setup_ue_5_8_1_project
    if blocker == "ambiguous_pcg":
        unsupported = plugins / "Experimental/PCG/PCG.uplugin"
        expected_dependency = "PCG"
    else:
        unsupported = plugins / "UnknownDependency/UnknownDependency.uplugin"
        expected_dependency = "UnknownDependency"
        descriptor = plugins / "Experimental/Toolsets/PCGToolset/PCGToolset.uplugin"
        data = json.loads(descriptor.read_bytes())
        data["Plugins"].append({"Name": expected_dependency, "Enabled": True})
        descriptor.write_text(json.dumps(data), encoding="utf-8")
    unsupported.parent.mkdir(parents=True, exist_ok=True)
    unsupported.write_text('{"FileVersion": 3}', encoding="utf-8")
    original = project.read_bytes()
    _assert_no_writes(prepare, monkeypatch)
    result = prepare.prepare_official_mcp(include_pcg_toolset=True)
    assert result["success"] is False
    assert result["error"] == (
        f"Cannot verify one installed descriptor for required PCGToolset dependency {expected_dependency}"
    )
    assert project.read_bytes() == original
    assert not config.parent.exists()


@pytest.mark.parametrize("flag", ["include_editor_toolset", "include_niagara_toolsets", "include_pcg_toolset"])
@pytest.mark.parametrize("value", ["false", "true", 0, 1, None, [], {}])
def test_non_boolean_flags_block_before_any_writes(setup_project, monkeypatch, flag, value):
    prepare, project, config, plugins = setup_project
    original = project.read_bytes()
    _assert_no_writes(prepare, monkeypatch)
    result = prepare.prepare_official_mcp(**{flag: value})
    assert result["success"] is False
    assert result["error"] == "invalid_include_flags"
    assert result["context"]["invalid_flags"] == [flag]
    assert project.read_bytes() == original
    assert not config.parent.exists()


@pytest.mark.parametrize("missing_pcg", [False, True])
def test_pcg_is_opt_in_and_not_validated_by_default(setup_project, missing_pcg):
    prepare, project, config, plugins = setup_project
    pcg_toolset = plugins / prepare._PLUGIN_RELATIVE_PATHS["PCGToolset"]
    if missing_pcg:
        pcg_toolset.unlink()
        (plugins / "PCG" / "PCG.uplugin").unlink()
    else:
        pcg_toolset.write_text("invalid", encoding="utf-8")
    result = prepare.prepare_official_mcp()
    assert result["success"] is True
    assert result["context"]["enabled_plugins"] == ["ModelContextProtocol", "EditorToolset"]
    assert result["context"]["required_dependencies"] == []
    assert result["context"]["runtime_verified"] is False
    assert "PCGToolset" not in project.read_text(encoding="utf-8")
    assert config.is_file()


@pytest.mark.parametrize("legacy_pcg", [False, True])
def test_pcg_opt_in_validates_installed_dependency_and_is_idempotent(setup_project, legacy_pcg, monkeypatch):
    prepare, project, config, plugins = setup_project
    if legacy_pcg:
        legacy = plugins / "Experimental" / "PCG" / "PCG.uplugin"
        legacy.parent.mkdir()
        (plugins / "PCG" / "PCG.uplugin").rename(legacy)
    result = prepare.prepare_official_mcp(include_pcg_toolset=True)
    assert result["success"] is True
    assert result["context"]["enabled_plugins"] == ["ModelContextProtocol", "EditorToolset", "PCGToolset"]
    assert result["context"]["required_dependencies"] == ["PCG"]
    assert result["context"]["restart_required"] is True
    assert result["context"]["runtime_verified"] is False
    data = json.loads(project.read_bytes())
    assert data["Description"] == "Keep me"
    assert "PCG" not in [entry["Name"] for entry in data["Plugins"]]
    original_project, original_config = project.read_bytes(), config.read_bytes()
    _assert_no_writes(prepare, monkeypatch)
    repeated = prepare.prepare_official_mcp(include_pcg_toolset=True)
    assert repeated["success"] is True
    assert repeated["context"]["changed_plugins"] == []
    assert repeated["context"]["config_changed"] is False
    assert repeated["context"]["restart_required"] is False
    assert project.read_bytes() == original_project
    assert config.read_bytes() == original_config


@pytest.mark.parametrize("missing", ["ModelContextProtocol", "EditorToolset", "PCGToolset", "PCG"])
def test_missing_descriptor_blocks_before_any_writes(setup_project, missing, monkeypatch):
    prepare, project, config, plugins = setup_project
    relative = Path("PCG/PCG.uplugin") if missing == "PCG" else prepare._PLUGIN_RELATIVE_PATHS[missing]
    (plugins / relative).unlink()
    original = project.read_bytes()
    _assert_no_writes(prepare, monkeypatch)
    result = prepare.prepare_official_mcp(include_pcg_toolset=True)
    assert result["success"] is False
    assert missing in result["error"]
    assert project.read_bytes() == original
    assert not config.parent.exists()


@pytest.mark.parametrize("target", ["PCGToolset", "PCG"])
@pytest.mark.parametrize("contents", [b"broken json", b"[]", b"{}"])
def test_malformed_pcg_descriptors_block_without_writes(setup_project, target, contents, monkeypatch):
    prepare, project, config, plugins = setup_project
    relative = Path("PCG/PCG.uplugin") if target == "PCG" else prepare._PLUGIN_RELATIVE_PATHS[target]
    (plugins / relative).write_bytes(contents)
    original = project.read_bytes()
    _assert_no_writes(prepare, monkeypatch)
    assert prepare.prepare_official_mcp(include_pcg_toolset=True)["success"] is False
    assert project.read_bytes() == original
    assert not config.exists()


@pytest.mark.parametrize(
    "references",
    [
        [],
        [{"Name": "PCG", "Enabled": False}],
        [{"Name": "PCG", "Enabled": True, "Optional": True}],
        [{"Name": "PCG"}],
        [{"Name": "PCG", "Enabled": "true"}],
        [{"Name": "PCG", "Enabled": True}, {"Name": "UnknownDependency", "Enabled": True}],
        {},
    ],
)
def test_invalid_or_unverifiable_direct_dependencies_block(setup_project, references, monkeypatch):
    prepare, project, config, plugins = setup_project
    descriptor = plugins / prepare._PLUGIN_RELATIVE_PATHS["PCGToolset"]
    descriptor.write_text(json.dumps({"FileVersion": 3, "Plugins": references}), encoding="utf-8")
    _assert_no_writes(prepare, monkeypatch)
    assert prepare.prepare_official_mcp(include_pcg_toolset=True)["success"] is False
    assert not config.exists()


@pytest.mark.parametrize(
    "dependency",
    [
        {"Name": "UnknownRequiredPlugin", "Enabled": True, "Optional": "false"},
        {"Name": "UnknownRequiredPlugin", "Enabled": True, "Optional": None},
        {"Name": "UnknownRequiredPlugin", "Enabled": True, "Optional": 0},
        {"Name": "UnknownRequiredPlugin", "Enabled": True, "Optional": 1},
        {"Name": "", "Enabled": True, "Optional": True},
        {"Name": "  ", "Enabled": True, "Optional": True},
    ],
)
def test_malformed_optional_dependencies_block_before_any_writes(setup_project, dependency, monkeypatch):
    prepare, project, config, plugins = setup_project
    descriptor = plugins / prepare._PLUGIN_RELATIVE_PATHS["PCGToolset"]
    references = [{"Name": "PCG", "Enabled": True}, dependency]
    descriptor.write_text(json.dumps({"FileVersion": 3, "Plugins": references}), encoding="utf-8")
    original = project.read_bytes()
    _assert_no_writes(prepare, monkeypatch)
    result = prepare.prepare_official_mcp(include_pcg_toolset=True)
    assert result["success"] is False
    assert "invalid plugin dependency declarations" in result["error"]
    assert project.read_bytes() == original
    assert not config.parent.exists()


def test_explicitly_disabled_pcg_is_not_silently_reenabled(setup_project, monkeypatch):
    prepare, project, config, plugins = setup_project
    project.write_text('{"Plugins":[{"Name":"PCG","Enabled":false}]}', encoding="utf-8")
    original = project.read_bytes()
    _assert_no_writes(prepare, monkeypatch)
    result = prepare.prepare_official_mcp(include_pcg_toolset=True)
    assert result["success"] is False
    assert "PCG is explicitly disabled" in result["error"]
    assert project.read_bytes() == original
    assert not config.exists()


def test_ambiguous_installed_pcg_descriptors_block(setup_project, monkeypatch):
    prepare, project, config, plugins = setup_project
    duplicate = plugins / "Experimental" / "PCG" / "PCG.uplugin"
    duplicate.parent.mkdir()
    duplicate.write_text('{"FileVersion":3}', encoding="utf-8")
    _assert_no_writes(prepare, monkeypatch)
    assert prepare.prepare_official_mcp(include_pcg_toolset=True)["success"] is False
    assert not config.exists()


@pytest.mark.parametrize("project_contents", [b"{ broken", b"[]", b'{"Plugins": {}}', b"\xff"])
def test_invalid_project_blocks_without_writes(setup_project, project_contents, monkeypatch):
    prepare, project, config, plugins = setup_project
    project.write_bytes(project_contents)
    _assert_no_writes(prepare, monkeypatch)
    assert prepare.prepare_official_mcp(include_pcg_toolset=True)["success"] is False
    assert project.read_bytes() == project_contents
    assert not config.parent.exists()


@pytest.mark.parametrize(
    ("config_contents", "error_type", "line_numbers"),
    [
        (b"FAKE_OPTION_TEST_ONLY=FAKE_SECRET_TEST_ONLY\n", "MissingSectionHeaderError", [1]),
        (b"[FAKE_SECTION_TEST_ONLY]\nFAKE_SECRET_TEST_ONLY\nOTHER_FAKE_SECRET_TEST_ONLY\n", "ParsingError", [2, 3]),
    ],
)
def test_ini_parse_error_does_not_echo_unrelated_configuration(
    setup_project, monkeypatch, config_contents, error_type, line_numbers
):
    prepare, project, config, plugins = setup_project
    config.parent.mkdir()
    config.write_bytes(config_contents)
    original = project.read_bytes()
    _assert_no_writes(prepare, monkeypatch)
    result = prepare.prepare_official_mcp()
    assert result["success"] is False
    assert "FAKE_" not in json.dumps(result)
    assert result["error"] == "invalid_editor_ini"
    assert result["context"]["error_type"] == error_type
    assert result["context"]["line_numbers"] == line_numbers
    assert project.read_bytes() == original
    assert config.read_bytes() == config_contents


@pytest.mark.parametrize("config_contents", [b"key=value\n", b"[Unclosed\n", b"[Valid]\nbroken\n", b"\xff"])
def test_malformed_ini_prevents_project_write(setup_project, config_contents, monkeypatch):
    prepare, project, config, plugins = setup_project
    config.parent.mkdir()
    config.write_bytes(config_contents)
    project_original = project.read_bytes()
    _assert_no_writes(prepare, monkeypatch)
    assert prepare.prepare_official_mcp(include_pcg_toolset=True)["success"] is False
    assert project.read_bytes() == project_original
    assert config.read_bytes() == config_contents


@pytest.mark.parametrize("port", [8000, 18081])
def test_unrelated_ini_bytes_comments_duplicates_and_arrays_are_preserved(setup_project, port):
    prepare, project, config, plugins = setup_project
    config.parent.mkdir()
    original = (
        b"\xef\xbb\xbf; Keep this comment and CRLF\r\n[Other]\r\n"
        b"Repeated=one\r\nRepeated=two\r\n+Array=one\r\n+Array=two\r\n"
        b"-Array=gone\r\n!Array=ClearArray\r\n.Array=duplicate\r\n"
        b"[/Script/ModelContextProtocolEngine.ModelContextProtocolSettings]\r\n"
        b"; Keep MCP comment\r\nServerPortNumber=42\r\nUnrelated=keep\r\n"
        b"[Other]\r\nPreserveNoFinalNewline=yes"
    )
    config.write_bytes(original)
    assert prepare.prepare_official_mcp(include_pcg_toolset=True, server_port=port)["success"] is True
    updated = config.read_bytes()
    assert updated.startswith(original)
    suffix = updated[len(original) :]
    assert f"ServerPortNumber={port}\r\n".encode() in suffix
    assert suffix.count(b"\n") == suffix.count(b"\r\n")
    assert prepare._configure_autostart(config, server_port=port) is False
    assert config.read_bytes() == updated


def test_ini_section_case_and_default_section_follow_unreal_semantics(setup_project):
    prepare, project, config, plugins = setup_project
    desired = "\n".join(f"{key}={value}" for key, value in prepare._AUTOSTART_SETTINGS.items())
    inherited = f"[DEFAULT]\n{desired}\n[{prepare._MCP_SECTION}]\n".encode()
    assert prepare._render_autostart(inherited) != inherited
    overrides = f"[{prepare._MCP_SECTION}]\n{desired}\n[{prepare._MCP_SECTION.lower()}]\nServerPortNumber=42\n".encode()
    corrected = prepare._render_autostart(overrides)
    assert corrected != overrides
    assert prepare._render_autostart(corrected) == corrected


@pytest.mark.parametrize("command", ["+", "-", ".", "!"])
def test_later_target_ini_commands_cannot_report_false_ready(setup_project, command):
    prepare, project, config, plugins = setup_project
    configured = prepare._render_autostart(None)
    original = configured + f"{command}ServerPortNumber=8000\n".encode()
    corrected = prepare._render_autostart(original)
    assert corrected.startswith(original)
    assert corrected != original
    assert prepare._render_autostart(corrected) == corrected


@pytest.mark.parametrize("existing_config", [False, True])
@pytest.mark.parametrize("fail_after_replace", [False, True])
def test_second_write_failure_restores_exact_originals_or_absence(
    setup_project, monkeypatch, existing_config, fail_after_replace
):
    prepare, project, config, plugins = setup_project
    config_original = b"\xef\xbb\xbf; unchanged\r\n[Other]\r\nRepeated=1\r\nRepeated=2\r\n"
    if existing_config:
        config.parent.mkdir()
        config.write_bytes(config_original)
    project_original = project.read_bytes()
    actual_write = prepare._atomic_write_bytes
    attempts = []

    def fail_second_write(path, contents):
        attempts.append(path)
        if len(attempts) == 2:
            if fail_after_replace:
                actual_write(path, contents)
            raise OSError("Injected second-write failure")
        actual_write(path, contents)

    monkeypatch.setattr(prepare, "_atomic_write_bytes", fail_second_write)
    result = prepare.prepare_official_mcp(include_pcg_toolset=True)
    assert result["success"] is False
    assert result["error"] == "configuration_write_failed"
    assert result["context"]["rollback_complete"] is True
    assert result["context"]["rollback_errors"] == []
    assert project.read_bytes() == project_original
    assert config.read_bytes() == config_original if existing_config else not config.exists()


def test_partial_rollback_is_reported_with_affected_path(setup_project, monkeypatch):
    prepare, project, config, plugins = setup_project
    actual_write = prepare._atomic_write_bytes
    attempts = []

    def fail_second_write_and_rollback(path, contents):
        attempts.append(path)
        if len(attempts) > 1:
            raise OSError("Injected write failure")
        actual_write(path, contents)

    monkeypatch.setattr(prepare, "_atomic_write_bytes", fail_second_write_and_rollback)
    result = prepare.prepare_official_mcp(include_pcg_toolset=True)
    assert result["success"] is False
    assert result["error"] == "configuration_rollback_failed"
    assert "rollback is incomplete" in result["message"]
    assert result["context"]["rollback_complete"] is False
    assert result["context"]["rollback_errors"] == [{"path": str(project), "error": "Injected write failure"}]
    assert not config.exists()


def test_atomic_replace_failure_keeps_original_and_removes_temporary_file(tmp_path, monkeypatch):
    prepare = _load_prepare_module()
    target = tmp_path / "test.ini"
    target.write_bytes(b"exact original")

    def fail_replace(source, destination):
        raise OSError("Injected atomic replace failure")

    monkeypatch.setattr(prepare.os, "replace", fail_replace)
    with pytest.raises(OSError, match="atomic replace"):
        prepare._atomic_write_bytes(target, b"replacement")
    assert target.read_bytes() == b"exact original"
    assert list(tmp_path.iterdir()) == [target]
