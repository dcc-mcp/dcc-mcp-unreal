"""Episode lifecycle controls adapted from the independent receiver model."""

import importlib.util
import math
import os
import sys
from pathlib import Path
from types import SimpleNamespace as N

import pytest
import yaml
from jsonschema import Draft202012Validator

SCRIPTS = Path(
    os.environ.get(
        "REVIEW_SCRIPTS",
        str(Path(__file__).resolve().parents[1] / "src/dcc_mcp_unreal/skills/unreal-playtest-agent/scripts"),
    )
)


class Cancel(BaseException):
    pass


@pytest.mark.parametrize("yaw", [0.0, 4.0])
def test_decorated_alignment_roundoff_obeys_schema(m, yaw):
    rotation = N(pitch=0.0, yaw=yaw, roll=0.0)
    m.controller.get_control_rotation = lambda: rotation
    m.player.get_actor_rotation = lambda: rotation
    accepted = m.load("playtest_execute_action").playtest_execute_action(
        episode_id=m.episode, action="move_relative", direction="forward", duration=0.25
    )
    validate(m, "playtest_execute_action", accepted)
    assert accepted["success"]
    m.player.loc = Vec(100 * math.cos(math.radians(yaw)), 100 * math.sin(math.radians(yaw)), 0)
    m.clock += 0.4
    result = m.load("playtest_poll_action").playtest_poll_action(
        episode_id=m.episode, action_id=accepted["context"]["action_id"]
    )
    assert result["success"] and result["context"]["transition"]["status"] == "completed"
    validate(m, "playtest_poll_action", result)


def test_core_catalog_observe_declares_owned_cleanup_mutation():
    import dcc_mcp_core as core

    registry = core.ToolRegistry()
    catalog = core.SkillCatalog(registry)

    def deny_execution(*args, **kwargs):
        pytest.fail("Metadata registration must not execute an action")

    catalog.set_in_process_executor(deny_execution)
    for name in ("unreal-pie", "unreal-playtest-agent"):
        catalog.load_skill_object(core.parse_skill_md(str(SCRIPTS.parent.parent / name)))
    parsed = core.parse_skill_md(str(SCRIPTS.parent))
    declaration = next(tool for tool in parsed.tools if tool.name == "playtest_observe")
    registered = registry.get_action("unreal_playtest_agent__playtest_observe")
    assert declaration.read_only is False
    assert declaration.annotations["readOnlyHint"] is False
    assert registered["annotations"]["read_only_hint"] is False


class Vec:
    def __init__(self, x=0, y=0, z=0):
        self.x, self.y, self.z = x, y, z

    def __sub__(self, other):
        return Vec(self.x - other.x, self.y - other.y, self.z - other.z)


class Obj:
    def __init__(self, name, kind="Actor"):
        self.name, self.kind = name, kind
        self.loc = Vec()
        self.pawn = None
        self.input = N(held=set(), events=[])
        self.failure = None
        self.props = {}
        self.cls = None

    def get_name(self):
        return self.name

    def get_path_name(self):
        return "/Independent/" + self.name

    def get_class(self):
        return self.cls or N(get_name=lambda: self.kind)

    def get_actor_location(self):
        if self.failure:
            raise self.failure
        return self.loc

    def get_actor_rotation(self):
        return N(pitch=0, yaw=0, roll=0)

    def get_control_rotation(self):
        return self.get_actor_rotation()

    def get_pawn(self):
        return self.pawn

    def get_editor_property(self, name):
        if name == "tags":
            return []
        if name in self.props:
            return self.props[name]
        raise AttributeError(name)

    def set_control_rotation(self, value):
        pass


class Model:
    def __init__(self, mp):
        self.world, self.controller, self.player = Obj("world"), Obj("controller"), Obj("pawn")
        self.controller.pawn = self.player
        self.original = self.controller
        self.receiver = self.controller.input
        self.clock = 1000.0
        self.callbacks, self.leases = {}, {}
        self.sequence = 0
        self.register_failure = self.release_failure = self.retire_failure = None
        self.release_after_failure = False
        self.unregister_count = 0
        self.nav_active, self.stop_calls, self.nav_events = False, [], []
        self.native_controller = None
        self.post_press = None
        self.game_mode = Obj("mode")
        self.game_mode.props["default_pawn_class"] = N(get_name=lambda: "PlayablePawn")
        self.game_mode.restart_player = self.restart
        self.u = N(
            Vector=Vec,
            Rotator=lambda **kw: N(**kw),
            Pawn=Obj,
            Actor=Obj,
            EditorLevelLibrary=N(get_game_world=lambda: self.world),
            GameplayStatics=N(
                get_player_controller=lambda w, i: self.controller,
                get_player_pawn=lambda w, i: self.player,
                get_all_actors_of_class=lambda w, c: [self.player],
                get_time_seconds=lambda w: self.clock,
                get_game_mode=lambda w: self.game_mode,
            ),
            register_slate_post_tick_callback=self.register,
            unregister_slate_post_tick_callback=self.unregister,
            DccMcpAutomationLibrary=N(
                acquire_pie_key=self.acquire,
                press_owned_pie_key=self.press,
                release_owned_pie_key=self.release,
                inject_pie_key=lambda *a: pytest.fail("unowned input fallback"),
                navigate_pie_to_location=self.navigate,
                navigate_owned_pie_to_location=self.navigate_owned,
                stop_owned_pie_navigation=self.stop,
            ),
        )
        mp.setitem(sys.modules, "unreal", self.u)
        self.r = self.load("_playtest_runtime")
        self.r._EPISODES = {}
        self.r.time = N(time=lambda: self.clock, monotonic=lambda: self.clock, strftime=lambda _: "independent")
        mp.setitem(sys.modules, "_playtest_runtime", self.r)
        self.mp = mp
        self.episode = self.r.start_episode()["episode_id"]

    def load(self, name):
        spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def acquire(self, world, controller, key):
        self.sequence += 1
        token = "lease-" + str(self.sequence)
        self.leases[token] = (world, controller, controller.pawn, controller.input, key)
        return token

    def press(self, token):
        w, c, p, recv, key = self.leases[token]
        assert w is self.world and c is self.controller and p is c.pawn and recv is c.input
        recv.events.append((key, "down"))
        recv.held.add(key)
        if self.post_press:
            self.post_press()
        return True

    def release(self, token):
        w, c, p, recv, key = self.leases.pop(token)
        recv.events.append((key, "up-attempt"))
        if not self.release_failure or self.release_after_failure:
            recv.held.discard(key)
        if self.release_failure:
            raise self.release_failure
        return True

    def register(self, fn):
        if self.register_failure:
            raise self.register_failure
        self.sequence += 1
        self.callbacks[self.sequence] = fn
        return self.sequence

    def unregister(self, handle):
        self.unregister_count += 1
        if self.retire_failure:
            raise self.retire_failure
        self.callbacks.pop(handle, None)

    def tick(self):
        for fn in list(self.callbacks.values()):
            fn()
        if self.nav_active:
            self.nav_events.append("movement-input")

    def navigate(self, point):
        c = self.native_controller or self.controller
        self.nav_events.append(("navigate", c.name))
        return True

    def steering(self, point):
        c = self.native_controller or self.controller
        self.nav_events.append(("steer", c.name))
        self.nav_active = True
        return True

    def navigate_owned(self, w, c, p, point):
        assert w is self.world and c is self.controller and p is c.pawn
        self.nav_events.append(("navigate", c.name))
        return True

    def steering_owned(self, w, c, p, point):
        assert w is self.world and c is self.controller and p is c.pawn
        self.nav_events.append(("steer", c.name))
        self.nav_active = True
        return True

    def stop(self, w, c, p):
        self.stop_calls.append((w.name, c.name, p.name))
        self.nav_active = False
        return w is self.world and c is self.controller and p is c.pawn

    def restart(self, c):
        self.player = Obj("restored-player", "PlayablePawn")
        self.player.cls = self.game_mode.props["default_pawn_class"]
        c.pawn = self.player

    def start(self, **kw):
        args = dict(direction="forward", duration=0.25)
        args.update(kw)
        self.action = self.r.execute_action(self.episode, "move_relative", **args)["action_id"]

    def nav(self, native=False):
        if native:
            self.u.DccMcpAutomationLibrary.start_pie_input_steering_to_location = self.steering
            self.u.DccMcpAutomationLibrary.start_owned_pie_input_steering_to_location = self.steering_owned
        self.action = self.r.execute_action(
            self.episode, "navigate_to_location", target_location=dict(x=2000, y=0, z=0)
        )["action_id"]
        self.clock += 1.1
        return self.poll()

    def poll(self):
        return self.r.poll_action(self.episode, self.action)

    def drift(self, kind):
        if kind == "input":
            self.controller.input = N(held=set(), events=[])
        elif kind == "pawn":
            self.controller.pawn = Obj("replacement")
        elif kind == "world":
            self.world = Obj("replacement-world")
        elif kind == "controller":
            self.controller = Obj("replacement-controller")
            self.controller.pawn = self.player

    def snapshot(self):
        return dict(
            events=self.receiver.events,
            held=sorted(self.receiver.held),
            callbacks=len(self.callbacks),
            unregister=self.unregister_count,
            nav_active=self.nav_active,
            nav_events=self.nav_events,
        )


@pytest.fixture
def m(monkeypatch):
    return Model(monkeypatch)


def validate(m, name, result):
    tools = yaml.safe_load((SCRIPTS.parent / "tools.yaml").read_text(encoding="utf8"))["tools"]
    schema = next(t["output_schema"] for t in tools if t["name"] == name)
    Draft202012Validator(schema).validate(result)


@pytest.mark.parametrize("drift", ["world", "controller", "pawn", "input"])
@pytest.mark.parametrize("terminal", ["tick", "poll", "finish", "zero"])
def test_owned_receiver_all_terminal_routes(m, drift, terminal):
    if terminal == "zero":
        m.post_press = lambda: m.drift(drift)
    m.start(duration=0 if terminal == "zero" else 0.25, expect_movement=False)
    if terminal != "zero":
        m.drift(drift)
    m.clock += 0.3
    if terminal == "tick":
        m.tick()
    elif terminal == "poll":
        m.poll()
    else:
        m.r.finish_episode(m.episode)
    print(m.snapshot())
    assert m.receiver.events == [("W", "down"), ("W", "up-attempt")]
    assert not m.receiver.held and not m.callbacks


@pytest.mark.parametrize("error_type", [RuntimeError, Cancel])
@pytest.mark.parametrize("phase", ["register", "poll", "tick", "finish", "zero"])
def test_exception_cleanup_and_primary_preservation(m, error_type, phase):
    error = error_type("primary-failure")
    if phase == "register":
        m.register_failure = error
        with pytest.raises(error_type) as caught:
            m.start()
        assert caught.value is error
    elif phase == "zero":
        m.post_press = lambda: m.drift("controller")
        m.start(duration=0)
    else:
        m.start()
        if phase == "poll":
            m.player.failure = error
            with pytest.raises(error_type) as caught:
                m.poll()
            assert caught.value is error
        elif phase == "tick":
            m.r._pie_context = lambda: (_ for _ in ()).throw(error)
            m.tick()
        else:
            m.player.failure = error
            result = m.r.finish_episode(m.episode)
            assert result["trace"][0]["status"] == "cancelled"
    assert not m.receiver.held and not m.callbacks


@pytest.mark.parametrize("error_type", [RuntimeError, Cancel])
@pytest.mark.parametrize("phase", ["poll", "tick", "finish"])
def test_refused_retirement_is_inert_truthful_and_eventually_retires(m, error_type, phase):
    m.start()
    m.retire_failure = error_type("refused")
    m.drift("pawn")
    m.clock += 0.3
    if phase == "tick":
        m.tick()
        result = m.poll()
    elif phase == "poll":
        result = m.poll()
    else:
        result = m.r.finish_episode(m.episode)["trace"][0]
    assert result["status"] in ("blocked", "cancelled")
    assert result["input_cleanup"] == dict(
        release_attempted=True, release_completed=True, retirement_attempted=True, retirement_completed=False
    )
    assert result["cleanup_errors"] == ["refused"]
    assert m.callbacks and not m.receiver.held
    before = list(m.receiver.events)
    for _ in range(3):
        m.tick()
    assert m.receiver.events == before and m.callbacks
    m.retire_failure = None
    m.tick()
    assert not m.callbacks and m.receiver.events == before
    print(result["input_cleanup"], m.snapshot())


@pytest.mark.parametrize("error_type", [RuntimeError, Cancel])
def test_attempted_keyup_never_replayed_after_post_delivery_error(m, error_type):
    m.start()
    m.release_failure = error_type("post-keyup")
    m.release_after_failure = True
    m.drift("pawn")
    result = m.poll()
    assert result["reason"] == "possession_changed"
    assert result["input_cleanup"]["release_completed"] is False
    m.tick()
    m.r.finish_episode(m.episode)
    assert m.receiver.events == [("W", "down"), ("W", "up-attempt")]


def test_legacy_navigation_drift_cleans_once(m):
    assert m.nav()["steering_backend"] == "legacy_key"
    m.drift("pawn")
    result = m.poll()
    assert result["reason"] == "possession_changed"
    assert not m.receiver.held and not m.callbacks
    assert m.stop_calls[-1][2] == "pawn"
    m.r.finish_episode(m.episode)
    assert m.receiver.events == [("W", "down"), ("W", "up-attempt")]


@pytest.mark.parametrize(
    "delta,elapsed,threshold,status,reason",
    [
        (0, 0.3, 1, "pending", None),
        (0, 1, 1, "stalled", "movement_below_threshold"),
        (5, 0.3, 1, "completed", None),
        (-5, 0.3, 1, "blocked", "movement_direction_mismatch"),
        (100000, 0.3, 100000, "blocked", "movement_exceeds_causal_bound"),
        (5, 2, 1, "blocked", "movement_proof_window_expired"),
    ],
)
def test_causal_truth_and_schema(m, delta, elapsed, threshold, status, reason):
    m.start(min_displacement=threshold, stall_seconds=0.5)
    m.player.loc = Vec(delta)
    m.clock += elapsed
    m.tick()
    result = m.load("playtest_poll_action").playtest_poll_action(episode_id=m.episode, action_id=m.action)
    validate(m, "playtest_poll_action", result)
    transition = result["context"]["transition"]
    assert transition["status"] == status and transition.get("reason") == reason
    assert transition["max_causal_displacement"] == 3000


@pytest.mark.parametrize("drift", ["world", "controller", "pawn"])
def test_terminal_drift_schemas_and_no_cross_session_telemetry(m, drift):
    m.start()
    m.drift(drift)
    result = m.load("playtest_poll_action").playtest_poll_action(episode_id=m.episode, action_id=m.action)
    validate(m, "playtest_poll_action", result)
    t = result["context"]["transition"]
    assert t["status"] == "blocked" and t["telemetry_deltas"] == [] and t["player_displacement"] is None


@pytest.mark.parametrize("member", ["acquire_pie_key", "press_owned_pie_key", "release_owned_pie_key"])
def test_missing_bridge_fails_closed(m, member):
    delattr(m.u.DccMcpAutomationLibrary, member)
    with pytest.raises(RuntimeError):
        m.start()
    assert not m.receiver.events


@pytest.mark.parametrize("timing", ["held", "tick", "zero"])
def test_finish_no_duplicate_keyup(m, timing):
    m.start(duration=0 if timing == "zero" else 0.25)
    if timing == "tick":
        m.clock += 0.3
        m.tick()
    result = m.load("playtest_episode_control").playtest_episode_control(action="finish", episode_id=m.episode)
    validate(m, "playtest_episode_control", result)
    assert m.receiver.events == [("W", "down"), ("W", "up-attempt")]


# Independent negative contract probes: preserve failures rather than relax assertions.
@pytest.mark.parametrize("error_type", [RuntimeError, Cancel])
def test_observe_api_failure_must_cleanup_owned_hold(m, error_type):
    m.start(duration=5)
    m.player.failure = error_type("observation-failed")
    try:
        result = m.load("playtest_observe").playtest_observe(episode_id=m.episode)
    except Cancel:
        result = {"cancelled": True}
    print(result, m.snapshot())
    assert not m.receiver.held and not m.callbacks


@pytest.mark.parametrize("error_type", [RuntimeError, Cancel])
def test_native_navigation_poll_exception_must_stop_owned_ticker(m, error_type):
    assert m.nav(native=True)["steering_backend"] == "native_pawn_movement"
    error = error_type("observation-failed")
    m.player.failure = error
    with pytest.raises(error_type) as caught:
        m.poll()
    assert caught.value is error
    before = len(m.nav_events)
    m.tick()
    print(m.snapshot(), m.stop_calls)
    assert not m.nav_active and len(m.nav_events) == before


def test_location_navigation_must_not_use_other_native_controller(m):
    m.native_controller = Obj("other-local-controller")
    m.action = m.r.execute_action(m.episode, "navigate_to_location", target_location=dict(x=0, y=0, z=0))["action_id"]
    result = m.poll()
    print(result["status"], m.snapshot())
    assert ("navigate", "other-local-controller") not in m.nav_events


def test_native_steering_must_not_resolve_another_controller(m):
    m.native_controller = Obj("other-local-controller")
    assert m.nav(native=True)["steering_backend"] == "native_pawn_movement"
    assert ("steer", "other-local-controller") not in m.nav_events
    assert ("steer", "controller") in m.nav_events


def test_explicit_player_recovery_remains_usable(m):
    m.player.kind = "SpectatorPawn"
    m.episode = m.r.start_episode()["episode_id"]
    m.action = m.r.execute_action(m.episode, "ensure_player_control")["action_id"]
    m.clock += 0.2
    result = m.poll()
    print(result["status"], result.get("reason"))
    assert result["status"] == "completed"
    assert result["reason"] == "authorized_player_recovery"
    assert result["player_displacement"] is None and result["telemetry_deltas"] == []
    assert m.r.observe_episode(m.r.get_episode(m.episode))["runtime"]["pawn_class"] == "PlayablePawn"
    assert m.r.execute_action(m.episode, "wait")["status"] == "pending"


def test_recovery_does_not_adopt_later_external_replacement(m):
    m.player.kind = "SpectatorPawn"
    m.episode = m.r.start_episode()["episode_id"]
    m.action = m.r.execute_action(m.episode, "ensure_player_control")["action_id"]
    m.restart(m.controller)
    result = m.poll()
    assert result["status"] == "blocked"
    assert result["reason"] == "possession_changed"


def test_recovery_without_actual_pawn_change_is_not_success(m):
    m.player.kind = "SpectatorPawn"
    m.episode = m.r.start_episode()["episode_id"]
    m.game_mode.restart_player = lambda controller: None
    with pytest.raises(RuntimeError, match="did not synchronously possess"):
        m.r.execute_action(m.episode, "ensure_player_control")


@pytest.mark.parametrize("configured", [True, False])
def test_decorated_recovery_uses_configured_uclass_not_short_name(m, configured):
    class PawnClass:
        def __init__(self, package):
            self.package = package

        def get_name(self):
            return "PlayablePawn_C"

        def get_path_name(self):
            return self.package + ".PlayablePawn_C"

    expected_class = PawnClass("/Game/Configured/PlayablePawn")
    other_class = PawnClass("/Game/OtherPackage/PlayablePawn")
    assert expected_class.get_name() == other_class.get_name()
    m.game_mode.props["default_pawn_class"] = expected_class
    m.player.kind = "SpectatorPawn"
    m.episode = m.r.start_episode()["episode_id"]
    previous_binding = m.r.get_episode(m.episode)["runtime_binding"]

    def restart(controller):
        m.restart(controller)
        m.player.cls = expected_class if configured else other_class

    m.game_mode.restart_player = restart
    accepted = m.load("playtest_execute_action").playtest_execute_action(
        episode_id=m.episode, action="ensure_player_control"
    )
    validate(m, "playtest_execute_action", accepted)
    assert accepted["success"] is configured
    if not configured:
        assert m.r.get_episode(m.episode)["runtime_binding"] is previous_binding
        return
    result = m.load("playtest_poll_action").playtest_poll_action(
        episode_id=m.episode, action_id=accepted["context"]["action_id"]
    )
    validate(m, "playtest_poll_action", result)
    transition = result["context"]["transition"]
    assert transition["status"] == "completed" and transition["reason"] == "authorized_player_recovery"
    assert transition["player_displacement"] is None and transition["telemetry_deltas"] == []
    assert m.r.get_episode(m.episode)["runtime_binding"]["_player_ref"] is m.player


@pytest.mark.parametrize("tool", ["playtest_observe", "playtest_poll_action"])
@pytest.mark.parametrize("error_type", [RuntimeError, Cancel])
def test_public_primary_error_retains_navigation_cleanup_diagnostics(m, tool, error_type):
    m.nav(native=True)

    def refused(w, c, p):
        raise Cancel("navigation cleanup refused")

    m.u.DccMcpAutomationLibrary.stop_owned_pie_navigation = refused
    m.player.failure = error_type("primary observation failure")
    result = getattr(m.load(tool), tool)(episode_id=m.episode, action_id=m.action)
    assert result["_meta"]["dcc.error"]["message"] == "primary observation failure"
    assert result["context"]["cleanup"][0]["cleanup_errors"] == ["navigation cleanup refused"]
    validate(m, tool, result)


@pytest.mark.parametrize(
    "tool,kwargs",
    [
        ("playtest_observe", dict(episode_id="missing")),
        ("playtest_poll_action", dict(episode_id="missing", action_id="missing")),
        ("playtest_execute_action", dict(episode_id="missing", action="wait")),
        ("playtest_episode_control", dict(episode_id="missing", action="finish")),
    ],
)
def test_public_error_envelopes_conform_to_actual_schema(m, tool, kwargs):
    result = getattr(m.load(tool), tool)(**kwargs)
    assert result["success"] is False
    print(tool, sorted(result))
    validate(m, tool, result)


@pytest.mark.parametrize("error_type", [RuntimeError, Cancel])
def test_failed_observe_releases_only_its_own_episode_hold(m, error_type):
    m.start(duration=5)
    other = m.r.start_episode()["episode_id"]
    m.r.execute_action(other, "attack_primary", duration=5)
    m.player.failure = error_type("observation failed")
    result = m.load("playtest_observe").playtest_observe(episode_id=m.episode)
    assert result["success"] is False
    assert m.receiver.held == {"LeftMouseButton"}
    assert len(m.callbacks) == 1
    validate(m, "playtest_observe", result)


@pytest.mark.parametrize("error_type", [RuntimeError, Cancel])
def test_observe_failure_retires_owned_native_steering(m, error_type):
    m.nav(native=True)
    m.player.failure = error_type("observation failed")
    result = m.load("playtest_observe").playtest_observe(episode_id=m.episode)
    before = list(m.nav_events)
    m.tick()
    assert not m.nav_active and m.nav_events == before
    assert result["context"]["cleanup"][0]["navigation_cleanup"] == {
        "stop_attempted": True,
        "stop_completed": True,
    }


@pytest.mark.parametrize(
    "tool", ["playtest_observe", "playtest_poll_action", "playtest_execute_action", "playtest_episode_control"]
)
def test_actual_success_envelopes_and_closed_metadata_schema(m, tool):
    if tool == "playtest_episode_control":
        args = dict(action="current", episode_id=m.episode)
    elif tool == "playtest_execute_action":
        args = dict(action="wait", episode_id=m.episode)
    elif tool == "playtest_poll_action":
        m.start(expect_movement=False)
        m.clock += 0.3
        args = dict(episode_id=m.episode, action_id=m.action)
    else:
        args = dict(episode_id=m.episode)
    result = getattr(m.load(tool), tool)(**args)
    assert result["success"] is True
    validate(m, tool, result)
    for meta in (
        {"unexpected": {}},
        {"dcc.error": {"type": 123, "message": "bad"}},
        {"dcc.error": {"type": "Error", "message": "bad", "extra": True}},
    ):
        with pytest.raises(Exception):
            validate(m, tool, dict(result, _meta=meta))


def test_authorized_recovery_public_schema(m):
    m.player.kind = "SpectatorPawn"
    m.episode = m.r.start_episode()["episode_id"]
    accepted = m.load("playtest_execute_action").playtest_execute_action(
        episode_id=m.episode, action="ensure_player_control"
    )
    assert accepted["success"] is True
    validate(m, "playtest_execute_action", accepted)
    result = m.load("playtest_poll_action").playtest_poll_action(
        episode_id=m.episode, action_id=accepted["context"]["action_id"]
    )
    assert result["context"]["transition"]["reason"] == "authorized_player_recovery"
    validate(m, "playtest_poll_action", result)


def test_each_poll_failure_retires_any_new_owned_navigation(m):
    m.u.DccMcpAutomationLibrary.start_owned_pie_input_steering_to_location = m.steering_owned
    m.action = m.r.execute_action(m.episode, "navigate_to_location", target_location=dict(x=2000, y=0, z=0))[
        "action_id"
    ]
    m.player.failure = RuntimeError("first observation failure")
    with pytest.raises(RuntimeError):
        m.poll()
    m.player.failure = None
    m.clock += 1.1
    assert m.poll()["steering_backend"] == "native_pawn_movement"
    m.player.failure = Cancel("second observation failure")
    with pytest.raises(Cancel):
        m.poll()
    before = list(m.nav_events)
    m.tick()
    assert not m.nav_active and m.nav_events == before
