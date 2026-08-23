"""Start the 4K Movie Render Queue job for the Audi rain film."""

from __future__ import annotations

import json
from pathlib import Path

from _automotive_common import LOOKDEV_LEVEL, SEQUENCE_PATH, dispatch_or_error
from _movie_render import apply_cinematic_console_settings, configure_render_job
from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

EXPECTED_FRAMES = 240
_render_executor = None
_render_finished_callback = None


def _render_audi_rain_film(
    output_directory: str,
    width: int,
    height: int,
    temporal_samples: int,
) -> dict:
    import unreal

    global _render_executor, _render_finished_callback
    width = max(1920, min(7680, int(width)))
    height = max(1080, min(4320, int(height)))
    temporal_samples = max(1, min(32, int(temporal_samples)))
    level_subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    level_subsystem.load_level(LOOKDEV_LEVEL)
    sequence_object_path = f"{SEQUENCE_PATH}.{SEQUENCE_PATH.rsplit('/', 1)[-1]}"
    sequence = unreal.EditorAssetLibrary.load_asset(sequence_object_path)
    if sequence is None:
        return skill_error("Audi rain-film Level Sequence is missing", sequence_object_path)

    output_path = Path(output_directory).resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    marker_path = output_path.parent / "render_status.json"
    marker_path.write_text(json.dumps({"status": "starting"}), encoding="utf-8")

    subsystem = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
    if subsystem.is_rendering():
        return skill_error("Movie Render Queue is already rendering", "Wait for the current render to finish.")
    queue = subsystem.get_queue()
    queue.delete_all_jobs()
    job = queue.allocate_new_job(unreal.MoviePipelineExecutorJob)
    job.set_editor_property("job_name", "UE58_Audi_Rain_Film_4K")
    map_object_path = f"{LOOKDEV_LEVEL}.{LOOKDEV_LEVEL.rsplit('/', 1)[-1]}"
    job.set_editor_property("map", unreal.SoftObjectPath(map_object_path))
    job.set_editor_property("sequence", unreal.SoftObjectPath(sequence_object_path))

    configure_render_job(
        unreal,
        job,
        output_directory=output_path,
        file_name_format="AudiRain_{frame_number}",
        width=width,
        height=height,
        temporal_samples=temporal_samples,
    )
    apply_cinematic_console_settings(unreal)

    _render_executor = unreal.MoviePipelinePIEExecutor()

    def _finished(executor, success):
        marker_path.write_text(
            json.dumps({"status": "completed" if success else "failed", "success": bool(success)}),
            encoding="utf-8",
        )

    _render_finished_callback = _finished
    _render_executor.on_executor_finished_delegate.add_callable(_render_finished_callback)
    subsystem.render_queue_with_executor_instance(_render_executor)
    marker_path.write_text(json.dumps({"status": "rendering"}), encoding="utf-8")
    return skill_success(
        "Audi rain-film Movie Render Queue job started.",
        prompt="Poll render_status.json and the PNG frame count until all 240 frames are complete.",
        output_directory=str(output_path),
        status_file=str(marker_path),
        expected_frames=EXPECTED_FRAMES,
        resolution=[width, height],
        frame_rate=24,
        temporal_samples=temporal_samples,
        lighting_phases=["day", "dusk", "night", "storm_wash", "dawn"],
    )


@skill_entry
def render_audi_rain_film(
    output_directory: str = "F:/dcc-mcp-tester/AutomotiveConfigurator58/Renders/4k_frames",
    width: int = 3840,
    height: int = 2160,
    temporal_samples: int = 16,
    **kwargs,
) -> dict:
    return dispatch_or_error(
        _render_audi_rain_film,
        output_directory,
        width,
        height,
        temporal_samples,
        timeout_hint_secs=30,
        required_capability="movie_render_queue",
    )


def main(**kwargs) -> dict:
    return render_audi_rain_film(**kwargs)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
