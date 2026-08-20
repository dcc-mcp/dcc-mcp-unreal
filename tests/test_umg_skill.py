"""Tests for the unreal-umg skill package.

Mock-based pytest tests that verify each tool's function signature,
input validation, and success/error return paths. These tests do NOT
require Unreal Editor — the ``unreal`` module is mocked.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

_SKILL_ROOT = Path(__file__).resolve().parents[1] / "src" / "dcc_mcp_unreal" / "skills" / "unreal-umg"
_SCRIPTS_DIR = _SKILL_ROOT / "scripts"


def _load_script(module_name: str) -> Any:
    """Load a skill script by path.

    The scripts live outside any importable package, and the repository already
    has a top-level ``scripts/`` directory, so importing them by name would be
    ambiguous. Load each one from its explicit file path instead, freshly per
    call so the currently patched ``unreal`` mock is the one it sees.
    """
    spec = importlib.util.spec_from_file_location(f"unreal_umg_{module_name}", _SCRIPTS_DIR / f"{module_name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _create_mock_unreal() -> types.ModuleType:
    """Build a mock ``unreal`` module with enough surface for UMG tool tests."""
    m = types.ModuleType("unreal")

    # Asset tools mock
    m.AssetToolsHelpers = mock.MagicMock()
    m.WidgetBlueprintFactory = mock.MagicMock()
    m.WidgetBlueprint = mock.MagicMock()

    # Widget class loading
    m.load_class = mock.MagicMock(return_value=mock.MagicMock())
    m.load_asset = mock.MagicMock()
    m.Vector2D = mock.MagicMock(return_value=mock.MagicMock())
    m.Anchors = mock.MagicMock(return_value=mock.MagicMock())
    m.FrameNumber = mock.MagicMock(return_value=mock.MagicMock())
    m.Name = mock.MagicMock(return_value=mock.MagicMock())

    # Slate visibility enum
    m.SlateVisibility = mock.MagicMock()
    m.SlateVisibility.Visible = 0
    m.SlateVisibility.Collapsed = 1
    m.SlateVisibility.Hidden = 2

    # Asset persistence — every mutating tool saves the Widget Blueprint
    m.EditorAssetLibrary = mock.MagicMock()
    m.EditorAssetLibrary.save_loaded_asset.return_value = True

    # Blueprint libraries
    m.KismetSystemLibrary = mock.MagicMock()
    m.BlueprintEditorLibrary = mock.MagicMock()
    m.WidgetBlueprintLibrary = mock.MagicMock()

    # Movie scene types
    m.MovieScene2DTransformTrack = mock.MagicMock()
    m.MovieSceneColorTrack = mock.MagicMock()
    m.MovieSceneVisibilityTrack = mock.MagicMock()
    m.MovieSceneFloatTrack = mock.MagicMock()

    return m


def _build_mock_widget_tree(
    root_widget: mock.MagicMock,
    children: list[mock.MagicMock] | None = None,
) -> mock.MagicMock:
    """Build a mock widget tree with the given root and optional children."""
    tree = mock.MagicMock()
    tree.root_widget = root_widget
    tree.find_widget = mock.MagicMock(return_value=root_widget)
    tree.construct_widget = mock.MagicMock(return_value=mock.MagicMock())
    if children:
        for i, child in enumerate(children):
            child.get_name = mock.MagicMock(return_value=f"Child_{i}")
            child.get_class = mock.MagicMock(return_value=mock.MagicMock())
    return tree


def _build_mock_blueprint(
    widget_tree: mock.MagicMock | None = None,
) -> mock.MagicMock:
    """Build a mock Widget Blueprint with an optional widget tree."""
    bp = mock.MagicMock()
    bp.widget_tree = widget_tree or _build_mock_widget_tree(mock.MagicMock())
    bp.generated_class = mock.MagicMock(return_value=mock.MagicMock())
    return bp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_unreal():
    """Inject a mocked unreal module and return it."""
    unreal_mock = _create_mock_unreal()
    original = sys.modules.get("unreal")
    sys.modules["unreal"] = unreal_mock
    yield unreal_mock
    if original is not None:
        sys.modules["unreal"] = original
    else:
        sys.modules.pop("unreal", None)


# ---------------------------------------------------------------------------
# Test helpers — shared across tools
# ---------------------------------------------------------------------------


class TestAssetPathValidation:
    """Asset path validation is shared across all tools."""

    @pytest.mark.parametrize(
        "path",
        [
            "/Game/UI/WBP_MainMenu",
            "/Game/MyProject/Widgets/WBP_HUD",
            "/Game/",
        ],
    )
    def test_valid_paths(self, path):
        """Valid /Game/ paths should pass validation."""
        create_widget_blueprint_module = _load_script("create_widget_blueprint")
        _validate_asset_path = create_widget_blueprint_module._validate_asset_path
        assert _validate_asset_path(path) is None

    @pytest.mark.parametrize(
        "path,expected_substr",
        [
            ("", "required"),
            ("/Other/UI/Widget", "/Game/"),
            ("C:\\Game\\UI", "/Game/"),
            ("/Game/../UI/Widget", ".."),
        ],
    )
    def test_invalid_paths(self, path, expected_substr):
        """Invalid paths should return an error message."""
        create_widget_blueprint_module = _load_script("create_widget_blueprint")
        _validate_asset_path = create_widget_blueprint_module._validate_asset_path
        err = _validate_asset_path(path)
        assert err is not None
        assert expected_substr in err


# ---------------------------------------------------------------------------
# create_widget_blueprint
# ---------------------------------------------------------------------------


class TestCreateWidgetBlueprint:
    """Tests for create_widget_blueprint tool."""

    def test_success(self, mock_unreal):
        """Should return success when asset creation succeeds."""
        mock_asset = mock.MagicMock()
        mock_tools = mock.MagicMock()
        mock_tools.create_asset.return_value = mock_asset
        mock_unreal.AssetToolsHelpers.get_asset_tools.return_value = mock_tools

        create_widget_blueprint_module = _load_script("create_widget_blueprint")
        create_widget_blueprint = create_widget_blueprint_module.create_widget_blueprint

        result = create_widget_blueprint(
            asset_path="/Game/UI/",
            widget_name="WBP_MainMenu",
        )
        assert result["success"] is True
        assert "WBP_MainMenu" in result["message"]
        assert result["context"]["asset_path"] == "/Game/UI/WBP_MainMenu"

    def test_invalid_asset_path(self):
        """Should return error for non-/Game/ paths."""
        create_widget_blueprint_module = _load_script("create_widget_blueprint")
        create_widget_blueprint = create_widget_blueprint_module.create_widget_blueprint

        result = create_widget_blueprint(
            asset_path="/Some/Path/",
            widget_name="WBP_Test",
        )
        assert result["success"] is False
        assert "/Game/" in result["error"]

    def test_missing_asset_path(self):
        """Should return error for empty asset_path."""
        create_widget_blueprint_module = _load_script("create_widget_blueprint")
        create_widget_blueprint = create_widget_blueprint_module.create_widget_blueprint

        result = create_widget_blueprint(asset_path="", widget_name="WBP_Test")
        assert result["success"] is False

    def test_missing_widget_name(self):
        """Should return error for empty widget_name."""
        create_widget_blueprint_module = _load_script("create_widget_blueprint")
        create_widget_blueprint = create_widget_blueprint_module.create_widget_blueprint

        result = create_widget_blueprint(asset_path="/Game/UI/", widget_name="")
        assert result["success"] is False

    def test_creation_returns_none(self, mock_unreal):
        """Should handle create_asset returning None."""
        mock_tools = mock.MagicMock()
        mock_tools.create_asset.return_value = None
        mock_unreal.AssetToolsHelpers.get_asset_tools.return_value = mock_tools

        create_widget_blueprint_module = _load_script("create_widget_blueprint")
        create_widget_blueprint = create_widget_blueprint_module.create_widget_blueprint

        result = create_widget_blueprint(
            asset_path="/Game/UI/",
            widget_name="WBP_Test",
        )
        assert result["success"] is False

    def test_unreal_not_available(self):
        """Should return error when unreal module cannot be imported."""
        # A ``None`` entry in sys.modules makes ``import unreal`` raise
        # ImportError, which is what running outside Unreal Editor looks like.
        # Blocking it explicitly keeps the test independent of whether the
        # repository's own ``unreal/`` plugin directory is importable.
        with mock.patch.dict(sys.modules, {"unreal": None}):
            create_widget_blueprint_module = _load_script("create_widget_blueprint")
            create_widget_blueprint = create_widget_blueprint_module.create_widget_blueprint
            result = create_widget_blueprint(
                asset_path="/Game/UI/",
                widget_name="WBP_Test",
            )
        assert result["success"] is False
        assert "not available" in result["message"]


# ---------------------------------------------------------------------------
# add_widget_to_canvas
# ---------------------------------------------------------------------------


class TestAddWidgetToCanvas:
    """Tests for add_widget_to_canvas tool."""

    def test_success(self, mock_unreal):
        """Should add a widget to a panel successfully."""
        mock_bp = _build_mock_blueprint()
        mock_unreal.load_asset.return_value = mock_bp

        add_widget_to_canvas_module = _load_script("add_widget_to_canvas")
        add_widget_to_canvas = add_widget_to_canvas_module.add_widget_to_canvas

        result = add_widget_to_canvas(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
            parent_widget_name="CanvasPanel_0",
            child_widget_type="Button",
            child_widget_name="Btn_Start",
        )
        assert result["success"] is True
        assert "Btn_Start" in result["message"]
        mock_unreal.EditorAssetLibrary.save_loaded_asset.assert_called_once_with(mock_bp, only_if_is_dirty=False)

    def test_invalid_widget_type(self):
        """Should reject widget types not in the whitelist."""
        add_widget_to_canvas_module = _load_script("add_widget_to_canvas")
        add_widget_to_canvas = add_widget_to_canvas_module.add_widget_to_canvas

        result = add_widget_to_canvas(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
            parent_widget_name="CanvasPanel_0",
            child_widget_type="UnknownWidget",
            child_widget_name="BadWidget",
        )
        assert result["success"] is False
        assert "widget type" in result["message"].lower()

    @pytest.mark.parametrize(
        "widget_type",
        [
            "Button",
            "TextBlock",
            "Image",
            "CanvasPanel",
            "VerticalBox",
            "HorizontalBox",
            "Overlay",
            "Border",
            "SizeBox",
            "EditableText",
            "ProgressBar",
            "Slider",
        ],
    )
    def test_all_whitelisted_types_accepted(self, mock_unreal, widget_type):
        """All whitelisted widget types should pass validation."""
        mock_bp = _build_mock_blueprint()
        mock_unreal.load_asset.return_value = mock_bp

        add_widget_to_canvas_module = _load_script("add_widget_to_canvas")
        add_widget_to_canvas = add_widget_to_canvas_module.add_widget_to_canvas

        result = add_widget_to_canvas(
            widget_blueprint_path="/Game/UI/WBP_Test",
            parent_widget_name="CanvasPanel_0",
            child_widget_type=widget_type,
            child_widget_name=f"Widget_{widget_type}",
        )
        # Validation passes; may fail later if blueprint is None but not due to type
        # The mock should work
        assert result["success"] is True

    def test_blueprint_not_found(self, mock_unreal):
        """Should return error when blueprint asset is missing."""
        mock_unreal.load_asset.return_value = None

        add_widget_to_canvas_module = _load_script("add_widget_to_canvas")
        add_widget_to_canvas = add_widget_to_canvas_module.add_widget_to_canvas

        result = add_widget_to_canvas(
            widget_blueprint_path="/Game/UI/WBP_NotFound",
            parent_widget_name="CanvasPanel_0",
            child_widget_type="Button",
            child_widget_name="Btn_Test",
        )
        assert result["success"] is False
        assert "not found" in result["message"].lower()

    def test_empty_child_name(self):
        """Should reject empty child widget name."""
        add_widget_to_canvas_module = _load_script("add_widget_to_canvas")
        add_widget_to_canvas = add_widget_to_canvas_module.add_widget_to_canvas

        result = add_widget_to_canvas(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
            parent_widget_name="CanvasPanel_0",
            child_widget_type="Button",
            child_widget_name="",
        )
        assert result["success"] is False


# ---------------------------------------------------------------------------
# set_widget_properties
# ---------------------------------------------------------------------------


class TestSetWidgetProperties:
    """Tests for set_widget_properties tool."""

    def test_set_visibility(self, mock_unreal):
        """Should set visibility on a widget."""
        mock_bp = _build_mock_blueprint()
        mock_unreal.load_asset.return_value = mock_bp

        set_widget_properties_module = _load_script("set_widget_properties")
        set_widget_properties = set_widget_properties_module.set_widget_properties

        result = set_widget_properties(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
            widget_name="Btn_Start",
            visibility="Hidden",
        )
        assert result["success"] is True

    def test_set_size_and_anchors(self, mock_unreal):
        """Should set size and anchor preset."""
        mock_bp = _build_mock_blueprint()
        mock_unreal.load_asset.return_value = mock_bp

        set_widget_properties_module = _load_script("set_widget_properties")
        set_widget_properties = set_widget_properties_module.set_widget_properties

        result = set_widget_properties(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
            widget_name="Btn_Start",
            size={"x": 300.0, "y": 80.0},
            anchors={"preset": "center-center"},
        )
        assert result["success"] is True

    def test_invalid_visibility(self):
        """Should reject unknown visibility values."""
        set_widget_properties_module = _load_script("set_widget_properties")
        set_widget_properties = set_widget_properties_module.set_widget_properties

        result = set_widget_properties(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
            widget_name="Btn_Start",
            visibility="Invisible",
        )
        assert result["success"] is False

    def test_invalid_anchor_preset(self):
        """Should reject unknown anchor presets."""
        set_widget_properties_module = _load_script("set_widget_properties")
        set_widget_properties = set_widget_properties_module.set_widget_properties

        result = set_widget_properties(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
            widget_name="Btn_Start",
            anchors={"preset": "nowhere"},
        )
        assert result["success"] is False

    def test_render_opacity_bounds(self):
        """Should reject out-of-range opacity values."""
        set_widget_properties_module = _load_script("set_widget_properties")
        set_widget_properties = set_widget_properties_module.set_widget_properties

        # render_opacity > 1.0
        result = set_widget_properties(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
            widget_name="Btn_Start",
            render_opacity=1.5,
        )
        assert result["success"] is False

        # render_opacity < 0.0
        result = set_widget_properties(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
            widget_name="Btn_Start",
            render_opacity=-0.1,
        )
        assert result["success"] is False

    def test_no_properties_changed(self, mock_unreal):
        """Should succeed with a note when no properties are given."""
        mock_bp = _build_mock_blueprint()
        mock_unreal.load_asset.return_value = mock_bp

        set_widget_properties_module = _load_script("set_widget_properties")
        set_widget_properties = set_widget_properties_module.set_widget_properties

        result = set_widget_properties(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
            widget_name="Btn_Start",
        )
        assert result["success"] is True
        assert "No properties changed" in result["message"]


# ---------------------------------------------------------------------------
# bind_widget_event
# ---------------------------------------------------------------------------


class TestBindWidgetEvent:
    """Tests for bind_widget_event tool."""

    def test_success(self, mock_unreal):
        """Should bind a widget event successfully."""
        mock_bp = _build_mock_blueprint()
        mock_unreal.load_asset.return_value = mock_bp

        bind_widget_event_module = _load_script("bind_widget_event")
        bind_widget_event = bind_widget_event_module.bind_widget_event

        result = bind_widget_event(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
            widget_name="Btn_Start",
            event_name="OnClicked",
            function_name="OnStartClicked",
        )
        assert result["success"] is True

    def test_invalid_event_name(self):
        """Should reject non-whitelisted event names."""
        bind_widget_event_module = _load_script("bind_widget_event")
        bind_widget_event = bind_widget_event_module.bind_widget_event

        result = bind_widget_event(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
            widget_name="Btn_Start",
            event_name="OnExplode",
            function_name="OnStartClicked",
        )
        assert result["success"] is False
        assert "event" in result["message"].lower()

    @pytest.mark.parametrize(
        "event",
        [
            "OnClicked",
            "OnPressed",
            "OnReleased",
            "OnHovered",
            "OnUnhovered",
            "OnDragDetected",
            "OnDragCancelled",
        ],
    )
    def test_all_event_types_accepted(self, mock_unreal, event):
        """All whitelisted event types should pass validation."""
        mock_bp = _build_mock_blueprint()
        mock_unreal.load_asset.return_value = mock_bp

        bind_widget_event_module = _load_script("bind_widget_event")
        bind_widget_event = bind_widget_event_module.bind_widget_event

        result = bind_widget_event(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
            widget_name="Btn_Start",
            event_name=event,
            function_name="OnEvent",
        )
        assert result["success"] is True

    def test_invalid_function_name(self):
        """Should reject invalid function names."""
        bind_widget_event_module = _load_script("bind_widget_event")
        bind_widget_event = bind_widget_event_module.bind_widget_event

        result = bind_widget_event(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
            widget_name="Btn_Start",
            event_name="OnClicked",
            function_name="123BadName",
        )
        assert result["success"] is False


# ---------------------------------------------------------------------------
# create_umg_animation
# ---------------------------------------------------------------------------


class TestCreateUmgAnimation:
    """Tests for create_umg_animation tool."""

    def test_success(self, mock_unreal):
        """Should create an animation successfully."""
        mock_bp = _build_mock_blueprint()
        mock_unreal.load_asset.return_value = mock_bp

        create_umg_animation_module = _load_script("create_umg_animation")
        create_umg_animation = create_umg_animation_module.create_umg_animation

        result = create_umg_animation(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
            animation_name="Anim_FadeIn",
            target_widget_name="Txt_Title",
            duration=0.5,
        )
        assert result["success"] is True
        assert "Anim_FadeIn" in result["message"]

    def test_zero_duration(self):
        """Should reject non-positive duration."""
        create_umg_animation_module = _load_script("create_umg_animation")
        create_umg_animation = create_umg_animation_module.create_umg_animation

        result = create_umg_animation(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
            animation_name="Anim_Test",
            target_widget_name="Btn_Start",
            duration=0,
        )
        assert result["success"] is False

    def test_empty_animation_name(self):
        """Should reject empty animation name."""
        create_umg_animation_module = _load_script("create_umg_animation")
        create_umg_animation = create_umg_animation_module.create_umg_animation

        result = create_umg_animation(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
            animation_name="",
            target_widget_name="Btn_Start",
        )
        assert result["success"] is False


# ---------------------------------------------------------------------------
# add_animation_keyframe
# ---------------------------------------------------------------------------


class TestAddAnimationKeyframe:
    """Tests for add_animation_keyframe tool."""

    def test_success(self, mock_unreal):
        """Should add a keyframe successfully."""
        mock_anim = mock.MagicMock()
        mock_anim.get_name.return_value = "Anim_FadeIn"
        mock_movie_scene = mock.MagicMock()
        mock_anim.get_movie_scene.return_value = mock_movie_scene

        mock_tree = _build_mock_widget_tree(mock.MagicMock())
        mock_tree.get_all_widget_animations.return_value = [mock_anim]
        mock_bp = _build_mock_blueprint(mock_tree)
        mock_unreal.load_asset.return_value = mock_bp

        add_animation_keyframe_module = _load_script("add_animation_keyframe")
        add_animation_keyframe = add_animation_keyframe_module.add_animation_keyframe

        result = add_animation_keyframe(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
            animation_name="Anim_FadeIn",
            time=0.0,
            property="opacity",
            value=0.0,
        )
        assert result["success"] is True

    def test_transform_property_keys_both_channels(self, mock_unreal):
        """A position keyframe should write keys on the X and Y channels."""
        mock_anim = mock.MagicMock()
        mock_anim.get_name.return_value = "Anim_Slide"
        mock_movie_scene = mock.MagicMock()
        mock_anim.get_movie_scene.return_value = mock_movie_scene
        section = (
            mock_movie_scene.find_spawnable_or_possessable.return_value.add_track.return_value.add_section.return_value
        )

        mock_tree = _build_mock_widget_tree(mock.MagicMock())
        mock_tree.get_all_widget_animations.return_value = [mock_anim]
        mock_unreal.load_asset.return_value = _build_mock_blueprint(mock_tree)

        add_animation_keyframe = _load_script("add_animation_keyframe").add_animation_keyframe

        result = add_animation_keyframe(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
            animation_name="Anim_Slide",
            time=0.5,
            property="position",
            value={"x": 10.0, "y": -20.0},
        )
        assert result["success"] is True
        channel_names = [call.args[0] for call in section.find_or_add_channel.call_args_list]
        assert channel_names == ["Translation.X", "Translation.Y"]
        keyed_values = [call.args[1] for call in section.find_or_add_channel.return_value.add_key.call_args_list]
        assert keyed_values == [10.0, -20.0]

    def test_visibility_property_keys_bool(self, mock_unreal):
        """A visibility keyframe should write a boolean key."""
        mock_anim = mock.MagicMock()
        mock_anim.get_name.return_value = "Anim_Show"
        mock_movie_scene = mock.MagicMock()
        mock_anim.get_movie_scene.return_value = mock_movie_scene
        section = (
            mock_movie_scene.find_spawnable_or_possessable.return_value.add_track.return_value.add_section.return_value
        )

        mock_tree = _build_mock_widget_tree(mock.MagicMock())
        mock_tree.get_all_widget_animations.return_value = [mock_anim]
        mock_unreal.load_asset.return_value = _build_mock_blueprint(mock_tree)

        add_animation_keyframe = _load_script("add_animation_keyframe").add_animation_keyframe

        result = add_animation_keyframe(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
            animation_name="Anim_Show",
            time=0.0,
            property="visibility",
            value=True,
        )
        assert result["success"] is True
        section.find_or_add_channel.assert_called_once_with("Visibility")
        assert section.find_or_add_channel.return_value.add_key.call_args.args[1] is True

    def test_save_failure_is_reported(self, mock_unreal):
        """A refused asset save should surface as an error, not a silent success."""
        mock_anim = mock.MagicMock()
        mock_anim.get_name.return_value = "Anim_FadeIn"
        mock_tree = _build_mock_widget_tree(mock.MagicMock())
        mock_tree.get_all_widget_animations.return_value = [mock_anim]
        mock_unreal.load_asset.return_value = _build_mock_blueprint(mock_tree)
        mock_unreal.EditorAssetLibrary.save_loaded_asset.return_value = False

        add_animation_keyframe = _load_script("add_animation_keyframe").add_animation_keyframe

        result = add_animation_keyframe(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
            animation_name="Anim_FadeIn",
            time=0.0,
            property="opacity",
            value=0.5,
        )
        assert result["success"] is False
        assert "could not be saved" in result["message"]

    def test_invalid_property(self):
        """Should reject non-animatable properties."""
        add_animation_keyframe_module = _load_script("add_animation_keyframe")
        add_animation_keyframe = add_animation_keyframe_module.add_animation_keyframe

        result = add_animation_keyframe(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
            animation_name="Anim_FadeIn",
            time=0.0,
            property="unknown_prop",
            value=0.5,
        )
        assert result["success"] is False
        assert "property" in result["message"].lower()

    def test_value_type_mismatch(self):
        """Should reject values that don't match the property type."""
        add_animation_keyframe_module = _load_script("add_animation_keyframe")
        add_animation_keyframe = add_animation_keyframe_module.add_animation_keyframe

        # Position requires {x, y} dict
        result = add_animation_keyframe(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
            animation_name="Anim_FadeIn",
            time=0.0,
            property="position",
            value=42.0,  # should be dict
        )
        assert result["success"] is False

    def test_negative_time(self):
        """Should reject negative time values."""
        add_animation_keyframe_module = _load_script("add_animation_keyframe")
        add_animation_keyframe = add_animation_keyframe_module.add_animation_keyframe

        result = add_animation_keyframe(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
            animation_name="Anim_FadeIn",
            time=-1.0,
            property="opacity",
            value=0.5,
        )
        assert result["success"] is False


# ---------------------------------------------------------------------------
# compile_widget_blueprint
# ---------------------------------------------------------------------------


class TestCompileWidgetBlueprint:
    """Tests for compile_widget_blueprint tool."""

    def test_success(self, mock_unreal):
        """Should compile successfully."""
        mock_bp = _build_mock_blueprint()
        mock_unreal.load_asset.return_value = mock_bp
        mock_unreal.BlueprintEditorLibrary.get_compiler_results.return_value = []

        compile_widget_blueprint_module = _load_script("compile_widget_blueprint")
        compile_widget_blueprint = compile_widget_blueprint_module.compile_widget_blueprint

        result = compile_widget_blueprint(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
        )
        assert result["success"] is True
        assert result["context"]["compile_success"] is True

    def test_with_errors(self, mock_unreal):
        """Should report compilation errors."""
        mock_bp = _build_mock_blueprint()
        mock_unreal.load_asset.return_value = mock_bp
        mock_unreal.BlueprintEditorLibrary.get_compiler_results.return_value = [
            "Error: Unknown variable",
            "Error: Type mismatch",
        ]

        compile_widget_blueprint_module = _load_script("compile_widget_blueprint")
        compile_widget_blueprint = compile_widget_blueprint_module.compile_widget_blueprint

        result = compile_widget_blueprint(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
        )
        assert result["success"] is False
        assert result["context"]["compile_success"] is False
        assert len(result["context"]["errors"]) == 2

    def test_blueprint_not_found(self, mock_unreal):
        """Should return error for missing blueprint."""
        mock_unreal.load_asset.return_value = None

        compile_widget_blueprint_module = _load_script("compile_widget_blueprint")
        compile_widget_blueprint = compile_widget_blueprint_module.compile_widget_blueprint

        result = compile_widget_blueprint(
            widget_blueprint_path="/Game/UI/WBP_NotFound",
        )
        assert result["success"] is False


# ---------------------------------------------------------------------------
# list_widget_hierarchy
# ---------------------------------------------------------------------------


class TestListWidgetHierarchy:
    """Tests for list_widget_hierarchy tool."""

    def test_success(self, mock_unreal):
        """Should list widget hierarchy successfully."""
        root = mock.MagicMock()
        root.get_name.return_value = "CanvasPanel_0"
        root.get_class.return_value = mock.MagicMock()
        root.get_class().get_name.return_value = "CanvasPanel"
        root.get_children_count.return_value = 0

        mock_tree = _build_mock_widget_tree(root)
        mock_bp = _build_mock_blueprint(mock_tree)
        mock_unreal.load_asset.return_value = mock_bp

        list_widget_hierarchy_module = _load_script("list_widget_hierarchy")
        list_widget_hierarchy = list_widget_hierarchy_module.list_widget_hierarchy

        result = list_widget_hierarchy(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
        )
        assert result["success"] is True
        assert result["context"]["total_widgets"] >= 1

    def test_with_children(self, mock_unreal):
        """Should traverse children up to max_depth."""
        child = mock.MagicMock()
        child.get_name.return_value = "Btn_Child"
        child.get_class.return_value = mock.MagicMock()
        child.get_class().get_name.return_value = "Button"
        child.get_children_count.return_value = 0

        root = mock.MagicMock()
        root.get_name.return_value = "CanvasPanel_0"
        root.get_class.return_value = mock.MagicMock()
        root.get_class().get_name.return_value = "CanvasPanel"
        root.get_children_count.return_value = 1
        root.get_child_at.return_value = child

        mock_tree = _build_mock_widget_tree(root)
        mock_bp = _build_mock_blueprint(mock_tree)
        mock_unreal.load_asset.return_value = mock_bp

        list_widget_hierarchy_module = _load_script("list_widget_hierarchy")
        list_widget_hierarchy = list_widget_hierarchy_module.list_widget_hierarchy

        result = list_widget_hierarchy(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
            max_depth=5,
        )
        assert result["success"] is True
        assert result["context"]["total_widgets"] >= 2

    def test_invalid_max_depth(self):
        """Should reject max_depth < 1."""
        list_widget_hierarchy_module = _load_script("list_widget_hierarchy")
        list_widget_hierarchy = list_widget_hierarchy_module.list_widget_hierarchy

        result = list_widget_hierarchy(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
            max_depth=0,
        )
        assert result["success"] is False

    def test_specific_root_widget(self, mock_unreal):
        """Should accept a specific root widget name."""
        mock_tree = _build_mock_widget_tree(mock.MagicMock())
        mock_bp = _build_mock_blueprint(mock_tree)
        mock_unreal.load_asset.return_value = mock_bp

        list_widget_hierarchy_module = _load_script("list_widget_hierarchy")
        list_widget_hierarchy = list_widget_hierarchy_module.list_widget_hierarchy

        result = list_widget_hierarchy(
            widget_blueprint_path="/Game/UI/WBP_MainMenu",
            root_widget_name="CanvasPanel_0",
        )
        assert result["success"] is True


# ---------------------------------------------------------------------------
# No exec/eval/subprocess — security verification
# ---------------------------------------------------------------------------


class TestNoArbitraryCodeExecution:
    """Verify that scripts do not use exec(), eval(), or subprocess."""

    FORBIDDEN = {"exec(", "eval(", "subprocess"}

    @pytest.mark.parametrize(
        "script_name",
        [
            "create_widget_blueprint.py",
            "add_widget_to_canvas.py",
            "set_widget_properties.py",
            "bind_widget_event.py",
            "create_umg_animation.py",
            "add_animation_keyframe.py",
            "compile_widget_blueprint.py",
            "list_widget_hierarchy.py",
        ],
    )
    def test_no_forbidden_calls(self, script_name):
        """No script should contain exec(), eval(), or subprocess calls."""
        import scripts  # noqa: F401 — ensure scripts package is importable

        script_path = _SCRIPTS_DIR / script_name
        source = script_path.read_text(encoding="utf-8")

        for forbidden in self.FORBIDDEN:
            assert forbidden not in source, f"{script_name} contains forbidden call: {forbidden}"


# ---------------------------------------------------------------------------
# Asset path namespace constraint
# ---------------------------------------------------------------------------


class TestAssetPathConstraints:
    """Verify all tools enforce /Game/ namespace only."""

    TOOL_SCRIPTS = [
        "create_widget_blueprint.py",
        "add_widget_to_canvas.py",
        "set_widget_properties.py",
        "bind_widget_event.py",
        "create_umg_animation.py",
        "add_animation_keyframe.py",
        "compile_widget_blueprint.py",
        "list_widget_hierarchy.py",
    ]

    @pytest.mark.parametrize("script_name", TOOL_SCRIPTS)
    def test_validate_asset_path_function_exists(self, script_name):
        """Every script should have _validate_asset_path defined."""

        script_path = _SCRIPTS_DIR / script_name
        source = script_path.read_text(encoding="utf-8")
        assert "_validate_asset_path" in source, f"{script_name} is missing _validate_asset_path function"

    @pytest.mark.parametrize("script_name", TOOL_SCRIPTS)
    def test_no_absolute_filesystem_path(self, script_name):
        """Scripts should not accept absolute filesystem paths."""

        script_path = _SCRIPTS_DIR / script_name
        source = script_path.read_text(encoding="utf-8")

        # Check that the validate function rejects non-/Game/ paths
        assert "/Game/" in source, f"{script_name} does not reference /Game/ namespace check"
