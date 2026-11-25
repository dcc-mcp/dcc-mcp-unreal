"""Behavioral contracts for the Unreal Canvas and Hyper3D skill."""

from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import yaml

ROOT = Path(__file__).parents[1]
SKILL_ROOT = ROOT / "src" / "dcc_mcp_unreal" / "skills" / "unreal-canvas"
SCRIPTS = SKILL_ROOT / "scripts"


def _load_script(name: str):
    script_dir = str(SCRIPTS)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    for module_name in (name, "_hyper3d_client"):
        sys.modules.pop(module_name, None)
    return importlib.import_module(name)


class FakeResponse:
    def __init__(self, status: int, payload: Any = None, body: bytes = b"", truncated: bool = False) -> None:
        self.status = status
        self._payload = payload
        self.bytes = body
        self.truncated = truncated

    def json(self) -> Any:
        return self._payload


def test_skill_metadata_and_tool_sources_are_valid():
    from dcc_mcp_core import validate_skill

    report = validate_skill(str(SKILL_ROOT))
    assert report.has_errors is False
    manifest = yaml.safe_load((SKILL_ROOT / "tools.yaml").read_text(encoding="utf-8"))
    tools = manifest["tools"]
    assert {tool["name"] for tool in tools} == {
        "inspect_canvas_support",
        "prepare_hyper3d_canvas_workflow",
        "submit_hyper3d_generation",
        "get_hyper3d_generation_status",
        "download_hyper3d_result",
        "import_hyper3d_asset",
    }
    for tool in tools:
        assert (SKILL_ROOT / tool["source_file"]).is_file()


def test_canvas_workflow_keeps_wiring_inside_action_graph():
    module = _load_script("prepare_hyper3d_canvas_workflow")

    result = module.prepare_hyper3d_canvas_workflow()

    assert result["success"] is True
    graph = result["context"]["graph"]
    assert graph["card_type"] == "Action"
    assert graph["scope"] == "inside_action_card_graph"
    assert graph["outer_canvas_connections"] == []
    assert {node["id"] for node in graph["nodes"]} >= {
        "image_input",
        "text_input",
        "submit_hyper3d",
        "status_hyper3d",
        "download_hyper3d",
        "import_hyper3d",
        "dcc_mcp_action",
        "render_showcase",
        "canvas_output",
    }
    assert any(
        connection["from"]["node"] == "download_hyper3d" and connection["to"]["node"] == "import_hyper3d"
        for connection in graph["connections"]
    )
    dcc_node = next(node for node in graph["nodes"] if node["id"] == "dcc_mcp_action")
    setting_names = {pin["name"] for pin in dcc_node["inputs"] if pin.get("source") == "setting"}
    assert setting_names == {"endpoint", "skill_name", "tool_name", "arguments"}
    assert graph["manual_settings"]["dcc_mcp"] == ["endpoint", "skill_name", "tool_name", "arguments"]
    submit_node = next(node for node in graph["nodes"] if node["id"] == "submit_hyper3d")
    assert {pin["name"] for pin in submit_node["inputs"]} >= {"image_paths", "prompt"}
    download_node = next(node for node in graph["nodes"] if node["id"] == "download_hyper3d")
    result_path_pin = next(pin for pin in download_node["inputs"] if pin["name"] == "result_path")
    assert result_path_pin["source"] == "setting"
    assert "absolute" in result_path_pin["description"].lower()
    assert graph["manual_settings"]["download"] == ["result_path"]
    assert any(
        connection["from"]["node"] == "dcc_mcp_action" and connection["to"]["node"] == "render_showcase"
        for connection in graph["connections"]
    )
    assert any(
        connection["from"]["node"] == "render_showcase" and connection["to"]["node"] == "canvas_output"
        for connection in graph["connections"]
    )


def test_canvas_workflow_accepts_manual_marketplace_skill_settings():
    module = _load_script("prepare_hyper3d_canvas_workflow")

    result = module.prepare_hyper3d_canvas_workflow(
        dcc_mcp_skill="dcc-mcp-geo",
        dcc_mcp_tool="optimize_scene",
    )

    dcc_node = next(node for node in result["context"]["graph"]["nodes"] if node["id"] == "dcc_mcp_action")
    defaults = {pin["name"]: pin.get("default") for pin in dcc_node["inputs"]}
    assert defaults["skill_name"] == "dcc-mcp-geo"
    assert defaults["tool_name"] == "optimize_scene"


def test_canvas_support_detects_project_plugins_without_unreal_runtime(tmp_path, monkeypatch):
    project_dir = tmp_path / "Project"
    plugin_dir = project_dir / "Plugins"
    for plugin_name in ("UnrealCanvasBridge", "UnrealCanvasGraph", "UnrealMCP"):
        folder = plugin_dir / plugin_name
        folder.mkdir(parents=True)
        (folder / f"{plugin_name}.uplugin").write_text(
            json.dumps({"Name": plugin_name, "FriendlyName": plugin_name}),
            encoding="utf-8",
        )
    (project_dir / "CanvasProject.uproject").write_text(
        json.dumps(
            {
                "FileVersion": 3,
                "Plugins": [
                    {"Name": "UnrealCanvasBridge", "Enabled": True},
                    {"Name": "UnrealCanvasGraph", "Enabled": True},
                    {"Name": "UnrealMCP", "Enabled": True},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("UNREAL_PROJECT_DIR", str(project_dir))
    monkeypatch.delenv("UNREAL_ENGINE_DIR", raising=False)
    monkeypatch.delenv("UE_ROOT_DIR", raising=False)
    module = _load_script("inspect_canvas_support")

    result = module.inspect_canvas_support()

    assert result["success"] is True
    context = result["context"]
    assert context["native_canvas_available"] is True
    assert context["canvas_bridge_ready"] is True
    assert context["canvas_graph_ready"] is True
    assert context["official_mcp_available"] is True


def test_canvas_support_reports_ue58_as_native_canvas_unsupported(tmp_path, monkeypatch):
    project_dir = tmp_path / "Project"
    plugin_dir = project_dir / "Plugins"
    for plugin_name in ("UnrealCanvasBridge", "UnrealCanvasGraph", "UnrealMCP"):
        folder = plugin_dir / plugin_name
        folder.mkdir(parents=True)
        (folder / f"{plugin_name}.uplugin").write_text(
            json.dumps({"Name": plugin_name, "FriendlyName": plugin_name}),
            encoding="utf-8",
        )
    (project_dir / "CanvasProject.uproject").write_text(
        json.dumps(
            {
                "FileVersion": 3,
                "Plugins": [
                    {"Name": "UnrealCanvasBridge", "Enabled": True},
                    {"Name": "UnrealCanvasGraph", "Enabled": True},
                    {"Name": "UnrealMCP", "Enabled": True},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("UNREAL_PROJECT_DIR", str(project_dir))
    monkeypatch.setenv("UNREAL_ENGINE_VERSION", "5.8.4")
    monkeypatch.delenv("UNREAL_ENGINE_DIR", raising=False)
    monkeypatch.delenv("UE_ROOT_DIR", raising=False)
    module = _load_script("inspect_canvas_support")

    result = module.inspect_canvas_support()

    assert result["success"] is True
    assert result["context"]["unreal_canvas_engine_supported"] is False
    assert result["context"]["native_canvas_available"] is False


def test_submit_requires_api_key_before_http_call(monkeypatch):
    module = _load_script("submit_hyper3d_generation")
    monkeypatch.delenv("HYPER3D_API_KEY", raising=False)
    monkeypatch.delenv("RODIN_API_KEY", raising=False)

    result = module.submit_hyper3d_generation(prompt="A small robot")

    assert result["success"] is False
    assert result["error"] == "missing_api_key"
    assert "test-secret-key" not in str(result)


def test_submit_accepts_shared_hyper3d_api_key(monkeypatch):
    monkeypatch.setenv("HYPER3D_API_KEY", "test-hyper3d-key")
    monkeypatch.delenv("RODIN_API_KEY", raising=False)
    module = _load_script("submit_hyper3d_generation")
    monkeypatch.setattr(
        module, "submit_generation", lambda **kwargs: {"task_uuid": "task", "subscription_key": "subscription"}
    )

    result = module.submit_hyper3d_generation(prompt="A small robot")

    assert result["success"] is True
    assert result["context"]["task_uuid"] == "task"


def test_submit_rejects_missing_image_path_before_api_key(monkeypatch):
    module = _load_script("submit_hyper3d_generation")
    monkeypatch.delenv("RODIN_API_KEY", raising=False)

    result = module.submit_hyper3d_generation(image_paths=["C:/missing/reference.png"])

    assert result["success"] is False
    assert result["error"] == "invalid_image_path"


def test_submit_builds_image_payload_and_sanitizes_response(tmp_path, monkeypatch):
    image_path = tmp_path / "reference.png"
    image_path.write_bytes(b"fake-image")
    monkeypatch.delenv("HYPER3D_API_KEY", raising=False)
    monkeypatch.setenv("RODIN_API_KEY", "test-secret-key")
    module = _load_script("submit_hyper3d_generation")
    client = sys.modules["_hyper3d_client"]
    calls = []

    def fake_http_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return FakeResponse(
            201,
            {
                "message": "Submitted.",
                "uuid": "task-uuid",
                "jobs": {"uuids": ["job-uuid"], "subscription_key": "subscription-key"},
                "consumed": 0.5,
            },
        )

    with patch.object(client, "http_request", side_effect=fake_http_request):
        result = module.submit_hyper3d_generation(
            image_paths=[str(image_path)],
            prompt="keep the front view",
            geometry_file_format="glb",
        )

    assert result["success"] is True
    assert result["context"]["task_uuid"] == "task-uuid"
    assert result["context"]["subscription_key"] == "subscription-key"
    assert "test-secret-key" not in str(result)
    method, url, request = calls[0]
    assert method == "POST"
    assert url.endswith("/rodin")
    assert request["headers"]["Authorization"] == "Bearer test-secret-key"
    assert b'name="images"' in request["body"]
    assert b"Gen-2.5-Medium" in request["body"]
    assert b"keep the front view" in request["body"]


def test_status_returns_only_graph_safe_job_fields(monkeypatch):
    monkeypatch.delenv("HYPER3D_API_KEY", raising=False)
    monkeypatch.setenv("RODIN_API_KEY", "test-secret-key")
    module = _load_script("get_hyper3d_generation_status")
    client = sys.modules["_hyper3d_client"]

    with patch.object(
        client,
        "http_request",
        return_value=FakeResponse(
            200,
            {
                "jobs": [{"uuid": "job-uuid", "status": "Done", "progress": 1.0, "subscription_key": "hidden"}],
                "signed_url": "https://example.invalid/secret",
            },
        ),
    ):
        result = module.get_hyper3d_generation_status(subscription_key="subscription-key")

    assert result["success"] is True
    assert result["context"]["all_done"] is True
    assert result["context"]["jobs"] == [{"job_uuid": "job-uuid", "status": "Done", "progress": 1.0}]
    assert "signed_url" not in str(result)
    assert "hidden" not in str(result)


def test_status_reports_application_error(monkeypatch):
    monkeypatch.delenv("HYPER3D_API_KEY", raising=False)
    monkeypatch.setenv("RODIN_API_KEY", "test-secret-key")
    module = _load_script("get_hyper3d_generation_status")
    client = sys.modules["_hyper3d_client"]

    with patch.object(
        client,
        "http_request",
        return_value=FakeResponse(201, {"error": "NO_SUCH_TASK", "message": "Unknown task"}),
    ):
        result = module.get_hyper3d_generation_status(subscription_key="subscription-key")

    assert result["success"] is False
    assert result["error"] == "NO_SUCH_TASK"


def test_download_writes_selected_geometry_without_returning_signed_url(tmp_path, monkeypatch):
    monkeypatch.delenv("HYPER3D_API_KEY", raising=False)
    monkeypatch.setenv("RODIN_API_KEY", "test-secret-key")
    module = _load_script("download_hyper3d_result")
    client = sys.modules["_hyper3d_client"]
    result_path = tmp_path / "generated.glb"

    def fake_http_request(method, url, **kwargs):
        if url.endswith("/download"):
            return FakeResponse(
                201,
                {
                    "list": [
                        {"name": "preview.png", "url": "https://example.invalid/preview.png"},
                        {"name": "model.glb", "url": "https://example.invalid/model.glb?signature=secret"},
                    ]
                },
            )
        return FakeResponse(200, body=b"glb-bytes")

    with patch.object(client, "http_request", side_effect=fake_http_request):
        result = module.download_hyper3d_result(task_uuid="task-uuid", result_path=str(result_path))

    assert result["success"] is True
    assert result["context"]["file_name"] == "model.glb"
    assert result["context"]["result_path"] == str(result_path)
    assert result_path.read_bytes() == b"glb-bytes"
    assert "signature" not in str(result)


def test_download_rejects_truncated_response(tmp_path, monkeypatch):
    monkeypatch.delenv("HYPER3D_API_KEY", raising=False)
    monkeypatch.setenv("RODIN_API_KEY", "test-secret-key")
    module = _load_script("download_hyper3d_result")
    client = sys.modules["_hyper3d_client"]
    result_path = tmp_path / "generated.glb"
    responses = [
        FakeResponse(200, {"list": [{"name": "model.glb", "url": "https://example.invalid/model.glb"}]}),
        FakeResponse(200, body=b"partial", truncated=True),
    ]

    with patch.object(client, "http_request", side_effect=responses):
        result = module.download_hyper3d_result(task_uuid="task-uuid", result_path=str(result_path))

    assert result["success"] is False
    assert result["error"] == "download_response_truncated"
    assert not result_path.exists()


def test_import_hyper3d_asset_uses_asset_tools(tmp_path, monkeypatch):
    source = tmp_path / "model.glb"
    source.write_bytes(b"glb")
    calls: Dict[str, Any] = {}

    class FakeTask:
        def __init__(self):
            self.properties = {}

        def set_editor_property(self, name, value):
            self.properties[name] = value

        def get_editor_property(self, name):
            return ["/Game/Merlin/Generated/model.model"] if name == "imported_object_paths" else None

    class FakeAssetTools:
        def import_asset_tasks(self, tasks):
            calls["tasks"] = tasks

    fake_unreal = types.ModuleType("unreal")
    fake_unreal.AssetImportTask = FakeTask
    fake_unreal.AssetToolsHelpers = types.SimpleNamespace(get_asset_tools=lambda: FakeAssetTools())
    monkeypatch.setitem(sys.modules, "unreal", fake_unreal)
    module = _load_script("import_hyper3d_asset")

    result = module.import_hyper3d_asset(source_path=str(source), asset_name="Hero")

    assert result["success"] is True
    assert result["context"]["imported_object_paths"] == ["/Game/Merlin/Generated/model.model"]
    task = calls["tasks"][0]
    assert Path(task.properties["filename"]).stem == "Hero"
    assert Path(task.properties["filename"]).suffix == ".glb"
    assert not Path(task.properties["filename"]).exists()
    assert task.properties["destination_path"] == "/Game/Merlin/Generated"
    assert task.properties["destination_name"] == "Hero"
