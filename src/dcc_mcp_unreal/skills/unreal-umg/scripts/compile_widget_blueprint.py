"""Compile a Widget Blueprint and return compilation status.

Validates the blueprint after making widget changes. Returns any
compilation errors or warnings from the Unreal compile step.
"""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


def _validate_asset_path(asset_path: str) -> str | None:
    if not asset_path:
        return "widget_blueprint_path is required"
    if not asset_path.startswith("/Game/"):
        return f"widget_blueprint_path must be under /Game/ namespace, got: {asset_path!r}"
    if ".." in asset_path or "\\" in asset_path:
        return f"widget_blueprint_path contains invalid characters: {asset_path!r}"
    return None


@skill_entry
def compile_widget_blueprint(
    widget_blueprint_path: str,
    **kwargs: object,
) -> dict:
    """Compile a Widget Blueprint and return errors/warnings."""
    err = _validate_asset_path(widget_blueprint_path)
    if err:
        return skill_error("Invalid asset path", err)

    try:
        import unreal
    except ImportError:
        return skill_error("Unreal Engine is not available", "ImportError: unreal module not found")

    try:
        blueprint = unreal.load_asset(widget_blueprint_path)
        if blueprint is None:
            return skill_error(
                f"Widget Blueprint not found: {widget_blueprint_path}",
                "Asset could not be loaded",
            )

        # Compile the blueprint; Unreal reports the outcome through the
        # compiler results below rather than a return value.
        unreal.KismetSystemLibrary.compile_blueprint(blueprint)

        # Collect compile results
        compiler_results = unreal.BlueprintEditorLibrary.get_compiler_results(blueprint)

        errors = []
        warnings_list = []
        if compiler_results:
            for entry in compiler_results:
                entry_str = str(entry)
                if "error" in entry_str.lower():
                    errors.append(entry_str)
                elif "warning" in entry_str.lower():
                    warnings_list.append(entry_str)

        if errors:
            return skill_error(
                f"Widget Blueprint '{widget_blueprint_path}' has compile errors",
                f"{len(errors)} error(s): {'; '.join(errors[:5])}",
                prompt="Fix the errors and recompile. Use list_widget_hierarchy to inspect widget setup.",
                errors=errors,
                warnings=warnings_list,
                compile_success=False,
            )

        if warnings_list:
            return skill_success(
                f"Widget Blueprint compiled with {len(warnings_list)} warning(s)",
                prompt="Blueprint is usable but has warnings. Review the warnings list.",
                widget_blueprint_path=widget_blueprint_path,
                errors=[],
                warnings=warnings_list,
                compile_success=True,
            )

        return skill_success(
            f"Widget Blueprint '{widget_blueprint_path}' compiled successfully",
            prompt="The blueprint is ready to use.",
            widget_blueprint_path=widget_blueprint_path,
            errors=[],
            warnings=[],
            compile_success=True,
        )
    except Exception as exc:
        return skill_error(
            f"Failed to compile Widget Blueprint '{widget_blueprint_path}'",
            repr(exc),
            prompt="Check Unreal Editor output log for details.",
        )
