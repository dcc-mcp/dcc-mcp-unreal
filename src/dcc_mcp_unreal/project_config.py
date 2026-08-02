"""Safe, project-scoped Unreal project configuration helpers."""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

PROJECT_CONFIG_SECTION = "[ConsoleVariables]"

# Keep the public surface intentionally narrow. New keys should be added with
# a test and a documented reason, rather than opening arbitrary INI writes to
# the agent.
ALLOWED_CONSOLE_VARIABLES = {
    "r.EyeAdaptation.CachedLightingPreExposure": "number",
    "r.Lumen.GlobalIllumination": "integer",
    "r.Lumen.Reflections.Allow": "integer",
    "r.LumenScene.SurfaceCache.AtlasSize": "atlas",
    "r.Nanite": "integer",
    "r.Shadow.Virtual.Enable": "integer",
    "r.TemporalAA.Upsampling": "integer",
}


def project_config_path(project_dir: Optional[str] = None) -> Path:
    """Return the active project's DefaultEngine.ini path."""
    if project_dir:
        root = Path(project_dir).expanduser().resolve()
    else:
        import unreal  # noqa: PLC0415

        root = Path(unreal.Paths.project_dir()).resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError("The Unreal project directory does not exist")
    return root / "Config" / "DefaultEngine.ini"


def _validate_section(section: str) -> str:
    normalized = section.strip()
    if not normalized.startswith("["):
        normalized = f"[{normalized}]"
    if normalized != PROJECT_CONFIG_SECTION:
        raise ValueError(f"Only {PROJECT_CONFIG_SECTION} is supported")
    return normalized


def validate_settings(settings: Mapping[str, Any]) -> Dict[str, Any]:
    if not settings:
        raise ValueError("At least one renderer setting is required")
    normalized: Dict[str, Any] = {}
    for key, value in settings.items():
        if key not in ALLOWED_CONSOLE_VARIABLES:
            raise ValueError(f"Unsupported renderer setting: {key}")
        kind = ALLOWED_CONSOLE_VARIABLES[key]
        if kind == "atlas":
            try:
                parsed = int(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key} must be a positive power of two") from exc
            if parsed < 1024 or parsed > 32768 or parsed & (parsed - 1):
                raise ValueError(f"{key} must be a power of two between 1024 and 32768")
            normalized[key] = parsed
        elif kind == "integer":
            if isinstance(value, bool):
                value = int(value)
            try:
                parsed = int(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key} must be an integer") from exc
            if parsed not in (0, 1):
                raise ValueError(f"{key} must be 0 or 1")
            normalized[key] = parsed
        else:
            try:
                normalized[key] = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key} must be numeric") from exc
    return normalized


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8-sig").splitlines()


def read_console_variables(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    section = None
    for line in _read_lines(path):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped
            continue
        if section != PROJECT_CONFIG_SECTION or not stripped or stripped.startswith((";", "#")):
            continue
        match = re.match(r"^([^=]+?)\s*=\s*(.*?)\s*$", stripped)
        if match:
            values[match.group(1).strip()] = match.group(2)
    return values


def requested_keys(values: Mapping[str, str], keys: Optional[Iterable[str]]) -> list[str]:
    """Select explicit keys or only configured allowlisted keys by default."""
    if keys is not None:
        return list(keys)
    return [key for key in values if key in ALLOWED_CONSOLE_VARIABLES]


def _serialize(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def patch_console_variables(path: Path, settings: Mapping[str, Any]) -> Dict[str, Any]:
    """Patch only the allowlisted console variables and atomically persist them."""
    normalized = validate_settings(settings)
    newline = "\r\n" if path.exists() and "\r\n" in path.read_text(encoding="utf-8-sig") else "\n"
    lines = _read_lines(path)
    section_start = next((i for i, line in enumerate(lines) if line.strip() == PROJECT_CONFIG_SECTION), None)
    changed: Dict[str, Any] = {}
    if section_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(PROJECT_CONFIG_SECTION)
        section_start = len(lines) - 1
        section_end = len(lines)
    else:
        section_end = next(
            (i for i in range(section_start + 1, len(lines)) if lines[i].strip().startswith("[")),
            len(lines),
        )

    seen = set()
    for index in range(section_start + 1, section_end):
        match = re.match(r"^\s*([^=;#]+?)\s*=", lines[index])
        if not match:
            continue
        key = match.group(1).strip()
        if key not in normalized:
            continue
        value = _serialize(normalized[key])
        replacement = f"{key}={value}"
        if lines[index].strip() != replacement:
            lines[index] = replacement
            changed[key] = normalized[key]
        seen.add(key)

    missing = [key for key in normalized if key not in seen]
    if missing:
        lines[section_end:section_end] = [f"{key}={_serialize(normalized[key])}" for key in missing]
        changed.update({key: normalized[key] for key in missing})

    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        payload = newline.join(lines) + newline
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
            handle.write(payload)
            temporary = Path(handle.name)
        temporary.replace(path)
    return {"changed": changed, "values": read_console_variables(path)}


def runtime_console_values(keys: Iterable[str]) -> Dict[str, Any]:
    """Read runtime values when the embedded Unreal Python API exposes them."""
    import unreal  # noqa: PLC0415

    system = getattr(unreal, "SystemLibrary", None)
    result: Dict[str, Any] = {}
    if system is None:
        return result
    for key in keys:
        for method_name in ("get_console_variable_int", "get_console_variable_float", "get_console_variable_string"):
            method = getattr(system, method_name, None)
            if method is None:
                continue
            try:
                result[key] = method(key)
                break
            except Exception:
                continue
    return result
