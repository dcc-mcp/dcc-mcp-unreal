"""Tests for the Houdini -> Unreal typed interchange manifest consumer.

Pure-contract tests (``_interchange_manifest``) run without Unreal. Orchestrator
tests inject fake sibling tools + a mocked ``unreal`` via ``sys.modules`` and
never touch a real Unreal runtime.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSET_SCRIPTS = REPO_ROOT / "src" / "dcc_mcp_unreal" / "skills" / "unreal-assets" / "scripts"
ASSET_SKILL = ASSET_SCRIPTS.parent
TOOLS_YAML = ASSET_SKILL / "tools.yaml"
CONTRACT_PATH = ASSET_SCRIPTS / "_interchange_manifest.py"
ORCHESTRATOR_PATH = ASSET_SCRIPTS / "import_interchange_manifest.py"


def _load_script(name, path, injected=None):
    """Load a skill script by file path, injecting fake siblings if provided."""
    injected = injected or {}
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, injected):
        spec.loader.exec_module(module)
    return module


@pytest.fixture()
def contract():
    """Load the pure contract module (no Unreal dependency)."""
    return _load_script("_interchange_manifest_test", CONTRACT_PATH)


@pytest.fixture()
def sample_manifest():
    return {
        "schema_version": 1,
        "producer": {"dcc": "houdini", "tool": "houdini-copernicus-unreal", "hda": "city_bank.hda"},
        "coordinate_system": {
            "source_unit": "m",
            "source_up_axis": "y",
            "target_unit": "cm",
            "target_up_axis": "z",
        },
        "destination_path": "/Game/Houdini/CityBank",
        "assets": [
            {"source_path": "mesh/city_bank.fbx", "kind": "geometry", "asset_name": "SM_CityBank"},
            {"source_path": "tex/city_bank_basecolor.exr", "kind": "texture", "map_type": "base_color"},
            {"source_path": "tex/city_bank_normal.exr", "kind": "texture", "map_type": "normal"},
            {"source_path": "tex/city_bank_roughness.exr", "kind": "texture", "map_type": "roughness"},
            {"source_path": "tex/city_bank_ao.png", "kind": "texture", "map_type": "ao"},
        ],
        "material": {"name": "M_CityBank"},
    }


# ---------------------------------------------------------------------------
# Pure-contract tests
# ---------------------------------------------------------------------------


class TestValidateManifest:
    def test_full_manifest_normalizes(self, contract, sample_manifest, tmp_path):
        plan = contract.validate_manifest(sample_manifest, str(tmp_path / "bundle.json"))
        assert plan["schema_version"] == 1
        assert plan["destination_path"] == "/Game/Houdini/CityBank"
        assert len(plan["assets"]) == 5
        assert plan["material"]["name"] == "M_CityBank"
        assert plan["producer"]["dcc"] == "houdini"

    def test_geometry_and_texture_kinds(self, contract, sample_manifest):
        plan = contract.validate_manifest(sample_manifest, "/bundle/manifest.json")
        kinds = [a["kind"] for a in plan["assets"]]
        assert kinds == ["geometry", "texture", "texture", "texture", "texture"]

    def test_base_color_is_srgb(self, contract, sample_manifest):
        plan = contract.validate_manifest(sample_manifest, "/bundle/manifest.json")
        basecolor = plan["assets"][1]
        assert basecolor["color_space"] == "srgb"
        assert basecolor["import_kwargs"]["non_color_texture"] is False

    def test_data_maps_are_linear(self, contract, sample_manifest):
        plan = contract.validate_manifest(sample_manifest, "/bundle/manifest.json")
        for asset in plan["assets"][2:]:
            assert asset["color_space"] == "linear"
            assert asset["import_kwargs"]["non_color_texture"] is True

    def test_coordinate_readback_m_to_cm(self, contract, sample_manifest):
        plan = contract.validate_manifest(sample_manifest, "/bundle/manifest.json")
        coords = plan["coordinate_system"]
        assert coords["unit_scale"] == pytest.approx(100.0)
        assert coords["unit_conversion_required"] is True
        assert coords["axis_conversion_required"] is True
        assert coords["applied_by"] == "producer_export"

    def test_no_conversion_when_already_cm_zup(self, contract):
        plan = contract.validate_manifest({"assets": [{"source_path": "/a.fbx"}]}, "/x.json")
        coords = plan["coordinate_system"]
        assert coords["unit_conversion_required"] is False
        assert coords["axis_conversion_required"] is False

    def test_relative_paths_resolve_against_manifest_dir(self, contract, sample_manifest, tmp_path):
        manifest_path = tmp_path / "bundle.json"
        plan = contract.validate_manifest(sample_manifest, str(manifest_path))
        expected = str(tmp_path / "mesh" / "city_bank.fbx")
        assert plan["assets"][0]["source_path"] == expected
        assert Path(plan["assets"][0]["source_path"]).is_absolute()

    def test_asset_name_defaults_to_file_stem(self, contract):
        plan = contract.validate_manifest({"assets": [{"source_path": "/art/SM_Rock.fbx"}]}, "/x.json")
        assert plan["assets"][0]["asset_name"] == "SM_Rock"

    def test_map_type_aliases(self, contract):
        data = {
            "assets": [
                {"source_path": "/t/albedo.png", "map_type": "albedo"},
                {"source_path": "/t/nrm.png", "map_type": "NRM"},
                {"source_path": "/t/metal.png", "map_type": "metalness"},
                {"source_path": "/t/occl.png", "map_type": "occlusion"},
            ]
        }
        plan = contract.validate_manifest(data, "/x.json")
        assert [a["map_type_canonical"] for a in plan["assets"]] == [
            "base_color",
            "normal",
            "metallic",
            "ambient_occlusion",
        ]

    def test_key_aliases(self, contract):
        data = {
            "version": 1,
            "destination": "/Game/Alias",
            "coords": {"unit": "m"},
            "files": [{"file": "/a.png", "map": "basecolor", "colorspace": "srgb"}],
        }
        plan = contract.validate_manifest(data, "/x.json")
        assert plan["destination_path"] == "/Game/Alias"
        assert plan["coordinate_system"]["source_unit"] == "m"
        assert plan["assets"][0]["kind"] == "texture"

    def test_color_space_override(self, contract):
        data = {"assets": [{"source_path": "/t/x.png", "map_type": "normal", "color_space": "srgb"}]}
        plan = contract.validate_manifest(data, "/x.json")
        assert plan["assets"][0]["color_space"] == "srgb"
        assert plan["assets"][0]["import_kwargs"]["non_color_texture"] is False

    def test_non_color_texture_alias(self, contract):
        data = {"assets": [{"source_path": "/t/x.png", "map_type": "normal", "non_color": True}]}
        plan = contract.validate_manifest(data, "/x.json")
        assert plan["assets"][0]["import_kwargs"]["non_color_texture"] is True

    def test_source_gamut(self, contract):
        data = {"assets": [{"source_path": "/t/x.png", "map_type": "base_color", "source_gamut": "srgb"}]}
        plan = contract.validate_manifest(data, "/x.json")
        assert plan["assets"][0]["import_kwargs"]["source_color_space"] == "srgb"

    def test_unknown_map_type_is_linear_with_warning(self, contract):
        data = {"assets": [{"source_path": "/t/x.png", "map_type": "novel_channel"}]}
        plan = contract.validate_manifest(data, "/x.json")
        assert plan["assets"][0]["color_space"] == "linear"
        assert any("novel_channel" in w for w in plan["warnings"])

    def test_alembic_geometry_cache_flag(self, contract):
        data = {"assets": [{"source_path": "/g/x.abc", "kind": "geometry", "geometry_cache": True}]}
        plan = contract.validate_manifest(data, "/x.json")
        assert plan["assets"][0]["import_kwargs"]["import_as_geometry_cache"] is True

    def test_material_texture_kwargs(self, contract, sample_manifest):
        plan = contract.validate_manifest(sample_manifest, "/x.json")
        object_paths = {
            plan["assets"][1]["entry_key"]: "/Game/CityBank/city_bank_basecolor",
            plan["assets"][2]["entry_key"]: "/Game/CityBank/city_bank_normal",
            plan["assets"][3]["entry_key"]: "/Game/CityBank/city_bank_roughness",
            plan["assets"][4]["entry_key"]: "/Game/CityBank/city_bank_ao",
        }
        kwargs = contract.material_texture_kwargs(plan["assets"], object_paths)
        assert kwargs["texture_path"] == "/Game/CityBank/city_bank_basecolor"
        assert kwargs["normal_texture_path"] == "/Game/CityBank/city_bank_normal"
        assert kwargs["roughness_texture_path"] == "/Game/CityBank/city_bank_roughness"
        assert kwargs["ambient_occlusion_texture_path"] == "/Game/CityBank/city_bank_ao"

    def test_entry_key_is_unique_per_asset(self, contract, sample_manifest):
        plan = contract.validate_manifest(sample_manifest, "/x.json")
        keys = [a["entry_key"] for a in plan["assets"]]
        assert keys == sorted(set(keys))
        assert len(set(keys)) == len(plan["assets"])

    def test_material_kwargs_no_crosswiring_for_shared_source(self, contract):
        """CR-2: two texture entries sharing one source_path but distinct entry
        keys must map to their own object paths, never overwrite each other."""
        assets = [
            {"kind": "texture", "source_path": "/t/x.png", "entry_key": 0, "map_type_canonical": "base_color"},
            {"kind": "texture", "source_path": "/t/x.png", "entry_key": 1, "map_type_canonical": "normal"},
        ]
        object_paths = {0: "/Game/basecolor", 1: "/Game/normal"}
        kwargs = contract.material_texture_kwargs(assets, object_paths)
        assert kwargs["texture_path"] == "/Game/basecolor"
        assert kwargs["normal_texture_path"] == "/Game/normal"

    def test_duplicate_wired_roles_detects_repeats(self, contract):
        # CR-9: two imported textures for the same wired role are ambiguous.
        assets = [
            {"kind": "texture", "source_path": "/a.png", "entry_key": 0, "map_type_canonical": "base_color"},
            {"kind": "texture", "source_path": "/b.png", "entry_key": 1, "map_type_canonical": "base_color"},
            {"kind": "texture", "source_path": "/n.png", "entry_key": 2, "map_type_canonical": "normal"},
        ]
        object_paths = {0: "/Game/a", 1: "/Game/b", 2: "/Game/n"}
        assert contract.duplicate_wired_roles(assets, object_paths) == ["base_color"]

    def test_duplicate_wired_roles_ignores_unimported_and_unwired(self, contract):
        # CR-9: a role only counts when it was imported; unwired roles are ignored.
        assets = [
            {"kind": "texture", "source_path": "/a.png", "entry_key": 0, "map_type_canonical": "base_color"},
            {"kind": "texture", "source_path": "/b.png", "entry_key": 1, "map_type_canonical": "base_color"},
            {"kind": "texture", "source_path": "/d.png", "entry_key": 2, "map_type_canonical": "data"},
            {"kind": "texture", "source_path": "/e.png", "entry_key": 3, "map_type_canonical": "data"},
        ]
        object_paths = {0: "/Game/a"}  # only one base_color imported, no data imported
        assert contract.duplicate_wired_roles(assets, object_paths) == []


class TestManifestErrors:
    @pytest.mark.parametrize(
        "data",
        [
            {"schema_version": 99, "assets": [{"source_path": "/a.fbx"}]},
            {"assets": []},
            {"assets": [{"kind": "geometry"}]},  # missing source_path
            {"assets": [{"source_path": "/a.png", "map_type": "normal", "color_space": "bogus"}]},
            {"assets": [{"source_path": "/a.png", "map_type": "normal", "source_gamut": "bogus"}]},
            {"coordinate_system": {"source_unit": "parsec"}, "assets": [{"source_path": "/a.fbx"}]},
            {"material": {"name": ""}, "assets": [{"source_path": "/a.fbx"}]},
            # CR-3: source_gamut on a linear data map is rejected.
            {"assets": [{"source_path": "/a.png", "map_type": "normal", "source_gamut": "srgb"}]},
            # CR-6: bool / float / string schema_version must not coerce to 1.
            {"schema_version": True, "assets": [{"source_path": "/a.fbx"}]},
            {"schema_version": 1.5, "assets": [{"source_path": "/a.fbx"}]},
            {"schema_version": "1", "assets": [{"source_path": "/a.fbx"}]},
            # CR-5: falsy non-object coordinate_system values are rejected.
            {"coordinate_system": False, "assets": [{"source_path": "/a.fbx"}]},
            {"coordinate_system": [], "assets": [{"source_path": "/a.fbx"}]},
            {"coordinate_system": 0, "assets": [{"source_path": "/a.fbx"}]},
            # CR-2: duplicate source_path is rejected.
            {
                "assets": [
                    {"source_path": "/t/x.png", "map_type": "base_color"},
                    {"source_path": "/t/x.png", "map_type": "normal"},
                ]
            },
        ],
    )
    def test_invalid_manifest_raises(self, contract, data):
        with pytest.raises(contract.ManifestError):
            contract.validate_manifest(data, "/x.json")

    def test_source_gamut_allowed_on_srgb_map(self, contract):
        # CR-3: the same gamut is fine on a colour (srgb) map.
        data = {"assets": [{"source_path": "/t/x.png", "map_type": "base_color", "source_gamut": "srgb"}]}
        plan = contract.validate_manifest(data, "/x.json")
        assert plan["assets"][0]["import_kwargs"]["source_color_space"] == "srgb"
        assert plan["assets"][0]["import_kwargs"]["non_color_texture"] is False

    def test_null_coordinate_system_uses_defaults(self, contract):
        # CR-5: None / missing still fall back to defaults (not rejected).
        plan = contract.validate_manifest({"coordinate_system": None, "assets": [{"source_path": "/a.fbx"}]}, "/x.json")
        assert plan["coordinate_system"]["source_unit"] == "cm"

    def test_duplicate_source_path_resolves_after_normalization(self, contract, tmp_path):
        # CR-2: two spellings that normalize to the same file are still duplicates.
        data = {
            "assets": [
                {"source_path": "tex/x.png", "asset_name": "A", "map_type": "base_color"},
                {"source_path": "tex/./x.png", "asset_name": "B", "map_type": "normal"},
            ]
        }
        with pytest.raises(contract.ManifestError):
            contract.validate_manifest(data, str(tmp_path / "bundle.json"))

    def test_duplicate_absolute_source_path_is_rejected(self, contract):
        # CR-8: absolute paths must also be normalized before the duplicate
        # check. /t/x.png and /t/./x.png resolve to the same file.
        data = {
            "assets": [
                {"source_path": "/t/x.png", "map_type": "base_color"},
                {"source_path": "/t/./x.png", "map_type": "normal"},
            ]
        }
        with pytest.raises(contract.ManifestError):
            contract.validate_manifest(data, "/x.json")

    def test_load_manifest_missing_file(self, contract, tmp_path):
        with pytest.raises(contract.ManifestError):
            contract.load_manifest(str(tmp_path / "nope.json"))

    def test_load_manifest_bad_json(self, contract, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        with pytest.raises(contract.ManifestError):
            contract.load_manifest(str(p))

    def test_load_manifest_non_object_root(self, contract, tmp_path):
        p = tmp_path / "list.json"
        p.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(contract.ManifestError):
            contract.load_manifest(str(p))


# ---------------------------------------------------------------------------
# Orchestrator tests (fake sibling tools + mocked unreal)
#
# _sibling_tool() resolves siblings at CALL time via importlib, so the fakes
# must stay injected into sys.modules for the whole call, not just module load.
# ---------------------------------------------------------------------------


@contextmanager
def _orchestrator_env(contract, fail_on=None, inject_unreal=True, material_fails=False):
    """Load the orchestrator with fake sibling tools kept in sys.modules."""
    calls = {"import_asset": [], "create_texture_material": []}

    def fake_import_asset(**kwargs):
        calls["import_asset"].append(kwargs)
        name = kwargs.get("asset_name", "asset")
        if fail_on and name == fail_on:
            return {"success": False, "message": "boom", "error": "import_failed", "context": {}}
        return {
            "success": True,
            "message": "ok",
            "error": None,
            "context": {"object_path": "/Game/Imports/{}.{}".format(name, name)},
        }

    def fake_create_material(**kwargs):
        calls["create_texture_material"].append(kwargs)
        if material_fails:
            return {"success": False, "message": "material boom", "error": "material_failed", "context": {}}
        return {"success": True, "message": "material ok", "error": None, "context": {"object_path": "/Game/M"}}

    mod_import = types.ModuleType("import_asset")
    mod_import.import_asset = fake_import_asset
    mod_material = types.ModuleType("create_texture_material")
    mod_material.create_texture_material = fake_create_material
    injected = {
        "import_asset": mod_import,
        "create_texture_material": mod_material,
        "_interchange_manifest": contract,
    }
    if inject_unreal:
        injected["unreal"] = types.ModuleType("unreal")

    with patch.dict(sys.modules, injected):
        module = _load_script("import_interchange_manifest_test", ORCHESTRATOR_PATH)
        yield module, calls


def _write_manifest(tmp_path, data):
    manifest_file = tmp_path / "bundle.json"
    manifest_file.write_text(json.dumps(data), encoding="utf-8")
    return str(manifest_file)


def test_validate_only_returns_plan_without_importing(contract, sample_manifest, tmp_path):
    path = _write_manifest(tmp_path, sample_manifest)
    with _orchestrator_env(contract) as (module, calls):
        result = module.import_interchange_manifest(manifest_path=path, validate_only=True)
    assert result["success"] is True
    assert result["context"]["validate_only"] is True
    assert len(result["context"]["assets"]) == 5
    assert all(a["status"] == "planned" for a in result["context"]["assets"])
    assert calls["import_asset"] == []  # no Unreal work in validate_only


def test_validate_only_surfaces_color_space(contract, sample_manifest, tmp_path):
    path = _write_manifest(tmp_path, sample_manifest)
    with _orchestrator_env(contract) as (module, _):
        result = module.import_interchange_manifest(manifest_path=path, validate_only=True)
    assets = result["context"]["assets"]
    by_map = {a.get("map_type"): a.get("color_space") for a in assets if a["kind"] == "texture"}
    assert by_map["base_color"] == "srgb"
    assert by_map["normal"] == "linear"
    assert by_map["roughness"] == "linear"
    assert by_map["ambient_occlusion"] == "linear"


def test_full_import_delegates_and_builds_material(contract, sample_manifest, tmp_path):
    path = _write_manifest(tmp_path, sample_manifest)
    with _orchestrator_env(contract) as (module, calls):
        result = module.import_interchange_manifest(manifest_path=path)
    assert result["success"] is True
    assert result["context"]["imports_succeeded"] == 5
    assert result["context"]["imports_failed"] == 0
    assert len(calls["import_asset"]) == 5
    import_kwargs = {c["asset_name"]: c for c in calls["import_asset"]}
    assert import_kwargs["city_bank_basecolor"]["non_color_texture"] is False
    assert import_kwargs["city_bank_normal"]["non_color_texture"] is True
    assert len(calls["create_texture_material"]) == 1
    mat_kwargs = calls["create_texture_material"][0]
    assert mat_kwargs["material_name"] == "M_CityBank"
    assert "texture_path" in mat_kwargs
    assert "normal_texture_path" in mat_kwargs


def test_build_material_false_skips_material(contract, sample_manifest, tmp_path):
    path = _write_manifest(tmp_path, sample_manifest)
    with _orchestrator_env(contract) as (module, calls):
        module.import_interchange_manifest(manifest_path=path, build_material=False)
    assert calls["create_texture_material"] == []


def _duplicate_role_manifest():
    # Two distinct files both declare base_color: the material path must
    # surface the ambiguity; import-only must stay valid.
    return {
        "assets": [
            {"source_path": "/t/base_a.png", "map_type": "base_color"},
            {"source_path": "/t/base_b.png", "map_type": "base_color"},
            {"source_path": "/t/n.png", "map_type": "normal"},
        ],
        "material": {"name": "M_Dup"},
    }


def test_duplicate_wired_roles_warns_when_building_material(contract, tmp_path):
    """CR-9: build_material path makes the ambiguous role explicit."""
    path = _write_manifest(tmp_path, _duplicate_role_manifest())
    with _orchestrator_env(contract) as (module, _):
        result = module.import_interchange_manifest(manifest_path=path, build_material=True)
    assert result["success"] is True  # ambiguity is surfaced, not a hard failure
    assert any("base_color" in w and "multiple" in w for w in result["context"]["warnings"])


def test_duplicate_wired_roles_silent_for_import_only(contract, tmp_path):
    """CR-9: import-only / build_material=false manifests remain valid and quiet."""
    path = _write_manifest(tmp_path, _duplicate_role_manifest())
    with _orchestrator_env(contract) as (module, calls):
        result = module.import_interchange_manifest(manifest_path=path, build_material=False)
    assert result["success"] is True
    assert calls["create_texture_material"] == []
    assert not any("multiple imported textures" in w for w in result["context"]["warnings"])


def test_missing_manifest_path_errors(contract):
    with _orchestrator_env(contract) as (module, _):
        result = module.import_interchange_manifest(manifest_path="")
    assert result["success"] is False
    assert result["error"] == "missing_manifest_path"


def test_invalid_manifest_errors(contract, tmp_path):
    path = _write_manifest(tmp_path, {"schema_version": 99, "assets": [{"source_path": "/a.fbx"}]})
    with _orchestrator_env(contract) as (module, calls):
        result = module.import_interchange_manifest(manifest_path=path)
    assert result["success"] is False
    assert result["error"] == "manifest_validation_failed"
    assert calls["import_asset"] == []


def test_partial_import_failure_is_reported(contract, sample_manifest, tmp_path):
    path = _write_manifest(tmp_path, sample_manifest)
    with _orchestrator_env(contract, fail_on="city_bank_normal") as (module, _):
        result = module.import_interchange_manifest(manifest_path=path)
    assert result["context"]["imports_succeeded"] == 4
    assert result["context"]["imports_failed"] == 1
    assert result["postcondition"]["verified"] is False
    failed = [a for a in result["context"]["assets"] if a["status"] == "failed"]
    assert len(failed) == 1
    assert any("boom" in w for w in result["context"]["warnings"])


def test_material_creation_failure_is_propagated(contract, sample_manifest, tmp_path):
    """CR-1: a failed PBR material must not be reported as a verified success."""
    path = _write_manifest(tmp_path, sample_manifest)
    with _orchestrator_env(contract, material_fails=True) as (module, calls):
        result = module.import_interchange_manifest(manifest_path=path)
    assert result["success"] is False
    assert result["error"] == "material_creation_failed"
    assert result["context"]["imports_succeeded"] == 5  # assets did import
    assert result["context"]["material"]["success"] is False
    assert any("material" in w.lower() for w in result["context"]["warnings"])
    # A failed material build must never carry a verified=True postcondition.
    assert result.get("postcondition", {}).get("verified") is not True
    assert len(calls["create_texture_material"]) == 1


def test_material_creation_success_is_verified(contract, sample_manifest, tmp_path):
    """CR-1 companion: a successful material build stays a verified success."""
    path = _write_manifest(tmp_path, sample_manifest)
    with _orchestrator_env(contract) as (module, _):
        result = module.import_interchange_manifest(manifest_path=path)
    assert result["success"] is True
    assert result["postcondition"]["verified"] is True


def test_validate_only_needs_no_unreal(contract, sample_manifest, tmp_path):
    """validate_only path must work even with no unreal importable at all."""
    path = _write_manifest(tmp_path, sample_manifest)
    with _orchestrator_env(contract, inject_unreal=False) as (module, _):
        result = module.import_interchange_manifest(manifest_path=path, validate_only=True)
    assert result["success"] is True


# ---------------------------------------------------------------------------
# Contract / tooling registration tests
# ---------------------------------------------------------------------------


def test_tool_declared_in_tools_yaml():
    data = yaml.safe_load(TOOLS_YAML.read_text(encoding="utf-8"))
    by_name = {t["name"]: t for t in data["tools"]}
    assert "import_interchange_manifest" in by_name
    tool = by_name["import_interchange_manifest"]
    for key in (
        "name",
        "description",
        "source_file",
        "execution",
        "affinity",
        "input_schema",
        "read_only",
        "destructive",
        "idempotent",
    ):
        assert key in tool
    assert (ASSET_SKILL / tool["source_file"]).is_file()
    assert tool["input_schema"]["required"] == ["manifest_path"]


def test_tool_is_marked_destructive():
    """CR-4: material.replace_existing defaults to true, so the tool can mutate
    an existing material's graph and must be flagged destructive for clients."""
    data = yaml.safe_load(TOOLS_YAML.read_text(encoding="utf-8"))
    tool = {t["name"]: t for t in data["tools"]}["import_interchange_manifest"]
    assert tool["destructive"] is True


def test_reference_doc_exists_and_linked():
    ref = ASSET_SKILL / "references" / "INTERCHANGE_MANIFEST.md"
    assert ref.is_file()
    skill_md = (ASSET_SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "references/INTERCHANGE_MANIFEST.md" in skill_md
    assert "import_interchange_manifest" in skill_md
    # CR-7: the reference must not claim map_type is required for textures;
    # it documents the "missing => linear data, excluded from material" behaviour.
    assert "Missing on a texture" in ref.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", [CONTRACT_PATH, ORCHESTRATOR_PATH])
def test_scripts_are_python37_grammar_clean(path):
    """Python 3.7 red line: new code must parse with 3.7 grammar."""
    source = path.read_text(encoding="utf-8")
    ast.parse(source, filename=str(path), feature_version=(3, 7))
    tree = ast.parse(source, filename=str(path))
    # no top-level `import unreal` (lazy import convention)
    for node in tree.body:
        if isinstance(node, ast.Import):
            assert all(alias.name != "unreal" for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module != "unreal" and not node.module.startswith("unreal.")
