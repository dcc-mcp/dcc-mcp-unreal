"""Measure known collision geometry after real ticks in an independent Editor."""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

HIT_FIELDS = (
    "blocking_hit",
    "initial_overlap",
    "time",
    "distance_cm",
    "location",
    "impact_point",
    "normal",
    "impact_normal",
    "physical_material",
    "actor",
    "component",
    "hit_bone_name",
    "bone_name",
    "hit_item",
    "element_index",
    "face_index",
    "trace_start",
    "trace_end",
)
NULL_HIT_FIELDS = ("distance_cm", "time", "location", "impact_point", "normal", "impact_normal", "actor", "component")


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _close(actual: float, expected: float, message: str) -> None:
    _check(math.isclose(actual, expected, rel_tol=0.0, abs_tol=0.02), f"{message}: {actual!r} != {expected}")


def _vector(x: float, y: float, z: float) -> dict:
    return {"x": x, "y": y, "z": z}


def _json_value(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if all(hasattr(value, axis) for axis in "xyz"):
        return {axis: float(getattr(value, axis)) for axis in "xyz"}
    if callable(getattr(value, "get_path_name", None)):
        return {
            "name": value.get_name(),
            "path": value.get_path_name(),
            "class": value.get_class().get_path_name(),
        }
    return str(value)


def _hit(context: dict, actor, component, distance: float, point: dict, normal: dict) -> None:
    _check(context["status"] == "hit" and context["blocking_hit"] is True, "Expected a blocking hit")
    _check(context["start_penetrating"] is False, "Fixture trace unexpectedly starts inside collision")
    _check(context["unit"] == "cm" and context["coordinate_space"] == "world", "Wrong measurement units or space")
    _close(context["distance_cm"], distance, "Collision distance")
    for axis in "xyz":
        _close(context["impact_point"][axis], point[axis], f"Impact point {axis}")
        _close(context["location"][axis], point[axis], f"Hit location {axis}")
        _close(context["impact_normal"][axis], normal[axis], f"Impact normal {axis}")
        _close(context["normal"][axis], normal[axis], f"Hit normal {axis}")
    for key, expected in (("actor", actor), ("component", component)):
        identity = context[key]
        _check(identity["path"] == expected.get_path_name(), f"Wrong {key} collision identity")
        _check(identity["name"] == expected.get_name(), f"Wrong {key} name")
        _check(identity["class"] == expected.get_class().get_path_name(), f"Wrong {key} class")


def _miss(context: dict) -> None:
    _check(context["status"] == "no_hit", "Expected an explicit no_hit result")
    _check(context["blocking_hit"] is False and context["start_penetrating"] is False, "Miss has hit flags")
    _check(all(context[field] is None for field in NULL_HIT_FIELDS), "Miss contains fabricated hit data")


def _fixture():
    receipt = {
        "success": False,
        "scope": "independent_editor_collision_fixture",
        "case_acceptance": False,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "execution": "NullRHI Editor with native post-tick callbacks",
        "level_saved": False,
        "actor_ownership": "fixture-owned actors in an unsaved independent world",
        "transient_flag_requested": False,
        "spawn_route": "Object.call_method -> GameplayStatics deferred spawn UFUNCTIONs",
        "results": {},
    }
    result_path = Path(os.environ["DCC_MCP_SPATIAL_RESULT"])

    def write_receipt():
        result_path.parent.mkdir(parents=True, exist_ok=True)
        pending = result_path.with_suffix(".json.tmp")
        pending.write_text(json.dumps(receipt, indent=2, allow_nan=False), encoding="utf-8")
        pending.replace(result_path)

    def checkpoint(phase):
        receipt["phase"] = phase
        receipt.setdefault("phase_history", []).append({"phase": phase, "at": datetime.now(timezone.utc).isoformat()})
        write_receipt()
        print(f"DCC_MCP_SPATIAL_SMOKE_PHASE={phase}", flush=True)

    def setup_call(phase, function, *args, **kwargs):
        checkpoint(f"{phase}.before")
        result = function(*args, **kwargs)
        checkpoint(f"{phase}.after")
        return result

    actors = []
    actor_subsystem = None
    try:
        checkpoint("import_unreal")
        import unreal  # noqa: PLC0415

        source_root = Path(os.environ["DCC_MCP_SPATIAL_SOURCE_ROOT"]).resolve()
        payload = Path(os.environ["DCC_MCP_SPATIAL_PYTHON_PAYLOAD"]).resolve()
        sys.path[:0] = [str(source_root / "src"), str(payload)]
        import dcc_mcp_core  # noqa: PLC0415

        import dcc_mcp_unreal  # noqa: PLC0415

        core_source = Path(dcc_mcp_core.__file__).resolve()
        product_source = Path(dcc_mcp_unreal.__file__).resolve()
        _check(payload in core_source.parents, "Core was imported outside the specified Python payload")
        _check(source_root / "src" in product_source.parents, "Adapter was imported outside this product checkout")
        core_version = importlib.metadata.version("dcc-mcp-core")
        expected_core = os.environ.get("DCC_MCP_SPATIAL_EXPECTED_CORE_VERSION", "")
        _check(
            not expected_core or core_version == expected_core, "Core version differs from the requested fixed version"
        )
        script = source_root / "src/dcc_mcp_unreal/skills/unreal-level/scripts/line_trace.py"
        decoder = source_root / "src/dcc_mcp_unreal/hit_result.py"
        receipt["runtime"] = {
            "engine_version": setup_call("engine_version", unreal.SystemLibrary.get_engine_version),
            "engine_build": json.loads(
                (Path(os.environ["DCC_MCP_SPATIAL_UE_ROOT"]) / "Engine/Build/Build.version").read_text(encoding="utf-8")
            ),
            "python_version": sys.version,
            "core_version": core_version,
            "core_source": str(core_source),
            "product_version": dcc_mcp_unreal.__version__,
            "product_source": str(product_source),
            "product_head": os.environ.get("DCC_MCP_SPATIAL_PRODUCT_HEAD", ""),
            "source_sha256": {
                str(path.relative_to(source_root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (script, decoder)
            },
            "dcc_mcp_automation_library_present": hasattr(unreal, "DccMcpAutomationLibrary"),
        }
        _check(not receipt["runtime"]["dcc_mcp_automation_library_present"], "DccMcp C++ plugin unexpectedly loaded")
        spec = importlib.util.spec_from_file_location("dcc_spatial_smoke_line_trace", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # The runner starts a fresh independent project in the engine Entry
        # map. Replacing a world from a Slate tick callback can re-enter editor
        # teardown; use that already initialized world and never save it.
        editor_subsystem = setup_call("editor_subsystem", unreal.get_editor_subsystem, unreal.UnrealEditorSubsystem)
        world = setup_call("editor_world", editor_subsystem.get_editor_world)
        _check(world is not None, "The independent project's editor world is unavailable")
        world_path = setup_call("editor_world_path", world.get_path_name)
        _check(world_path == "/Engine/Maps/Entry.Entry", "The independent project's configured startup world differs")
        receipt["world"] = {
            "name": setup_call("editor_world_name", world.get_name),
            "path": world_path,
            "type": "editor",
            "source": "independent_project_startup_map",
            "replaced_during_script": False,
        }
        actor_subsystem = setup_call("actor_subsystem", unreal.get_editor_subsystem, unreal.EditorActorSubsystem)
        gameplay = setup_call("gameplay_statics_default_object", unreal.get_default_object, unreal.GameplayStatics)
        mesh = setup_call("load_cube_mesh", unreal.load_asset, "/Engine/BasicShapes/Cube.Cube")
        _check(mesh is not None, "Engine BasicShapes Cube is unavailable")
        bounds = setup_call("cube_mesh_bounds", mesh.get_bounding_box)
        for axis in "xyz":
            _close(getattr(bounds.min, axis), -50.0, f"Fixture cube minimum {axis}")
            _close(getattr(bounds.max, axis), 50.0, f"Fixture cube maximum {axis}")

        def cube(label, location, scale):
            checkpoint(f"{label}.spawn_transform.before")
            transform = unreal.Transform(location=unreal.Vector(**location), scale=unreal.Vector(**scale))
            checkpoint(f"{label}.spawn_transform.after")
            # Both functions are known native UFUNCTIONs with
            # BlueprintInternalUseOnly metadata. Public Object.call_method
            # supports reflected methods that have no generated Python glue.
            scale_method = unreal.SpawnActorScaleMethod.OVERRIDE_ROOT_SCALE
            actor = setup_call(
                f"{label}.begin_deferred_spawn",
                gameplay.call_method,
                "BeginDeferredActorSpawnFromClass",
                args=(
                    world,
                    unreal.StaticMeshActor,
                    transform,
                    unreal.SpawnActorCollisionHandlingMethod.ALWAYS_SPAWN,
                    None,
                    scale_method,
                ),
            )
            _check(actor is not None, f"Could not spawn {label}")
            actors.append(actor)
            setup_call(f"{label}.actor_label", actor.set_actor_label, label)
            checkpoint(f"{label}.mesh_component.before")
            component = actor.static_mesh_component
            checkpoint(f"{label}.mesh_component.after")
            _check(
                setup_call(f"{label}.set_static_mesh", component.set_static_mesh, mesh),
                f"Could not assign the cube mesh to {label}",
            )
            setup_call(f"{label}.collision_profile", component.set_collision_profile_name, "BlockAll")
            setup_call(
                f"{label}.collision_enabled", component.set_collision_enabled, unreal.CollisionEnabled.QUERY_ONLY
            )
            finished = setup_call(
                f"{label}.finish_spawning",
                gameplay.call_method,
                "FinishSpawningActor",
                args=(actor, transform, scale_method),
            )
            _check(finished == actor, f"Deferred spawn did not finish {label}")
            actual_scale = setup_call(f"{label}.read_scale", actor.get_actor_scale3d)
            for axis in "xyz":
                _close(getattr(actual_scale, axis), scale[axis], f"{label} scale {axis}")
            return actor, component

        floor, floor_component = cube("DccSpatialFloor", _vector(0, 0, -25), _vector(20, 20, 0.5))
        left, left_component = cube("DccSpatialLeftWall", _vector(-175, 0, 150), _vector(1, 10, 3))
        right, right_component = cube("DccSpatialRightWall", _vector(175, 0, 150), _vector(1, 10, 3))
        mesh_subsystem = setup_call(
            "static_mesh_subsystem", unreal.get_editor_subsystem, unreal.StaticMeshEditorSubsystem
        )
        collision_count = setup_call("cube_simple_collision_count", mesh_subsystem.get_simple_collision_count, mesh)
        receipt["fixture"] = {
            "mesh": setup_call("cube_mesh_path", mesh.get_path_name),
            "floor_top_z_cm": 0.0,
            "wall_inner_x_cm": [-125.0, 125.0],
            "expected_clear_gap_cm": 250.0,
            "actor_paths": {
                "floor": setup_call("floor_actor_path", floor.get_path_name),
                "left": setup_call("left_actor_path", left.get_path_name),
                "right": setup_call("right_actor_path", right.get_path_name),
            },
            "collision_profile": "BlockAll",
            "collision_enabled": "QueryOnly",
            "simple_collision_count": collision_count,
        }

        ground_start, ground_end = _vector(0, 0, 200), _vector(0, 0, -100)
        origin = _vector(0, 0, 100)

        def native_trace(start, end):
            return unreal.SystemLibrary.line_trace_single(
                world,
                unreal.Vector(**start),
                unreal.Vector(**end),
                unreal.TraceTypeQuery.cast(0),
                False,
                [],
                unreal.DrawDebugTrace.NONE,
                False,
            )

        # A commandlet never advances the Editor loop while a Python function
        # runs. Physics state creation and static mesh compilation may defer
        # collision registration, so observe actual native hits across ticks.
        receipt["readiness"] = {"ticks_observed": 0, "probes": []}
        deadline = time.monotonic() + 60.0
        probes = (
            ("ground", ground_start, ground_end, floor, 200.0),
            ("left", origin, _vector(-500, 0, 100), left, 125.0),
            ("right", origin, _vector(500, 0, 100), right, 125.0),
        )
        checkpoint("await_native_collision_readiness")
        yield
        for tick in range(1, 601):
            observations = {}
            hits = {}
            ready = True
            for name, start, end, expected_actor, expected_distance in probes:
                hit = native_trace(start, end)
                if hit is None:
                    observations[name] = {"hit": False}
                    ready = False
                    continue
                values = hit.to_tuple()
                _check(isinstance(values, tuple) and len(values) == 18, "Unexpected native HitResult.to_tuple layout")
                observations[name] = {
                    "hit": True,
                    "blocking_hit": values[0],
                    "distance_cm": values[3],
                    "actor": _json_value(values[9]),
                }
                hits[name] = hit
                ready &= (
                    values[0] is True
                    and values[1] is False
                    and values[9] == expected_actor
                    and math.isclose(values[3], expected_distance, abs_tol=0.02)
                )
            receipt["readiness"]["ticks_observed"] = tick
            receipt["readiness"]["probes"].append({"tick": tick, "observations": observations})
            if ready:
                raw = hits["ground"]
                break
            _check(
                tick < 600 and time.monotonic() < deadline,
                "Native fixture collision did not become ready across Editor ticks",
            )
            yield
        checkpoint("native_binding_decode")
        values = raw.to_tuple()
        receipt["native_binding"] = {
            "hit_type": type(raw).__name__,
            "tuple_length": len(values),
            "fields": dict(zip(HIT_FIELDS, map(_json_value, values))),
            "standalone_break_hit_result_exported": callable(getattr(unreal.GameplayStatics, "break_hit_result", None)),
        }
        _check(isinstance(values, tuple) and len(values) == 18, "Unexpected native HitResult.to_tuple layout")
        _check(values[0] is True and values[1] is False, "Native tuple hit flags differ")
        _close(values[3], 200.0, "Native tuple collision distance")
        _check(values[9] == floor and values[10] == floor_component, "Native tuple actor/component identity differs")

        def trace(name, start, end, **kwargs):
            checkpoint(f"typed_trace.{name}")
            result = module.line_trace(
                start=start,
                end=end,
                world="editor",
                collision_channel="visibility",
                trace_complex=False,
                expected_world_path=world_path,
                **kwargs,
            )
            receipt["results"][name] = result
            _check(result.get("success") is True, f"Typed trace {name} failed: {result}")
            context = result["context"]
            _check(context["world"]["path"] == world_path, f"Typed trace {name} changed world")
            return context

        ground = trace("ground", ground_start, ground_end)
        _hit(ground, floor, floor_component, 200.0, _vector(0, 0, 0), _vector(0, 0, 1))
        left_hit = trace("left_wall", origin, _vector(-500, 0, 100))
        _hit(left_hit, left, left_component, 125.0, _vector(-125, 0, 100), _vector(1, 0, 0))
        right_hit = trace("right_wall", origin, _vector(500, 0, 100))
        _hit(right_hit, right, right_component, 125.0, _vector(125, 0, 100), _vector(-1, 0, 0))
        gap = left_hit["distance_cm"] + right_hit["distance_cm"]
        receipt["measured"] = {"ground_distance_cm": ground["distance_cm"], "clear_gap_cm": gap}
        _close(gap, 250.0, "Collision-derived clear gap")
        _miss(trace("miss", _vector(0, 0, 400), _vector(0, 0, 800)))
        ignored = trace("ignored_left_wall", origin, _vector(-500, 0, 100), ignored_actor_paths=[left.get_path_name()])
        _miss(ignored)
        _check(ignored["ignored_actor_paths"] == [left.get_path_name()], "Ignored actor binding differs")
        checkpoint("typed_trace.unknown_actor_path")
        unknown = module.line_trace(
            start=origin,
            end=_vector(-500, 0, 100),
            world="editor",
            collision_channel="visibility",
            trace_complex=False,
            expected_world_path=world_path,
            ignored_actor_paths=[world_path + ":PersistentLevel.DccSpatialMissingActor"],
        )
        receipt["results"]["unknown_actor_path"] = unknown
        _check(unknown.get("success") is False, "Unknown ignored actor path unexpectedly succeeded")
        _check(unknown["context"]["reason"] == "ignored_actor_not_found", "Unknown actor returned the wrong failure")
        receipt["success"] = True
    except Exception as exc:
        receipt["error"] = str(exc)
        receipt["traceback"] = traceback.format_exc()
    finally:
        cleanup = []
        for actor in reversed(actors):
            path = actor.get_path_name()
            try:
                destroyed = setup_call(f"cleanup.{path}", actor_subsystem.destroy_actor, actor)
                cleanup.append({"path": path, "destroyed": bool(destroyed)})
                if not destroyed:
                    receipt["success"] = False
            except Exception as exc:
                cleanup.append({"path": path, "destroyed": False, "error": str(exc)})
                receipt["success"] = False
        receipt["cleanup"] = cleanup
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        checkpoint("complete" if receipt["success"] else "failed")
    print(f"DCC_MCP_SPATIAL_SMOKE_RESULT={result_path} success={receipt['success']}", flush=True)
    if not receipt["success"]:
        raise RuntimeError(f"Spatial collision fixture failed; inspect {result_path}")
    return receipt


def main():
    import unreal  # noqa: PLC0415

    unreal.EditorPythonScripting.set_keep_python_script_alive(True)
    fixture = _fixture()
    state = {"handle": None}

    def advance(_delta_seconds):
        try:
            next(fixture)
            return
        except StopIteration:
            pass
        except Exception:
            unreal.log_error(traceback.format_exc())
        finally:
            # The generator remains suspended only when it yielded for a real
            # native tick; close this independent Editor after final receipt.
            if fixture.gi_frame is None:
                unreal.unregister_slate_post_tick_callback(state["handle"])
                unreal.EditorPythonScripting.set_keep_python_script_alive(False)

    try:
        state["handle"] = unreal.register_slate_post_tick_callback(advance)
    except Exception:
        unreal.EditorPythonScripting.set_keep_python_script_alive(False)
        raise
    return state


if __name__ == "__main__":
    _RUNNER = main()
