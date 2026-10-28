"""Bounded contract tests for the unreal-ai Blackboard vertical slice.

These are mock-based contract/failure tests, not native Unreal acceptance. The
core and the tool scripts are loaded by explicit file path so the suite is
independent of whichever ``dcc_mcp_unreal`` checkout happens to be installed in
the environment. A separate, live-Editor commandlet probe
(``ue_ai_blackboard_commandlet.py``) documents the real-host acceptance gate.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import types
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from dcc_mcp_unreal.skill_runner import run_skill_script

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "src" / "dcc_mcp_unreal" / "skills" / "unreal-ai"
SCRIPTS = SKILL_DIR / "scripts"
CORE = SCRIPTS / "_ai_blackboard.py"
TOOLS = SKILL_DIR / "tools.yaml"
SKILL_MD = SKILL_DIR / "SKILL.md"
MATRIX_DOC = ROOT / "docs" / "unreal-ai-capability-matrix.md"
COMMANDLET_PROBE = ROOT / "tests" / "ue_ai_blackboard_commandlet.py"

KEY_TYPE_CLASSES = [
    "BlackboardKeyType_Bool",
    "BlackboardKeyType_Int",
    "BlackboardKeyType_Float",
    "BlackboardKeyType_String",
    "BlackboardKeyType_Name",
    "BlackboardKeyType_Vector",
    "BlackboardKeyType_Rotator",
    "BlackboardKeyType_Object",
    "BlackboardKeyType_Class",
]


# ---------------------------------------------------------------------------
# Loading helpers (explicit path -> no dependency on the installed checkout)
# ---------------------------------------------------------------------------


def _load_core():
    spec = importlib.util.spec_from_file_location("_ai_blackboard_test_core", CORE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Behavioral double for the Unreal Python API
# ---------------------------------------------------------------------------


class FakeName:
    def __init__(self, value=""):
        self.value = value

    def __str__(self):
        return self.value


class FakeKeyType:
    def __init__(self, name="BlackboardKeyType_Float", get_class_name=None):
        self._name = get_class_name or name

    def get_class(self):
        return types.SimpleNamespace(get_name=lambda: self._name)


class FakeEntry:
    def __init__(self, name="", key_type=None):
        self._props = {"entry_name": FakeName(name), "key_type": key_type}

    def get_editor_property(self, name):
        return self._props.get(name)

    def set_editor_property(self, name, value):
        self._props[name] = value


class FakeClass:
    def __init__(self, name="BlackboardData"):
        self._name = name

    def get_name(self):
        return self._name

    def get_path_name(self):
        return "/Script/AIModule." + self._name


class FakeAsset:
    def __init__(self, class_name="BlackboardData", keys=None, drop_writes=False):
        self._class = FakeClass(class_name)
        self._props = {"keys": list(keys or [])}
        self.drop_writes = drop_writes

    def get_class(self):
        return self._class

    def get_editor_property(self, name):
        if name not in self._props:
            raise AttributeError(name)
        return self._props[name]

    def set_editor_property(self, name, value):
        if self.drop_writes and name == "keys":
            return  # simulate a host that silently did not apply the mutation
        self._props[name] = value


class FakeTransaction:
    def __init__(self, label, cancel_raises=False):
        self.label = label
        self.cancelled = False
        self.entered = False
        self.exited = False
        self._cancel_raises = cancel_raises

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *args):
        self.exited = True
        return False

    def cancel(self):
        self.cancelled = True
        if self._cancel_raises:
            raise RuntimeError("cancel failed")


class FakeEditorAssetLibrary:
    def __init__(self, assets=None, save_result=True):
        self.assets = assets if assets is not None else {}
        self.save_result = save_result
        self.saved = []

    def does_asset_exist(self, path):
        return path in self.assets

    def load_asset(self, path):
        return self.assets.get(path)

    def save_loaded_asset(self, asset):
        self.saved.append(asset)
        return self.save_result


class FakeAssetTools:
    def __init__(self, editor_lib, created_class="BlackboardData"):
        self.editor_lib = editor_lib
        self.created_class = created_class

    def create_asset(self, name, package_path, asset_class, factory):
        path = package_path + "/" + name
        asset = FakeAsset(self.created_class)
        self.editor_lib.assets[path] = asset
        return asset


class FakeUnreal:
    """Configurable ``unreal`` module double."""

    def __init__(
        self,
        *,
        version="5.4.2-0",
        plugins=None,
        missing_symbols=None,
        plugin_bridge=True,
        assets=None,
        save_result=True,
        drop_writes=False,
        entry_constructible=True,
        key_type_constructible=True,
        cancel_raises=False,
    ):
        self._module = types.ModuleType("unreal")
        self.editor_lib = FakeEditorAssetLibrary(assets=assets, save_result=save_result)
        self.transactions = []
        self.created_assets = {}

        self._module.SystemLibrary = types.SimpleNamespace(get_engine_version=lambda: version)
        if plugin_bridge:
            self._module.DccMcpAutomationLibrary = types.SimpleNamespace(
                get_enabled_plugin_names=lambda: list(plugins if plugins is not None else ["AIModule"])
            )
        self._module.EditorAssetLibrary = self.editor_lib
        self._module.AssetToolsHelpers = types.SimpleNamespace(get_asset_tools=lambda: FakeAssetTools(self.editor_lib))
        self._module.BlackboardData = type("BlackboardData", (), {})
        self._module.BlackboardDataFactory = type("BlackboardDataFactory", (), {})

        for cls_name in KEY_TYPE_CLASSES:
            setattr(
                self._module,
                cls_name,
                (lambda n: lambda: FakeKeyType(n))(cls_name),
            )
        if not key_type_constructible:

            def bad_key_type():
                raise RuntimeError("cannot construct key type")

            for cls_name in KEY_TYPE_CLASSES:
                setattr(self._module, cls_name, bad_key_type)

        if entry_constructible:
            self._module.BlackboardEntry = FakeEntry
        else:

            def bad_entry():
                raise RuntimeError("cannot construct entry")

            self._module.BlackboardEntry = bad_entry

        def make_txn(label):
            txn = FakeTransaction(label, cancel_raises=cancel_raises)
            self.transactions.append(txn)
            return txn

        self._module.ScopedEditorTransaction = make_txn

        for name in missing_symbols or []:
            if hasattr(self._module, name):
                delattr(self._module, name)

    @property
    def module(self):
        return self._module


def _seed_asset(unreal, path, keys=None, class_name="BlackboardData", drop_writes=False):
    asset = FakeAsset(class_name=class_name, keys=keys, drop_writes=drop_writes)
    unreal.editor_lib.assets[path] = asset
    return asset


def _existing_key(name="Existing", key_type_name="BlackboardKeyType_Float"):
    return FakeEntry(name=name, key_type=FakeKeyType(get_class_name=key_type_name))


# ---------------------------------------------------------------------------
# Preflight contract (version / plugin / API gating, read-only)
# ---------------------------------------------------------------------------


def test_preflight_ready_on_qualified_host():
    core = _load_core()
    result = core.preflight(FakeUnreal().module)
    assert result["ready"] is True
    assert result["version_supported"] is True
    assert result["missing_apis"] == []
    assert result["plugin_bridge_available"] is True
    assert result["next_action"]["action"] == "proceed"
    assert "DccMcpAutomationLibrary" not in result  # not mutated / no side effect markers


def test_preflight_rejects_unsupported_engine_version():
    core = _load_core()
    result = core.preflight(FakeUnreal(version="4.27.2-0").module)
    assert result["ready"] is False
    assert result["version_supported"] is False
    assert result["next_action"]["action"] == "unsupported_engine_version"
    assert result["next_action"]["requires"] == ">=5.0"


def test_preflight_fails_closed_when_api_symbol_missing():
    core = _load_core()
    result = core.preflight(FakeUnreal(missing_symbols=["BlackboardEntry"]).module)
    assert result["ready"] is False
    assert "BlackboardEntry" in result["missing_apis"]
    assert result["next_action"]["action"] == "update_adapter_plugin"
    assert "BlackboardEntry" in result["next_action"]["missing_apis"]


def test_preflight_fails_closed_when_plugin_bridge_unavailable():
    core = _load_core()
    result = core.preflight(FakeUnreal(plugin_bridge=False).module)
    assert result["ready"] is False
    assert result["plugin_bridge_available"] is False
    assert result["next_action"]["action"] == "update_adapter_plugin"


def test_preflight_rejects_unknown_capability():
    core = _load_core()
    with pytest.raises(core.AiBlackboardError) as exc:
        core.preflight(FakeUnreal().module, "state_tree")
    assert exc.value.reason == "unknown_capability"


def test_preflight_is_read_only_no_asset_creation():
    core = _load_core()
    fake = FakeUnreal()
    core.preflight(fake.module)
    assert fake.editor_lib.saved == []
    assert fake.editor_lib.assets == {}


# ---------------------------------------------------------------------------
# Inspect contract (bounded real readback, never mutates)
# ---------------------------------------------------------------------------


def test_inspect_reports_missing_asset_without_creating():
    core = _load_core()
    fake = FakeUnreal()
    result = core.inspect_blackboard(fake.module, "/Game/AI/BB_Missing")
    assert result["exists"] is False
    assert result["readback_verified"] is True
    assert result["read_only"] is True
    assert fake.editor_lib.assets == {}


def test_inspect_reads_bounded_keys_from_existing_asset():
    core = _load_core()
    fake = FakeUnreal()
    _seed_asset(
        fake, "/Game/AI/BB_Enemy", keys=[_existing_key("Target"), _existing_key("Dist", "BlackboardKeyType_Int")]
    )
    result = core.inspect_blackboard(fake.module, "/Game/AI/BB_Enemy")
    assert result["exists"] is True
    assert result["key_count"] == 2
    assert result["keys"][0]["name"] == "Target"
    assert result["keys"][1]["key_type"] == "BlackboardKeyType_Int"
    assert result["readback_verified"] is True


def test_inspect_rejects_wrong_class_asset():
    core = _load_core()
    fake = FakeUnreal()
    _seed_asset(fake, "/Game/AI/NotABB", class_name="StaticMesh")
    with pytest.raises(core.AiBlackboardError) as exc:
        core.inspect_blackboard(fake.module, "/Game/AI/NotABB")
    assert exc.value.reason == "wrong_asset_class"


def test_inspect_rejects_invalid_path():
    core = _load_core()
    with pytest.raises(core.AiBlackboardError) as exc:
        core.inspect_blackboard(FakeUnreal().module, "/Engine/Foo")
    assert exc.value.reason == "invalid_asset_path"


def test_inspect_enforces_key_limit():
    core = _load_core()
    fake = FakeUnreal()
    many = [_existing_key("K{}".format(i)) for i in range(core._MAX_KEYS + 1)]
    _seed_asset(fake, "/Game/AI/BB_Big", keys=many)
    with pytest.raises(core.AiBlackboardError) as exc:
        core.inspect_blackboard(fake.module, "/Game/AI/BB_Big")
    assert exc.value.reason == "inspection_limit"


# ---------------------------------------------------------------------------
# Authoring contract (minimal action, real readback, undo/cancel)
# ---------------------------------------------------------------------------


def test_author_creates_asset_and_key_with_real_readback():
    core = _load_core()
    fake = FakeUnreal()
    result = core.author_blackboard_key(fake.module, "/Game/AI/BB_Enemy", "TargetDistance", key_type="float")
    assert result["created"] is True
    assert result["readback_verified"] is True
    assert result["saved"] is True
    assert result["key_count_before"] == 0
    assert result["key_count_after"] == 1
    assert result["mutation_state"] == "committed"
    assert result["key_type_class"] == "BlackboardKeyType_Float"
    assert result["generation_verified"] is False
    assert result["reopen_verified"] is False
    # Readback really observed the key on the asset.
    asset = fake.editor_lib.assets["/Game/AI/BB_Enemy"]
    assert len(asset.get_editor_property("keys")) == 1
    assert fake.editor_lib.saved == [asset]
    assert fake.transactions and fake.transactions[0].exited and not fake.transactions[0].cancelled


def test_author_adds_key_to_existing_asset_without_overwrite():
    core = _load_core()
    fake = FakeUnreal()
    asset = _seed_asset(fake, "/Game/AI/BB_Enemy", keys=[_existing_key("Target")])
    result = core.author_blackboard_key(fake.module, "/Game/AI/BB_Enemy", "Health", key_type="int")
    assert result["created"] is False
    assert result["key_count_before"] == 1
    assert result["key_count_after"] == 2
    assert result["readback_verified"] is True
    names = [str(e.get_editor_property("entry_name")) for e in asset.get_editor_property("keys")]
    assert names == ["Target", "Health"]


def test_author_refuses_duplicate_key_before_transaction():
    core = _load_core()
    fake = FakeUnreal()
    _seed_asset(fake, "/Game/AI/BB_Enemy", keys=[_existing_key("Target")])
    with pytest.raises(core.AiBlackboardError) as exc:
        core.author_blackboard_key(fake.module, "/Game/AI/BB_Enemy", "Target")
    assert exc.value.reason == "duplicate_key"
    assert fake.transactions == []  # no mutation started
    assert fake.editor_lib.saved == []


def test_author_fails_closed_when_preflight_not_ready():
    core = _load_core()
    fake = FakeUnreal(version="4.26.0-0")
    with pytest.raises(core.AiBlackboardError) as exc:
        core.author_blackboard_key(fake.module, "/Game/AI/BB_Enemy", "X")
    assert exc.value.reason == "preflight_not_ready"
    assert exc.value.context["next_action"]["action"] == "unsupported_engine_version"
    assert fake.editor_lib.assets == {}
    assert fake.transactions == []


def test_author_rejects_unsupported_key_type():
    core = _load_core()
    with pytest.raises(core.AiBlackboardError) as exc:
        core.author_blackboard_key(FakeUnreal().module, "/Game/AI/BB_Enemy", "X", key_type="widget")
    assert exc.value.reason == "unsupported_key_type"


def test_author_rejects_invalid_key_name_and_path():
    core = _load_core()
    with pytest.raises(core.AiBlackboardError) as exc:
        core.author_blackboard_key(FakeUnreal().module, "/Game/AI/BB_Enemy", "9bad")
    assert exc.value.reason == "invalid_key_name"
    with pytest.raises(core.AiBlackboardError) as exc:
        core.author_blackboard_key(FakeUnreal().module, "/Game/../bad", "Good")
    assert exc.value.reason == "invalid_asset_path"


def test_author_respects_create_if_missing_false():
    core = _load_core()
    with pytest.raises(core.AiBlackboardError) as exc:
        core.author_blackboard_key(FakeUnreal().module, "/Game/AI/BB_Enemy", "X", create_if_missing=False)
    assert exc.value.reason == "asset_not_found"


def test_author_rolls_back_on_readback_mismatch():
    core = _load_core()
    fake = FakeUnreal(drop_writes=True)
    _seed_asset(fake, "/Game/AI/BB_Enemy", drop_writes=True)
    with pytest.raises(core.AiBlackboardError) as exc:
        core.author_blackboard_key(fake.module, "/Game/AI/BB_Enemy", "X")
    assert exc.value.reason == "readback_mismatch"
    assert exc.value.context["mutation_state"] == "rolled_back"
    assert fake.transactions and fake.transactions[0].cancelled
    assert fake.editor_lib.saved == []  # never saved on mismatch


def test_author_rolls_back_on_save_failure():
    core = _load_core()
    fake = FakeUnreal(save_result=False)
    with pytest.raises(core.AiBlackboardError) as exc:
        core.author_blackboard_key(fake.module, "/Game/AI/BB_Enemy", "X")
    assert exc.value.reason == "save_failed"
    assert exc.value.context["mutation_state"] == "rolled_back"
    assert fake.transactions and fake.transactions[0].cancelled


def test_author_rolls_back_when_key_type_construction_fails():
    core = _load_core()
    fake = FakeUnreal(key_type_constructible=False)
    with pytest.raises(core.AiBlackboardError) as exc:
        core.author_blackboard_key(fake.module, "/Game/AI/BB_Enemy", "X")
    # Construction happens inside the transaction, so rollback is exercised.
    assert exc.value.context["mutation_state"] == "rolled_back"
    assert fake.transactions and fake.transactions[0].cancelled


def test_author_reports_recovery_error_when_cancel_fails():
    core = _load_core()
    fake = FakeUnreal(drop_writes=True, cancel_raises=True)
    _seed_asset(fake, "/Game/AI/BB_Enemy", drop_writes=True)
    with pytest.raises(core.AiBlackboardError) as exc:
        core.author_blackboard_key(fake.module, "/Game/AI/BB_Enemy", "X")
    assert exc.value.context["mutation_state"] == "rolled_back"
    assert any("cancel failed" in note for note in exc.value.context["recovery_errors"])


def test_author_enforces_key_limit_before_mutation():
    core = _load_core()
    fake = FakeUnreal()
    many = [_existing_key("K{}".format(i)) for i in range(core._MAX_KEYS)]
    _seed_asset(fake, "/Game/AI/BB_Full", keys=many)
    with pytest.raises(core.AiBlackboardError) as exc:
        core.author_blackboard_key(fake.module, "/Game/AI/BB_Full", "OneMore")
    assert exc.value.reason == "limit_exceeded"
    assert fake.transactions == []


def test_author_refuses_wrong_class_existing_asset():
    core = _load_core()
    fake = FakeUnreal()
    _seed_asset(fake, "/Game/AI/NotABB", class_name="StaticMesh")
    with pytest.raises(core.AiBlackboardError) as exc:
        core.author_blackboard_key(fake.module, "/Game/AI/NotABB", "X")
    assert exc.value.reason == "wrong_asset_class"


def test_capability_matrix_statuses_are_explicit():
    core = _load_core()
    matrix = {row["capability"]: row["status"] for row in core.capability_matrix()}
    assert matrix["ai_blackboard"] == "supported"
    assert matrix["behavior_tree_graph"] == "gap"
    assert matrix["state_tree"] == "gap"
    assert matrix["eqs"] == "gap"
    assert matrix["ai_perception"] == "partial"
    assert matrix["gameplay_tags"] == "partial"


# ---------------------------------------------------------------------------
# Tool script contracts (skill_success / skill_error), via run_skill_script
# ---------------------------------------------------------------------------


def _run_script(script_name, fake, **params):
    from unittest.mock import patch  # noqa: PLC0415

    core = _load_core()
    # Pre-seed the sibling helper so the script's ``from _ai_blackboard import``
    # resolves to our path-independent module regardless of sys.path state.
    with patch.dict(sys.modules, {"unreal": fake.module, "_ai_blackboard": core}):
        return run_skill_script(str(SCRIPTS / script_name), dict(params))


def test_preflight_tool_returns_success_contract():
    fake = FakeUnreal()
    result = _run_script("ai_capability_preflight.py", fake, capability="ai_blackboard")
    assert result["success"] is True
    assert result["context"]["ready"] is True
    assert result["context"]["next_action"]["action"] == "proceed"


def test_preflight_tool_surfaces_not_ready_without_raising():
    fake = FakeUnreal(version="4.27.0-0")
    result = _run_script("ai_capability_preflight.py", fake)
    assert result["success"] is True  # preflight itself succeeded; readiness is in context
    assert result["context"]["ready"] is False
    assert result["context"]["next_action"]["action"] == "unsupported_engine_version"


def test_inspect_tool_returns_bounded_contract():
    fake = FakeUnreal()
    _seed_asset(fake, "/Game/AI/BB_Enemy", keys=[_existing_key("Target")])
    result = _run_script("inspect_ai_blackboard.py", fake, asset_path="/Game/AI/BB_Enemy")
    assert result["success"] is True
    assert result["context"]["exists"] is True
    assert result["context"]["key_count"] == 1
    assert result["context"]["readback_verified"] is True


def test_author_tool_returns_verified_receipt():
    fake = FakeUnreal()
    result = _run_script(
        "author_ai_blackboard_key.py",
        fake,
        asset_path="/Game/AI/BB_Enemy",
        key_name="TargetDistance",
        key_type="float",
    )
    assert result["success"] is True
    assert result["context"]["readback_verified"] is True
    assert result["context"]["mutation_state"] == "committed"


def test_author_tool_surfaces_typed_error_on_duplicate():
    fake = FakeUnreal()
    _seed_asset(fake, "/Game/AI/BB_Enemy", keys=[_existing_key("Target")])
    result = _run_script(
        "author_ai_blackboard_key.py",
        fake,
        asset_path="/Game/AI/BB_Enemy",
        key_name="Target",
        key_type="float",
    )
    assert result["success"] is False
    assert result["context"]["reason"] == "duplicate_key"


def test_author_tool_surfaces_typed_error_on_readback_mismatch():
    fake = FakeUnreal(drop_writes=True)
    _seed_asset(fake, "/Game/AI/BB_Enemy", drop_writes=True)
    result = _run_script(
        "author_ai_blackboard_key.py",
        fake,
        asset_path="/Game/AI/BB_Enemy",
        key_name="X",
        key_type="float",
    )
    assert result["success"] is False
    assert result["context"]["reason"] == "readback_mismatch"
    assert result["context"]["mutation_state"] == "rolled_back"


def test_scripts_fail_gracefully_when_unreal_is_absent():
    from unittest.mock import patch  # noqa: PLC0415

    core = _load_core()
    # Setting sys.modules["unreal"] = None makes ``import unreal`` raise
    # ImportError, exercising the script's graceful "not available" path.
    with patch.dict(sys.modules, {"unreal": None, "_ai_blackboard": core}):
        result = run_skill_script(str(SCRIPTS / "ai_capability_preflight.py"), {})
    assert result["success"] is False
    assert "Unreal" in result["message"] or "unreal" in result["error"].lower()


# ---------------------------------------------------------------------------
# Static/source contracts: tools.yaml, SKILL.md, matrix doc, py37 syntax
# ---------------------------------------------------------------------------


def _tools():
    return yaml.safe_load(TOOLS.read_text(encoding="utf-8"))["tools"]


def test_tools_yaml_schemas_and_call_examples_are_valid():
    tools = _tools()
    names = {t["name"] for t in tools}
    assert names == {"ai_capability_preflight", "inspect_ai_blackboard", "author_ai_blackboard_key"}
    for tool in tools:
        Draft202012Validator.check_schema(tool["input_schema"])
        source = SKILL_DIR / tool["source_file"]
        assert source.is_file(), "missing source_file for {}".format(tool["name"])
        for example in tool.get("call_examples", []):
            Draft202012Validator(tool["input_schema"]).validate(example["arguments"])


def test_author_tool_declares_main_thread_and_cancellation():
    tool = next(t for t in _tools() if t["name"] == "author_ai_blackboard_key")
    assert tool["enforce_thread_affinity"] is True
    assert tool["affinity"] == "main"
    assert tool["read_only"] is False
    assert any("advisory" in p for p in tool["preconditions"])


def test_preflight_and_inspect_are_read_only():
    for name in ("ai_capability_preflight", "inspect_ai_blackboard"):
        tool = next(t for t in _tools() if t["name"] == name)
        assert tool["read_only"] is True
        assert tool["destructive"] is False


def test_next_tools_reference_known_or_diagnostic_tools():
    known = {t["name"] for t in _tools()}
    known.add("dcc_diagnostics__audit_log")
    for tool in _tools():
        for group in tool.get("next-tools", {}).values():
            for ref in group:
                assert ref in known or ref in {
                    "unreal_ai__ai_capability_preflight",
                    "unreal_ai__inspect_ai_blackboard",
                    "unreal_ai__author_ai_blackboard_key",
                    "dcc_diagnostics__audit_log",
                }, "unknown next-tool reference: {}".format(ref)


def test_skill_md_frontmatter_and_matrix_present():
    text = SKILL_MD.read_text(encoding="utf-8")
    assert text.startswith("---")
    front = text.split("---", 2)[1]
    meta = yaml.safe_load(front)
    assert meta["name"] == "unreal-ai"
    assert meta["metadata"]["dcc-mcp"]["tools"] == "tools.yaml"
    assert "Capability matrix" in text
    assert "undo/cancel" in text.lower()
    assert MATRIX_DOC.is_file()
    doc = MATRIX_DOC.read_text(encoding="utf-8")
    for status in ("supported", "partial", "gap", "not applicable"):
        assert status in doc
    assert "DccMcpAutomationLibrary" in doc


def test_commandlet_probe_is_separate_gate_and_loads_core_by_path():
    text = COMMANDLET_PROBE.read_text(encoding="utf-8")
    assert "spec_from_file_location" in text
    assert "_ai_blackboard.py" in text
    assert "run_probe" in text


def test_all_new_python_files_parse_as_python_37():
    new_files = [
        CORE,
        SCRIPTS / "ai_capability_preflight.py",
        SCRIPTS / "inspect_ai_blackboard.py",
        SCRIPTS / "author_ai_blackboard_key.py",
        COMMANDLET_PROBE,
        Path(__file__),
    ]
    for path in new_files:
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path), feature_version=(3, 7))
