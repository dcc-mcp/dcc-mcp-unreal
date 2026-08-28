"""Tests for the structured Unreal playtest-agent skill."""

from __future__ import annotations

import copy
import importlib.util
import sys
import types
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

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
        self.components = []

    def get_name(self):
        return self._name

    def get_path_name(self):
        return "/Game/Test/TestWorld.TestWorld:PersistentLevel.{}".format(self._name)

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

    def get_components_by_class(self, _component_class):
        return list(self.components)

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
        self.possessed_pawn = player
        self.control_rotation = _Rotator()
        self.stop_count = 0
        self.visible = True

    def get_control_rotation(self):
        return self.control_rotation

    def get_pawn(self):
        return self.possessed_pawn

    def get_player_view_point(self):
        return self.player.location, self.control_rotation

    def set_control_rotation(self, value):
        self.control_rotation = value

    def stop_movement(self):
        self.stop_count += 1

    def line_of_sight_to(self, _actor):
        return self.visible


class _World:
    def __init__(self, name="TestWorld"):
        self._name = name

    def get_name(self):
        return self._name

    def get_path_name(self):
        return "/Game/Test/{}.{}".format(self._name, self._name)


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


def _load_runtime(monkeypatch, *, reports_pie=True):
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
            return reports_pie

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

    class ActorComponent:
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
        def acquire_pie_key(world, bound_controller, key):
            return (world, bound_controller, key)

        @staticmethod
        def press_owned_pie_key(owner):
            return DccMcpAutomationLibrary.inject_pie_key(owner[2], True)

        @staticmethod
        def release_owned_pie_key(owner):
            return DccMcpAutomationLibrary.inject_pie_key(owner[2], False)

        @staticmethod
        def stop_owned_pie_navigation(world, bound_controller, pawn):
            if bound_controller.get_pawn() is not pawn:
                return False
            bound_controller.stop_movement()
            return True

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
        def navigate_owned_pie_to_location(bound_world, bound_controller, pawn, target_location):
            assert bound_world is world and bound_controller is controller and pawn is controller.get_pawn()
            navigation_calls.append((bound_controller, target_location))
            return True

        @staticmethod
        def navigate_owned_pie_to_actor(bound_world, bound_controller, pawn, target):
            assert bound_world is world and bound_controller is controller and pawn is controller.get_pawn()
            navigation_calls.append((bound_controller, target))
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
        def start_owned_pie_input_steering_to_location(bound_world, bound_controller, pawn, target_location):
            assert bound_world is world and bound_controller is controller and pawn is controller.get_pawn()
            navigation_calls.append(("input_steering", bound_controller, target_location))
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
        log=lambda _message: None,
        Actor=Actor,
        ActorComponent=ActorComponent,
        Pawn=Pawn,
        PlayerController=PlayerController,
        PlayerStart=PlayerStart,
        UserWidget=UserWidget,
        WidgetBlueprintLibrary=WidgetBlueprintLibrary,
        EditorLevelLibrary=types.SimpleNamespace(get_game_world=lambda: world),
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


def test_observe_uses_shared_game_world_when_pie_flag_is_transient(monkeypatch):
    runtime, _player, _enemy, _door, _controller, _keys, _navigation = _load_runtime(
        monkeypatch,
        reports_pie=False,
    )

    observation = runtime.observe({"include_pawns": True, "max_entities": 8})

    assert observation["world"] == "TestWorld"


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
    assert by_name["playtest_observe"]["read_only"] is False
    assert by_name["playtest_observe"]["annotations"]["read_only_hint"] is False
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
    assert action_properties["expect_movement"]["type"] == "boolean"
    assert action_properties["min_displacement"] == {
        "type": "number",
        "minimum": 0.001,
        "maximum": 1000000,
        "default": 1,
        "description": "Minimum measured player displacement in Unreal centimeters required when movement is expected.",
    }
    assert any(
        example["arguments"].get("expect_movement") is True and example["arguments"].get("min_displacement") == 5
        for example in by_name["playtest_execute_action"]["call_examples"]
    )
    assert action_properties["target_include_hidden"]["default"] is False
    assert action_properties["target_exclude_class_contains"]["maxItems"] == 16
    target_location = by_name["playtest_execute_action"]["input_schema"]["properties"]["target_location"]
    assert target_location["required"] == ["x", "y", "z"]
    assert target_location["additionalProperties"] is False
    telemetry_aliases = episode_properties["telemetry_aliases"]
    assert telemetry_aliases["maxProperties"] == 24
    assert telemetry_aliases["additionalProperties"]["maxItems"] == 8
    skill_text = (_SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert "runtime.possessed" in skill_text
    assert "player_displacement" in skill_text
    assert "Unreal centimeters" in skill_text
    assert 'reason="movement_below_threshold"' in skill_text

    for tool_name in (
        "playtest_episode_control",
        "playtest_observe",
        "playtest_execute_action",
        "playtest_poll_action",
    ):
        output_schema = by_name[tool_name]["output_schema"]
        Draft202012Validator.check_schema(output_schema)
        assert output_schema["required"] == ["success", "message", "error", "prompt", "context"]
        assert output_schema["additionalProperties"] is False

    execute_context = by_name["playtest_execute_action"]["output_schema"]["$defs"]["success_context"]
    assert execute_context["additionalProperties"] is False
    assert {
        "episode_id",
        "action_id",
        "status",
        "action",
        "before_hash",
        "movement_expected",
        "min_displacement",
        "distance_unit",
        "duration",
        "duration_unit",
    }.issubset(execute_context["required"])

    transition_schema = by_name["playtest_poll_action"]["output_schema"]["$defs"]["transition"]
    assert transition_schema["additionalProperties"] is False
    assert {
        "action_id",
        "action",
        "status",
        "elapsed_seconds",
        "movement_expected",
        "min_displacement",
        "distance_unit",
        "duration",
        "duration_unit",
    }.issubset(transition_schema["required"])


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
    possessed = observation["runtime"].pop("possessed")
    session = observation["runtime"].pop("session")
    assert observation["runtime"] == {
        "game_mode_class": "TestGameMode",
        "default_pawn_class": "TestPlayerPawn_C",
        "player_start_count": 4,
        "controller_class": "PlayerController",
        "pawn_class": "PlayerPawn",
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
    assert possessed["name"] == "Player_0"
    assert possessed["class"] == "PlayerPawn"
    assert possessed["is_observed_player"] is True
    assert session["session_identity"].startswith("sha256:")
    assert session["world"]["object_path_hash"].startswith("sha256:")
    assert session["controller"]["identity"].startswith("sha256:")
    assert session["player"]["identity"] == possessed["identity"]
    assert possessed["identity"].startswith("sha256:")
    assert "/Game/" not in str(possessed)
    assert (
        runtime.observe({"include_pawns": True, "max_entities": 8})["runtime"]["possessed"]["identity"]
        == possessed["identity"]
    )
    assert [item["name"] for item in observation["entities"]] == ["Door_0", "Enemy_0"]
    assert observation["entities"][1]["attributes"] == {"health": 40.0}
    assert observation["observation_hash"].startswith("sha256:")


def test_observe_does_not_infer_possession_without_controller_evidence(monkeypatch):
    runtime, _player, _enemy, _door, controller, _keys, _navigation = _load_runtime(monkeypatch)
    controller.possessed_pawn = None

    observation = runtime.observe({"include_pawns": True, "max_entities": 8})

    assert observation["runtime"]["possessed"] is None


def test_observe_exposes_default_health_ammo_and_cooldown_telemetry(monkeypatch):
    runtime, player, enemy, _door, _controller, _keys, _navigation = _load_runtime(monkeypatch)
    player.attributes.update({"MaxHealth": 125.0, "SkillCooldownRemaining": 3.2})
    player.components.append(
        _Actor(
            "WeaponComponent_0",
            "WeaponComponent",
            _Vector(),
            attributes={"CurrentAmmo": 8, "ReserveAmmo": 24},
        )
    )
    enemy.attributes["MaxHealth"] = 80.0

    observation = runtime.observe({"include_pawns": True, "max_entities": 8})

    assert observation["player"]["telemetry"] == {
        "health": 100.0,
        "max_health": 125.0,
        "magazine": 8,
        "reserve_ammo": 24,
        "skill_cooldown_remaining": 3.2,
    }
    assert observation["entities"][0]["telemetry"] == {
        "health": 40.0,
        "max_health": 80.0,
    }
    assert observation["action_availability"] == {"skill": {"ready": False, "remaining_seconds": 3.2}}


def test_observe_supports_bounded_project_telemetry_aliases(monkeypatch):
    runtime, player, _enemy, _door, _controller, _keys, _navigation = _load_runtime(monkeypatch)
    player.attributes["UltimateCooldown"] = 1.5

    episode = runtime.start_episode(
        include_pawns=True,
        max_entities=8,
        telemetry_aliases={"ultimate_cooldown_remaining": ["UltimateCooldown"]},
    )

    assert episode["observation"]["player"]["telemetry"]["ultimate_cooldown_remaining"] == 1.5
    assert episode["observation"]["action_availability"] == {"ultimate": {"ready": False, "remaining_seconds": 1.5}}


def test_episode_rejects_unsafe_telemetry_alias_names(monkeypatch):
    runtime, _player, _enemy, _door, _controller, _keys, _navigation = _load_runtime(monkeypatch)

    invalid_aliases = [
        {"bad-key": ["Health"]},
        {"health": []},
        {"field_{}".format(index): ["Health"] for index in range(25)},
    ]
    for aliases in invalid_aliases:
        try:
            runtime.start_episode(telemetry_aliases=aliases)
        except ValueError as exc:
            assert "telemetry" in str(exc)
        else:
            raise AssertionError("expected unsafe telemetry aliases to fail closed")


def test_episode_accepts_maximum_bounded_project_telemetry_aliases(monkeypatch):
    runtime, _player, _enemy, _door, _controller, _keys, _navigation = _load_runtime(monkeypatch)
    aliases = {"field_{}".format(index): ["health"] for index in range(24)}

    episode = runtime.start_episode(telemetry_aliases=aliases)

    assert episode["observation"]["player"]["telemetry"]["field_23"] == 100.0


def test_attack_transition_reports_observed_damage_and_resource_deltas(monkeypatch):
    runtime, player, enemy, _door, _controller, _keys, _navigation = _load_runtime(monkeypatch)
    clock = [300.0]
    monkeypatch.setattr(runtime.time, "time", lambda: clock[0])
    player.attributes.update({"CurrentAmmo": 8, "ReserveAmmo": 24})
    episode = runtime.start_episode(include_pawns=True, max_entities=8)

    accepted = runtime.execute_action(
        episode["episode_id"],
        "attack_primary_entity",
        target_name="Enemy_0",
        duration=0,
    )
    enemy.attributes["health"] = 25.0
    player.attributes["CurrentAmmo"] = 7
    clock[0] = 300.2

    transition = runtime.poll_action(episode["episode_id"], accepted["action_id"])

    assert transition["combat_feedback"] == {
        "observed_hit": True,
        "damage_dealt": 15.0,
        "target": "Enemy_0",
    }
    assert transition["damage_events"] == [
        {
            "source": "Player_0",
            "target": "Enemy_0",
            "amount": 15.0,
            "time_seconds": 12.5,
            "observed": True,
        }
    ]
    assert {
        (item["scope"], item["actor"], item["field"], item["before"], item["after"], item["delta"])
        for item in transition["telemetry_deltas"]
    } == {
        ("player", "Player_0", "magazine", 8, 7, -1.0),
        ("entity", "Enemy_0", "health", 40.0, 25.0, -15.0),
    }


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


def test_navigation_with_explicit_movement_expectation_stalls_without_displacement(monkeypatch):
    runtime, _player, _enemy, _door, _controller, _keys, _navigation = _load_runtime(monkeypatch)
    clock = [130.0]
    monkeypatch.setattr(runtime.time, "time", lambda: clock[0])
    episode = runtime.start_episode(include_pawns=True, max_entities=8)

    accepted = runtime.execute_action(
        episode["episode_id"],
        "navigate_to_location",
        target_location={"x": 0, "y": 0, "z": 0},
        acceptance_radius=100,
        expect_movement=True,
        min_displacement=5,
        stall_seconds=0.5,
    )
    clock[0] = 130.6

    transition = runtime.poll_action(episode["episode_id"], accepted["action_id"])

    assert transition["status"] == "stalled"
    assert transition["reason"] == "movement_below_threshold"
    assert transition["distance_to_target"] == 0.0
    assert transition["player_displacement"] == 0.0


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

    def restart(actual_controller):
        controller.game_mode.restart_calls.append(actual_controller)
        actual_controller.possessed_pawn = _Actor("RecoveredPawn", "TestPlayerPawn_C", _Vector())
        actual_controller.possessed_pawn._class = controller.game_mode.attributes["default_pawn_class"]

    controller.game_mode.restart_player = restart
    monkeypatch.setattr(
        sys.modules["unreal"].GameplayStatics, "get_player_pawn", lambda _world, _index: controller.get_pawn()
    )

    accepted = runtime.execute_action(episode["episode_id"], "ensure_player_control")
    assert controller.game_mode.restart_calls == [controller]
    clock[0] = 150.2
    transition = runtime.poll_action(episode["episode_id"], accepted["action_id"])

    assert transition["status"] == "completed"
    assert transition["reason"] == "authorized_player_recovery"
    assert controller.get_pawn() is not player


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
    assert navigation[0] == (controller, enemy)
    assert navigation[1][0:2] == ("input_steering", controller)
    assert runtime._vector(navigation[1][2]) == runtime._vector(enemy.get_actor_bounds()[0])
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


def test_move_relative_stalls_when_measured_displacement_is_below_threshold(monkeypatch):
    runtime, player, _enemy, _door, _controller, _keys, _navigation = _load_runtime(monkeypatch)
    clock = [400.0]
    monkeypatch.setattr(runtime.time, "time", lambda: clock[0])
    episode = runtime.start_episode(include_pawns=True, max_entities=8)

    accepted = runtime.execute_action(
        episode["episode_id"],
        "move_relative",
        direction="forward",
        duration=0,
        stall_seconds=0.5,
        min_displacement=5,
    )
    player.location = _Vector(0.25, 0, 0)
    clock[0] = 400.6

    transition = runtime.poll_action(episode["episode_id"], accepted["action_id"])

    assert transition["status"] == "stalled"
    assert transition["reason"] == "movement_below_threshold"
    assert transition["movement_expected"] is True
    assert transition["min_displacement"] == 5.0
    assert transition["player_displacement"] == 0.25
    assert transition["before"] == episode["observation"]
    assert transition["after"]["player"]["location"]["x"] == 0.25
    assert transition["before_hash"] == transition["before"]["observation_hash"]
    assert transition["after_hash"] == transition["after"]["observation_hash"]


def test_move_relative_completes_only_after_measured_displacement(monkeypatch):
    runtime, player, _enemy, _door, _controller, _keys, _navigation = _load_runtime(monkeypatch)
    clock = [500.0]
    monkeypatch.setattr(runtime.time, "time", lambda: clock[0])
    episode = runtime.start_episode(include_pawns=True, max_entities=8)

    accepted = runtime.execute_action(
        episode["episode_id"],
        "move_relative",
        direction="right",
        duration=0,
        expect_movement=True,
        min_displacement=5,
    )
    player.location = _Vector(0, 6, 0)
    clock[0] = 500.2

    transition = runtime.poll_action(episode["episode_id"], accepted["action_id"])

    assert transition["status"] == "completed"
    assert transition["player_location_delta"] == {"x": 0.0, "y": 6.0, "z": 0.0}
    assert transition["player_displacement"] == 6.0
    assert transition["movement_expected"] is True
    assert transition["before"]["player"]["location"]["y"] == 0.0
    assert transition["after"]["player"]["location"]["y"] == 6.0


def test_move_relative_can_preserve_legacy_input_acceptance_when_effect_is_not_required(monkeypatch):
    runtime, _player, _enemy, _door, _controller, _keys, _navigation = _load_runtime(monkeypatch)
    clock = [600.0]
    monkeypatch.setattr(runtime.time, "time", lambda: clock[0])
    episode = runtime.start_episode(include_pawns=True, max_entities=8)

    accepted = runtime.execute_action(
        episode["episode_id"],
        "move_relative",
        direction="forward",
        duration=0,
        expect_movement=False,
    )
    clock[0] = 600.2

    transition = runtime.poll_action(episode["episode_id"], accepted["action_id"])

    assert transition["status"] == "completed"
    assert transition["movement_expected"] is False
    assert transition["player_displacement"] == 0.0


def test_movement_transition_blocks_when_possession_identity_drifts(monkeypatch):
    runtime, player, enemy, _door, controller, _keys, _navigation = _load_runtime(monkeypatch)
    clock = [700.0]
    monkeypatch.setattr(runtime.time, "time", lambda: clock[0])
    episode = runtime.start_episode(include_pawns=True, max_entities=8)
    accepted = runtime.execute_action(
        episode["episode_id"],
        "move_relative",
        direction="forward",
        duration=0,
        expect_movement=True,
    )

    controller.possessed_pawn = enemy
    player.location = _Vector(10, 0, 0)
    clock[0] = 700.2
    transition = runtime.poll_action(episode["episode_id"], accepted["action_id"])

    assert transition["status"] == "blocked"
    assert transition["reason"] == "possession_changed"
    assert transition["before"]["runtime"]["possessed"]["name"] == "Player_0"
    assert transition["after"]["runtime"]["possessed"]["name"] == "Enemy_0"


def test_possession_drift_during_bounded_key_hold_still_releases_key(monkeypatch):
    runtime, _player, _enemy, _door, controller, keys, _navigation = _load_runtime(monkeypatch)
    callbacks = []
    unreal = runtime._unreal()
    monkeypatch.setattr(unreal, "register_slate_post_tick_callback", lambda callback: callbacks.append(callback) or 1)
    monkeypatch.setattr(unreal, "unregister_slate_post_tick_callback", lambda _handle: None)
    monotonic = [100.0]
    monkeypatch.setattr(runtime.time, "monotonic", lambda: monotonic[0])
    episode = runtime.start_episode(include_pawns=True, max_entities=8)

    accepted = runtime.execute_action(
        episode["episode_id"],
        "move_relative",
        direction="forward",
        duration=0.25,
        expect_movement=True,
    )
    assert keys == [("W", True)]

    controller.possessed_pawn = _Actor("Replacement_0", "PlayerPawn", _Vector())
    monotonic[0] = 100.3
    callbacks[0]()

    transition = runtime.poll_action(episode["episode_id"], accepted["action_id"])
    assert transition["status"] == "blocked"
    assert transition["reason"] == "possession_changed"
    assert keys == [("W", True), ("W", False)]

    callbacks[0]()
    assert keys == [("W", True), ("W", False)]


def test_key_release_failure_does_not_hide_possession_drift_transition(monkeypatch):
    runtime, _player, _enemy, _door, controller, keys, _navigation = _load_runtime(monkeypatch)
    callbacks = []
    unreal = runtime._unreal()
    monkeypatch.setattr(unreal, "register_slate_post_tick_callback", lambda callback: callbacks.append(callback) or 1)
    monkeypatch.setattr(unreal, "unregister_slate_post_tick_callback", lambda _handle: None)
    original_inject = unreal.DccMcpAutomationLibrary.inject_pie_key

    def fail_release(key, pressed):
        if not pressed:
            raise RuntimeError("key release failed")
        return original_inject(key, pressed)

    monkeypatch.setattr(unreal.DccMcpAutomationLibrary, "inject_pie_key", fail_release)
    monotonic = [300.0]
    monkeypatch.setattr(runtime.time, "monotonic", lambda: monotonic[0])
    episode = runtime.start_episode(include_pawns=True, max_entities=8)
    accepted = runtime.execute_action(
        episode["episode_id"],
        "move_relative",
        direction="forward",
        duration=0.25,
        expect_movement=True,
    )

    controller.possessed_pawn = _Actor("Replacement_0", "PlayerPawn", _Vector())
    monotonic[0] = 300.3
    callbacks[0]()
    transition = runtime.poll_action(episode["episode_id"], accepted["action_id"])

    assert transition["status"] == "blocked"
    assert transition["reason"] == "possession_changed"
    assert transition["cleanup_errors"] == ["key release failed"]
    assert keys == [("W", True)]


def test_zero_duration_key_release_survives_drift_after_key_down(monkeypatch):
    runtime, _player, _enemy, _door, controller, keys, _navigation = _load_runtime(monkeypatch)
    unreal = runtime._unreal()
    original_inject = unreal.DccMcpAutomationLibrary.inject_pie_key

    def drift_after_key_down(key, pressed):
        accepted = original_inject(key, pressed)
        if pressed:
            controller.possessed_pawn = _Actor("Replacement_0", "PlayerPawn", _Vector())
        return accepted

    monkeypatch.setattr(unreal.DccMcpAutomationLibrary, "inject_pie_key", drift_after_key_down)
    episode = runtime.start_episode(include_pawns=True, max_entities=8)
    accepted = runtime.execute_action(
        episode["episode_id"],
        "move_relative",
        direction="forward",
        duration=0,
        expect_movement=True,
    )

    transition = runtime.poll_action(episode["episode_id"], accepted["action_id"])

    assert transition["status"] == "blocked"
    assert transition["reason"] == "possession_changed"
    assert keys == [("W", True), ("W", False)]


def test_movement_transition_blocks_when_possession_is_lost(monkeypatch):
    runtime, player, _enemy, _door, controller, _keys, _navigation = _load_runtime(monkeypatch)
    clock = [800.0]
    monkeypatch.setattr(runtime.time, "time", lambda: clock[0])
    episode = runtime.start_episode(include_pawns=True, max_entities=8)
    accepted = runtime.execute_action(
        episode["episode_id"],
        "move_relative",
        direction="forward",
        duration=0,
        expect_movement=True,
    )

    controller.possessed_pawn = None
    player.location = _Vector(10, 0, 0)
    clock[0] = 800.2
    transition = runtime.poll_action(episode["episode_id"], accepted["action_id"])

    assert transition["status"] == "blocked"
    assert transition["reason"] == "possession_lost"
    assert transition["after"]["runtime"]["possessed"] is None


def test_finishing_episode_captures_cancelled_pending_transition(monkeypatch):
    runtime, _player, _enemy, _door, _controller, _keys, _navigation = _load_runtime(monkeypatch)
    clock = [900.0]
    monkeypatch.setattr(runtime.time, "time", lambda: clock[0])
    episode = runtime.start_episode(include_pawns=True, max_entities=8)
    accepted = runtime.execute_action(
        episode["episode_id"],
        "move_relative",
        direction="forward",
        duration=0,
        expect_movement=True,
    )
    clock[0] = 900.2

    summary = runtime.finish_episode(episode["episode_id"])

    assert summary["pending_action_ids"] == []
    assert summary["transition_count"] == 1
    assert summary["trace"][0]["action_id"] == accepted["action_id"]
    assert summary["trace"][0]["status"] == "cancelled"
    assert summary["trace"][0]["reason"] == "episode_finished"
    assert summary["trace"][0]["before"]["observation_hash"]
    assert summary["trace"][0]["after"]["observation_hash"]


def test_finishing_episode_releases_bounded_key_exactly_once(monkeypatch):
    runtime, _player, _enemy, _door, _controller, keys, _navigation = _load_runtime(monkeypatch)
    callbacks = []
    unreal = runtime._unreal()
    monkeypatch.setattr(unreal, "register_slate_post_tick_callback", lambda callback: callbacks.append(callback) or 1)
    monkeypatch.setattr(unreal, "unregister_slate_post_tick_callback", lambda _handle: None)
    monotonic = [200.0]
    monkeypatch.setattr(runtime.time, "monotonic", lambda: monotonic[0])
    episode = runtime.start_episode(include_pawns=True, max_entities=8)
    accepted = runtime.execute_action(
        episode["episode_id"],
        "jump",
        duration=0.25,
    )

    summary = runtime.finish_episode(episode["episode_id"])

    assert summary["trace"][0]["action_id"] == accepted["action_id"]
    assert summary["trace"][0]["status"] == "cancelled"
    assert [event for event in keys if event[0] == "SpaceBar"] == [("SpaceBar", True), ("SpaceBar", False)]
    monotonic[0] = 200.3
    callbacks[0]()
    assert [event for event in keys if event[0] == "SpaceBar"] == [("SpaceBar", True), ("SpaceBar", False)]


def test_pie_loss_does_not_reclassify_pending_movement_as_completed(monkeypatch):
    from dcc_mcp_unreal.pie_session import PieSessionUnavailableError

    runtime, _player, _enemy, _door, _controller, _keys, _navigation = _load_runtime(monkeypatch)
    episode = runtime.start_episode(include_pawns=True, max_entities=8)
    accepted = runtime.execute_action(
        episode["episode_id"],
        "move_relative",
        direction="forward",
        duration=0,
        expect_movement=True,
    )

    def unavailable():
        raise PieSessionUnavailableError("PIE world was lost")

    monkeypatch.setattr(runtime, "_pie_context", unavailable)
    try:
        runtime.poll_action(episode["episode_id"], accepted["action_id"])
    except PieSessionUnavailableError as exc:
        assert str(exc) == "PIE world was lost"
    else:
        raise AssertionError("expected PIE loss to remain a typed non-success")

    action = runtime.get_episode(episode["episode_id"])["actions"][accepted["action_id"]]
    assert action["status"] == "pending"
    assert action["transition"] is None


def test_pie_loss_releases_bounded_key_once_without_hiding_primary_error(monkeypatch):
    from dcc_mcp_unreal.pie_session import PieSessionUnavailableError

    runtime, _player, _enemy, _door, _controller, keys, _navigation = _load_runtime(monkeypatch)
    callbacks = []
    unreal = runtime._unreal()
    monkeypatch.setattr(unreal, "register_slate_post_tick_callback", lambda callback: callbacks.append(callback) or 1)
    monkeypatch.setattr(unreal, "unregister_slate_post_tick_callback", lambda _handle: None)
    episode = runtime.start_episode(include_pawns=True, max_entities=8)
    accepted = runtime.execute_action(
        episode["episode_id"],
        "move_relative",
        direction="forward",
        duration=0.25,
        expect_movement=True,
    )

    def unavailable():
        raise PieSessionUnavailableError("PIE world was lost")

    monkeypatch.setattr(runtime, "_pie_context", unavailable)
    try:
        runtime.poll_action(episode["episode_id"], accepted["action_id"])
    except PieSessionUnavailableError as exc:
        assert str(exc) == "PIE world was lost"
    else:
        raise AssertionError("expected PIE loss to remain the primary typed non-success")

    assert keys == [("W", True), ("W", False)]
    callbacks[0]()
    assert keys == [("W", True), ("W", False)]


def test_poll_tool_route_preserves_retryable_pie_loss(monkeypatch):
    from dcc_mcp_unreal.pie_session import PieSessionUnavailableError

    def unavailable(_episode_id, _action_id):
        raise PieSessionUnavailableError("PIE world was lost")

    runtime, *_ = _load_runtime(monkeypatch)
    monkeypatch.setattr(runtime, "poll_action", unavailable)
    monkeypatch.setitem(sys.modules, "_playtest_runtime", runtime)
    script_path = _SKILL_DIR / "scripts" / "playtest_poll_action.py"
    spec = importlib.util.spec_from_file_location("_test_playtest_poll_action", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    result = module.playtest_poll_action(episode_id="episode", action_id="action")

    assert result["success"] is False
    assert result["error"] == "pie_session_unavailable"
    assert result["context"]["retryable"] is True
    assert result["context"]["reason"] == "PIE world was lost"


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


def test_missing_object_path_never_mints_a_possession_identity(monkeypatch):
    runtime, player, _enemy, _door, _controller, _keys, _navigation = _load_runtime(monkeypatch)
    player.get_path_name = lambda: None

    identity = runtime._actor_identity(player, player)

    assert identity["identity"] is None
    assert identity["object_path_hash"] is None


def test_same_path_replacement_has_a_distinct_exact_actor_identity(monkeypatch):
    runtime, player, _enemy, _door, _controller, _keys, _navigation = _load_runtime(monkeypatch)
    replacement = _Actor("Player_0", "PlayerPawn", _Vector(25, 0, 0))

    first = runtime._actor_identity(player, player)
    second = runtime._actor_identity(replacement, replacement)

    assert first["object_path_hash"] == second["object_path_hash"]
    assert first["identity"] != second["identity"]


def test_episode_binding_rejects_same_path_world_controller_and_pawn_replacements(monkeypatch):
    runtime, player, _enemy, _door, controller, _keys, _navigation = _load_runtime(monkeypatch)
    unreal, world, _controller, _player = runtime._pie_context()
    episode = runtime.start_episode(include_pawns=True, max_entities=8)
    binding = runtime.get_episode(episode["episode_id"])["runtime_binding"]

    replacement_world = _World()
    replacement_controller = _Controller(player)
    replacement_player = _Actor("Player_0", "PlayerPawn", _Vector())

    assert runtime._context_change_reason(binding, (unreal, replacement_world, controller, player)) == "world_changed"
    assert (
        runtime._context_change_reason(binding, (unreal, world, replacement_controller, player)) == "controller_changed"
    )
    assert (
        runtime._context_change_reason(binding, (unreal, world, controller, replacement_player)) == "possession_changed"
    )


def test_execute_action_rejects_wrong_world_observation_before_input(monkeypatch):
    runtime, _player, _enemy, _door, _controller, keys, _navigation = _load_runtime(monkeypatch)
    episode = runtime.start_episode(include_pawns=True, max_entities=8)
    wrong_world = copy.deepcopy(episode["observation"])
    wrong_world["world"] = "OtherPIEWorld"
    wrong_world["observation_hash"] = "sha256:wrong-world-before"
    monkeypatch.setattr(runtime, "observe", lambda _selectors: copy.deepcopy(wrong_world))

    try:
        runtime.execute_action(
            episode["episode_id"],
            "move_relative",
            direction="forward",
            duration=0,
            expect_movement=True,
        )
    except RuntimeError as exc:
        assert "world" in str(exc).casefold() or "session" in str(exc).casefold()
    else:
        raise AssertionError("a mismatched PIE world observation must fail closed")

    assert keys == []


def test_execute_action_rechecks_exact_context_after_pre_input_observation(monkeypatch):
    runtime, player, _enemy, _door, controller, keys, _navigation = _load_runtime(monkeypatch)
    unreal, world, _controller, _player = runtime._pie_context()
    episode = runtime.start_episode(include_pawns=True, max_entities=8)
    original_observe = runtime.observe
    replacement_world = _World()

    def observe_then_replace(selectors):
        observation = original_observe(selectors)
        monkeypatch.setattr(
            runtime,
            "_pie_context",
            lambda: (unreal, replacement_world, controller, player),
        )
        return observation

    monkeypatch.setattr(runtime, "observe", observe_then_replace)

    try:
        runtime.execute_action(
            episode["episode_id"],
            "move_relative",
            direction="forward",
            duration=0,
            expect_movement=True,
        )
    except RuntimeError as exc:
        assert "world" in str(exc).casefold() or "session" in str(exc).casefold()
    else:
        raise AssertionError("context replacement between observation and input must fail closed")

    assert keys == []
    assert world is not replacement_world


def test_poll_blocks_displacement_observed_from_a_different_world(monkeypatch):
    runtime, _player, _enemy, _door, _controller, _keys, _navigation = _load_runtime(monkeypatch)
    clock = [1_000.0]
    monkeypatch.setattr(runtime.time, "time", lambda: clock[0])
    episode = runtime.start_episode(include_pawns=True, max_entities=8)
    accepted = runtime.execute_action(
        episode["episode_id"],
        "move_relative",
        direction="forward",
        duration=0,
        expect_movement=True,
        min_displacement=5,
    )
    action = runtime.get_episode(episode["episode_id"])["actions"][accepted["action_id"]]
    wrong_world_after = copy.deepcopy(action["before"])
    wrong_world_after["world"] = "OtherPIEWorld"
    wrong_world_after["player"]["location"]["x"] = 50.0
    wrong_world_after["observation_hash"] = "sha256:wrong-world-after"
    monkeypatch.setattr(runtime, "observe", lambda _selectors: copy.deepcopy(wrong_world_after))
    clock[0] = 1_000.2

    transition = runtime.poll_action(episode["episode_id"], accepted["action_id"])

    assert transition["status"] == "blocked"
    assert transition["reason"] in {"world_changed", "session_changed", "observation_identity_mismatch"}


def test_navigation_never_adopts_a_same_name_replacement_target(monkeypatch):
    runtime, player, _enemy, _door, _controller, _keys, _navigation = _load_runtime(monkeypatch)
    clock = [1_500.0]
    monkeypatch.setattr(runtime.time, "time", lambda: clock[0])
    episode = runtime.start_episode(include_pawns=True, max_entities=8)
    accepted = runtime.execute_action(
        episode["episode_id"],
        "navigate_to_entity",
        target_name="Enemy_0",
        acceptance_radius=100,
    )
    replacement = _Actor("Enemy_0", "EnemyPawn", _Vector())
    monkeypatch.setattr(runtime, "_resolve_target", lambda _world, _player, _selector: replacement)
    player.location = _Vector()
    clock[0] = 1_500.2

    transition = runtime.poll_action(episode["episode_id"], accepted["action_id"])

    assert transition["status"] == "blocked"
    assert transition["reason"] == "target_changed"


def test_wrong_direction_displacement_does_not_prove_relative_input_effect(monkeypatch):
    runtime, player, _enemy, _door, _controller, _keys, _navigation = _load_runtime(monkeypatch)
    clock = [2_000.0]
    monkeypatch.setattr(runtime.time, "time", lambda: clock[0])
    episode = runtime.start_episode(include_pawns=True, max_entities=8)
    accepted = runtime.execute_action(
        episode["episode_id"],
        "move_relative",
        direction="forward",
        duration=0,
        expect_movement=True,
        min_displacement=5,
    )
    player.location = _Vector(0, 6, 0)
    clock[0] = 2_000.2

    transition = runtime.poll_action(episode["episode_id"], accepted["action_id"])

    assert transition["status"] == "blocked"
    assert transition["reason"] == "movement_direction_mismatch"


def test_forward_teleport_like_jump_does_not_prove_relative_input_effect(monkeypatch):
    runtime, player, _enemy, _door, _controller, _keys, _navigation = _load_runtime(monkeypatch)
    clock = [2_500.0]
    monkeypatch.setattr(runtime.time, "time", lambda: clock[0])
    episode = runtime.start_episode(include_pawns=True, max_entities=8)
    accepted = runtime.execute_action(
        episode["episode_id"],
        "move_relative",
        direction="forward",
        duration=0,
        expect_movement=True,
        min_displacement=5,
    )
    player.location = _Vector(100_000, 0, 0)
    clock[0] = 2_500.2

    transition = runtime.poll_action(episode["episode_id"], accepted["action_id"])

    assert transition["status"] == "blocked"
    assert transition["reason"] == "movement_exceeds_causal_bound"


def test_terminal_trace_retains_relative_action_parameters_and_units(monkeypatch):
    runtime, player, _enemy, _door, _controller, _keys, _navigation = _load_runtime(monkeypatch)
    clock = [3_000.0]
    monkeypatch.setattr(runtime.time, "time", lambda: clock[0])
    episode = runtime.start_episode(include_pawns=True, max_entities=8)
    accepted = runtime.execute_action(
        episode["episode_id"],
        "move_relative",
        direction="left",
        duration=0.25,
        expect_movement=True,
        min_displacement=5,
    )
    player.location = _Vector(0, -6, 0)
    clock[0] = 3_000.3

    transition = runtime.poll_action(episode["episode_id"], accepted["action_id"])

    assert transition["status"] == "completed"
    assert transition["direction"] == "left"
    assert transition["duration"] == 0.25
    assert transition["duration_unit"] == "seconds"
    assert transition["distance_unit"] == "centimeters"
    assert transition["causal_displacement"] >= 5.0
    assert transition["max_causal_displacement"] < 100_000.0


def test_execute_and_poll_wrapper_outputs_validate_against_manifest(monkeypatch):
    runtime, player, _enemy, _door, _controller, _keys, _navigation = _load_runtime(monkeypatch)
    clock = [4_000.0]
    monkeypatch.setattr(runtime.time, "time", lambda: clock[0])
    episode = runtime.start_episode(include_pawns=True, max_entities=8)
    monkeypatch.setitem(sys.modules, "_playtest_runtime", runtime)

    control_path = _SKILL_DIR / "scripts" / "playtest_episode_control.py"
    control_spec = importlib.util.spec_from_file_location("_test_playtest_control_schema", control_path)
    control_module = importlib.util.module_from_spec(control_spec)
    assert control_spec.loader is not None
    control_spec.loader.exec_module(control_module)
    current_result = control_module.playtest_episode_control(
        action="current",
        episode_id=episode["episode_id"],
    )

    observe_path = _SKILL_DIR / "scripts" / "playtest_observe.py"
    observe_spec = importlib.util.spec_from_file_location("_test_playtest_observe_schema", observe_path)
    observe_module = importlib.util.module_from_spec(observe_spec)
    assert observe_spec.loader is not None
    observe_spec.loader.exec_module(observe_module)
    observe_result = observe_module.playtest_observe(episode_id=episode["episode_id"])

    execute_path = _SKILL_DIR / "scripts" / "playtest_execute_action.py"
    execute_spec = importlib.util.spec_from_file_location("_test_playtest_execute_schema", execute_path)
    execute_module = importlib.util.module_from_spec(execute_spec)
    assert execute_spec.loader is not None
    execute_spec.loader.exec_module(execute_module)
    execute_result = execute_module.playtest_execute_action(
        episode_id=episode["episode_id"],
        action="move_relative",
        direction="forward",
        duration=0,
        expect_movement=True,
        min_displacement=5,
    )

    player.location = _Vector(6, 0, 0)
    clock[0] = 4_000.2
    poll_path = _SKILL_DIR / "scripts" / "playtest_poll_action.py"
    poll_spec = importlib.util.spec_from_file_location("_test_playtest_poll_schema", poll_path)
    poll_module = importlib.util.module_from_spec(poll_spec)
    assert poll_spec.loader is not None
    poll_spec.loader.exec_module(poll_module)
    poll_result = poll_module.playtest_poll_action(
        episode_id=episode["episode_id"],
        action_id=execute_result["context"]["action_id"],
    )
    finish_result = control_module.playtest_episode_control(
        action="finish",
        episode_id=episode["episode_id"],
    )

    manifest = yaml.safe_load((_SKILL_DIR / "tools.yaml").read_text(encoding="utf-8"))
    by_name = {tool["name"]: tool for tool in manifest["tools"]}
    Draft202012Validator(by_name["playtest_episode_control"]["output_schema"]).validate(current_result)
    Draft202012Validator(by_name["playtest_episode_control"]["output_schema"]).validate(finish_result)
    Draft202012Validator(by_name["playtest_observe"]["output_schema"]).validate(observe_result)
    Draft202012Validator(by_name["playtest_execute_action"]["output_schema"]).validate(execute_result)
    Draft202012Validator(by_name["playtest_poll_action"]["output_schema"]).validate(poll_result)
