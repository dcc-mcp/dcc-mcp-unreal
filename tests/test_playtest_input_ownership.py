"""Disposable receiver model adapted from the independent ownership regressions.

The legacy bridge resolves the current controller; the owned bridge captures
the receiver before delivery. Per-controller held sets expose misdelivery.
"""

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import jsonschema
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(os.environ.get("REVIEW_SCRIPTS", str(ROOT / "src/dcc_mcp_unreal/skills/unreal-playtest-agent/scripts")))


class Cancelled(BaseException):
    pass


class Vector:
    def __init__(self, x=0, y=0, z=0):
        self.x, self.y, self.z = x, y, z

    def __sub__(self, other):
        return Vector(self.x - other.x, self.y - other.y, self.z - other.z)


class Object:
    def __init__(self, name):
        self.name = name
        self.location = Vector()
        self.pawn = None
        self.held = set()
        self.location_error = None

    def get_name(self):
        return self.name

    def get_path_name(self):
        return "/Disposable/PIE/" + self.name

    def get_class(self):
        return NS(get_name=lambda: "FixtureObject")

    def get_actor_location(self):
        if self.location_error:
            raise self.location_error
        return self.location

    def get_actor_rotation(self):
        return NS(pitch=0, yaw=0, roll=0)

    get_control_rotation = get_actor_rotation

    def set_control_rotation(self, rotation):
        pass

    def get_editor_property(self, name):
        if name == "tags":
            return []
        raise AttributeError(name)

    def get_pawn(self):
        return self.pawn


class Harness:
    def __init__(self, monkeypatch):
        self.world = Object("world")
        self.player = Object("player")
        self.controller = Object("controller")
        self.controller.pawn = self.player
        self.original = self.controller
        self.now = 100.0
        self.events = []
        self.callbacks = {}
        self.next_handle = 1
        self.unregister_calls = []
        self.register_error = self.release_error = self.unregister_error = None
        self.after_press = None
        self.actors = []
        self.u = NS(
            Vector=Vector,
            Rotator=lambda **kw: NS(**kw),
            Pawn=Object,
            Actor=Object,
            EditorLevelLibrary=NS(get_game_world=lambda: self.world),
            GameplayStatics=NS(
                get_player_controller=lambda world, index: self.controller,
                get_player_pawn=lambda world, index: self.player,
                get_all_actors_of_class=lambda world, cls: [self.player] + self.actors,
                get_time_seconds=lambda world: self.now,
            ),
            DccMcpAutomationLibrary=NS(
                inject_pie_key=self.inject,
                acquire_pie_key=self.acquire,
                press_owned_pie_key=self.press,
                release_owned_pie_key=self.release,
                stop_pie_navigation=lambda: True,
                stop_owned_pie_navigation=lambda world, controller, pawn: (
                    world is self.world and controller is self.controller and controller.pawn is pawn
                ),
                navigate_pie_to_location=lambda location: True,
            ),
            register_slate_post_tick_callback=self.register,
            unregister_slate_post_tick_callback=self.unregister,
        )
        monkeypatch.setitem(sys.modules, "unreal", self.u)
        spec = importlib.util.spec_from_file_location("reviewer_runtime", SCRIPTS / "_playtest_runtime.py")
        self.r = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.r)
        self.r._EPISODES = {}
        self.r.time = NS(time=lambda: self.now, monotonic=lambda: self.now, strftime=lambda _: "fixture")
        self.episode = self.r.start_episode(max_entities=3)["episode_id"]

    def acquire(self, world, controller, key):
        assert world is self.world and controller is self.controller
        return NS(world=world, controller=controller, key=key)

    def press(self, owner):
        assert owner.controller is self.controller
        return self.inject(owner.key, True)

    def release(self, owner):
        target = owner.controller
        self.events.append((target.name, owner.key, False))
        if self.release_error:
            raise self.release_error
        target.held.discard(owner.key)
        return True

    def inject(self, key, pressed):
        target = self.controller
        self.events.append((target.name if target else None, key, pressed))
        if not pressed and self.release_error:
            raise self.release_error
        if target is None:
            return False
        if pressed:
            target.held.add(key)
        else:
            target.held.discard(key)
        if pressed and self.after_press:
            self.after_press()
        return True

    def register(self, callback):
        if self.register_error:
            raise self.register_error
        handle = self.next_handle
        self.next_handle += 1
        self.callbacks[handle] = callback
        return handle

    def unregister(self, handle):
        self.unregister_calls.append(handle)
        if self.unregister_error:
            raise self.unregister_error
        self.callbacks.pop(handle, None)

    def drift(self):
        self.player = Object("replacement-player")
        self.controller = Object("replacement-controller")
        self.controller.pawn = self.player

    def start(self, duration=0.25, **kwargs):
        self.action = self.r.execute_action(
            self.episode, "move_relative", direction="forward", duration=duration, **kwargs
        )["action_id"]
        return self.action

    def poll(self):
        return self.r.poll_action(self.episode, self.action)

    def tick(self):
        for callback in list(self.callbacks.values()):
            callback()

    def snapshot(self):
        return dict(
            events=self.events,
            original_held=sorted(self.original.held),
            callbacks=len(self.callbacks),
            unregister_calls=self.unregister_calls,
        )


@pytest.fixture
def h(monkeypatch):
    return Harness(monkeypatch)


@pytest.mark.parametrize("trigger", ["tick", "poll", "finish", "zero_duration"])
def test_original_controller_receives_release_after_drift(h, trigger):
    if trigger == "zero_duration":
        h.after_press = h.drift
        h.start(duration=0)
    else:
        h.start()
        h.drift()
        h.now += 0.3
        if trigger == "tick":
            h.tick()
        elif trigger == "poll":
            result = h.poll()
            assert result["reason"] == "controller_changed"
        else:
            h.r.finish_episode(h.episode)
    print(json.dumps(h.snapshot()))
    assert h.events == [("controller", "W", True), ("controller", "W", False)]
    assert not h.original.held


@pytest.mark.parametrize("timing", ["during_hold", "after_tick", "zero_duration"])
def test_finish_forward_has_one_key_up(h, timing):
    h.start(duration=0 if timing == "zero_duration" else 0.25)
    if timing == "after_tick":
        h.now += 0.3
        h.tick()
    result = h.r.finish_episode(h.episode)
    assert result["trace"][0]["status"] == "cancelled"
    print(json.dumps(h.snapshot()))
    assert h.events.count(("controller", "W", False)) == 1


@pytest.mark.parametrize("error_type", [RuntimeError, Cancelled])
def test_registration_failure_releases_pressed_key(h, error_type):
    h.register_error = error_type("registration failed")
    with pytest.raises(error_type):
        h.start()
    print(json.dumps(h.snapshot()))
    assert not h.original.held


@pytest.mark.parametrize("operation", ["poll", "finish", "tick"])
@pytest.mark.parametrize("stage", ["release", "unregister"])
def test_cleanup_baseexception_preserves_primary_result(h, operation, stage):
    h.start()
    setattr(h, stage + "_error", Cancelled("cleanup cancelled"))
    if operation == "poll":
        h.controller.pawn = Object("new-pawn")
    h.now += 0.3
    error = result = None
    try:
        if operation == "poll":
            result = h.poll()
        elif operation == "finish":
            result = h.r.finish_episode(h.episode)
        else:
            h.tick()
    except BaseException as exc:
        error = type(exc).__name__
    print(json.dumps(dict(h.snapshot(), error=error)))
    assert error is None, "cleanup replaced the primary operation"
    if stage == "unregister":
        assert h.callbacks  # The host refused retirement; do not fabricate success.
        assert h.unregister_calls
        transition = result if operation == "poll" else result["trace"][0] if operation == "finish" else None
        if transition is not None:
            assert transition["input_cleanup"]["retirement_attempted"] is True
            assert transition["input_cleanup"]["retirement_completed"] is False
        events = list(h.events)
        h.tick()
        assert h.events == events  # A retained callback is inert for input.
        h.unregister_error = None
        h.tick()
    assert not h.callbacks
    if operation == "poll":
        assert result["reason"] == "possession_changed"


@pytest.mark.parametrize("error_type", [RuntimeError, Cancelled])
def test_observation_failure_releases_input(h, error_type):
    h.start()
    h.player.location_error = error_type("observation lost")
    with pytest.raises(error_type):
        h.poll()
    print(json.dumps(h.snapshot()))
    assert not h.original.held
    assert not h.callbacks


def test_primary_pie_loss_not_masked_by_cleanup_cancellation(h):
    from dcc_mcp_unreal.pie_session import PieSessionUnavailableError

    h.start()
    h.world = None
    h.release_error = Cancelled("cleanup cancelled")
    error = None
    try:
        h.poll()
    except BaseException as exc:
        error = type(exc).__name__
    print(json.dumps(dict(h.snapshot(), error=error)))
    assert error == PieSessionUnavailableError.__name__


def test_drift_transition_conforms_to_output_schema(h):
    from dcc_mcp_unreal.api import unreal_success

    h.start()
    h.controller.pawn = Object("other-pawn")
    result = h.poll()
    manifest = yaml.safe_load((SCRIPTS.parent / "tools.yaml").read_text(encoding="utf-8"))
    schema = next(t["output_schema"] for t in manifest["tools"] if t["name"] == "playtest_poll_action")
    envelope = unreal_success("fixture", episode_id=h.episode, transition=result)
    errors = list(jsonschema.Draft202012Validator(schema).iter_errors(envelope))
    print(json.dumps([dict(path=list(e.absolute_path), message=e.message) for e in errors]))
    assert not errors


def test_legacy_navigation_hold_is_released_on_drift(h):
    h.action = h.r.execute_action(h.episode, "navigate_to_location", target_location=dict(x=2000, y=0, z=0))[
        "action_id"
    ]
    h.now += 1.1
    assert h.poll()["steering_backend"] == "legacy_key"
    assert h.original.held == {"W"}
    h.controller.pawn = Object("new-pawn")
    result = h.poll()
    print(json.dumps(dict(h.snapshot(), reason=result["reason"])))
    assert not h.original.held


@pytest.mark.parametrize(
    "delta,elapsed,status,reason",
    [
        (0, 0.3, "pending", None),
        (0.5, 1.0, "stalled", "movement_below_threshold"),
        (5, 0.3, "completed", None),
        (-5, 0.3, "blocked", "movement_direction_mismatch"),
        (50000, 0.3, "blocked", "movement_exceeds_causal_bound"),
        (5, 2.0, "blocked", "movement_proof_window_expired"),
    ],
)
def test_movement_truth_controls(h, delta, elapsed, status, reason):
    h.start(stall_seconds=0.5)
    h.player.location = Vector(delta, 0, 0)
    h.now += elapsed
    h.tick()
    result = h.poll()
    assert result["status"] == status
    assert result.get("reason") == reason
    if status != "pending":
        assert result["player_location_delta"] == dict(x=delta, y=0.0, z=0.0)
        assert result["player_displacement"] == abs(delta)
        for prefix in ("before", "after"):
            observation = dict(result[prefix])
            recorded = observation.pop("observation_hash")
            assert recorded == h.r._observation_hash(observation)
            assert result[prefix + "_hash"] == recorded
        assert h.poll() is result


def test_default_navigation_compatibility(h):
    h.action = h.r.execute_action(h.episode, "navigate_to_location", target_location=dict(x=20, y=0, z=0))["action_id"]
    result = h.poll()
    assert result["status"] == "completed"
    assert result["movement_expected"] is False


def test_no_expectation_preserves_legacy_acceptance(h):
    h.start(expect_movement=False)
    h.now += 0.3
    assert h.poll()["status"] == "completed"


def test_normal_tick_is_idempotent(h):
    h.start()
    callbacks = list(h.callbacks.values())
    h.now += 0.3
    for _ in range(3):
        for callback in callbacks:
            callback()
    assert h.events == [("controller", "W", True), ("controller", "W", False)]
    assert h.unregister_calls == [1]


def test_ordinary_cleanup_failure_keeps_drift_reason(h):
    h.start()
    h.controller.pawn = Object("new-pawn")
    h.release_error = RuntimeError("synthetic release failed")
    result = h.poll()
    assert result["reason"] == "possession_changed"
    assert result["cleanup_errors"] == ["synthetic release failed"]
    assert not h.callbacks


def test_large_threshold_cannot_expand_physical_causal_bound(h):
    h.start(duration=0, min_displacement=100000)
    h.player.location = Vector(100000, 0, 0)
    h.now += 0.2
    result = h.poll()
    print(json.dumps({k: result[k] for k in ("status", "duration", "player_displacement", "max_causal_displacement")}))
    assert result["status"] == "blocked"


def test_declared_timeout_control(h):
    h.start(timeout_seconds=0.1)
    h.now += 0.11
    assert h.poll()["status"] == "timed_out"
    assert not h.original.held


@pytest.mark.parametrize("component", ["world", "controller", "player"])
def test_replacement_before_input_never_delivers(h, component):
    old = getattr(h, component)
    replacement = Object(old.name)
    replacement.pawn = h.player
    setattr(h, component, replacement)
    if component == "player":
        h.controller.pawn = replacement
    with pytest.raises(RuntimeError):
        h.start()
    assert h.events == []


def test_bounded_observation_and_no_fabricated_possession(h):
    h.actors = [Object("npc" + str(index)) for index in range(20)]
    observation = h.r.observe(h.r.get_episode(h.episode)["selectors"])
    assert len(observation["entities"]) == observation["entity_count"] == 3
    assert observation["runtime"]["possessed"]["is_observed_player"] is True
    h.controller.pawn = None
    assert h.r.observe(h.r.get_episode(h.episode)["selectors"])["runtime"]["possessed"] is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 6])
def test_invalid_duration_rejected_before_input(h, value):
    with pytest.raises(ValueError):
        h.start(duration=value)
    assert h.events == []


def test_arbitrary_action_rejected(h):
    with pytest.raises(ValueError):
        h.r.execute_action(h.episode, "exec", code="raise RuntimeError('must not run')")
    assert h.events == []


def test_failed_release_cannot_report_completed(h, monkeypatch):
    monkeypatch.setattr(h.u.DccMcpAutomationLibrary, "release_owned_pie_key", lambda owner: False)
    h.start(expect_movement=False)
    h.now += 0.3
    result = h.poll()
    assert result["status"] == "blocked"
    assert result["reason"] == "input_cleanup_failed"
    assert result["input_cleanup"]["release_attempted"] is True
    assert result["input_cleanup"]["release_completed"] is False
    assert not h.callbacks


@pytest.mark.parametrize("component", ["world", "controller", "player", "possession", "lost_possession"])
def test_public_wrapper_drift_schema(h, monkeypatch, component):
    h.start()
    if component == "possession":
        h.controller.pawn = Object("other-pawn")
    elif component == "lost_possession":
        h.controller.pawn = None
    else:
        replacement = Object(component)
        replacement.pawn = h.player
        setattr(h, component, replacement)
    monkeypatch.setitem(sys.modules, "_playtest_runtime", h.r)
    spec = importlib.util.spec_from_file_location("owned_poll_tool", SCRIPTS / "playtest_poll_action.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.playtest_poll_action(episode_id=h.episode, action_id=h.action)
    schema = next(
        tool["output_schema"]
        for tool in yaml.safe_load((SCRIPTS.parent / "tools.yaml").read_text(encoding="utf-8"))["tools"]
        if tool["name"] == "playtest_poll_action"
    )
    jsonschema.Draft202012Validator(schema).validate(result)
    assert result["context"]["transition"]["status"] == "blocked"
    assert result["context"]["transition"]["telemetry_deltas"] == []
    assert not h.original.held


def test_missing_owned_bridge_rejects_before_key_down(h, monkeypatch):
    monkeypatch.delattr(h.u.DccMcpAutomationLibrary, "acquire_pie_key")
    with pytest.raises(RuntimeError, match="owned PIE input"):
        h.start()
    assert h.events == []


@pytest.mark.parametrize("stage", ["release", "unregister"])
def test_delivered_key_up_is_never_replayed_after_cleanup_cancellation(h, stage):
    delivered_release = h.release

    def release_then_cancel(owner):
        delivered_release(owner)
        raise Cancelled("cancelled after key-up delivery")

    if stage == "release":
        h.u.DccMcpAutomationLibrary.release_owned_pie_key = release_then_cancel
    else:
        h.unregister_error = Cancelled("retirement refused")
    h.start()
    h.controller.pawn = Object("other")
    result = h.poll()
    assert result["status"] == "blocked"
    assert not h.original.held
    events = list(h.events)
    h.now += 1
    h.tick()
    h.r.finish_episode(h.episode)
    assert h.events == events


def test_finish_after_observation_loss_reports_cleanup_failure(h, monkeypatch):
    monkeypatch.setattr(h.u.DccMcpAutomationLibrary, "release_owned_pie_key", lambda owner: False)
    h.start()
    h.world = None
    result = h.r.finish_episode(h.episode)["trace"][0]
    assert result["status"] == "cancelled"
    assert result["reason"] == "episode_finished_after_observation_loss"
    assert result["input_cleanup"]["release_completed"] is False
    assert result["cleanup_errors"]
    assert not h.callbacks


def test_owner_cannot_be_retargeted_when_receiver_disappears(h, monkeypatch):
    def release_missing(owner):
        # Native weak receiver validation refuses without resolving a replacement.
        assert owner.controller is h.original
        return False

    monkeypatch.setattr(h.u.DccMcpAutomationLibrary, "release_owned_pie_key", release_missing)
    h.start()
    h.drift()
    result = h.poll()
    assert result["status"] == "blocked"
    assert result["reason"] == "controller_changed"
    assert result["input_cleanup"]["release_completed"] is False
    assert h.events == [("controller", "W", True)]
    assert not h.controller.held


def test_native_owned_receiver_contract():
    native = ROOT / "unreal/plugin/Source/DccMcpUnreal/Private/DccMcpAutomationLibrary.cpp"
    # Source-only guard; installed-wheel behavior is covered by the same public tests.
    if not native.exists():
        native = (
            Path(__import__("dcc_mcp_unreal").__file__).parent
            / "_plugin/Source/DccMcpUnreal/Private/DccMcpAutomationLibrary.cpp"
        )
    source = native.read_text(encoding="utf-8")
    delivery = source.split("bool DeliverOwnedKey(", 1)[1].split("struct FDccMcpInputSteeringState", 1)[0]
    assert "State.Receiver.Get()" in delivery
    assert "Receiver->InputKey(" in delivery
    assert "GetPiePlayerController" not in delivery
    assert "InjectSlate" not in delivery
    assert "Receiver->GetOuter() != Controller" in delivery
    release = source.split("bool UDccMcpAutomationLibrary::ReleaseOwnedPieKey(", 1)[1].split(
        "bool UDccMcpAutomationLibrary::InjectPieKey(", 1
    )[0]
    assert "RemoveAndCopyValue" in release
    assert "DeliverOwnedKey(State, false)" in release
    assert "GetPiePlayerController" not in release


def test_synchronous_callback_registration_retires_returned_handle(h):
    register = h.register

    def synchronous(callback):
        handle = register(callback)
        h.now += 1
        callback()
        return handle

    h.u.register_slate_post_tick_callback = synchronous
    h.start()
    assert not h.original.held
    assert not h.callbacks


def test_navigation_cleanup_import_failure_preserves_cancelled_result(h, monkeypatch):
    h.start()
    action = h.r.get_episode(h.episode)["actions"][h.action]
    action["action"] = "navigate_to_location"

    def lost_bridge():
        raise Cancelled("native bridge unavailable during cleanup")

    monkeypatch.setattr(h.r, "_unreal", lost_bridge)
    result = h.r.finish_episode(h.episode)["trace"][0]
    assert result["status"] == "cancelled"
    assert result["cleanup_errors"] == ["native bridge unavailable during cleanup"]
    assert not h.original.held
    assert not h.callbacks
