"""Build the UE 5.8 Automotive Configurator Audi rain-film scene."""

from __future__ import annotations

import math
from pathlib import Path

from _automotive_common import (
    AUDI_BLUEPRINT,
    GENERATED_TAG,
    HDRI_PATH,
    LOOKDEV_LEVEL,
    SEQUENCE_PATH,
    actor_box,
    audit_actor,
    dispatch_or_error,
    set_property,
)
from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

SEQUENCE_END_FRAME = 240
SHOT_SPECS = (
    ("Weight_Hero", 0, 48, (920, -1160, 150), (760, -1030, 138), (0, 0, 78), 58.0, 3.2),
    ("Paint_Macro", 48, 96, (520, -660, 175), (410, -535, 148), (0, -55, 108), 85.0, 3.2),
    ("Wheel_Detail", 96, 144, (330, -265, 72), (275, -220, 66), (115, -15, 47), 92.0, 2.8),
    ("Rain_Impact", 144, 192, (650, -720, 255), (480, -620, 215), (0, -40, 118), 70.0, 3.5),
    ("Finale_Hero", 192, 240, (-980, -1060, 165), (-850, -930, 150), (0, 0, 82), 62.0, 3.5),
)


def _tag(actor, folder: str) -> None:
    actor.tags = [GENERATED_TAG]
    try:
        actor.set_folder_path(folder)
    except Exception:
        pass


def _spawn(unreal, subsystem, actor_class, name, location, rotation=None, folder="AutomotiveRainFilm"):
    actor = subsystem.spawn_actor_from_class(
        actor_class,
        location,
        rotation or unreal.Rotator(roll=0.0, pitch=0.0, yaw=0.0),
        False,
    )
    actor.set_actor_label(name)
    _tag(actor, folder)
    return actor


def _static_mesh_actor(unreal, subsystem, mesh, name, location, scale, material=None, folder="AutomotiveRainFilm/Set"):
    actor = _spawn(unreal, subsystem, unreal.StaticMeshActor, name, location, folder=folder)
    component = actor.get_component_by_class(unreal.StaticMeshComponent)
    component.set_static_mesh(mesh)
    actor.set_actor_scale3d(scale)
    if material is not None:
        component.set_material(0, material)
    set_property(component, "mobility", unreal.ComponentMobility.MOVABLE)
    return actor


def _expression(unreal, material, expression_type, x, y):
    return unreal.MaterialEditingLibrary.create_material_expression(material, expression_type, x, y)


def _constant(unreal, material, value, material_property, x, y):
    expression = _expression(unreal, material, unreal.MaterialExpressionConstant, x, y)
    expression.set_editor_property("r", float(value))
    unreal.MaterialEditingLibrary.connect_material_property(expression, "", material_property)


def _color(unreal, material, color, material_property, x, y):
    expression = _expression(unreal, material, unreal.MaterialExpressionConstant3Vector, x, y)
    expression.set_editor_property("constant", unreal.LinearColor(*color))
    unreal.MaterialEditingLibrary.connect_material_property(expression, "", material_property)


def _material(unreal, asset_tools, name, color, roughness, metallic=0.0, emissive=None):
    folder = "/Game/AutomotiveRainFilm/Materials"
    path = f"{folder}/{name}"
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        unreal.EditorAssetLibrary.delete_asset(path)
    material = asset_tools.create_asset(name, folder, unreal.Material, unreal.MaterialFactoryNew())
    _color(unreal, material, color, unreal.MaterialProperty.MP_BASE_COLOR, -460, -80)
    _constant(unreal, material, roughness, unreal.MaterialProperty.MP_ROUGHNESS, -460, 10)
    _constant(unreal, material, metallic, unreal.MaterialProperty.MP_METALLIC, -460, 90)
    _constant(unreal, material, 0.72, unreal.MaterialProperty.MP_SPECULAR, -460, 160)
    if emissive is not None:
        _color(unreal, material, emissive, unreal.MaterialProperty.MP_EMISSIVE_COLOR, -460, 240)
    unreal.MaterialEditingLibrary.recompile_material(material)
    unreal.EditorAssetLibrary.save_loaded_asset(material)
    return material


def _wet_floor_material(unreal, asset_tools):
    material = _material(unreal, asset_tools, "M_Wet_Blacktop", (0.009, 0.012, 0.017, 1.0), 0.19)
    noise = _expression(unreal, material, unreal.MaterialExpressionNoise, -560, 280)
    set_property(noise, "scale", 0.025)
    set_property(noise, "levels", 6)
    low = _expression(unreal, material, unreal.MaterialExpressionConstant, -460, 400)
    high = _expression(unreal, material, unreal.MaterialExpressionConstant, -460, 470)
    low.set_editor_property("r", 0.08)
    high.set_editor_property("r", 0.28)
    lerp = _expression(unreal, material, unreal.MaterialExpressionLinearInterpolate, -230, 330)
    unreal.MaterialEditingLibrary.connect_material_expressions(low, "", lerp, "A")
    unreal.MaterialEditingLibrary.connect_material_expressions(high, "", lerp, "B")
    unreal.MaterialEditingLibrary.connect_material_expressions(noise, "", lerp, "Alpha")
    unreal.MaterialEditingLibrary.connect_material_property(lerp, "", unreal.MaterialProperty.MP_ROUGHNESS)
    unreal.MaterialEditingLibrary.recompile_material(material)
    unreal.EditorAssetLibrary.save_loaded_asset(material)
    return material


def _particle_material(unreal, asset_tools, name, color, opacity):
    """Create a lit translucent water material with engine sphere mask and normals."""
    folder = "/Game/AutomotiveRainFilm/Materials"
    path = f"{folder}/{name}"
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        unreal.EditorAssetLibrary.delete_asset(path)
    material = asset_tools.create_asset(name, folder, unreal.Material, unreal.MaterialFactoryNew())
    set_property(material, "blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    set_property(material, "shading_model", unreal.MaterialShadingModel.MSM_DEFAULT_LIT)
    set_property(material, "two_sided", True)
    set_property(material, "used_with_niagara_sprites", True)
    _color(unreal, material, color, unreal.MaterialProperty.MP_BASE_COLOR, -220, -220)
    _constant(unreal, material, 0.035, unreal.MaterialProperty.MP_ROUGHNESS, -220, -130)
    _constant(unreal, material, 1.0, unreal.MaterialProperty.MP_SPECULAR, -220, -40)

    mask_texture = unreal.EditorAssetLibrary.load_asset(
        "/Engine/Functions/Engine_MaterialFunctions02/ExampleContent/Textures/SphereRenderMask"
    )
    normal_texture = unreal.EditorAssetLibrary.load_asset(
        "/Engine/Functions/Engine_MaterialFunctions02/ExampleContent/Textures/smoothNormalSphere"
    )
    if mask_texture is None or normal_texture is None:
        raise RuntimeError("Required engine droplet mask or normal texture is unavailable")
    mask_sample = _expression(unreal, material, unreal.MaterialExpressionTextureSample, -100, 190)
    mask_sample.set_editor_property("texture", mask_texture)
    normal_sample = _expression(unreal, material, unreal.MaterialExpressionTextureSample, -100, -20)
    normal_sample.set_editor_property("texture", normal_texture)
    normal_sample.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL)
    unreal.MaterialEditingLibrary.connect_material_property(normal_sample, "RGB", unreal.MaterialProperty.MP_NORMAL)
    power = _expression(unreal, material, unreal.MaterialExpressionPower, 500, 190)
    set_property(power, "const_exponent", 1.0)
    unreal.MaterialEditingLibrary.connect_material_expressions(mask_sample, "R", power, "Base")

    refraction_strength = _expression(unreal, material, unreal.MaterialExpressionConstant, 500, 60)
    refraction_strength.set_editor_property("r", 0.018)
    refraction_delta = _expression(unreal, material, unreal.MaterialExpressionMultiply, 680, 60)
    unreal.MaterialEditingLibrary.connect_material_expressions(power, "", refraction_delta, "A")
    unreal.MaterialEditingLibrary.connect_material_expressions(refraction_strength, "", refraction_delta, "B")
    refraction_base = _expression(unreal, material, unreal.MaterialExpressionConstant, 680, -30)
    refraction_base.set_editor_property("r", 1.0)
    refraction = _expression(unreal, material, unreal.MaterialExpressionAdd, 860, 60)
    unreal.MaterialEditingLibrary.connect_material_expressions(refraction_base, "", refraction, "A")
    unreal.MaterialEditingLibrary.connect_material_expressions(refraction_delta, "", refraction, "B")
    unreal.MaterialEditingLibrary.connect_material_property(refraction, "", unreal.MaterialProperty.MP_REFRACTION)
    opacity_constant = _expression(unreal, material, unreal.MaterialExpressionConstant, 500, 290)
    opacity_constant.set_editor_property("r", float(opacity))
    opacity_multiply = _expression(unreal, material, unreal.MaterialExpressionMultiply, 680, 190)
    unreal.MaterialEditingLibrary.connect_material_expressions(power, "", opacity_multiply, "A")
    unreal.MaterialEditingLibrary.connect_material_expressions(opacity_constant, "", opacity_multiply, "B")
    unreal.MaterialEditingLibrary.connect_material_property(opacity_multiply, "", unreal.MaterialProperty.MP_OPACITY)
    unreal.MaterialEditingLibrary.recompile_material(material)
    unreal.EditorAssetLibrary.save_loaded_asset(material)
    return material


def _distance(a, b) -> float:
    return math.sqrt(sum((left - right) ** 2 for left, right in zip(a, b)))


def _camera(unreal, subsystem, spec):
    name, _, _, start, _, target, focal_length, aperture = spec
    position = unreal.Vector(*start)
    target_vector = unreal.Vector(*target)
    actor = _spawn(
        unreal, subsystem, unreal.CineCameraActor, f"Camera_{name}", position, folder="AutomotiveRainFilm/Camera"
    )
    actor.set_actor_rotation(unreal.MathLibrary.find_look_at_rotation(position, target_vector), False)
    component = actor.get_cine_camera_component()
    set_property(component, "current_focal_length", focal_length)
    set_property(component, "current_aperture", aperture)
    focus = component.get_editor_property("focus_settings")
    set_property(focus, "focus_method", unreal.CameraFocusMethod.MANUAL)
    set_property(focus, "manual_focus_distance", _distance(start, target))
    set_property(focus, "smooth_focus_changes", True)
    set_property(focus, "focus_smoothing_interp_speed", 7.0)
    component.set_editor_property("focus_settings", focus)
    return actor


def _transform_track(unreal, binding, frames, positions, rotations, scales=None):
    track = binding.add_track(unreal.MovieScene3DTransformTrack)
    section = track.add_section()
    section.set_range(frames[0], frames[-1] + 1)
    values = {
        "Location.X": [p.x for p in positions],
        "Location.Y": [p.y for p in positions],
        "Location.Z": [p.z for p in positions],
        "Rotation.X": [r.roll for r in rotations],
        "Rotation.Y": [r.pitch for r in rotations],
        "Rotation.Z": [r.yaw for r in rotations],
        "Scale.X": [scale.x for scale in scales] if scales else [1.0] * len(frames),
        "Scale.Y": [scale.y for scale in scales] if scales else [1.0] * len(frames),
        "Scale.Z": [scale.z for scale in scales] if scales else [1.0] * len(frames),
    }
    names = []
    for channel in section.get_all_channels():
        name = str(channel.get_editor_property("channel_name"))
        names.append(name)
        for frame, value in zip(frames, values[name]):
            channel.add_key(unreal.FrameNumber(frame), float(value), 0.0)
    return names


def _float_track(unreal, binding, property_name, frames, values):
    track = binding.add_track(unreal.MovieSceneFloatTrack)
    track.set_property_name_and_path(property_name, property_name)
    section = track.add_section()
    section.set_range(frames[0], frames[-1] + 1)
    channel = list(section.get_all_channels())[0]
    for frame, value in zip(frames, values):
        channel.add_key(unreal.FrameNumber(frame), float(value), 0.0)


def _visibility_track(unreal, binding, frames, values):
    track = binding.add_track(unreal.MovieSceneVisibilityTrack)
    section = track.add_section()
    section.set_range(0, SEQUENCE_END_FRAME)
    channel = list(section.get_all_channels())[0]
    for frame, value in zip(frames, values):
        channel.add_key(unreal.FrameNumber(frame), bool(value))


def _sequence(
    unreal,
    asset_tools,
    cameras,
    flow_lights,
    intensity_tracks,
    wash_tracks,
    visibility_tracks,
):
    if unreal.EditorAssetLibrary.does_asset_exist(SEQUENCE_PATH):
        unreal.EditorAssetLibrary.delete_asset(SEQUENCE_PATH)
    sequence = asset_tools.create_asset(
        "LS_Audi_Rain_Film",
        "/Game/AutomotiveRainFilm/Cinematics",
        unreal.LevelSequence,
        unreal.LevelSequenceFactoryNew(),
    )
    sequence.set_display_rate(unreal.FrameRate(24, 1))
    sequence.set_tick_resolution_directly(unreal.FrameRate(24000, 1))
    sequence.set_playback_start(0)
    sequence.set_playback_end(SEQUENCE_END_FRAME)
    cut_track = sequence.add_track(unreal.MovieSceneCameraCutTrack)
    first_binding_id = None
    channel_names = []
    for camera, spec in zip(cameras, SHOT_SPECS):
        _, start_frame, end_frame, start, end, target, _, _ = spec
        positions = [unreal.Vector(*start), unreal.Vector(*end)]
        target_vector = unreal.Vector(*target)
        rotations = [unreal.MathLibrary.find_look_at_rotation(position, target_vector) for position in positions]
        binding = sequence.add_spawnable_from_instance(camera)
        channel_names = _transform_track(unreal, binding, [start_frame, end_frame - 1], positions, rotations)
        binding_id = sequence.get_binding_id(binding)
        if first_binding_id is None:
            first_binding_id = binding_id
        cut = cut_track.add_section()
        cut.set_range(start_frame, end_frame)
        cut.set_camera_binding_id(binding_id)

    for light, frames, points in flow_lights:
        positions = [unreal.Vector(*point) for point in points]
        rotations = [
            unreal.MathLibrary.find_look_at_rotation(position, unreal.Vector(0, 0, 90)) for position in positions
        ]
        _transform_track(unreal, sequence.add_possessable(light), frames, positions, rotations)

    for component, frames, values in intensity_tracks:
        _float_track(unreal, sequence.add_possessable(component), "Intensity", frames, values)

    for actor, frames, points, rotations, scale in wash_tracks:
        positions = [unreal.Vector(*point) for point in points]
        rotation_values = [
            unreal.Rotator(roll=rotation[0], pitch=rotation[1], yaw=rotation[2]) for rotation in rotations
        ]
        scales = [unreal.Vector(*scale) for _ in frames]
        _transform_track(
            unreal,
            sequence.add_possessable(actor),
            frames,
            positions,
            rotation_values,
            scales,
        )

    for actor, frames, values in visibility_tracks:
        _visibility_track(unreal, sequence.add_possessable(actor), frames, values)

    unreal.EditorAssetLibrary.save_loaded_asset(sequence)
    return sequence, first_binding_id, channel_names


def _niagara_field(
    unreal,
    subsystem,
    system,
    material,
    name,
    location,
    rotation,
    scale,
    folder,
):
    actor = _spawn(unreal, subsystem, unreal.NiagaraActor, name, location, rotation, folder)
    component = actor.get_component_by_class(unreal.NiagaraComponent)
    component.set_asset(system)
    if material is not None:
        component.set_material(0, material)
    set_property(component, "cast_shadow", False)
    component.activate(True)
    actor.set_actor_scale3d(scale)
    return actor


def _niagara_module(unreal, fx, emitter, name, asset_path, category, version=None):
    asset_data = fx.create_asset_data(asset_path)
    args = (
        unreal.CreateScriptContextArgs(asset_data, version) if version else unreal.CreateScriptContextArgs(asset_data)
    )
    return emitter.find_or_add_module_script(name, args, category)


def _create_niagara_droplet_system(
    unreal,
    asset_tools,
    *,
    asset_path,
    emitter_name,
    material,
    spawn_rate,
    box_size,
    velocity,
    lifetime,
    sprite_size,
    gravity=(0.0, 0.0, 0.0),
    local_space=False,
    velocity_aligned=True,
):
    """Author a real Niagara droplet emitter instead of cloning the Fountain template."""
    if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        unreal.EditorAssetLibrary.delete_asset(asset_path)
    folder, name = asset_path.rsplit("/", 1)
    system = asset_tools.create_asset(name, folder, unreal.NiagaraSystem, unreal.NiagaraSystemFactoryNew())
    if system is None:
        raise RuntimeError(f"Failed to create Niagara system: {asset_path}")

    fx = unreal.FXConverterUtilitiesLibrary
    system_context = fx.create_system_conversion_context(system)
    emitter = system_context.add_empty_emitter(emitter_name)
    emitter.set_local_space(bool(local_space))

    emitter_state = _niagara_module(
        unreal,
        fx,
        emitter,
        "EmitterState",
        "/Niagara/Modules/Emitter/EmitterState.EmitterState",
        unreal.ScriptExecutionCategory.EMITTER_UPDATE,
        [1, 0],
    )
    emitter_state.set_parameter(
        "Life Cycle Mode",
        fx.create_script_input_enum(
            "/Niagara/Enums/ENiagaraEmitterLifeCycleMode.ENiagaraEmitterLifeCycleMode",
            "Self",
        ),
    )
    emitter_state.set_parameter(
        "Loop Behavior",
        fx.create_script_input_enum(
            "/Niagara/Enums/ENiagara_EmitterStateOptions.ENiagara_EmitterStateOptions",
            "Infinite",
        ),
    )

    spawn = _niagara_module(
        unreal,
        fx,
        emitter,
        "SpawnRate",
        "/Niagara/Modules/Emitter/SpawnRate.SpawnRate",
        unreal.ScriptExecutionCategory.EMITTER_UPDATE,
        [1, 0],
    )
    spawn.set_parameter("SpawnRate", fx.create_script_input_float(float(spawn_rate)))

    initialize = _niagara_module(
        unreal,
        fx,
        emitter,
        "InitializeParticle",
        "/Niagara/Modules/Spawn/Initialization/V2/InitializeParticle.InitializeParticle",
        unreal.ScriptExecutionCategory.PARTICLE_SPAWN,
        [1, 0],
    )
    initialize.set_parameter("Lifetime", fx.create_script_input_float(float(lifetime)))
    initialize.set_parameter(
        "Sprite Size Mode",
        fx.create_script_input_enum(
            "/Niagara/Enums/ENiagara_SizeScaleMode.ENiagara_SizeScaleMode",
            "Non-Uniform",
        ),
    )
    initialize.set_parameter(
        "Sprite Size",
        fx.create_script_input_vec2(unreal.Vector2D(float(sprite_size[0]), float(sprite_size[1]))),
        True,
        True,
    )

    location = _niagara_module(
        unreal,
        fx,
        emitter,
        "ShapeLocation",
        "/Niagara/Modules/Spawn/Location/V2/ShapeLocation.ShapeLocation",
        unreal.ScriptExecutionCategory.PARTICLE_SPAWN,
    )
    location.set_parameter(
        "Shape Primitive",
        fx.create_script_input_enum(
            "/Niagara/Enums/Location/ENiagara_LocationShapes.ENiagara_LocationShapes",
            "Box",
        ),
    )
    location.set_parameter("Box Size", fx.create_script_input_vector(unreal.Vector(*box_size)))

    add_velocity = _niagara_module(
        unreal,
        fx,
        emitter,
        "AddVelocity",
        "/Niagara/Modules/Spawn/Velocity/AddVelocity.AddVelocity",
        unreal.ScriptExecutionCategory.PARTICLE_SPAWN,
        [1, 2],
    )
    add_velocity.set_parameter("Velocity", fx.create_script_input_vector(unreal.Vector(*velocity)))

    if any(abs(float(value)) > 0.001 for value in gravity):
        gravity_module = _niagara_module(
            unreal,
            fx,
            emitter,
            "GravityForce",
            "/Niagara/Modules/Update/Forces/GravityForce.GravityForce",
            unreal.ScriptExecutionCategory.PARTICLE_UPDATE,
        )
        gravity_module.set_parameter("Gravity", fx.create_script_input_vector(unreal.Vector(*gravity)))

    _niagara_module(
        unreal,
        fx,
        emitter,
        "ParticleState",
        "/Niagara/Modules/Update/Lifetime/ParticleState.ParticleState",
        unreal.ScriptExecutionCategory.PARTICLE_UPDATE,
        [1, 1],
    )
    _niagara_module(
        unreal,
        fx,
        emitter,
        "SolveForcesAndVelocity",
        "/Niagara/Modules/Solvers/SolveForcesAndVelocity.SolveForcesAndVelocity",
        unreal.ScriptExecutionCategory.PARTICLE_UPDATE,
    )

    renderer = unreal.NiagaraSpriteRendererProperties()
    renderer.set_editor_property("Material", material)
    set_property(
        renderer,
        "alignment",
        getattr(
            unreal.NiagaraSpriteAlignment,
            "VELOCITY_ALIGNED" if velocity_aligned else "UNALIGNED",
        ),
    )
    set_property(renderer, "facing_mode", getattr(unreal.NiagaraSpriteFacingMode, "FACE_CAMERA"))
    set_property(renderer, "cast_shadows", False)
    emitter.add_renderer("SpriteRenderer", renderer)

    system_context.set_warmup_tick_delta(1.0 / 60.0)
    system_context.set_warmup_time(1.25)
    system_context.finalize()
    set_property(system, "warmup_time", 1.25)
    set_property(system, "warmup_tick_delta", 1.0 / 60.0)
    unreal.EditorAssetLibrary.save_loaded_asset(system)
    return system


def _build_audi_rain_film(rain_density: int, preview_width: int, preview_height: int) -> dict:
    import unreal

    rain_density = max(240, min(1600, int(rain_density)))
    preview_width = max(960, min(3840, int(preview_width)))
    preview_height = max(540, min(2160, int(preview_height)))
    audi_class = unreal.EditorAssetLibrary.load_blueprint_class(AUDI_BLUEPRINT)
    hdri = unreal.EditorAssetLibrary.load_asset(HDRI_PATH)
    if audi_class is None or hdri is None:
        return skill_error(
            "Required Automotive Configurator assets are missing",
            f"audi_class={audi_class!r}, hdri={hdri!r}",
            possible_solutions=["Verify the official Automotive Configurator sample is installed."],
        )

    level_subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    actor_subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    if unreal.EditorAssetLibrary.does_asset_exist(LOOKDEV_LEVEL):
        level_subsystem.load_level(LOOKDEV_LEVEL)
        for actor in list(actor_subsystem.get_all_level_actors()):
            if GENERATED_TAG in [str(tag) for tag in actor.tags]:
                actor_subsystem.destroy_actor(actor)
    elif not level_subsystem.new_level(LOOKDEV_LEVEL):
        return skill_error("Failed to create the Audi rain-film level", LOOKDEV_LEVEL)

    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    cube = unreal.EditorAssetLibrary.load_asset("/Engine/BasicShapes/Cube.Cube")
    cylinder = unreal.EditorAssetLibrary.load_asset("/Engine/BasicShapes/Cylinder.Cylinder")
    if cube is None or cylinder is None:
        return skill_error("Engine basic-shape assets are unavailable", "Cube or Cylinder could not be loaded.")

    wet_floor = _wet_floor_material(unreal, asset_tools)
    rain_particle_material = _particle_material(
        unreal,
        asset_tools,
        "M_Rain_Droplet_Particle",
        (0.10, 0.18, 0.30, 1.0),
        0.50,
    )
    impact_particle_material = _particle_material(
        unreal,
        asset_tools,
        "M_Rain_Impact_Particle",
        (0.12, 0.22, 0.36, 1.0),
        0.46,
    )
    lens_particle_material = _particle_material(
        unreal,
        asset_tools,
        "M_Lens_Rain_Droplet",
        (0.18, 0.30, 0.48, 1.0),
        0.58,
    )
    wash_particle_material = _particle_material(
        unreal,
        asset_tools,
        "M_Water_Wash_Particle",
        (0.16, 0.28, 0.46, 1.0),
        0.48,
    )
    wall_material = _material(unreal, asset_tools, "M_Studio_Wall", (0.015, 0.020, 0.028, 1.0), 0.34)
    puddle_material = _material(unreal, asset_tools, "M_Deep_Puddle", (0.002, 0.006, 0.011, 1.0), 0.025)
    cyan_emissive = _material(
        unreal,
        asset_tools,
        "M_Practical_Cyan",
        (0.0, 0.035, 0.055, 1.0),
        0.12,
        0.1,
        (0.0, 7.5, 12.0, 1.0),
    )

    ground = _static_mesh_actor(
        unreal,
        actor_subsystem,
        cube,
        "Wet_Blacktop_Stage",
        unreal.Vector(0, 0, -10),
        unreal.Vector(26, 18, 0.2),
        wet_floor,
    )
    set_property(ground.get_component_by_class(unreal.StaticMeshComponent), "cast_shadow", True)

    for name, location, scale in (
        ("Negative_Space_Backdrop", unreal.Vector(0, 1320, 310), unreal.Vector(22, 0.25, 6.2)),
        ("Studio_Mass_Left", unreal.Vector(-930, 540, 300), unreal.Vector(2.6, 4.8, 6.0)),
        ("Studio_Mass_Right", unreal.Vector(920, 650, 215), unreal.Vector(2.0, 2.7, 4.3)),
        ("Studio_Canopy", unreal.Vector(-120, 720, 620), unreal.Vector(12, 1.1, 0.28)),
    ):
        _static_mesh_actor(unreal, actor_subsystem, cube, name, location, scale, wall_material)

    for index, (location, scale) in enumerate(
        (
            (unreal.Vector(-460, -120, 0.12), unreal.Vector(3.8, 1.7, 0.001)),
            (unreal.Vector(390, 250, 0.12), unreal.Vector(2.9, 1.25, 0.001)),
            (unreal.Vector(720, -410, 0.12), unreal.Vector(2.0, 0.85, 0.001)),
        )
    ):
        _static_mesh_actor(
            unreal,
            actor_subsystem,
            cylinder,
            f"Puddle_{index:02d}",
            location,
            scale,
            puddle_material,
            "AutomotiveRainFilm/Set/Puddles",
        )

    for index, x in enumerate((-760, -410, 410, 760)):
        _static_mesh_actor(
            unreal,
            actor_subsystem,
            cube,
            f"Cyan_Practical_{index:02d}",
            unreal.Vector(x, 1110, 170),
            unreal.Vector(0.018, 0.08, 1.35),
            cyan_emissive,
        )

    audi = _spawn(
        unreal,
        actor_subsystem,
        audi_class,
        "Hero_Audi_A5_Official",
        unreal.Vector(0, 0, 30.5),
        unreal.Rotator(roll=0, pitch=0, yaw=-90),
        "AutomotiveRainFilm/Hero",
    )
    minimum, _ = actor_box(audi)
    initial_ground_gap = None
    if minimum is not None:
        initial_ground_gap = float(minimum.z)
        location = audi.get_actor_location()
        audi.set_actor_location(unreal.Vector(location.x, location.y, location.z + 0.35 - minimum.z), False, False)
    settled_minimum, _ = actor_box(audi)
    audit = audit_actor(unreal, audi)

    rain_path = "/Game/AutomotiveRainFilm/FX/NS_Heavy_Rain_Droplets"
    impact_path = "/Game/AutomotiveRainFilm/FX/NS_Rain_Impact_Spray"
    wash_path = "/Game/AutomotiveRainFilm/FX/NS_Car_Surface_Wash"
    lens_path = "/Game/AutomotiveRainFilm/FX/NS_Near_Lens_Droplets"
    rain_system = _create_niagara_droplet_system(
        unreal,
        asset_tools,
        asset_path=rain_path,
        emitter_name="HeavyRain",
        material=rain_particle_material,
        spawn_rate=rain_density * 5.0,
        box_size=(1850.0, 1550.0, 760.0),
        velocity=(82.0, -28.0, -1650.0),
        lifetime=0.78,
        sprite_size=(0.34, 0.68),
        gravity=(0.0, 0.0, -240.0),
        velocity_aligned=False,
    )
    impact_system = _create_niagara_droplet_system(
        unreal,
        asset_tools,
        asset_path=impact_path,
        emitter_name="ImpactSpray",
        material=impact_particle_material,
        spawn_rate=rain_density * 0.10,
        box_size=(42.0, 42.0, 6.0),
        velocity=(35.0, -22.0, 285.0),
        lifetime=0.34,
        sprite_size=(0.75, 1.65),
        gravity=(0.0, 0.0, -980.0),
        local_space=True,
    )
    wash_system = _create_niagara_droplet_system(
        unreal,
        asset_tools,
        asset_path=wash_path,
        emitter_name="SurfaceWash",
        material=wash_particle_material,
        spawn_rate=240.0,
        box_size=(72.0, 14.0, 5.0),
        velocity=(0.0, 0.0, -320.0),
        lifetime=0.78,
        sprite_size=(1.1, 2.6),
        gravity=(0.0, 0.0, -220.0),
        local_space=True,
    )
    lens_system = _create_niagara_droplet_system(
        unreal,
        asset_tools,
        asset_path=lens_path,
        emitter_name="LensDrops",
        material=lens_particle_material,
        spawn_rate=1.5,
        box_size=(30.0, 18.0, 3.0),
        velocity=(0.0, 0.0, -2.0),
        lifetime=3.4,
        sprite_size=(1.4, 2.0),
        gravity=(0.0, 0.0, 0.0),
        local_space=True,
        velocity_aligned=False,
    )

    rain_fields = [
        _niagara_field(
            unreal,
            actor_subsystem,
            rain_system,
            rain_particle_material,
            "Niagara_Heavy_Rain_Volume",
            unreal.Vector(0, -40, 590),
            unreal.Rotator(roll=0, pitch=0, yaw=0),
            unreal.Vector(1.0, 1.0, 1.0),
            "AutomotiveRainFilm/FX/Rain",
        )
    ]

    impact_points = (
        ("Hood", unreal.Vector(80, -115, 128), unreal.Vector(0.42, 0.42, 0.32)),
        ("Roof", unreal.Vector(-35, 30, 172), unreal.Vector(0.55, 0.55, 0.34)),
        ("Windshield", unreal.Vector(-10, -55, 150), unreal.Vector(0.48, 0.48, 0.30)),
        ("RearDeck", unreal.Vector(-145, 95, 122), unreal.Vector(0.38, 0.38, 0.28)),
    )
    impact_fields = [
        _niagara_field(
            unreal,
            actor_subsystem,
            impact_system,
            impact_particle_material,
            f"Niagara_Impact_{name}",
            location,
            unreal.Rotator(roll=0, pitch=0, yaw=0),
            scale,
            "AutomotiveRainFilm/FX/Impacts",
        )
        for name, location, scale in impact_points
    ]

    wash_specs = (
        (
            "Roof_Wash",
            [(0, 20, 176), (-65, 85, 154), (-145, 130, 124)],
            [(0, 58, -90), (0, 62, -90), (0, 68, -90)],
            (1.45, 0.44, 0.22),
        ),
        (
            "Windshield_Wash",
            [(0, -50, 160), (48, -112, 132), (108, -170, 104)],
            [(0, 42, -90), (0, 48, -90), (0, 55, -90)],
            (1.25, 0.36, 0.20),
        ),
        (
            "Hood_Wash",
            [(82, -118, 130), (138, -180, 111), (205, -238, 88)],
            [(0, 36, -90), (0, 44, -90), (0, 52, -90)],
            (1.6, 0.40, 0.18),
        ),
    )
    wash_tracks = []
    wash_fields = []
    for name, points, rotations, scale in wash_specs:
        actor = _niagara_field(
            unreal,
            actor_subsystem,
            wash_system,
            wash_particle_material,
            f"Niagara_{name}",
            unreal.Vector(*points[0]),
            unreal.Rotator(roll=rotations[0][0], pitch=rotations[0][1], yaw=rotations[0][2]),
            unreal.Vector(*scale),
            "AutomotiveRainFilm/FX/WaterWash",
        )
        wash_fields.append(actor)
        wash_tracks.append((actor, [144, 168, 191], points, rotations, scale))

    lens_fields = []
    lens_tracks = []
    visibility_tracks = []
    for actor in wash_fields:
        visibility_tracks.append((actor, [0, 143, 144, 191, 192, 239], [False, False, True, True, False, False]))
    for index, spec in enumerate(SHOT_SPECS):
        _, start_frame, end_frame, start, end, target, _, _ = spec
        points = [
            tuple(value + (target[axis] - value) * 0.055 for axis, value in enumerate(camera_point))
            for camera_point in (start, end)
        ]
        location = unreal.Vector(*points[0])
        lens_fields.append(
            _niagara_field(
                unreal,
                actor_subsystem,
                lens_system,
                lens_particle_material,
                f"Niagara_Near_Lens_{index:02d}",
                location,
                unreal.Rotator(roll=180, pitch=0, yaw=0),
                unreal.Vector(1.0, 1.0, 1.0),
                "AutomotiveRainFilm/FX/NearLens",
            )
        )
        actor = lens_fields[-1]
        rotations = []
        for point in points:
            rotation = unreal.MathLibrary.find_look_at_rotation(unreal.Vector(*point), unreal.Vector(*target))
            rotations.append((rotation.roll, rotation.pitch, rotation.yaw))
        lens_tracks.append((actor, [start_frame, end_frame - 1], points, rotations, (1.0, 1.0, 1.0)))
        if start_frame == 0:
            frames = [0, end_frame - 1, end_frame, 239]
            values = [True, True, False, False]
        elif end_frame == SEQUENCE_END_FRAME:
            frames = [0, start_frame - 1, start_frame, 239]
            values = [False, False, True, True]
        else:
            frames = [0, start_frame - 1, start_frame, end_frame - 1, end_frame, 239]
            values = [False, False, True, True, False, False]
        visibility_tracks.append((actor, frames, values))

    skylight = _spawn(
        unreal,
        actor_subsystem,
        unreal.SkyLight,
        "HDRI_Studio_Skylight",
        unreal.Vector(0, 0, 520),
        folder="AutomotiveRainFilm/Lighting",
    )
    sky = skylight.get_component_by_class(unreal.SkyLightComponent)
    set_property(sky, "source_type", unreal.SkyLightSourceType.SLS_SPECIFIED_CUBEMAP)
    set_property(sky, "cubemap", hdri)
    set_property(sky, "intensity_scale", 1.25)
    set_property(sky, "source_cubemap_angle", 28.0)
    set_property(sky, "lower_hemisphere_is_solid_color", False)
    set_property(sky, "mobility", unreal.ComponentMobility.MOVABLE)
    sky.recapture_sky()

    day_sun = _spawn(
        unreal,
        actor_subsystem,
        unreal.DirectionalLight,
        "Animated_Day_Night_Sun",
        unreal.Vector(0, 0, 650),
        unreal.Rotator(roll=0, pitch=-28, yaw=138),
        "AutomotiveRainFilm/Lighting",
    )
    day_sun_component = day_sun.get_component_by_class(unreal.DirectionalLightComponent)
    set_property(day_sun_component, "intensity", 11000.0)
    set_property(day_sun_component, "light_color", unreal.Color(255, 225, 190, 255))
    set_property(day_sun_component, "atmosphere_sun_light", True)
    set_property(day_sun_component, "volumetric_scattering_intensity", 0.8)
    set_property(day_sun_component, "contact_shadow_length", 0.08)
    intensity_frames = [0, 48, 96, 144, 192, 239]
    intensity_tracks = [
        (day_sun_component, intensity_frames, [11000.0, 6500.0, 1200.0, 200.0, 3000.0, 11000.0]),
        (sky, intensity_frames, [1.35, 1.15, 0.62, 0.42, 0.72, 1.3]),
    ]

    key_specs = (
        ("Key_Softbox", (430, -540, 420), 32000.0, unreal.Color(204, 222, 242, 255), 260.0, 340.0),
        ("Rim_Cyan", (-520, 285, 330), 21000.0, unreal.Color(110, 176, 230, 255), 170.0, 300.0),
        ("Fill_Warm", (650, 390, 220), 14000.0, unreal.Color(238, 178, 128, 255), 150.0, 240.0),
        ("Roof_Strip", (-120, 180, 650), 24000.0, unreal.Color(176, 204, 234, 255), 430.0, 90.0),
        ("Grille_Kicker", (310, -260, 82), 9000.0, unreal.Color(150, 205, 255, 255), 55.0, 150.0),
    )
    for name, point, intensity, color, width, height in key_specs:
        location = unreal.Vector(*point)
        light = _spawn(unreal, actor_subsystem, unreal.RectLight, name, location, folder="AutomotiveRainFilm/Lighting")
        light.set_actor_rotation(unreal.MathLibrary.find_look_at_rotation(location, unreal.Vector(0, 0, 90)), False)
        component = light.get_component_by_class(unreal.RectLightComponent)
        set_property(component, "intensity", intensity)
        set_property(component, "light_color", color)
        set_property(component, "source_width", width)
        set_property(component, "source_height", height)
        set_property(component, "volumetric_scattering_intensity", 0.42)
        set_property(component, "mobility", unreal.ComponentMobility.MOVABLE)
        if name == "Key_Softbox":
            values = [18000.0, 14000.0, 9000.0, 8000.0, 9000.0, 17000.0]
        elif name == "Rim_Cyan":
            values = [9000.0, 13000.0, 23000.0, 27000.0, 22000.0, 14000.0]
        elif name == "Fill_Warm":
            values = [12000.0, 8000.0, 3500.0, 3200.0, 4200.0, 10000.0]
        else:
            values = [intensity, intensity * 0.75, intensity * 0.55, intensity * 0.48, intensity * 0.6, intensity * 0.8]
        intensity_tracks.append((component, intensity_frames, values))

    flow_lights = [
        (
            day_sun,
            intensity_frames,
            [
                (900, -900, 800),
                (300, -900, 1000),
                (-700, -500, 450),
                (-900, 300, 180),
                (-400, 800, 420),
                (800, -900, 800),
            ],
        )
    ]
    for name, intensity, color, frames, points in (
        (
            "Flow_Cool",
            24000.0,
            unreal.Color(145, 200, 242, 255),
            [0, 72, 144, 239],
            [(-720, -300, 260), (0, -260, 215), (720, -240, 270), (-440, 130, 245)],
        ),
        (
            "Flow_Warm",
            18000.0,
            unreal.Color(242, 160, 105, 255),
            [20, 96, 176, 239],
            [(650, 350, 200), (30, 320, 255), (-680, 280, 225), (500, -120, 305)],
        ),
    ):
        location = unreal.Vector(*points[0])
        light = _spawn(
            unreal, actor_subsystem, unreal.RectLight, name, location, folder="AutomotiveRainFilm/Lighting/Flow"
        )
        light.set_actor_rotation(unreal.MathLibrary.find_look_at_rotation(location, unreal.Vector(0, 0, 90)), False)
        component = light.get_component_by_class(unreal.RectLightComponent)
        set_property(component, "intensity", intensity)
        set_property(component, "light_color", color)
        set_property(component, "source_width", 34.0)
        set_property(component, "source_height", 410.0)
        set_property(component, "volumetric_scattering_intensity", 0.5)
        set_property(component, "mobility", unreal.ComponentMobility.MOVABLE)
        flow_lights.append((light, frames, points))
        if "Cool" in name:
            values = [2500.0, 7000.0, 18000.0, intensity, intensity, 9000.0]
        else:
            values = [1800.0, 5200.0, 14000.0, intensity, intensity, 7000.0]
        intensity_tracks.append((component, intensity_frames, values))

    fog = _spawn(
        unreal,
        actor_subsystem,
        unreal.ExponentialHeightFog,
        "Rain_Atmospheric_Perspective",
        unreal.Vector(0, 0, 0),
        folder="AutomotiveRainFilm/Atmosphere",
    )
    fog_component = fog.get_component_by_class(unreal.ExponentialHeightFogComponent)
    set_property(fog_component, "fog_density", 0.014)
    set_property(fog_component, "fog_height_falloff", 0.085)
    set_property(fog_component, "fog_inscattering_color", unreal.LinearColor(0.035, 0.07, 0.12, 1.0))
    set_property(fog_component, "volumetric_fog", True)
    set_property(fog_component, "volumetric_fog_scattering_distribution", 0.3)
    set_property(fog_component, "volumetric_fog_albedo", unreal.Color(105, 140, 185, 255))
    set_property(fog_component, "volumetric_fog_extinction_scale", 0.72)
    _spawn(
        unreal,
        actor_subsystem,
        unreal.SkyAtmosphere,
        "Rain_Sky_Atmosphere",
        unreal.Vector(),
        folder="AutomotiveRainFilm/Atmosphere",
    )

    post = _spawn(
        unreal,
        actor_subsystem,
        unreal.PostProcessVolume,
        "ACES_Color_DOF",
        unreal.Vector(),
        folder="AutomotiveRainFilm/Camera",
    )
    set_property(post, "unbound", True)
    settings = post.get_editor_property("settings")
    for name, value in (
        ("override_auto_exposure_method", True),
        ("auto_exposure_method", unreal.AutoExposureMethod.AEM_MANUAL),
        ("override_auto_exposure_bias", True),
        ("auto_exposure_bias", 0.0),
        ("override_color_saturation", True),
        ("color_saturation", unreal.Vector4(0.93, 0.95, 0.98, 1.0)),
        ("override_color_contrast", True),
        ("color_contrast", unreal.Vector4(1.08, 1.07, 1.06, 1.0)),
        ("override_film_slope", True),
        ("film_slope", 0.9),
        ("override_film_toe", True),
        ("film_toe", 0.43),
        ("override_film_shoulder", True),
        ("film_shoulder", 0.22),
        ("override_bloom_intensity", True),
        ("bloom_intensity", 0.18),
        ("override_motion_blur_amount", True),
        ("motion_blur_amount", 0.0),
        ("override_vignette_intensity", True),
        ("vignette_intensity", 0.22),
        ("override_ambient_occlusion_intensity", True),
        ("ambient_occlusion_intensity", 1.4),
        ("override_ambient_occlusion_radius", True),
        ("ambient_occlusion_radius", 75.0),
    ):
        set_property(settings, name, value)
    post.set_editor_property("settings", settings)

    for command in (
        "r.MotionBlurQuality 4",
        "r.DepthOfFieldQuality 4",
        "r.VolumetricFog 1",
        "r.Lumen.Reflections.Quality 4",
        "r.Lumen.ScreenProbeGather.Quality 4",
    ):
        unreal.SystemLibrary.execute_console_command(None, command)

    cameras = [_camera(unreal, actor_subsystem, spec) for spec in SHOT_SPECS]
    sequence, first_binding_id, channel_names = _sequence(
        unreal,
        asset_tools,
        cameras,
        flow_lights,
        intensity_tracks,
        wash_tracks + lens_tracks,
        visibility_tracks,
    )
    first_position = unreal.Vector(*SHOT_SPECS[0][3])
    first_rotation = unreal.MathLibrary.find_look_at_rotation(first_position, unreal.Vector(*SHOT_SPECS[0][5]))
    cameras[0].set_actor_location(first_position, False, False)
    cameras[0].set_actor_rotation(first_rotation, False)
    unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
    unreal.LevelSequenceEditorBlueprintLibrary.set_current_time(0)
    unreal.LevelSequenceEditorBlueprintLibrary.force_update()
    unreal.EditorLevelLibrary.set_level_viewport_camera_info(first_position, first_rotation)

    level_subsystem.save_current_level()
    unreal.EditorAssetLibrary.save_directory("/Game/AutomotiveRainFilm", only_if_is_dirty=False, recursive=True)
    preview = Path(str(unreal.Paths.project_saved_dir())) / "Screenshots" / "Audi_Rain_Film_Preview.png"
    preview.parent.mkdir(parents=True, exist_ok=True)
    unreal.AutomationLibrary.take_high_res_screenshot(
        preview_width, preview_height, str(preview), cameras[0], False, False
    )

    return skill_success(
        "Built the UE 5.8 official Audi A5 rain-film scene and requested a validation still.",
        prompt="Inspect the preview, then call render_audi_rain_film for final 4K frames.",
        level=LOOKDEV_LEVEL,
        sequence=SEQUENCE_PATH,
        audi_blueprint=AUDI_BLUEPRINT,
        official_automotive_materials_preserved=True,
        initial_ground_gap_cm=initial_ground_gap,
        final_ground_contact_z=None if settled_minimum is None else settled_minimum.z,
        hdri_asset=HDRI_PATH,
        hdri_class=hdri.get_class().get_name(),
        hdri_primary_lighting=True,
        niagara_rain_system=rain_path,
        niagara_impact_system=impact_path,
        rain_volume_count=len(rain_fields),
        impact_field_count=len(impact_fields),
        near_lens_field_count=len(lens_fields),
        water_wash_particle_field_count=len(wash_fields),
        water_wash_frames=[144, 191],
        rain_density=rain_density,
        mesh_rain_actor_count=0,
        lighting_phases=["day", "dusk", "night", "storm_wash", "dawn"],
        animated_lighting_track_count=len(intensity_tracks),
        shot_count=len(SHOT_SPECS),
        sequence_frames=SEQUENCE_END_FRAME,
        camera_channel_names=channel_names,
        first_camera_binding_id=str(first_binding_id),
        preview_path=str(preview),
        audit=audit,
    )


@skill_entry
def build_audi_rain_film(
    rain_density: int = 720, preview_width: int = 1920, preview_height: int = 1080, **kwargs
) -> dict:
    return dispatch_or_error(
        _build_audi_rain_film,
        rain_density,
        preview_width,
        preview_height,
        timeout_hint_secs=180,
    )


def main(**kwargs) -> dict:
    return build_audi_rain_film(**kwargs)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
