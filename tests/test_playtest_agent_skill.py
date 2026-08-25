"""Tests for the structured Unreal playtest-agent skill."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import yaml

_SKILL_DIR = Path(__file__).resolve().parents[1] / "src" / "dcc_mcp_unreal" / "skills" / "unreal-playtest-agent"
_RUNTIME_PATH = _SKILL_DIR / "scripts" / "_playtest_runtime.py"


class _Vector:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = x
        self.y = y
        self.z = z

    def __sub__(self, other):
        return _Vector(self.x - other.x, self.y - other.y, self.z - other.z)


class _Rotator:
    def __init__(self, roll=0.0, pitch=0.0, yaw=0.0):
        self.roll = roll
        self.pitch = pitch
        self.yaw = yaw


class _UnrealClass:
    def __init__(self, name):
        self._name = name

    def get_name(self):
        return self._name


class _Actor:
    def __init__(self, name, class_name, location, *, tags=(), attributes=None):
        self._name = name
        self._class = _UnrealClass(class_name)
        self.location = location
        self.rotation = _Rotator()
        self.tags = list(tags)
        self.attributes = dict(attributes or {})

    def get_name(self):
        return self._name

    def get_class(self):
        return self._class

    def get_actor_location(self):
        return self.location

    def get_actor_bounds(self, _only_colliding_components=False, _include_from_child_actors=False):
        return (
            _Vector(self.location.x, self.location.y, self.location.z + 90.0),
            _Vector(40.0, 40.0, 90.0),
        )

    def get_actor_rotation(self):
        return self.rotation

    def get_velocity(self):
        return _Vector()

    def get_editor_property(self, name):
        if name == "tags":
            return self.tags
        if name in self.attributes:
            return self.attributes[name]
        raise AttributeError(name)


class _Controller(_Actor):
    def __init__(self, player):
        super().__init__("PlayerController_0", "PlayerController", _Vector())
        self.player = player
        self.control_rotation = _Rotator()
        self.stop_count = 0
        self.visible = True

    def get_control_rotation(self):
        return self.control_rotation

    def get_player_view_point(self):
        return self.player.location, self.control_rotation

    def set_control_rotation(self, value):
        self.control_rotation = value

    def stop_movement(self):
        self.stop_count += 1

    def line_of_sight_to(self, _actor):
        return self.visible


class _World:
    def get_name(self):
        return "TestWorld"


class _Widget:
    def __init__(self, name, class_name, visibility="Visible"):
        self._name = name
        self._class = _UnrealClass(class_name)
        self._visibility = visibility

    def get_name(self):
        return self._name

    def get_class(self):
        return self._class

    def get_visibility(self):
        return self._visibility

    def is_in_viewport(self):
        return True

    def get_is_enabled(self):
        return True


def _load_runtime(monkeypatch):
    player = _Actor("Player_0", "PlayerPawn", _Vector(), attributes={"health": 100.0})
    enemy = _Actor("Enemy_0", "EnemyPawn", _Vector(1000, 0, 0), attributes={"health": 40.0})
    door = _Actor("Door_0", "TestDoor", _Vector(250, 100, 0), tags=("Interactable",))
    controller = _Controller(player)
    world = _World()
    game_mode = _Actor(
        "GameMode_0",
        "TestGameMode",
        _Vector(),
        attributes={"default_pawn_class": _UnrealClass("TestPlayerPawn_C")},
    )
    game_mode.restart_calls = []
    game_mode.restart_player = lambda actual_controller: game_mode.restart_calls.append(actual_controller)
    controller.game_mode = game_mode
    widgets = [_Widget("HUD_0", "TestHudWidget")]
    actors = [player, enemy, door, controller]
    key_events = []
    navigation_calls = []

    class LevelEditorSubsystem:
        def is_in_play_in_editor(self):
            return True

    class UnrealEditorSubsystem:
        def get_game_world(self):
            return world

    class GameplayStatics:
        @staticmethod
        def get_player_controller(_world, _index):
            return controller

        @staticmethod
        def get_player_pawn(_world, _index):
            return player

        @staticmethod
        def get_game_mode(_world):
            return game_mode

        @staticmethod
        def get_all_actors_of_class(_world, requested_class):
            if requested_class is Pawn:
                return [player, enemy]
            if requested_class is PlayerController:
                return [controller]
            return list(actors)

        @staticmethod
        def get_time_seconds(_world):
            return 12.5

    class Actor:
        pass

    class Pawn:
        pass

    class PlayerController:
        pass

    class PlayerStart:
        pass

    class UserWidget:
        pass

    class WidgetBlueprintLibrary:
        @staticmethod
        def get_all_widgets_of_class(_world, requested_class, _top_level_only):
            assert requested_class is UserWidget
            return widgets

    class AIBlueprintHelperLibrary:
        @staticmethod
        def simple_move_to_actor(actual_controller, target):
            navigation_calls.append((actual_controller, target))

    class DccMcpAutomationLibrary:
        @staticmethod
        def inject_pie_key(key, pressed):
            key_events.append((key, pressed))
            return True

        @staticmethod
        def navigate_pie_to_actor(actor_name):
            target = next(item for item in actors if item.get_name() == actor_name)
            navigation_calls.append((controller, target))
            return True

        @staticmethod
        def navigate_pie_to_location(target_location):
            navigation_calls.append((controller, target_location))
            return True

        @staticmethod
        def start_pie_input_steering(actor_name):
            target = next(item for item in actors if item.get_name() == actor_name)
            navigation_calls.append(("input_steering", controller, target))
            return True

        @staticmethod
        def start_pie_input_steering_to_location(target_location):
            navigation_calls.append(("input_steering", controller, target_location))
            return True

        @staticmethod
        def stop_pie_navigation():
            controller.stop_movement()
            return True

    def get_editor_subsystem(requested_class):
        if requested_class is LevelEditorSubsystem:
            return LevelEditorSubsystem()
        return UnrealEditorSubsystem()

    unreal = types.SimpleNamespace(
        Actor=Actor,
        Pawn=Pawn,
        PlayerController=PlayerController,
        PlayerStart=PlayerStart,
        UserWidget=UserWidget,
        WidgetBlueprintLibrary=WidgetBlueprintLibrary,
        LevelEditorSubsystem=LevelEditorSubsystem,
        UnrealEditorSubsystem=UnrealEditorSubsystem,
        GameplayStatics=GameplayStatics,
        AIBlueprintHelperLibrary=AIBlueprintHelperLibrary,
        DccMcpAutomationLibrary=DccMcpAutomationLibrary,
        Vector=_Vector,
        Rotator=_Rotator,
        get_editor_subsystem=get_editor_subsystem,
        register_slate_post_tick_callback=lambda callback: callback,
        unregister_slate_post_tick_callback=lambda _handle: None,
    )
    monkeypatch.setitem(sys.modules, "unreal", unreal)

    module_name = "_test_playtest_runtime"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, _RUNTIME_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    module._EPISODES.clear()
    return module, player, enemy, door, controller, key_events, navigation_calls


def test_tools_manifest_declares_episode_observe_act_poll_contract():
    data = yaml.safe_load((_SKILL_DIR / "tools.yaml").read_text(encoding="utf-8"))
    tools = data["tools"]
    assert [tool["name"] for tool in tools] == [
        "playtest_episode_control",
        "playtest_observe",
        "playtest_execute_action",
        "playtest_poll_action",
    ]
    by_name = {tool["name"]: tool for tool in tools}
    assert by_name["playtest_observe"]["read_only"] is True
    assert by_name["playtest_observe"]["annotations"]["read_only_hint"] is True
    assert by_name["playtest_poll_action"]["read_only"] is False
    assert by_name["playtest_poll_action"]["annotations"]["read_only_hint"] is False
    assert "ensure_player_control" in by_name["playtest_execute_action"]["input_schema"]["properties"]["action"]["enum"]
    assert "move_relative" in by_name["playtest_execute_action"]["input_schema"]["properties"]["action"]["enum"]
    assert "navigate_to_location" in by_name["playtest_execute_action"]["input_schema"]["properties"]["action"]["enum"]
    assert "face_location" in by_name["playtest_execute_action"]["input_schema"]["properties"]["action"]["enum"]
    assert by_name["playtest_execute_action"]["input_schema"]["properties"]["direction"]["enum"] == [
        "forward",
        "backward",
        "left",
        "right",
    ]
    episode_properties = by_name["playtest_episode_control"]["input_schema"]["properties"]
    assert episode_properties["include_hidden"]["default"] is False
    assert episode_properties["exclude_class_contains"]["maxItems"] == 16
    action_properties = by_name["playtest_execute_action"]["input_schema"]["properties"]
    assert action_properties["target_include_hidden"]["default"] is False
    assert action_properties["target_exclude_class_contains"]["maxItems"] == 16
    target_location = by_name["playtest_execute_action"]["input_schema"]["properties"]["target_location"]
    assert target_location["required"] == ["x", "y", "z"]
    assert target_location["additionalProperties"] is False


def test_dependency_manifest_uses_skill_ids_only():
    depends = (_SKILL_DIR / "metadata" / "depends.md").read_text(encoding="utf-8").splitlines()
    assert depends == ["- unreal-pie"]


def test_observe_returns_bounded_entities_and_scalar_attributes(monkeypatch):
    runtime, _player, _enemy, _door, _controller, _keys, _navigation = _load_runtime(monkeypatch)
    observation = runtime.observe(
        {
            "include_pawns": True,
            "class_contains": ["Door"],
            "name_contains": [],
            "tags": [],
            "attribute_names": ["health"],
            "max_entities": 8,
            "max_distance": 0,
        }
    )

    assert observation["schema"] == "dcc-mcp-playtest-observation-v1"
    assert observation["runtime"] == {
        "game_mode_class": "TestGameMode",
        "default_pawn_class": "TestPlayerPawn_C",
        "player_start_count": 4,
        "controller_class": "PlayerController",
        "pawn_class": "PlayerPawn",
        "possessed": None,
        "spectating": False,
        "active_widget_count": 1,
        "active_widgets": [
            {
                "name": "HUD_0",
                "class": "TestHudWidget",
                "visibility": "Visible",
                "in_viewport": True,
                "enabled": True,
            }
        ],
    }
    assert [item["name"] for item in observation["entities"]] == ["Door_0", "Enemy_0"]
    assert observation["entities"][1]["attributes"] == {"health": 40.0}
    assert observation["observation_hash"].startswith("sha256:")


def test_observe_excludes_hidden_entities_by_default_and_can_opt_in(monkeypatch):
    runtime, _player, enemy, _door, _controller, _keys, _navigation = _load_runtime(monkeypatch)
    enemy.attributes["bHidden"] = True
    selectors = {
        "include_pawns": True,
        "class_contains": [],
        "name_contains": [],
        "tags": [],
        "attribute_names": [],
        "max_entities": 8,
        "max_distance": 0,
    }

    assert runtime.observe(selectors)["entities"] == []
    selectors["include_hidden"] = True
    visible = runtime.observe(selectors)["entities"]
    assert [item["name"] for item in visible] == ["Enemy_0"]
    assert visible[0]["hidden"] is True


def test_observe_can_exclude_debris_like_classes(monkeypatch):
    runtime, _player, _enemy, door, _controller, _keys, _navigation = _load_runtime(monkeypatch)
    door._class = _UnrealClass("BP_DroidLimb_C")

    observation = runtime.observe(
        {
            "include_pawns": False,
            "class_contains": ["Droid"],
            "exclude_class_contains": ["DroidLimb"],
            "name_contains": [],
            "tags": [],
            "attribute_names": [],
            "max_entities": 8,
            "max_distance": 0,
        }
    )

    assert observation["entities"] == []


def test_target_resolution_excludes_hidden_and_debris_like_classes(monkeypatch):
    runtime, player, enemy, door, _controller, _keys, _navigation = _load_runtime(monkeypatch)
    _unreal, world, _controller, _player = runtime._pie_context()
    enemy.attributes["bHidden"] = True
    door._class = _UnrealClass("BP_DroidLimb_C")

    assert runtime._resolve_target(world, player, {"target_name": "Enemy_0"}) is None
    assert (
        runtime._resolve_target(
            world,
            player,
            {"target_name": "Enemy_0", "target_include_hidden": True},
        )
        is enemy
    )
    assert (
        runtime._resolve_target(
            world,
            player,
            {
                "target_class_contains": "Droid",
                "target_exclude_class_contains": ["DroidLimb"],
            },
        )
        is None
    )


def test_navigation_action_completes_from_structured_distance(monkeypatch):
    runtime, player, enemy, _door, controller, _keys, navigation = _load_runtime(monkeypatch)
    clock = [100.0]
    monkeypatch.setattr(runtime.time, "time", lambda: clock[0])
    episode = runtime.start_episode(include_pawns=True, max_entities=8)

    accepted = runtime.execute_action(
        episode["episode_id"],
        "navigate_to_entity",
        target_name="Enemy_0",
        acceptance_radius=100,
    )
    assert navigation == [(controller, enemy)]

    player.location = _Vector(950, 0, 0)
    clock[0] = 100.5
    transition = runtime.poll_action(episode["episode_id"], accepted["action_id"])

    assert transition["status"] == "completed"
    assert transition["distance_to_target"] == 50.0
    assert transition["player_location_delta"]["x"] == 950.0


def test_location_navigation_completes_from_structured_distance(monkeypatch):
    runtime, player, _enemy, _door, controller, _keys, navigation = _load_runtime(monkeypatch)
    clock = [125.0]
    monkeypatch.setattr(runtime.time, "time", lambda: clock[0])
    episode = runtime.start_episode(include_pawns=True, max_entities=8)

    accepted = runtime.execute_action(
        episode["episode_id"],
        "navigate_to_location",
        target_location={"x": 800, "y": 100, "z": 0},
        acceptance_radius=100,
    )
    assert len(navigation) == 1
    assert navigation[0][0] is controller
    assert runtime._vector(navigation[0][1]) == {"x": 800.0, "y": 100.0, "z": 0.0}
    assert accepted["target"]["class"] == "Waypoint"

    player.location = _Vector(750, 100, 0)
    clock[0] = 125.5
    transition = runtime.poll_action(episode["episode_id"], accepted["action_id"])

    assert transition["status"] == "completed"
    assert transition["distance_to_target"] == 50.0
    assert transition["player_location_delta"]["x"] == 750.0


def test_location_navigation_requires_finite_explicit_coordinates(monkeypatch):
    runtime, _player, _enemy, _door, _controller, _keys, _navigation = _load_runtime(monkeypatch)
    episode = runtime.start_episode(include_pawns=True, max_entities=8)

    for target_location in (None, {"x": 1, "y": 2}, {"x": float("inf"), "y": 2, "z": 3}):
        try:
            runtime.execute_action(
                episode["episode_id"],
                "navigate_to_location",
                target_location=target_location,
            )
        except ValueError as exc:
            assert "target_location" in str(exc)
        else:
            raise AssertionError("expected navigate_to_location to reject invalid coordinates")


def test_face_location_uses_explicit_world_coordinates(monkeypatch):
    runtime, _player, _enemy, _door, controller, _keys, _navigation = _load_runtime(monkeypatch)
    episode = runtime.start_episode(include_pawns=True, max_entities=8)

    runtime.execute_action(
        episode["episode_id"],
        "face_location",
        target_location={"x": 100, "y": 100, "z": 0},
    )

    assert controller.control_rotation.yaw == 45.0
    assert controller.control_rotation.pitch == 0.0


def test_ensure_player_control_restarts_only_a_spectator(monkeypatch):
    runtime, player, _enemy, _door, controller, _keys, _navigation = _load_runtime(monkeypatch)
    player._class = _UnrealClass("SpectatorPawn")
    clock = [150.0]
    monkeypatch.setattr(runtime.time, "time", lambda: clock[0])
    episode = runtime.start_episode(include_pawns=True, max_entities=8)

    accepted = runtime.execute_action(episode["episode_id"], "ensure_player_control")
    assert controller.game_mode.restart_calls == [controller]
    clock[0] = 150.2
    transition = runtime.poll_action(episode["episode_id"], accepted["action_id"])

    assert transition["status"] == "completed"


def test_ensure_player_control_rejects_an_existing_player_pawn(monkeypatch):
    runtime, _player, _enemy, _door, _controller, _keys, _navigation = _load_runtime(monkeypatch)
    episode = runtime.start_episode(include_pawns=True, max_entities=8)

    try:
        runtime.execute_action(episode["episode_id"], "ensure_player_control")
    except RuntimeError as exc:
        assert "already owns a playable pawn" in str(exc)
    else:
        raise AssertionError("expected ensure_player_control to fail closed")


def test_navigation_falls_back_to_bounded_input_steering_and_releases_forward(monkeypatch):
    runtime, player, enemy, _door, controller, keys, navigation = _load_runtime(monkeypatch)
    clock = [100.0]
    monkeypatch.setattr(runtime.time, "time", lambda: clock[0])
    episode = runtime.start_episode(include_pawns=True, max_entities=8)

    accepted = runtime.execute_action(
        episode["episode_id"],
        "navigate_to_entity",
        target_name="Enemy_0",
        acceptance_radius=100,
        stall_seconds=4,
    )
    assert accepted["navigation_driver"] == "native_pathfinding"
    assert navigation == [(controller, enemy)]

    clock[0] = 101.0
    pending = runtime.poll_action(episode["episode_id"], accepted["action_id"])
    assert pending["status"] == "pending"
    assert pending["navigation_driver"] == "input_steering"
    assert pending["steering_fallback_used"] is True
    assert pending["steering_backend"] == "native_pawn_movement"
    assert navigation == [(controller, enemy), ("input_steering", controller, enemy)]
    assert keys == []

    player.location = _Vector(950, 0, 0)
    clock[0] = 101.5
    transition = runtime.poll_action(episode["episode_id"], accepted["action_id"])

    assert transition["status"] == "completed"
    assert transition["navigation_driver"] == "input_steering"
    assert transition["steering_fallback_used"] is True
    assert transition["steering_backend"] == "native_pawn_movement"
    assert keys == []
    assert controller.stop_count == 1


def test_face_and_input_actions_are_finite_and_traced(monkeypatch):
    runtime, _player, _enemy, _door, controller, keys, _navigation = _load_runtime(monkeypatch)
    clock = [200.0]
    monkeypatch.setattr(runtime.time, "time", lambda: clock[0])
    episode = runtime.start_episode(include_pawns=True, max_entities=8)

    face = runtime.execute_action(
        episode["episode_id"],
        "face_entity",
        target_name_contains="Enemy",
    )
    assert controller.control_rotation.yaw == 0.0
    clock[0] = 200.2
    assert runtime.poll_action(episode["episode_id"], face["action_id"])["status"] == "completed"

    attack = runtime.execute_action(episode["episode_id"], "attack_primary", duration=0)
    assert keys == [("LeftMouseButton", True), ("LeftMouseButton", False)]
    clock[0] = 200.4
    assert runtime.poll_action(episode["episode_id"], attack["action_id"])["status"] == "completed"

    summary = runtime.finish_episode(episode["episode_id"])
    assert summary["transition_count"] == 2
    assert [item["action"] for item in summary["trace"]] == ["face_entity", "attack_primary"]


def test_targeted_attack_faces_and_fires_atomically(monkeypatch):
    runtime, _player, _enemy, _door, controller, keys, _navigation = _load_runtime(monkeypatch)
    episode = runtime.start_episode(include_pawns=True, max_entities=8)

    accepted = runtime.execute_action(
        episode["episode_id"],
        "attack_primary_entity",
        target_name="Enemy_0",
        duration=0,
    )

    assert accepted["target"]["name"] == "Enemy_0"
    assert controller.control_rotation.yaw == 0.0
    assert 5.0 < controller.control_rotation.pitch < 5.2
    assert keys == [("LeftMouseButton", True), ("LeftMouseButton", False)]


def test_targeted_attack_fails_closed_when_target_is_occluded(monkeypatch):
    runtime, _player, _enemy, _door, controller, keys, _navigation = _load_runtime(monkeypatch)
    controller.visible = False
    episode = runtime.start_episode(include_pawns=True, max_entities=8)

    try:
        runtime.execute_action(
            episode["episode_id"],
            "attack_primary_entity",
            target_name="Enemy_0",
            duration=0,
        )
    except RuntimeError as exc:
        assert "occluded" in str(exc)
    else:
        raise AssertionError("expected an occluded targeted attack to fail closed")

    assert keys == []


def test_targeted_combat_utilities_are_bounded_semantic_actions(monkeypatch):
    runtime, _player, _enemy, _door, _controller, keys, _navigation = _load_runtime(monkeypatch)
    episode = runtime.start_episode(include_pawns=True, max_entities=8)

    for action in ("melee_entity", "explosive_entity", "skill_entity"):
        runtime.execute_action(
            episode["episode_id"],
            action,
            target_name="Enemy_0",
            duration=0,
        )

    assert keys == [
        ("V", True),
        ("V", False),
        ("Q", True),
        ("Q", False),
        ("E", True),
        ("E", False),
    ]


def test_move_relative_maps_a_bounded_direction_to_gameplay_input(monkeypatch):
    runtime, _player, _enemy, _door, _controller, keys, _navigation = _load_runtime(monkeypatch)
    episode = runtime.start_episode(include_pawns=True, max_entities=8)

    accepted = runtime.execute_action(
        episode["episode_id"],
        "move_relative",
        direction="right",
        duration=0,
    )

    assert keys == [("D", True), ("D", False)]
    assert accepted["direction"] == "right"


def test_move_relative_rejects_an_unknown_direction(monkeypatch):
    runtime, _player, _enemy, _door, _controller, _keys, _navigation = _load_runtime(monkeypatch)
    episode = runtime.start_episode(include_pawns=True, max_entities=8)

    try:
        runtime.execute_action(
            episode["episode_id"],
            "move_relative",
            direction="up",
        )
    except ValueError as exc:
        assert "direction" in str(exc)
    else:
        raise AssertionError("expected move_relative to reject an unknown direction")
