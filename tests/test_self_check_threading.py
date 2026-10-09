"""Exercise the decorated self-check through the real bridge with a synthetic host."""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from dcc_mcp_unreal.server import _make_execution_bridge

SKILL = Path(__file__).parents[1] / "src/dcc_mcp_unreal/skills/unreal-automation"
SCRIPT = SKILL / "scripts/mcp_self_check.py"


@pytest.fixture
def self_check_host(monkeypatch, tmp_path):
    import dcc_mcp_unreal.server as server_module

    host_thread = threading.get_ident()
    callbacks = []
    engine_reads = []
    http_reads = []
    editor = tmp_path / "UnrealEditor.exe"
    editor.write_bytes(b"synthetic Editor identity")
    project = tmp_path / "Project/Test.uproject"
    project.parent.mkdir()
    project.write_text("{}", encoding="utf-8")
    plugin = project.parent / "Plugins/DccMcpUnreal"
    plugin.mkdir(parents=True)
    (plugin / "DccMcpUnreal.uplugin").write_text("{}", encoding="utf-8")

    def engine_read(name, value):
        assert threading.get_ident() == host_thread, "Unreal API called outside its registered main thread"
        engine_reads.append(name)
        return value

    monkeypatch.setitem(
        sys.modules,
        "unreal",
        SimpleNamespace(
            register_slate_post_tick_callback=lambda callback: callbacks.append(callback) or "owned-tick",
            unregister_slate_post_tick_callback=lambda handle: None,
            Paths=SimpleNamespace(get_project_file_path=lambda: engine_read("project", str(project))),
            PluginBlueprintLibrary=SimpleNamespace(get_plugin_base_dir=lambda name: engine_read("plugin", str(plugin))),
            SystemLibrary=SimpleNamespace(get_engine_version=lambda: engine_read("version", "5.7.4-release")),
        ),
    )
    dispatcher, bridge = _make_execution_bridge(2)
    skills = ["unreal-actors", "unreal-assets", "unreal-level", "unreal-automation"]
    tools = [
        "unreal_actors__list_actors",
        "unreal_actors__spawn_actor",
        "unreal_assets__list_assets",
        "unreal_level__get_level_info",
        "unreal_automation__mcp_self_check",
        "unreal_automation__list_automation_tests",
    ]
    server = SimpleNamespace(
        _main_thread_dispatcher=dispatcher,
        instance_id="11111111-1111-1111-1111-111111111111",
        process_start_token="a" * 32,
        is_running=True,
        mcp_url="http://self-check.invalid/mcp",
        list_skills=lambda: [SimpleNamespace(name=name) for name in skills],
        is_skill_loaded=lambda name: True,
        list_actions=lambda: [SimpleNamespace(name=name) for name in tools],
    )
    monkeypatch.setattr(server_module, "_server_instance", server)
    monkeypatch.setattr(sys, "executable", str(editor))

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'{"ready": true}'

    def http_get(request, timeout):
        assert threading.get_ident() != host_thread, "Self-HTTP must not block the host pump"
        http_reads.append(request.full_url)
        # Model a readiness response that needs that same main-thread pump.
        result = dispatcher.submit_callable("http-readiness", lambda: "ready", timeout_ms=1000)
        assert result["success"] and result["output"] == "ready"
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", http_get)
    metadata = next(
        item for item in yaml.safe_load((SKILL / "tools.yaml").read_text())["tools"] if item["name"] == "mcp_self_check"
    )
    yield SimpleNamespace(
        dispatcher=dispatcher,
        bridge=bridge,
        callbacks=callbacks,
        engine_reads=engine_reads,
        http_reads=http_reads,
        metadata=metadata,
        project=project,
        plugin=plugin,
    )
    dispatcher.close()


def execute(host, check_http):
    return host.bridge.execute_script(
        str(SCRIPT),
        {"check_http": check_http},
        action_name="unreal_automation__mcp_self_check",
        thread_affinity=host.metadata["affinity"],
        timeout_hint_secs=2,
    )


@pytest.mark.parametrize("check_http", [False, True])
def test_formal_worker_self_check_reads_engine_on_main_thread(self_check_host, check_http):
    host = self_check_host
    results = []
    worker = threading.Thread(target=lambda: results.append(execute(host, check_http)))
    worker.start()
    deadline = time.monotonic() + 3
    try:
        while worker.is_alive() and time.monotonic() < deadline:
            host.callbacks[0](0)
            time.sleep(0.001)
        worker.join(0.1)
        assert not worker.is_alive(), "self-check blocked its own main-thread pump"
        assert results[0]["success"], results[0]
        identity = results[0]["context"]["install_identity"]
        assert identity["project_file"] == str(host.project.resolve())
        assert identity["plugin_root"] == str(host.plugin.resolve())
        assert identity["process_start_token"] == "a" * 32
        assert host.engine_reads == ["project", "plugin", "version"]
        assert host.http_reads == (
            ["http://self-check.invalid/health", "http://self-check.invalid/v1/readyz"] if check_http else []
        )
        assert len(host.callbacks) == 1
    finally:
        if worker.is_alive():
            host.dispatcher.close()
            worker.join(3)


def test_main_thread_self_http_is_rejected_before_network(self_check_host):
    host = self_check_host
    result = execute(host, True)
    assert not result["success"]
    assert "HTTP probes require" in json.dumps(result)
    assert host.http_reads == []


def test_identity_dispatch_error_is_preserved_without_network(self_check_host, monkeypatch):
    host = self_check_host

    def timeout(*args, **kwargs):
        raise TimeoutError("identity-main-timeout")

    monkeypatch.setattr(host.dispatcher, "dispatch_callable", timeout)
    # Run directly through the actual decorated entry to avoid replacing its outer bridge.
    from dcc_mcp_unreal.skill_runner import run_skill_script

    result = run_skill_script(str(SCRIPT), {"check_http": False})
    assert not result["success"]
    assert "identity-main-timeout" in json.dumps(result)
    assert host.engine_reads == [] and host.http_reads == []
