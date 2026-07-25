"""Snapshot the Unreal Engine Output Log buffer.

Reads recent log entries from the in-engine log system. Supports optional
verbosity tagging and substring filtering.
"""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import unreal_from_exception, unreal_success


def _read_log_via_file(log_path: str, max_lines: int, line_filter: str = "") -> list:
    """Read log entries from the log file on disk (fallback path)."""
    import os

    entries = []
    if not os.path.isfile(log_path):
        return entries

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()

        # Take last N lines
        lines = lines[-max_lines:] if len(lines) > max_lines else lines

        for line in lines:
            line = line.rstrip("\n\r")
            if not line:
                continue
            if line_filter and line_filter.lower() not in line.lower():
                continue
            entries.append(line)

        return entries
    except Exception:
        return entries


def _collect_log_entries(max_lines: int, line_filter: str = "", include_verbosity: bool = True) -> dict:
    """Collect recent log entries using the best available method.

    Tries, in order:
    1. Log file from project Saved/Logs directory.
    2. The unreal.log API (UE 5.0+).
    """
    import os

    import unreal  # noqa: PLC0415

    entries = []
    method = "none"
    log_path = ""

    # Path 1: Read from project log file
    try:
        project_dir = unreal.Paths.project_dir()
        log_dir = os.path.join(project_dir, "Saved", "Logs")
        if os.path.isdir(log_dir):
            # Find the most recent log file
            log_files = sorted(
                [f for f in os.listdir(log_dir) if f.endswith(".log")],
                key=lambda f: os.path.getmtime(os.path.join(log_dir, f)),
                reverse=True,
            )
            if log_files:
                log_path = os.path.join(log_dir, log_files[0])
                entries = _read_log_via_file(log_path, max_lines, line_filter)
                method = "log_file"
    except Exception:
        pass

    # Path 2: Try unreal.log if available and no entries yet
    if not entries and hasattr(unreal, "log"):
        try:
            log_obj = unreal.log
            if hasattr(log_obj, "get_log") and callable(log_obj.get_log):
                raw = log_obj.get_log(max_lines)
                if isinstance(raw, str):
                    for line in raw.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        if line_filter and line_filter.lower() not in line.lower():
                            continue
                        entries.append(line)
                    method = "unreal.log.get_log"
        except Exception:
            pass

    # Apply verbosity tagging if requested
    if include_verbosity and entries:
        tagged = []
        for line in entries:
            verbosity = "Log"
            upper = line.upper()
            if "ERROR" in upper:
                verbosity = "Error"
            elif "WARNING" in upper or "WARN" in upper:
                verbosity = "Warning"
            tagged.append("[{}] {}".format(verbosity, line))
        entries = tagged

    return {
        "method": method,
        "log_path": log_path,
        "entries": entries,
        "count": len(entries),
        "max_lines": max_lines,
        "filter": line_filter,
    }


@skill_entry
def pie_snapshot_log(
    max_lines: int = 200,
    filter: str = "",
    include_verbosity: bool = True,
    **kwargs,
) -> dict:
    """Snapshot recent entries from the Unreal Engine Output Log.

    Args:
        max_lines: Maximum number of log lines to return.
        filter: Optional substring filter on log lines.
        include_verbosity: Tag lines with [Error]/[Warning]/[Log] prefix.
    """
    try:
        if max_lines <= 0:
            max_lines = 200
        if max_lines > 2000:
            max_lines = 2000

        result = _collect_log_entries(
            max_lines=max_lines,
            line_filter=str(filter or "").strip(),
            include_verbosity=include_verbosity,
        )

        return unreal_success(
            "Log snapshot captured: {} entries via {}".format(result["count"], result["method"]),
            prompt="Review log entries for errors, warnings, or Automation Test output.",
            **result,
        )
    except Exception as exc:
        return unreal_from_exception(exc, "Failed to snapshot output log")
