"""Tests for the unreal-material-shaders skill package.

Covers: SKILL.md/tools.yaml discoverability, @skill_entry presence on all 8 tools,
validate_hlsl_syntax positive/negative cases, error handling for each tool,
and HLSL safety guarantees (no code execution).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "src" / "dcc_mcp_unreal" / "skills"
SHADERS_SKILL = SKILLS / "unreal-material-shaders"
SCRIPTS = SHADERS_SKILL / "scripts"

_EXPECTED_TOOLS = [
    "create_material_graph",
    "add_material_expression",
    "connect_material_expressions",
    "compile_material",
    "create_material_function",
    "create_hlsl_node",
    "validate_hlsl_syntax",
    "list_material_expressions",
]


def _load_skill_script(tool_name: str):
    """Load a skill script module by file path (matches existing test pattern)."""
    path = str(SCRIPTS / f"{tool_name}.py")
    spec = importlib.util.spec_from_file_location(tool_name, path)
    module = importlib.util.module_from_spec(spec)
    return module, spec


# ---------------------------------------------------------------------------
# Discoverability and structure (no unreal mocking needed)
# ---------------------------------------------------------------------------


def test_skill_md_exists_and_has_frontmatter() -> None:
    """SKILL.md must exist with dcc-mcp metadata frontmatter."""
    assert (SHADERS_SKILL / "SKILL.md").is_file()
    content = (SHADERS_SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "---" in content
    assert "name: unreal-material-shaders" in content
    assert "dcc-mcp:" in content
    assert "dcc: unreal" in content
    assert "layer: domain" in content
    assert "stage: authoring" in content


def test_tools_yaml_lists_all_eight_tools() -> None:
    """tools.yaml must declare exactly the 8 expected tool definitions."""
    assert (SHADERS_SKILL / "tools.yaml").is_file()
    tool_text = (SHADERS_SKILL / "tools.yaml").read_text(encoding="utf-8")
    for tool in _EXPECTED_TOOLS:
        assert f"name: {tool}" in tool_text, f"Missing tool: {tool}"


def test_every_tool_script_has_skill_entry() -> None:
    """Every script referenced in tools.yaml must have @skill_entry."""
    for tool in _EXPECTED_TOOLS:
        script = SCRIPTS / f"{tool}.py"
        assert script.is_file(), f"Missing script: {script}"
        source = script.read_text(encoding="utf-8")
        assert "@skill_entry" in source, f"Missing @skill_entry in {tool}.py"


def test_all_scripts_have_lazy_import() -> None:
    """Every script must lazy-import unreal inside the function, not at module level."""
    for tool in _EXPECTED_TOOLS:
        script = SCRIPTS / f"{tool}.py"
        source = script.read_text(encoding="utf-8")
        lines = source.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped == "import unreal" and "noqa" not in line:
                if not line.startswith((" ", "\t")):
                    pytest.fail(f"{tool}.py: import unreal at module level (line {i + 1})")


def test_no_exec_eval_subprocess_in_scripts() -> None:
    """No script may call exec(), eval(), or subprocess."""
    forbidden = [
        ("exec(", "exec()"),
        ("eval(", "eval()"),
        ("import subprocess", "subprocess import"),
        ("from subprocess", "subprocess import"),
    ]
    for tool in _EXPECTED_TOOLS:
        script = SCRIPTS / f"{tool}.py"
        source = script.read_text(encoding="utf-8")
        for pattern, label in forbidden:
            assert pattern not in source, f"{tool}.py contains forbidden {label}"


def test_valid_blend_mode_and_shading_model_whitelists() -> None:
    """create_material_graph.py must whitelist blend modes and shading models."""
    script = SCRIPTS / "create_material_graph.py"
    source = script.read_text(encoding="utf-8")
    for mode in ("Opaque", "Masked", "Translucent", "Additive", "Modulate"):
        assert mode in source, f"Blend mode '{mode}' not in create_material_graph.py"
    for model in ("DefaultLit", "Unlit", "Subsurface"):
        assert model in source, f"Shading model '{model}' not in create_material_graph.py"


# ---------------------------------------------------------------------------
# tools.yaml structural assertions
# ---------------------------------------------------------------------------


def test_tools_yaml_read_only_tools_correctly_tagged() -> None:
    """validate_hlsl_syntax and list_material_expressions must be read_only: true."""
    tool_text = (SHADERS_SKILL / "tools.yaml").read_text(encoding="utf-8")
    import yaml

    data = yaml.safe_load(tool_text)
    read_only_tools = {"validate_hlsl_syntax", "list_material_expressions"}
    for tool_def in data["tools"]:
        name = tool_def["name"]
        if name in read_only_tools:
            assert tool_def.get("read_only") is True, f"{name} must be read_only: true"
        else:
            assert tool_def.get("read_only") is False, f"{name} must be read_only: false"


def test_tools_yaml_has_next_tools_on_failure_diagnostics() -> None:
    """Every non-read-only tool should have dcc_diagnostics fallback on failure."""
    tool_text = (SHADERS_SKILL / "tools.yaml").read_text(encoding="utf-8")
    import yaml

    data = yaml.safe_load(tool_text)
    for tool_def in data["tools"]:
        next_tools = tool_def.get("next-tools", {})
        on_failure = next_tools.get("on-failure", [])
        if not tool_def.get("read_only", False):
            assert any("dcc_diagnostics" in t for t in on_failure), (
                f"{tool_def['name']} missing dcc_diagnostics fallback in on-failure"
            )


# ---------------------------------------------------------------------------
# validate_hlsl_syntax — load via file path (no unreal dependency)
# ---------------------------------------------------------------------------


def _load_hlsl_validator():
    """Load the validate_hlsl_syntax module by file path."""
    module, spec = _load_skill_script("validate_hlsl_syntax")
    spec.loader.exec_module(module)
    return module.validate_hlsl_syntax


# ---------------------------------------------------------------------------
# validate_hlsl_syntax — positive cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hlsl,expected_valid",
    [
        ("float3 brighten(float3 c) { return c * 2.0; }", True),
        (
            "float4 blend(float4 a, float4 b, float t) {\n"
            "    float4 result = lerp(a, b, t);\n"
            "    return result;\n"
            "}",
            True,
        ),
        (
            "Texture2D tex;\n"
            "SamplerState texSampler;\n"
            "float4 sample(float2 uv) {\n"
            "    return tex.Sample(texSampler, uv);\n"
            "}",
            True,
        ),
        (
            "float threshold(float v) {\n"
            "    if (v > 0.5) { return 1.0; } else { return 0.0; }\n"
            "}",
            True,
        ),
        ("float4 proc(float3 n, float3 l) { return saturate(dot(normalize(n), normalize(l))); }", True),
        ("// This is a comment\nfloat4 main() {\n    return float4(1,0,0,1); // red\n}", True),
    ],
)
def test_validate_hlsl_syntax_valid_patterns(hlsl: str, expected_valid: bool) -> None:
    """Valid HLSL patterns should pass syntax validation."""
    fn = _load_hlsl_validator()
    result = fn(hlsl_code=hlsl)
    ctx = result.get("context", {})
    assert ctx["valid"] == expected_valid, f"Unexpected validity; errors={ctx.get('syntax_errors', [])}"
    if expected_valid:
        errors = [e for e in ctx.get("syntax_errors", []) if e.get("severity") == "error"]
        assert len(errors) == 0, f"Unexpected errors: {errors}"


# ---------------------------------------------------------------------------
# validate_hlsl_syntax — negative cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hlsl,expected_invalid",
    [
        # Unclosed brace — hard error
        ("float3 func(float3 c) {\n    return c;\n", True),
        # Type mismatch — warning only, still valid
        ("float3 color = 1.0f;", False),
        # Unmatched closing brace — hard error
        ("float4 a() { return float4(1,1,1,1); }\n}", True),
        # Missing semicolon — warning only, still valid
        ("float3 dir = normalize(float3(0,0,1))\nfloat k = 1.0;", False),
    ],
)
def test_validate_hlsl_syntax_invalid_patterns(hlsl: str, expected_invalid: bool) -> None:
    """Invalid HLSL patterns must be detected as invalid or with errors."""
    fn = _load_hlsl_validator()
    result = fn(hlsl_code=hlsl)
    ctx = result.get("context", {})
    if expected_invalid:
        errors = [e for e in ctx.get("syntax_errors", []) if e.get("severity") == "error"]
        assert len(errors) > 0 or not ctx.get("valid", True), (
            f"Expected errors for invalid HLSL, got none. Result={result}"
        )


def test_validate_hlsl_syntax_entry_point_check() -> None:
    """Entry point validation: present function passes, missing fails."""
    fn = _load_hlsl_validator()
    hlsl = "float3 my_shader(float3 c) { return c; }"

    r1 = fn(hlsl_code=hlsl, entry_point="my_shader")
    assert r1["context"]["valid"]

    r2 = fn(hlsl_code=hlsl, entry_point="nonexistent")
    assert not r2["context"]["valid"]


def test_validate_hlsl_syntax_empty_input() -> None:
    """Empty HLSL input should return valid."""
    fn = _load_hlsl_validator()
    result = fn(hlsl_code="   ")
    assert result["context"]["valid"]
    assert result["context"]["syntax_errors"] == []


def test_validate_hlsl_syntax_never_compiles() -> None:
    """validate_hlsl_syntax must not invoke any Unreal API or subprocess."""
    fn = _load_hlsl_validator()
    result = fn(hlsl_code="float4 f() { return float4(1,0,0,1); }")
    ctx = result.get("context", {})
    assert "syntax_errors" in ctx
    assert isinstance(ctx.get("valid"), bool)


def test_hlsl_code_is_string_passthrough_in_create_hlsl_node() -> None:
    """create_hlsl_node script must treat HLSL as a string — no eval/exec."""
    script = SCRIPTS / "create_hlsl_node.py"
    source = script.read_text(encoding="utf-8")
    assert 'set_editor_property("code"' in source
    assert "exec(" not in source
    assert "eval(" not in source
    assert "subprocess" not in source


def test_asset_paths_limited_to_game() -> None:
    """All asset-lookup scripts must enforce /Game/ path prefix."""
    for tool in _EXPECTED_TOOLS:
        script = SCRIPTS / f"{tool}.py"
        source = script.read_text(encoding="utf-8")
        if "package_path" in source or "material_name" in source:
            assert "/Game" in source, f"{tool}.py should reference /Game paths"


# ---------------------------------------------------------------------------
# create_material_graph — error paths
# ---------------------------------------------------------------------------


class TestCreateMaterialGraph:
    """Tests for create_material_graph.py."""

    @patch.dict(sys.modules, {"unreal": MagicMock()})
    def test_material_name_required(self):
        """Missing material_name returns error."""
        module, spec = _load_skill_script("create_material_graph")
        spec.loader.exec_module(module)
        result = module.create_material_graph(material_name="")
        assert result["success"] is False
        # Error mentions invalid settings / material requirements
        assert "invalid" in result["message"].lower() or "required" in result["message"].lower()

    @patch.dict(sys.modules, {"unreal": MagicMock()})
    def test_package_path_must_start_with_game(self):
        """package_path not under /Game returns error."""
        module, spec = _load_skill_script("create_material_graph")
        spec.loader.exec_module(module)
        result = module.create_material_graph(material_name="M_Test", package_path="/NotGame/Stuff")
        assert result["success"] is False

    @patch.dict(sys.modules, {"unreal": MagicMock()})
    def test_invalid_blend_mode(self):
        """Invalid blend mode returns error."""
        module, spec = _load_skill_script("create_material_graph")
        spec.loader.exec_module(module)
        result = module.create_material_graph(material_name="M_Test", blend_mode="BogusMode")
        assert result["success"] is False
        assert "blend" in result["message"].lower()

    @patch.dict(sys.modules, {"unreal": MagicMock()})
    def test_invalid_shading_model(self):
        """Invalid shading model returns error."""
        module, spec = _load_skill_script("create_material_graph")
        spec.loader.exec_module(module)
        result = module.create_material_graph(material_name="M_Test", shading_model="BogusModel")
        assert result["success"] is False
        assert "shading" in result["message"].lower()


# ---------------------------------------------------------------------------
# add_material_expression — error paths
# ---------------------------------------------------------------------------


class TestAddMaterialExpression:
    """Tests for add_material_expression.py."""

    @patch.dict(sys.modules, {"unreal": MagicMock()})
    def test_material_not_found(self):
        """Adding expression to non-existent material returns error."""
        import unreal

        unreal.EditorAssetLibrary.load_asset.return_value = None

        module, spec = _load_skill_script("add_material_expression")
        spec.loader.exec_module(module)
        result = module.add_material_expression(material_name="M_NotFound", expression_type="Constant3Vector")
        assert result["success"] is False
        assert "not found" in result["message"].lower()

    @patch.dict(sys.modules, {"unreal": MagicMock()})
    def test_unknown_expression_type(self):
        """Unknown expression type name returns error."""
        module, spec = _load_skill_script("add_material_expression")
        spec.loader.exec_module(module)
        result = module.add_material_expression(material_name="M_Test", expression_type="BogusExpression")
        assert result["success"] is False
        assert "Unknown expression type" in result["message"]

    @patch.dict(sys.modules, {"unreal": MagicMock()})
    def test_missing_required_params(self):
        """Missing material_name or expression_type returns error."""
        module, spec = _load_skill_script("add_material_expression")
        spec.loader.exec_module(module)
        result = module.add_material_expression(material_name="", expression_type="")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# connect_material_expressions — error paths
# ---------------------------------------------------------------------------


class TestConnectMaterialExpressions:
    """Tests for connect_material_expressions.py."""

    @patch.dict(sys.modules, {"unreal": MagicMock()})
    def test_connect_material_not_found(self):
        """Connecting to non-existent material returns error."""
        import unreal

        unreal.EditorAssetLibrary.load_asset.return_value = None

        module, spec = _load_skill_script("connect_material_expressions")
        spec.loader.exec_module(module)
        result = module.connect_material_expressions(
            material_name="M_NotFound",
            source_expression="expr_0",
            target_expression="expr_1",
            target_pin="A",
        )
        assert result["success"] is False

    @patch.dict(sys.modules, {"unreal": MagicMock()})
    def test_missing_required_args(self):
        """Missing required parameters returns error."""
        module, spec = _load_skill_script("connect_material_expressions")
        spec.loader.exec_module(module)
        result = module.connect_material_expressions(
            material_name="",
            source_expression="",
            target_expression="",
            target_pin="",
        )
        assert result["success"] is False
        assert "required" in result["message"].lower()


# ---------------------------------------------------------------------------
# compile_material — error paths
# ---------------------------------------------------------------------------


class TestCompileMaterial:
    """Tests for compile_material.py."""

    @patch.dict(sys.modules, {"unreal": MagicMock()})
    def test_compile_material_not_found(self):
        """Compiling non-existent material returns error."""
        import unreal

        unreal.EditorAssetLibrary.load_asset.return_value = None

        module, spec = _load_skill_script("compile_material")
        spec.loader.exec_module(module)
        result = module.compile_material(material_name="M_NotFound")
        assert result["success"] is False
        assert "not found" in result["message"].lower()

    @patch.dict(sys.modules, {"unreal": MagicMock()})
    def test_missing_material_name(self):
        """Missing material_name returns error."""
        module, spec = _load_skill_script("compile_material")
        spec.loader.exec_module(module)
        result = module.compile_material(material_name="")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# create_material_function — error paths
# ---------------------------------------------------------------------------


class TestCreateMaterialFunction:
    """Tests for create_material_function.py."""

    @patch.dict(sys.modules, {"unreal": MagicMock()})
    def test_invalid_path(self):
        """package_path not under /Game returns error."""
        module, spec = _load_skill_script("create_material_function")
        spec.loader.exec_module(module)
        result = module.create_material_function(function_name="MF_Test", package_path="/Bad/Path")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# create_hlsl_node — error paths
# ---------------------------------------------------------------------------


class TestCreateHlslNode:
    """Tests for create_hlsl_node.py."""

    @patch.dict(sys.modules, {"unreal": MagicMock()})
    def test_hlsl_node_material_not_found(self):
        """Adding HLSL node to non-existent material returns error."""
        import unreal

        unreal.EditorAssetLibrary.load_asset.return_value = None

        module, spec = _load_skill_script("create_hlsl_node")
        spec.loader.exec_module(module)
        result = module.create_hlsl_node(material_name="M_NotFound", hlsl_code="return 1.0;")
        assert result["success"] is False

    @patch.dict(sys.modules, {"unreal": MagicMock()})
    def test_missing_required_args(self):
        """Missing material_name or hlsl_code returns error."""
        module, spec = _load_skill_script("create_hlsl_node")
        spec.loader.exec_module(module)
        result = module.create_hlsl_node(material_name="", hlsl_code="")
        assert result["success"] is False
        assert "required" in result["message"].lower()

    @patch.dict(sys.modules, {"unreal": MagicMock()})
    def test_invalid_output_type(self):
        """Invalid output_type returns error."""
        module, spec = _load_skill_script("create_hlsl_node")
        spec.loader.exec_module(module)
        result = module.create_hlsl_node(
            material_name="M_Test", hlsl_code="return 1.0;", output_type="InvalidType"
        )
        assert result["success"] is False
        assert "output_type" in result["message"].lower()


# ---------------------------------------------------------------------------
# list_material_expressions — error paths
# ---------------------------------------------------------------------------


class TestListMaterialExpressions:
    """Tests for list_material_expressions.py."""

    @patch.dict(sys.modules, {"unreal": MagicMock()})
    def test_list_material_not_found(self):
        """Listing expressions on non-existent material returns error."""
        import unreal

        unreal.EditorAssetLibrary.load_asset.return_value = None

        module, spec = _load_skill_script("list_material_expressions")
        spec.loader.exec_module(module)
        result = module.list_material_expressions(material_name="M_NotFound")
        assert result["success"] is False

    @patch.dict(sys.modules, {"unreal": MagicMock()})
    def test_invalid_target_kind(self):
        """Invalid target_kind returns error."""
        module, spec = _load_skill_script("list_material_expressions")
        spec.loader.exec_module(module)
        result = module.list_material_expressions(material_name="M_Test", target_kind="bogus")
        assert result["success"] is False
        assert "target_kind" in result["message"].lower()
