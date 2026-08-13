from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "src" / "dcc_mcp_unreal" / "skills" / "unreal-hair"
SCRIPTS = SKILL / "scripts"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Props:
    def __init__(self, path: str = "", **values) -> None:
        self.path = path
        self.values = values

    def set_editor_property(self, name, value) -> None:
        self.values[name] = value

    def get_editor_property(self, name):
        return self.values[name]

    def get_path_name(self):
        return self.path


def fake_unreal():
    class GroomAsset(Props):
        pass

    class GroomCache(Props):
        pass

    class GroomComponent(Props):
        def set_groom_asset(self, value):
            self.values["groom_asset"] = value

        def set_groom_cache(self, value):
            self.values["groom_cache"] = value

    class LevelSequence(Props):
        def __init__(self, path: str):
            super().__init__(path)
            self.bindings = []

        def add_possessable(self, component):
            binding = Binding(component)
            self.bindings.append(binding)
            return binding

        def get_bindings(self):
            return self.bindings

    class Binding:
        def __init__(self, component):
            self.component = component
            self.name = ""
            self.tracks = []

        def set_display_name(self, name):
            self.name = name

        def get_display_name(self):
            return self.name

        def add_track(self, cls):
            track = cls()
            self.tracks.append(track)
            return track

    class MovieSceneGroomCacheTrack:
        def __init__(self):
            self.sections = []

        def add_section(self):
            section = Section()
            self.sections.append(section)
            return section

    class Section(Props):
        def __init__(self):
            super().__init__(params=Props())
            self.frame_range = None

        def set_range(self, start, end):
            self.frame_range = (start, end)

    module = types.ModuleType("unreal")
    module.GroomAsset = GroomAsset
    module.GroomCache = GroomCache
    module.GroomComponent = GroomComponent
    module.LevelSequence = LevelSequence
    module.MovieSceneGroomCacheTrack = MovieSceneGroomCacheTrack
    module.EditorAssetLibrary = types.SimpleNamespace(save_loaded_asset=lambda *args, **kwargs: True)
    return module


def test_bind_and_query_exact_groom_component_paths() -> None:
    unreal = fake_unreal()
    helper = load("_hair_runtime", SCRIPTS / "_hair_runtime.py")
    group = Props(
        num_curves=20_640,
        num_guides=128,
        num_curve_vertices=660_480,
        num_guide_vertices=4_096,
    )
    groom = unreal.GroomAsset("/Game/Hair/G.G", hair_groups_info=[group])
    cache = unreal.GroomCache("/Game/Hair/GC.GC")
    component = unreal.GroomComponent(
        "/Game/Maps/L.L:PersistentLevel.GroomActor.GroomComponent0",
        groom_asset=None,
        groom_cache=None,
        running=False,
        looping=False,
        manual_tick=True,
    )
    objects = {item.get_path_name(): item for item in (groom, cache, component)}
    unreal.load_object = lambda outer, path: objects.get(path)
    with patch.dict(sys.modules, {"_hair_runtime": helper, "unreal": unreal}):
        bind = load("bind_groom_cache", SCRIPTS / "bind_groom_cache.py")
        query = load("get_groom_component_info", SCRIPTS / "get_groom_component_info.py")
        result = bind.bind_groom_cache(
            component_path=component.get_path_name(),
            groom_asset_path=groom.get_path_name(),
            groom_cache_path=cache.get_path_name(),
            running=True,
            looping=True,
            manual_tick=False,
        )
        info = query.get_groom_component_info(component_path=component.get_path_name())

    assert result["success"] is True
    assert result["context"]["component_path"] == component.get_path_name()
    assert info["success"] is True
    assert info["context"]["groom_asset_path"] == groom.get_path_name()
    assert info["context"]["groom_cache_path"] == cache.get_path_name()
    assert info["context"]["running"] is True
    assert info["context"]["looping"] is True
    assert info["context"]["manual_tick"] is False
    assert info["context"]["groom_curve_count"] == 20_640
    assert info["context"]["groom_guide_count"] == 128


def test_add_groom_cache_track_uses_exact_paths_and_versioned_binding() -> None:
    unreal = fake_unreal()
    helper = load("_hair_runtime", SCRIPTS / "_hair_runtime.py")
    cache = unreal.GroomCache("/Game/Hair/GC.GC")
    component = unreal.GroomComponent("/Game/Maps/L.L:PersistentLevel.A.C")
    sequence = unreal.LevelSequence("/Game/Cinematics/LS.LS")
    existing = sequence.add_possessable(component)
    existing.set_display_name("V12_VellumGroomCache")
    objects = {item.get_path_name(): item for item in (cache, component, sequence)}
    unreal.load_object = lambda outer, path: objects.get(path)
    with patch.dict(sys.modules, {"_hair_runtime": helper, "unreal": unreal}):
        module = load("add_groom_cache_track", SCRIPTS / "add_groom_cache_track.py")
        result = module.add_groom_cache_track(
            sequence_path=sequence.get_path_name(),
            component_path=component.get_path_name(),
            groom_cache_path=cache.get_path_name(),
            start_frame=0,
            end_frame=150,
            play_rate=1.0 / 150.0,
            binding_name="V12_VellumGroomCache",
        )

    assert result["success"] is True
    binding = sequence.bindings[1]
    assert binding.name == "V12_VellumGroomCache_v001"
    section = binding.tracks[0].sections[0]
    assert section.frame_range == (0, 150)
    assert section.values["params"].values == {
        "groom_cache": cache,
        "play_rate": 1.0 / 150.0,
        "reverse": False,
    }


def test_hair_skill_contract_exposes_narrow_tools() -> None:
    tools = yaml.safe_load((SKILL / "tools.yaml").read_text(encoding="utf-8"))["tools"]
    assert [tool["name"] for tool in tools] == [
        "bind_groom_cache",
        "get_groom_component_info",
        "add_groom_cache_track",
    ]
    bind = tools[0]
    assert bind["input_schema"]["required"] == ["component_path", "groom_asset_path"]
    assert "actor_name" not in bind["input_schema"]["properties"]
    assert tools[1]["read_only"] is True
    assert tools[2]["input_schema"]["required"] == [
        "sequence_path",
        "component_path",
        "groom_cache_path",
    ]
