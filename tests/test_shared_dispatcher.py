"""Exercise the real Core dispatcher through a controlled, single Slate pump.

These are host-contract tests, not evidence of execution in Unreal Editor.
"""

import sys
import threading
import time
from types import SimpleNamespace

import pytest
from dcc_mcp_core import ChunkedRunner, HostUiDispatcherBase

from dcc_mcp_unreal.server import UnrealMainThreadDispatcher, _make_execution_bridge


@pytest.fixture
def slate(monkeypatch):
    host_thread = threading.get_ident()
    callbacks = []
    removed = []

    def register(callback):
        assert threading.get_ident() == host_thread
        callbacks.append(callback)
        return "owned-slate-tick"

    def unregister(handle):
        assert threading.get_ident() == host_thread
        removed.append(handle)

    monkeypatch.setitem(
        sys.modules,
        "unreal",
        SimpleNamespace(
            register_slate_post_tick_callback=register,
            unregister_slate_post_tick_callback=unregister,
        ),
    )
    return SimpleNamespace(callbacks=callbacks, removed=removed, host_thread=host_thread)


def wait_until(predicate):
    deadline = time.monotonic() + 2
    while not predicate():
        assert time.monotonic() < deadline, "worker did not reach the expected checkpoint"
        time.sleep(0.001)


def test_public_core_contract_and_single_initialization(slate, monkeypatch):
    original = HostUiDispatcherBase.__init__
    initialized = []

    def initialize(self, **kwargs):
        initialized.append(self)
        original(self, **kwargs)

    monkeypatch.setattr(HostUiDispatcherBase, "__init__", initialize)
    dispatcher, bridge = _make_execution_bridge(1)
    assert bridge.dispatcher is dispatcher
    assert isinstance(dispatcher, HostUiDispatcherBase)
    assert initialized == [dispatcher]
    assert len(slate.callbacks) == 1
    for name in ("submit_callable", "submit_async_callable", "submit_chunked_runner", "cancel", "shutdown"):
        assert callable(getattr(dispatcher, name))
    dispatcher.close()


def test_chunk_fairness_with_python_http_and_scene_work(slate):
    dispatcher = UnrealMainThreadDispatcher()
    events = []
    terminals = []

    def record(label):
        assert threading.get_ident() == slate.host_thread
        events.append(label)

    def steps(label):
        for i in range(2):
            yield lambda i=i: record((label, i))

    runners = [ChunkedRunner(steps(label), total=2) for label in ("a", "b")]
    for label, runner in zip(("a", "b"), runners):
        dispatcher.submit_chunked_runner(label, runner, on_complete=terminals.append)
    dispatcher.submit_async_callable("python", lambda: record("python"))
    http = [lambda: record("http")]

    def http_tick(max_jobs):
        assert max_jobs == 1
        http.pop(0)()
        return SimpleNamespace(jobs_executed=1)

    dispatcher.attach_http_dispatcher(
        SimpleNamespace(
            pending=lambda: len(http),
            tick=http_tick,
            shutdown=http.clear,
        )
    )
    dispatcher.attach_scene_publisher(lambda: record("scene"))
    for index, expected in enumerate((("a", 0), ("b", 0), ("a", 1), ("b", 1))):
        slate.callbacks[0](0)
        chunks = [event for event in events if isinstance(event, tuple)]
        assert chunks[-1] == expected
        assert len(chunks) == index + 1
        if index == 0:
            assert events == [("a", 0), "http", "python", "scene"]
    for _ in range(2):
        slate.callbacks[0](0)
    assert len(terminals) == 2
    assert all(result["success"] for result in terminals)
    assert len(slate.callbacks) == 1
    dispatcher.close()


def test_tick_has_one_positive_cooperative_budget(slate, monkeypatch):
    dispatcher = UnrealMainThreadDispatcher()
    drains = []
    monkeypatch.setattr(dispatcher, "drain_queue", lambda *, budget_ms: drains.append(budget_ms))
    slate.callbacks[0](0)
    assert len(drains) == 1 and drains[0] > 0
    dispatcher.close()


def test_over_budget_step_is_not_preempted_or_run_twice(slate, monkeypatch):
    import dcc_mcp_unreal.server as server_module

    monkeypatch.setattr(server_module, "_DISPATCH_BUDGET_MS", 0.1)
    dispatcher = UnrealMainThreadDispatcher()
    calls = []

    def step():
        time.sleep(0.01)
        calls.append("finished")

    dispatcher.submit_chunked_runner("slow", ChunkedRunner(iter([step, step]), total=2))
    slate.callbacks[0](0)
    assert calls == ["finished"]
    dispatcher.close()


@pytest.mark.parametrize("during_step", [False, True])
def test_chunk_cancel_has_one_terminal_checkpoint(slate, during_step):
    dispatcher = UnrealMainThreadDispatcher()
    effects = []
    outcomes = []

    def first():
        effects.append("first")
        assert dispatcher.cancel("cancel-me")

    runner = ChunkedRunner(iter([first, lambda: effects.append("second")]), total=2)
    dispatcher.submit_chunked_runner("cancel-me", runner, on_complete=outcomes.append)
    if not during_step:
        assert dispatcher.cancel("cancel-me")
    for _ in range(3):
        slate.callbacks[0](0)
    assert effects == (["first"] if during_step else [])
    assert len(outcomes) == 1
    assert outcomes[0]["error"] == "Cancelled"
    assert runner.outcome.status == "cancelled"
    dispatcher.close()


def test_chunk_exception_does_not_stop_other_jobs(slate):
    dispatcher = UnrealMainThreadDispatcher()
    outcomes = []
    other = []

    def fail():
        raise ValueError("bounded-step-failed")

    dispatcher.submit_chunked_runner("bad", ChunkedRunner(iter([fail])), on_complete=outcomes.append)
    dispatcher.submit_async_callable("other", lambda: other.append(True))
    slate.callbacks[0](0)
    assert other == [True]
    assert len(outcomes) == 1 and not outcomes[0]["success"]
    assert "bounded-step-failed" in outcomes[0]["error"]
    dispatcher.close()


def test_worker_close_wakes_waiters_then_detaches_on_host(slate):
    dispatcher = UnrealMainThreadDispatcher(timeout_secs=1)
    outcomes = []
    effects = []
    worker = threading.Thread(
        target=lambda: outcomes.append(
            dispatcher.submit_callable(
                "waiting",
                lambda: effects.append("unexpected"),
                timeout_ms=1000,
            )
        )
    )
    worker.start()
    wait_until(lambda: dispatcher.queue_size() == 1)
    runner = ChunkedRunner(iter([lambda: effects.append("chunk")]))
    dispatcher.submit_chunked_runner("chunk", runner)
    shutdowns = []
    dispatcher.attach_http_dispatcher(
        SimpleNamespace(
            pending=lambda: 0,
            tick=lambda _: None,
            shutdown=lambda: shutdowns.append(True),
        )
    )
    closer = threading.Thread(target=dispatcher.close)
    closer.start()
    worker.join(1)
    assert not worker.is_alive()
    assert outcomes[0]["error"] == "Interrupted"
    assert runner.outcome.status == "cancelled"
    assert slate.removed == []
    slate.callbacks[0](0)
    closer.join(1)
    assert not closer.is_alive()
    dispatcher.close()
    assert slate.removed == ["owned-slate-tick"]
    assert shutdowns == [True]
    assert effects == []
    for affinity in ("main", "any"):
        assert not dispatcher.submit_callable("closed", lambda: effects.append(True), affinity)["success"]
        assert not dispatcher.submit_async_callable("closed", lambda: effects.append(True), affinity=affinity)[
            "success"
        ]
    assert not dispatcher.submit_chunked_runner("closed", ChunkedRunner(iter([])))["success"]
    with pytest.raises(RuntimeError, match="closed"):
        dispatcher.dispatch_callable(lambda: effects.append(True))
    assert effects == []


def test_timeout_cancels_queued_python_work(slate):
    dispatcher = UnrealMainThreadDispatcher(timeout_secs=0.01)
    outcomes = []
    effects = []
    worker = threading.Thread(
        target=lambda: outcomes.append(
            dispatcher.submit_callable(
                "timeout",
                lambda: effects.append(True),
                timeout_ms=5,
            )
        )
    )
    worker.start()
    worker.join(1)
    assert not worker.is_alive()
    assert "Timeout" in outcomes[0]["error"]
    slate.callbacks[0](0)
    assert effects == []
    dispatcher.close()


def test_close_from_running_chunk_finishes_cancellation_before_detach(slate):
    dispatcher = UnrealMainThreadDispatcher()
    effects = []
    terminals = []

    def step():
        effects.append("started")
        dispatcher.close()
        assert slate.removed == []
        effects.append("returned")

    runner = ChunkedRunner(iter([step, lambda: effects.append("unexpected")]))
    dispatcher.submit_chunked_runner("closing", runner, on_complete=terminals.append)
    slate.callbacks[0](0)
    assert effects == ["started", "returned"]
    assert runner.outcome.status == "cancelled"
    assert len(terminals) == 1 and terminals[0]["error"] == "Cancelled"
    assert dispatcher.queue_size() == 0
    assert slate.removed == ["owned-slate-tick"]
    dispatcher.close()
    assert len(terminals) == 1


def test_nested_drain_does_not_advance_another_chunk(slate):
    dispatcher = UnrealMainThreadDispatcher()
    outcomes = []
    other = []
    runner = ChunkedRunner(iter([lambda: dispatcher.drain_queue(4)]))
    dispatcher.submit_chunked_runner("recursive", runner, on_complete=outcomes.append)
    dispatcher.submit_chunked_runner("other", ChunkedRunner(iter([lambda: other.append(True)])))
    slate.callbacks[0](0)
    assert not other
    assert len(outcomes) == 1 and "Recursive" in outcomes[0]["error"]
    dispatcher.close()


@pytest.mark.parametrize("close_during_step", [False, True])
def test_nested_slate_tick_defers_work_and_owned_cleanup(slate, close_during_step):
    dispatcher = UnrealMainThreadDispatcher()
    effects = []
    terminals = []
    other = []
    scenes = []
    dispatcher.attach_scene_publisher(lambda: scenes.append("published"))

    def step():
        effects.append("started")
        if close_during_step:
            dispatcher.close()
        slate.callbacks[0](3)
        assert other == [] and scenes == [] and slate.removed == []
        effects.append("returned")

    runner = ChunkedRunner(iter([step]), total=1)
    dispatcher.submit_chunked_runner("nested-tick", runner, on_complete=terminals.append)
    dispatcher.submit_chunked_runner("other", ChunkedRunner(iter([lambda: other.append("advanced")])))
    slate.callbacks[0](0)
    assert effects == ["started", "returned"]
    assert other == []
    if close_during_step:
        assert scenes == [] and slate.removed == ["owned-slate-tick"]
    else:
        assert scenes == ["published"] and slate.removed == []
        for _ in range(3):
            slate.callbacks[0](0)
        assert other == ["advanced"]
    assert len(terminals) == 1
    if close_during_step:
        assert terminals[0]["error"] == "Cancelled", terminals[0]
    else:
        assert terminals[0]["success"], terminals[0]
    dispatcher.close()
    assert len(terminals) == 1


def test_missing_slate_rejects_before_enqueue(monkeypatch):
    monkeypatch.setitem(sys.modules, "unreal", SimpleNamespace())
    dispatcher = UnrealMainThreadDispatcher()
    for submit in (
        lambda: dispatcher.submit_callable("sync", lambda: None),
        lambda: dispatcher.submit_async_callable("async", lambda: None),
        lambda: dispatcher.submit_chunked_runner("chunk", ChunkedRunner(iter([]))),
    ):
        with pytest.raises(RuntimeError, match="unavailable"):
            submit()
    assert dispatcher.queue_size() == 0
    dispatcher.close()


def test_wrong_thread_cannot_pump_or_construct(slate):
    dispatcher = UnrealMainThreadDispatcher()
    errors = []

    def wrong_thread():
        for call in (
            lambda: slate.callbacks[0](0),
            lambda: dispatcher.drain_queue(4),
            lambda: UnrealMainThreadDispatcher(main_thread_id=slate.host_thread),
        ):
            try:
                call()
            except RuntimeError as exc:
                errors.append(str(exc))

    worker = threading.Thread(target=wrong_thread)
    worker.start()
    worker.join(1)
    assert len(errors) == 3 and all("host thread" in error for error in errors)
    assert len(slate.callbacks) == 1
    dispatcher.close()


def test_real_native_http_queue_and_python_share_the_slate_pump(slate):
    dispatcher, bridge = _make_execution_bridge(1)
    native = bridge.resolve_host_dispatcher()
    assert native is dispatcher._http_dispatcher
    assert native is bridge.resolve_host_dispatcher()
    native_call = native.post(lambda: bridge.dispatch_callable(threading.get_ident, thread_affinity="main"))
    python_calls = []
    dispatcher.submit_async_callable("python", lambda: python_calls.append(threading.get_ident()))
    assert dispatcher.pending_count() == 2
    slate.callbacks[0](0)
    assert native_call.wait(timeout=1) == slate.host_thread
    assert python_calls == [slate.host_thread]
    assert dispatcher.pending_count() == 0
    assert len(slate.callbacks) == 1
    dispatcher.close()


def test_bridge_resolves_chunked_result_on_same_dispatcher(slate):
    dispatcher, bridge = _make_execution_bridge(2)
    results = []
    steps = []

    def build_runner():
        assert threading.get_ident() == slate.host_thread
        return ChunkedRunner(iter([lambda: steps.append(threading.get_ident()) for _ in range(3)]), total=3)

    worker = threading.Thread(
        target=lambda: results.append(
            bridge.dispatch_callable(
                build_runner,
                action_name="bounded_sample",
                thread_affinity="main",
                execution="async",
                job_strategy="chunked",
                timeout_hint_secs=2,
            )
        )
    )
    worker.start()
    wait_until(lambda: dispatcher.queue_size() == 1)
    slate.callbacks[0](0)
    wait_until(lambda: dispatcher.queue_size() == 1)
    for count in range(1, 4):
        slate.callbacks[0](0)
        assert len(steps) == count
    slate.callbacks[0](0)
    worker.join(1)
    assert not worker.is_alive()
    assert steps == [slate.host_thread] * 3
    assert results == [{"current": 3, "total": 3, "message": None}]
    dispatcher.close()
