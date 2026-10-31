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
    def __init__(self, name="BlackboardKeyType_Float", get_class_name=None, outer=None):
        self._name = name if get_class_name is None else get_class_name
        # Models the UObject Outer.  A key type outered to the Blackboard asset
        # is serialized on save; a transient (None) outer is not (H2).
        self.outer = outer

    def get_class(self):
        return types.SimpleNamespace(get_name=lambda: self._name)


class FakeKeyTypeClass:
    """Stand-in for the UClass returned by ``unreal.load_class`` on UE 5.5/5.8.

    On those hosts ``BlackboardKeyType_*`` are not exposed as ``unreal.``
    attributes; they are only reachable through ``load_class``.  Instances are
    then built with ``unreal.new_object(cls, outer)``.
    """

    def __init__(self, name):
        self._name = name

    def get_name(self):
        return self._name


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
    def __init__(self, class_name="BlackboardData", keys=None, drop_writes=False, read_raises=False):
        self._class = FakeClass(class_name)
        self._props = {"keys": list(keys or [])}
        self.drop_writes = drop_writes
        self.read_raises = read_raises

    def get_class(self):
        return self._class

    def get_editor_property(self, name):
        if self.read_raises and name == "keys":
            raise RuntimeError("keys property unavailable")
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
    def __init__(self, assets=None, save_result=True, delete_result=True, unloadable=None):
        self.assets = assets if assets is not None else {}
        self.save_result = save_result
        self.delete_result = delete_result
        # Paths that "exist" (does_asset_exist True) but fail to load -> None.
        self.unloadable = set(unloadable or ())
        self.saved = []
        self.deleted = []
        self.delete_calls = []

    def does_asset_exist(self, path):
        return path in self.assets or path in self.unloadable

    def load_asset(self, path):
        if path in self.unloadable:
            return None
        return self.assets.get(path)

    def save_loaded_asset(self, asset):
        self.saved.append(asset)
        return self.save_result

    def delete_loaded_asset(self, asset):
        self.delete_calls.append(asset)
        for path, existing in list(self.assets.items()):
            if existing is asset:
                del self.assets[path]
                self.deleted.append(path)
                break
        return self.delete_result

    def delete_asset(self, path):
        self.delete_calls.append(path)
        if path in self.assets:
            del self.assets[path]
            self.deleted.append(path)
        return self.delete_result


class FakeAssetTools:
    def __init__(self, editor_lib, created_class="BlackboardData", created_read_raises=False):
        self.editor_lib = editor_lib
        self.created_class = created_class
        self.created_read_raises = created_read_raises
        self.create_calls = []

    def create_asset(self, name, package_path, asset_class, factory):
        path = package_path + "/" + name
        self.create_calls.append((name, package_path))
        asset = FakeAsset(self.created_class, read_raises=self.created_read_raises)
        self.editor_lib.assets[path] = asset
        return asset


class FakeUnreal:
    """Configurable ``unreal`` module double that models the real 5.5/5.8 host.

    On those hosts the ``BlackboardKeyType_*`` UCLASSes are NOT exposed as
    ``unreal.<Name>`` attributes; they are resolved through
    ``unreal.load_class(None, "/Script/AIModule.<Name>")`` and instantiated via
    ``unreal.new_object(cls, outer)``.  Previously this double hung the classes
    on the module, which is why the CI suite missed the H1 host failure.  The
    default model below uses ``load_class`` + ``new_object`` and records the
    outer so persistence (H2) can be asserted; ``key_type_on_module=True``
    re-enables the legacy attribute path for fallback-path tests.
    """

    _SCRIPT_PREFIX = "/Script/AIModule."

    def __init__(
        self,
        *,
        version="5.4.2-0",
        plugins=None,
        missing_symbols=None,
        plugin_bridge=True,
        assets=None,
        save_result=True,
        delete_result=True,
        unloadable=None,
        created_class="BlackboardData",
        created_read_raises=False,
        drop_writes=False,
        entry_constructible=True,
        key_type_constructible=True,
        key_type_loadable=True,
        key_type_on_module=False,
        new_object_available=True,
        new_object_transient=False,
        cancel_raises=False,
        empty_key_type_class=False,
    ):
        self._module = types.ModuleType("unreal")
        self.editor_lib = FakeEditorAssetLibrary(
            assets=assets, save_result=save_result, delete_result=delete_result, unloadable=unloadable
        )
        self.asset_tools = FakeAssetTools(
            self.editor_lib, created_class=created_class, created_read_raises=created_read_raises
        )
        self.transactions = []
        self.created_assets = {}
        self.load_class_calls = []
        self.new_object_calls = []
        self._key_type_loadable = key_type_loadable
        self._key_type_constructible = key_type_constructible
        self._empty_key_type_class = empty_key_type_class
        self._new_object_transient = new_object_transient

        self._module.SystemLibrary = types.SimpleNamespace(get_engine_version=lambda: version)
        if plugin_bridge:
            self._module.DccMcpAutomationLibrary = types.SimpleNamespace(
                get_enabled_plugin_names=lambda: list(plugins if plugins is not None else ["AIModule"])
            )
        self._module.EditorAssetLibrary = self.editor_lib
        self._module.AssetToolsHelpers = types.SimpleNamespace(get_asset_tools=lambda: self.asset_tools)
        self._module.BlackboardData = type("BlackboardData", (), {})
        self._module.BlackboardDataFactory = type("BlackboardDataFactory", (), {})

        # Real-host key type resolution + construction surface.
        self._module.load_class = self._load_class
        if new_object_available:
            self._module.new_object = self._new_object

        if key_type_on_module:
            for cls_name in KEY_TYPE_CLASSES:
                if empty_key_type_class:
                    setattr(self._module, cls_name, lambda: FakeKeyType(get_class_name=""))
                else:
                    setattr(self._module, cls_name, (lambda n: lambda: FakeKeyType(n))(cls_name))
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

    def _load_class(self, outer, path):
        self.load_class_calls.append((outer, path))
        if not self._key_type_loadable:
            return None
        if isinstance(path, str) and path.startswith(self._SCRIPT_PREFIX):
            name = path[len(self._SCRIPT_PREFIX) :]
            if name in KEY_TYPE_CLASSES:
                return FakeKeyTypeClass(name)
        return None

    def _new_object(self, cls, outer=None):
        self.new_object_calls.append((cls, outer))
        if not self._key_type_constructible:
            raise RuntimeError("cannot construct key type")
        name = cls.get_name() if isinstance(cls, FakeKeyTypeClass) else getattr(cls, "_name", "BlackboardKeyType_Float")
        if self._empty_key_type_class:
            name = ""
        effective_outer = None if self._new_object_transient else outer
        return FakeKeyType(name=name, outer=effective_outer)

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
    # The class is still resolvable via load_class; only new_object() fails.
    assert core.preflight(fake.module, key_type="float")["key_type_available"] is True
    with pytest.raises(core.AiBlackboardError) as exc:
        core.author_blackboard_key(fake.module, "/Game/AI/BB_Enemy", "X")
    # Construction happens inside the transaction, so rollback is exercised.
    assert exc.value.reason == "key_type_construction_unavailable"
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


# ---------------------------------------------------------------------------
# NACK regression contracts (F2/F3/F5/F6 blocking, F1/F4/F7/F8 follow-ups)
# ---------------------------------------------------------------------------


def test_f2_author_fails_closed_when_existing_asset_cannot_load():
    core = _load_core()
    fake = FakeUnreal(unloadable=["/Game/AI/BB_Occupied"])
    with pytest.raises(core.AiBlackboardError) as exc:
        core.author_blackboard_key(fake.module, "/Game/AI/BB_Occupied", "NewKey")
    assert exc.value.reason == "asset_load_failed"
    # create_asset must NEVER run on an occupied path (no overwrite).
    assert fake.asset_tools.create_calls == []
    assert fake.editor_lib.saved == []


def test_f2_inspect_fails_closed_when_existing_asset_cannot_load():
    core = _load_core()
    fake = FakeUnreal(unloadable=["/Game/AI/BB_Occupied"])
    with pytest.raises(core.AiBlackboardError) as exc:
        core.inspect_blackboard(fake.module, "/Game/AI/BB_Occupied")
    assert exc.value.reason == "asset_load_failed"


def test_f3_created_asset_is_deleted_when_save_fails():
    core = _load_core()
    fake = FakeUnreal(save_result=False)
    with pytest.raises(core.AiBlackboardError) as exc:
        core.author_blackboard_key(fake.module, "/Game/AI/BB_New", "X")
    assert exc.value.reason == "save_failed"
    assert exc.value.context["created"] is True
    assert exc.value.context["mutation_state"] == "rolled_back"
    # The empty asset this call created must not be left behind.
    assert "/Game/AI/BB_New" not in fake.editor_lib.assets
    assert "/Game/AI/BB_New" in fake.editor_lib.deleted


def test_f3_created_asset_deletion_is_recorded_when_delete_fails():
    core = _load_core()
    fake = FakeUnreal(save_result=False, delete_result=False)
    with pytest.raises(core.AiBlackboardError) as exc:
        core.author_blackboard_key(fake.module, "/Game/AI/BB_New", "X")
    assert exc.value.context["created"] is True
    assert any("delete" in note.lower() for note in exc.value.context["recovery_errors"])


def test_f3_post_creation_failure_reports_created_flag():
    core = _load_core()
    # create_asset succeeds but the just-created asset cannot be read back,
    # raising unsupported_property from _read_keys BEFORE the transaction.
    fake = FakeUnreal(created_read_raises=True)
    with pytest.raises(core.AiBlackboardError) as exc:
        core.author_blackboard_key(fake.module, "/Game/AI/BB_New", "X")
    assert exc.value.reason == "unsupported_property"
    assert exc.value.context["created"] is True
    assert "/Game/AI/BB_New" not in fake.editor_lib.assets
    assert "/Game/AI/BB_New" in fake.editor_lib.deleted


def test_f3_wrong_class_after_creation_is_cleaned_up_with_created_flag():
    core = _load_core()
    fake = FakeUnreal(created_class="StaticMesh")
    with pytest.raises(core.AiBlackboardError) as exc:
        core.author_blackboard_key(fake.module, "/Game/AI/BB_Wrong", "X")
    assert exc.value.reason == "wrong_asset_class"
    assert exc.value.context["created"] is True
    assert "/Game/AI/BB_Wrong" not in fake.editor_lib.assets


def test_f5_empty_readback_key_type_fails_closed():
    core = _load_core()
    fake = FakeUnreal(empty_key_type_class=True)
    with pytest.raises(core.AiBlackboardError) as exc:
        core.author_blackboard_key(fake.module, "/Game/AI/BB_Empty", "X")
    assert exc.value.reason == "readback_type_mismatch"
    assert exc.value.context["mutation_state"] == "rolled_back"
    # An empty observed type must never reach save with readback_verified=True.
    assert fake.editor_lib.saved == []


def test_f5_matching_key_type_still_commits():
    core = _load_core()
    fake = FakeUnreal()
    result = core.author_blackboard_key(fake.module, "/Game/AI/BB_Ok", "X")
    assert result["readback_verified"] is True
    assert result["mutation_state"] == "committed"
    assert result["saved"] is True


def test_f6_output_schemas_are_response_envelopes():
    tools = _tools()
    for tool in tools:
        schema = tool["output_schema"]
        Draft202012Validator.check_schema(schema)
        props = schema["properties"]
        assert {"success", "message", "error", "prompt", "context"} <= set(props), tool["name"]
        # Result fields live under context, not as top-level required keys.
        assert set(schema["required"]) <= {"success", "message"}, tool["name"]
        assert "context" in props and "properties" in props["context"]


def test_f6_output_schemas_validate_success_and_error_responses():
    from dcc_mcp_core.skill import skill_error  # noqa: PLC0415

    tools = {t["name"]: t for t in _tools()}
    success_responses = {
        "ai_capability_preflight": _run_script("ai_capability_preflight.py", FakeUnreal(), capability="ai_blackboard"),
        "inspect_ai_blackboard": _run_script(
            "inspect_ai_blackboard.py", FakeUnreal(), asset_path="/Game/AI/BB_Missing"
        ),
        "author_ai_blackboard_key": _run_script(
            "author_ai_blackboard_key.py", FakeUnreal(), asset_path="/Game/AI/BB_New", key_name="X"
        ),
    }
    # A genuine skill_error envelope carries reason/typed context, not the
    # result-field keys the old schema wrongly required on every response.
    error_response = skill_error(
        "rejected", "Engine error", reason="duplicate_key", mutation_state="rolled_back", recovery_errors=[]
    )
    for name, tool in tools.items():
        schema = tool["output_schema"]
        Draft202012Validator.check_schema(schema)
        # Both a real success envelope and a real error envelope must validate.
        Draft202012Validator(schema).validate(success_responses[name])
        Draft202012Validator(schema).validate(error_response)


def test_f6_author_error_response_validates():
    tools = {t["name"]: t for t in _tools()}
    schema = tools["author_ai_blackboard_key"]["output_schema"]
    dup_fake = FakeUnreal()
    _seed_asset(dup_fake, "/Game/AI/BB_Dup", keys=[_existing_key("Target")])
    error = _run_script("author_ai_blackboard_key.py", dup_fake, asset_path="/Game/AI/BB_Dup", key_name="Target")
    assert error["success"] is False
    Draft202012Validator(schema).validate(error)


def test_f7_preflight_fails_closed_when_required_method_missing():
    core = _load_core()
    fake = FakeUnreal()
    fake.editor_lib.save_loaded_asset = None  # symbol present, method not callable
    result = core.preflight(fake.module)
    assert result["ready"] is False
    assert "EditorAssetLibrary.save_loaded_asset" in result["missing_methods"]
    assert result["next_action"]["action"] == "update_adapter_plugin"
    assert "EditorAssetLibrary.save_loaded_asset" in result["next_action"]["missing_methods"]


def test_f7_preflight_ready_when_all_required_methods_present():
    core = _load_core()
    result = core.preflight(FakeUnreal().module)
    assert result["ready"] is True
    assert result["missing_methods"] == []


def test_f4_lookalike_class_name_is_rejected():
    core = _load_core()
    fake = FakeUnreal()
    _seed_asset(fake, "/Game/AI/BB_Lookalike", class_name="NotBlackboardDataTable")
    with pytest.raises(core.AiBlackboardError) as exc:
        core.inspect_blackboard(fake.module, "/Game/AI/BB_Lookalike")
    assert exc.value.reason == "wrong_asset_class"


def test_f4_subclass_via_is_child_of_is_accepted():
    core = _load_core()
    fake = FakeUnreal()

    class ChildClass(FakeClass):
        def is_child_of(self, base):
            return True

    asset = FakeAsset()
    asset._class = ChildClass("BlackboardData")
    fake.editor_lib.assets["/Game/AI/BB_Child"] = asset
    result = core.inspect_blackboard(fake.module, "/Game/AI/BB_Child")
    assert result["exists"] is True


def test_f1_docs_describe_direct_bridge_call_not_module_reuse():
    matrix = MATRIX_DOC.read_text(encoding="utf-8")
    skill = SKILL_MD.read_text(encoding="utf-8")
    core_source = CORE.read_text(encoding="utf-8")
    assert "get_enabled_plugin_names" in matrix
    assert "get_enabled_plugin_names" in skill
    # Docs must no longer claim plugin_preflight.py is reused as a helper.
    assert "plugin_preflight.py` are reused" not in matrix
    # The core calls the bridge directly and does not import plugin_preflight.
    assert "import plugin_preflight" not in core_source
    assert "from dcc_mcp_unreal.plugin_preflight" not in core_source


def test_f8_commandlet_probe_is_idempotent_on_rerun():
    # Load the probe module and drive run_probe twice against the same fake
    # project; a second run must reuse the existing key instead of rejecting.
    import importlib.util  # noqa: PLC0415
    from unittest.mock import patch  # noqa: PLC0415

    spec = importlib.util.spec_from_file_location("ue_probe_idempotent", COMMANDLET_PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    fake = FakeUnreal()
    with patch.dict(sys.modules, {"unreal": fake.module, "_ai_blackboard": _load_core()}):
        first = module.run_probe()
        second = module.run_probe()

    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert second["author"].get("reused_existing_key") is True


# ---------------------------------------------------------------------------
# Round-2 NACK regression contracts (N1 blocking; N2/N3 follow-ups)
# ---------------------------------------------------------------------------


def test_n1_author_refuses_case_insensitive_duplicate_key():
    core = _load_core()
    fake = FakeUnreal()
    _seed_asset(fake, "/Game/AI/BB_Enemy", keys=[_existing_key("ProbeDistance")])
    with pytest.raises(core.AiBlackboardError) as exc:
        core.author_blackboard_key(fake.module, "/Game/AI/BB_Enemy", "probedistance")
    assert exc.value.reason == "duplicate_key"
    assert fake.transactions == []  # rejected before any mutation
    assert fake.editor_lib.saved == []
    # No case-variant duplicate and the existing key is untouched.
    asset = fake.editor_lib.assets["/Game/AI/BB_Enemy"]
    names = [str(e.get_editor_property("entry_name")) for e in asset.get_editor_property("keys")]
    assert names == ["ProbeDistance"]


def test_n1_readback_matches_key_after_fname_case_normalization():
    # FName equality ignores case and preserves an earlier spelling, so the
    # authored key can reappear in the readback under a different case. The
    # post-write readback must still match it instead of failing closed.
    core = _load_core()
    fake = FakeUnreal()
    asset = _seed_asset(fake, "/Game/AI/BB_Enemy")
    original_set = asset.set_editor_property

    def normalize_case(name, value):
        if name == "keys":
            for entry in value:
                entry.set_editor_property("entry_name", str(entry.get_editor_property("entry_name")).lower())
        original_set(name, value)

    asset.set_editor_property = normalize_case
    result = core.author_blackboard_key(fake.module, "/Game/AI/BB_Enemy", "ProbeDistance", key_type="float")
    assert result["readback_verified"] is True
    assert result["saved"] is True


def test_n2_commandlet_probe_fails_closed_when_first_inspect_raises():
    import importlib.util  # noqa: PLC0415
    from unittest.mock import patch  # noqa: PLC0415

    spec = importlib.util.spec_from_file_location("ue_probe_n2", COMMANDLET_PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    fake = FakeUnreal(unloadable=["/Game/DccMcpAiProbe/BB_Probe"])
    with patch.dict(sys.modules, {"unreal": fake.module, "_ai_blackboard": _load_core()}):
        result = module.run_probe()
    assert result["status"] == "rejected"
    assert result["reason"] == "asset_load_failed"


def test_n3_failure_context_matches_documented_expectations():
    core = _load_core()
    # Pre-mutation validation failures carry neither created nor recovery_errors.
    with pytest.raises(core.AiBlackboardError) as exc:
        core.author_blackboard_key(FakeUnreal().module, "/Game/AI/BB", "9bad")
    assert "created" not in exc.value.context
    assert "recovery_errors" not in exc.value.context
    # In-transaction failures carry created and the rollback's recovery_errors.
    fake = FakeUnreal(drop_writes=True)
    _seed_asset(fake, "/Game/AI/BB", drop_writes=True)
    with pytest.raises(core.AiBlackboardError) as exc:
        core.author_blackboard_key(fake.module, "/Game/AI/BB", "X")
    assert exc.value.context["created"] is False
    assert "recovery_errors" in exc.value.context


# ---------------------------------------------------------------------------
# Real-host acceptance regressions (H1 load_class, H2 asset outer, H3 gates)
# ---------------------------------------------------------------------------


def test_h1_fake_unreal_models_real_host_key_type_surface():
    # On UE 5.5/5.8 the BlackboardKeyType_* UCLASSes are NOT unreal module
    # attributes; the double must reflect that (this is why CI missed H1).
    fake = FakeUnreal()
    assert getattr(fake.module, "BlackboardKeyType_Float", None) is None
    # But they are resolvable through load_class from the AIModule package.
    cls = fake.module.load_class(None, "/Script/AIModule.BlackboardKeyType_Float")
    assert isinstance(cls, FakeKeyTypeClass)
    assert cls.get_name() == "BlackboardKeyType_Float"
    assert callable(fake.module.new_object)


def test_h1_author_resolves_key_type_via_load_class_not_attribute():
    core = _load_core()
    fake = FakeUnreal()
    # Authoring must succeed even though the class is not an unreal attribute.
    result = core.author_blackboard_key(fake.module, "/Game/AI/BB_Enemy", "X", key_type="float")
    assert result["saved"] is True
    assert result["readback_verified"] is True
    assert result["key_type_class"] == "BlackboardKeyType_Float"
    # The AIModule load path was actually exercised.
    assert any(path == "/Script/AIModule.BlackboardKeyType_Float" for _, path in fake.load_class_calls)


def test_h1_author_fails_closed_when_key_type_class_unresolvable():
    core = _load_core()
    fake = FakeUnreal(key_type_loadable=False)
    with pytest.raises(core.AiBlackboardError) as exc:
        core.author_blackboard_key(fake.module, "/Game/AI/BB_Enemy", "X", key_type="float")
    # Preflight now gates the requested class, so it fails closed before any
    # mutation with a machine-readable unsupported signal.
    assert exc.value.reason == "preflight_not_ready"
    assert exc.value.context["next_action"]["missing_key_types"] == ["BlackboardKeyType_Float"]
    assert fake.editor_lib.assets == {}
    assert fake.editor_lib.saved == []
    assert fake.transactions == []


def test_h1_author_fails_closed_when_persistent_outer_unavailable():
    core = _load_core()
    # No unreal.new_object(): a key type cannot be outered to the Blackboard
    # asset, so authoring must fail closed instead of saving a transient-outer
    # key whose type is silently lost on reopen (CodeRabbit F1).
    fake = FakeUnreal(new_object_available=False)
    with pytest.raises(core.AiBlackboardError) as exc:
        core.author_blackboard_key(fake.module, "/Game/AI/BB_Enemy", "X", key_type="float")
    assert exc.value.reason == "unsupported_api"
    assert exc.value.context["api"] == "new_object"
    assert exc.value.context["next_action"]["action"] == "update_adapter_plugin"
    assert fake.editor_lib.saved == []


def test_h2_key_type_is_outered_to_the_blackboard_asset():
    core = _load_core()
    fake = FakeUnreal()
    result = core.author_blackboard_key(fake.module, "/Game/AI/BB_Enemy", "X", key_type="float")
    assert result["saved"] is True
    asset = fake.editor_lib.assets["/Game/AI/BB_Enemy"]
    # new_object must be called with the resolved UClass and the asset as outer.
    assert fake.new_object_calls, "key type must be constructed via new_object"
    cls, outer = fake.new_object_calls[-1]
    assert isinstance(cls, FakeKeyTypeClass)
    assert cls.get_name() == "BlackboardKeyType_Float"
    assert outer is asset
    # The authored entry carries a key type whose Outer is the asset, which is
    # what makes it persist across save/reopen on real UE 5.5/5.8.
    entry = fake.editor_lib.assets["/Game/AI/BB_Enemy"].get_editor_property("keys")[-1]
    key_type = entry.get_editor_property("key_type")
    assert key_type.outer is asset


def test_h2_transient_outer_key_type_does_not_pass_type_readback_after_reopen():
    # Model the H2 defect: a key type with a transient (None) outer is lost on
    # reopen, so a "name present but type empty" asset must fail closed in the
    # commandlet probe reuse branch (H3) instead of reporting status=ok.
    import importlib.util  # noqa: PLC0415
    from unittest.mock import patch  # noqa: PLC0415

    core = _load_core()
    spec = importlib.util.spec_from_file_location("ue_probe_h3", COMMANDLET_PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    fake = FakeUnreal()
    # A previously-saved asset where the key name exists but its type was lost.
    lost = FakeEntry(name="ProbeDistance", key_type=FakeKeyType(name="", outer=None))
    _seed_asset(fake, "/Game/DccMcpAiProbe/BB_Probe", keys=[lost])
    with patch.dict(sys.modules, {"unreal": fake.module, "_ai_blackboard": core}):
        result = module.run_probe()
    assert result["status"] == "rejected"
    assert result["reason"] == "reused_key_type_mismatch"
    assert result["readback_verified"] is False


def test_h3_preflight_reports_key_type_availability():
    core = _load_core()
    fake = FakeUnreal()
    result = core.preflight(fake.module)
    assert result["ready"] is True
    assert result["checked_key_types"] == ["BlackboardKeyType_Float"]
    assert result["available_key_types"] == ["BlackboardKeyType_Float"]
    assert result["missing_key_types"] == []
    assert result["key_type_available"] is True
    # A specific requested type is gated, not just the default.
    int_result = core.preflight(fake.module, key_type="int")
    assert int_result["checked_key_types"] == ["BlackboardKeyType_Int"]


def test_h3_preflight_fails_closed_when_requested_key_type_unresolvable():
    core = _load_core()
    fake = FakeUnreal(key_type_loadable=False)
    result = core.preflight(fake.module)
    assert result["ready"] is False
    assert result["missing_key_types"] == ["BlackboardKeyType_Float"]
    assert result["key_type_available"] is False
    assert result["next_action"]["action"] == "update_adapter_plugin"
    assert result["next_action"]["missing_key_types"] == ["BlackboardKeyType_Float"]


def test_h3_preflight_tool_threads_requested_key_type():
    fake = FakeUnreal(key_type_loadable=False)
    result = _run_script("ai_capability_preflight.py", fake, capability="ai_blackboard", key_type="float")
    # Preflight itself succeeds; readiness is reported in context.
    assert result["success"] is True
    assert result["context"]["ready"] is False
    assert result["context"]["missing_key_types"] == ["BlackboardKeyType_Float"]


def test_h3_commandlet_probe_fails_closed_on_type_lost_asset():
    import importlib.util  # noqa: PLC0415
    from unittest.mock import patch  # noqa: PLC0415

    core = _load_core()
    spec = importlib.util.spec_from_file_location("ue_probe_h3b", COMMANDLET_PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    fake = FakeUnreal()
    lost = FakeEntry(name="ProbeDistance", key_type=FakeKeyType(name="", outer=None))
    _seed_asset(fake, "/Game/DccMcpAiProbe/BB_Probe", keys=[lost])
    with patch.dict(sys.modules, {"unreal": fake.module, "_ai_blackboard": core}):
        result = module.run_probe()
    # Must NOT report status=ok / readback_verified=true on a type-lost asset.
    assert result["status"] != "ok"
    assert result["readback_verified"] is False


# ---------------------------------------------------------------------------
# CodeRabbit follow-up findings (F1 fail-closed, F2 next_action, F3 JSON guard,
# F4 reopen_verified) — resolved against the exact-head review.
# ---------------------------------------------------------------------------


def _load_probe(name):
    import importlib.util  # noqa: PLC0415

    spec = importlib.util.spec_from_file_location(name, COMMANDLET_PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_f1_new_key_type_fails_closed_when_new_object_unavailable():
    core = _load_core()
    # No new_object at all: must raise unsupported_api, never call key_cls().
    called = {"fallback": False}

    class KeyCls:
        def __call__(self):
            called["fallback"] = True
            return FakeKeyType()

    with pytest.raises(core.AiBlackboardError) as exc:
        core._new_key_type(types.SimpleNamespace(), KeyCls(), object())
    assert exc.value.reason == "unsupported_api"
    assert exc.value.context["api"] == "new_object"
    assert exc.value.context["next_action"]["action"] == "update_adapter_plugin"
    assert called["fallback"] is False


def test_f1_new_key_type_fails_closed_when_new_object_returns_none():
    core = _load_core()
    unreal = types.SimpleNamespace(new_object=lambda cls, outer=None: None)
    with pytest.raises(core.AiBlackboardError) as exc:
        core._new_key_type(unreal, FakeKeyTypeClass("BlackboardKeyType_Float"), object())
    assert exc.value.reason == "key_type_construction_unavailable"
    assert exc.value.context["next_action"]["action"] == "update_adapter_plugin"


def test_f1_new_key_type_returns_the_asset_outered_instance():
    core = _load_core()
    asset = object()
    captured = {}

    def new_object(cls, outer=None):
        captured["outer"] = outer
        return FakeKeyType(name="BlackboardKeyType_Float", outer=outer)

    unreal = types.SimpleNamespace(new_object=new_object)
    instance = core._new_key_type(unreal, FakeKeyTypeClass("BlackboardKeyType_Float"), asset)
    assert instance.get_class().get_name() == "BlackboardKeyType_Float"
    assert captured["outer"] is asset


def test_f2_unsupported_api_errors_carry_next_action():
    core = _load_core()
    bare = types.SimpleNamespace()
    calls = (
        lambda: core._method(bare, "missing"),
        lambda: core._symbol(bare, "Missing"),
        lambda: core._load_key_type_class(bare, "BlackboardKeyType_Float"),
    )
    for call in calls:
        with pytest.raises(core.AiBlackboardError) as exc:
            call()
        assert exc.value.reason == "unsupported_api"
        next_action = exc.value.context["next_action"]
        assert next_action["action"] == "update_adapter_plugin"
        assert next_action["retry_tool"] == "unreal_ai__ai_capability_preflight"


def test_f3_probe_returns_json_error_when_preflight_raises():
    import json  # noqa: PLC0415
    from unittest.mock import patch  # noqa: PLC0415

    module = _load_probe("ue_probe_f3")
    fake = FakeUnreal()

    def exploding_version():
        raise RuntimeError("host getter exploded")

    fake.module.SystemLibrary = types.SimpleNamespace(get_engine_version=exploding_version)
    with patch.dict(sys.modules, {"unreal": fake.module}):
        result = module.run_probe()
    assert result["status"] == "error"
    assert "host getter exploded" in result["error"]
    assert result["reopen_verified"] is False
    json.dumps(result)  # must be JSON-serializable, never a raw traceback


def test_f4_probe_reports_reopen_verified_false_on_success():
    import json  # noqa: PLC0415
    from unittest.mock import patch  # noqa: PLC0415

    module = _load_probe("ue_probe_f4")
    fake = FakeUnreal()
    with patch.dict(sys.modules, {"unreal": fake.module}):
        result = module.run_probe()
    assert result["status"] == "ok"
    assert result["readback_verified"] is True
    # A single in-process readback is NOT a disk-persistence verdict.
    assert result["reopen_verified"] is False
    assert "reopen_note" in result
    json.dumps(result)


def test_f4_probe_reports_reopen_verified_false_when_reusing_key():
    from unittest.mock import patch  # noqa: PLC0415

    module = _load_probe("ue_probe_f4_reuse")
    fake = FakeUnreal()
    with patch.dict(sys.modules, {"unreal": fake.module}):
        first = module.run_probe()
        second = module.run_probe()
    assert first["status"] == "ok" and second["status"] == "ok"
    assert second["author"].get("reused_existing_key") is True
    assert second["reopen_verified"] is False
