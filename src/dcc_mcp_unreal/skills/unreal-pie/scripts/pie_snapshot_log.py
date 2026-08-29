"""Bounded, queryable snapshots of the Unreal Engine Output Log."""

from __future__ import annotations

import os
import re
from collections import OrderedDict, deque
from datetime import datetime, timezone
from typing import Iterable, Optional

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import unreal_from_exception, unreal_success

_TIMESTAMP_RE = re.compile(r"^\[(?P<timestamp>\d{4}\.\d{2}\.\d{2}-[^\]]+)\]")
_CATEGORY_RE = re.compile(r"(?P<category>[A-Za-z_][\w]*)\s*:\s*(?P<verbosity>[A-Za-z]+)\s*:\s*(?P<message>.*)$")
_MAX_CURSOR_OFFSET = 10_000_000
_MAX_API_PAYLOAD_BYTES = 8 * 1024 * 1024


def _parse_timestamp(value: str) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y.%m.%d-%H.%M.%S:%f")
        except ValueError:
            return None
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)


def _entry_parts(line: str) -> tuple[Optional[datetime], str, str]:
    timestamp = None
    match = _TIMESTAMP_RE.match(line)
    if match:
        timestamp = _parse_timestamp(match.group("timestamp"))
        line = line[match.end() :]
    match = _CATEGORY_RE.match(line)
    if not match:
        return timestamp, "", line.strip()
    return timestamp, match.group("category"), match.group("message").strip()


def _process_lines(
    lines: Iterable[str],
    max_lines: int,
    category_filter: str = "",
    message_contains: str = "",
    include_verbosity: bool = True,
    since_timestamp: Optional[datetime] = None,
    until_timestamp: Optional[datetime] = None,
    since_line: int = 0,
    dedupe: bool = False,
) -> dict:
    """Filter an iterable in one pass, retaining at most ``max_lines`` results."""
    category_filter = category_filter.casefold()
    message_contains = message_contains.casefold()
    accepted = deque(maxlen=max_lines)
    groups: OrderedDict[tuple[str, str], list] = OrderedDict()
    total_lines = 0
    for raw in lines:
        line = str(raw).rstrip("\r\n")
        line_number = total_lines
        total_lines += 1
        if line_number < since_line or not line.strip():
            continue
        timestamp, category, message = _entry_parts(line)
        if (since_timestamp or until_timestamp) and timestamp is None:
            continue
        if since_timestamp and timestamp < since_timestamp:
            continue
        if until_timestamp and timestamp > until_timestamp:
            continue
        if category_filter and category_filter not in category.casefold():
            continue
        if message_contains and message_contains not in message.casefold():
            continue
        output = line
        if include_verbosity:
            upper = line.upper()
            verbosity = "Error" if "ERROR" in upper else "Warning" if ("WARNING" in upper or "WARN" in upper) else "Log"
            output = f"[{verbosity}] {line}"
        key = (category.casefold(), message.casefold())
        if dedupe:
            if key in groups:
                groups[key][1] += 1
                groups.move_to_end(key)
                groups[key][0] = output
            else:
                groups[key] = [output, 1]
                if len(groups) > max_lines:
                    groups.popitem(last=False)
        else:
            accepted.append([key, output])
    if dedupe:
        entries = [item[0] for item in groups.values()]
        occurrence_counts = [item[1] for item in groups.values()]
    else:
        entries = [item[1] for item in accepted]
        occurrence_counts = [1 for _ in accepted]
    return {
        "entries": entries,
        "count": len(entries),
        "occurrence_counts": occurrence_counts,
        # Keep both spellings discoverable for clients that model a singular
        # occurrence_count field while preserving the list-oriented contract.
        "occurrence_count": occurrence_counts,
        "next_cursor": str(total_lines),
        "cursor": str(total_lines),
        "cursor_supported": True,
    }


def _read_log_via_file(log_path: str, max_lines: int, line_filter: str = "", **kwargs) -> dict:
    """Read a log file without loading it into memory."""
    if not os.path.isfile(log_path):
        cursor = str(kwargs.get("since_line", 0))
        return {
            "entries": [],
            "count": 0,
            "occurrence_counts": [],
            "occurrence_count": [],
            "next_cursor": cursor,
            "cursor": cursor,
            "cursor_supported": True,
            "source_consistent": True,
        }
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
            return _process_lines(fh, max_lines, line_filter, **kwargs)
    except OSError:
        cursor = str(kwargs.get("since_line", 0))
        return {
            "entries": [],
            "count": 0,
            "occurrence_counts": [],
            "occurrence_count": [],
            "next_cursor": cursor,
            "cursor": cursor,
            "cursor_supported": True,
            "source_consistent": True,
        }


def _collect_log_entries(
    max_lines: int,
    line_filter: str = "",
    include_verbosity: bool = True,
    *,
    message_contains: str = "",
    since_timestamp: Optional[datetime] = None,
    until_timestamp: Optional[datetime] = None,
    since_line: int = 0,
    dedupe: bool = False,
    cursor: Optional[int] = None,
    cursor_requested: bool = False,
) -> dict:
    """Collect recent log entries using the best available method.

    Tries, in order:
    1. Log file from project Saved/Logs directory.
    2. The unreal.log API (UE 5.0+).
    """
    import unreal  # noqa: PLC0415

    method = "none"
    log_path = ""
    file_fallback = ""
    since_line = cursor if cursor is not None else since_line
    try:
        project_dir = unreal.Paths.project_dir()
        log_dir = os.path.join(project_dir, "Saved", "Logs")
        if os.path.isdir(log_dir):
            log_files = sorted(
                (f for f in os.listdir(log_dir) if f.endswith(".log")),
                key=lambda f: os.path.getmtime(os.path.join(log_dir, f)),
                reverse=True,
            )
            if log_files:
                log_path = os.path.join(log_dir, log_files[0])
                file_size = os.path.getsize(log_path)
                if file_size and (since_line > _MAX_CURSOR_OFFSET or since_line > file_size):
                    return {
                        "entries": [],
                        "count": 0,
                        "occurrence_counts": [],
                        "occurrence_count": [],
                        "next_cursor": str(since_line),
                        "cursor": str(since_line),
                        "cursor_supported": True,
                        "source_consistent": True,
                        "fallback_reason": "",
                        "method": "log_file",
                        "log_path": log_path,
                    }
                result = _read_log_via_file(
                    log_path,
                    max_lines,
                    line_filter,
                    message_contains=message_contains,
                    include_verbosity=include_verbosity,
                    since_timestamp=since_timestamp,
                    until_timestamp=until_timestamp,
                    since_line=since_line,
                    dedupe=dedupe,
                )
                if result["count"]:
                    return {
                        **result,
                        "method": "log_file",
                        "log_path": log_path,
                        "source_consistent": True,
                        "fallback_reason": "",
                    }
                file_fallback = "empty_or_filtered_file"
            else:
                file_fallback = "no_file"
        else:
            file_fallback = "no_file"
    except Exception:
        pass
    if hasattr(unreal, "log") and hasattr(unreal.log, "get_log"):
        try:
            if since_line or cursor_requested:
                return {
                    "error": "unreal.log backend does not support physical cursor continuation",
                    "method": "unreal.log.get_log",
                    "log_path": "",
                    "entries": [],
                    "count": 0,
                    "occurrence_counts": [],
                    "occurrence_count": [],
                    "next_cursor": None,
                    "cursor": None,
                    "cursor_supported": False,
                    "source_consistent": file_fallback in ("", "no_file"),
                    "fallback_reason": file_fallback,
                }
            try:
                raw = unreal.log.get_log(max_lines)
            except TypeError:
                return {
                    "error": "unreal.log backend does not expose a bounded get_log(max_lines) signature",
                    "method": "unreal.log.get_log",
                    "log_path": "",
                    "entries": [],
                    "count": 0,
                    "occurrence_counts": [],
                    "occurrence_count": [],
                    "next_cursor": None,
                    "cursor": None,
                    "cursor_supported": False,
                    "source_consistent": file_fallback in ("", "no_file"),
                    "fallback_reason": file_fallback,
                }
            if isinstance(raw, str) and len(raw.encode("utf-8", errors="replace")) > _MAX_API_PAYLOAD_BYTES:
                return {
                    "error": "unreal.log payload exceeds the bounded API read budget",
                    "method": "unreal.log.get_log",
                    "log_path": "",
                    "entries": [],
                    "count": 0,
                    "occurrence_counts": [],
                    "occurrence_count": [],
                    "next_cursor": None,
                    "cursor": None,
                    "cursor_supported": False,
                    "source_consistent": not bool(file_fallback and file_fallback != "no_file"),
                    "fallback_reason": file_fallback,
                }
            # Keep iterable backends lazy; converting a large generator to a
            # list would defeat the max_lines memory bound.
            lines = raw.splitlines() if isinstance(raw, str) else (raw or ())
            result = _process_lines(
                lines,
                max_lines,
                line_filter,
                message_contains,
                include_verbosity,
                since_timestamp,
                until_timestamp,
                since_line,
                dedupe,
            )
            return {
                **result,
                "method": "unreal.log.get_log",
                "log_path": "",
                "next_cursor": None,
                "cursor": None,
                "cursor_supported": False,
                "fallback_reason": file_fallback,
                "source_consistent": file_fallback in ("", "no_file"),
            }
        except Exception:
            pass
    cursor = str(since_line)
    return {
        "error": "no log source available",
        "method": method,
        "log_path": log_path,
        "entries": [],
        "count": 0,
        "occurrence_counts": [],
        "occurrence_count": [],
        "next_cursor": cursor,
        "cursor": cursor,
        "cursor_supported": False,
        "source_consistent": False,
        "fallback_reason": file_fallback or "no_source",
    }


@skill_entry
def pie_snapshot_log(
    max_lines: int = 200,
    filter: str = "",
    include_verbosity: bool = True,
    message_contains: str = "",
    since_timestamp: str = "",
    until_timestamp: str = "",
    since_line: int = 0,
    cursor: str = "",
    dedupe: bool = False,
    **kwargs,
) -> dict:
    """Snapshot recent entries from the Unreal Engine Output Log.

    Args:
        max_lines: Maximum number of log lines to return.
        filter: Optional substring filter on log category.
        include_verbosity: Tag lines with [Error]/[Warning]/[Log] prefix.
    """
    try:
        max_lines = min(max(int(max_lines), 1), 2000)
        since_line = int(since_line)
        if since_line < 0:
            raise ValueError("since_line must be non-negative")
        if since_line > _MAX_CURSOR_OFFSET:
            raise ValueError("since_line exceeds the supported scan budget")
        cursor_value = None
        if cursor:
            if not str(cursor).isdigit():
                raise ValueError("cursor must be numeric")
            cursor_value = int(cursor)
            if cursor_value > _MAX_CURSOR_OFFSET:
                raise ValueError("cursor exceeds the supported scan budget")
        since_dt = _parse_timestamp(since_timestamp)
        until_dt = _parse_timestamp(until_timestamp)
        if (since_timestamp and since_dt is None) or (until_timestamp and until_dt is None):
            raise ValueError("timestamps must be ISO-8601 values")
        if since_dt and until_dt and since_dt > until_dt:
            raise ValueError("since_timestamp must not be later than until_timestamp")

        result = _collect_log_entries(
            max_lines=max_lines,
            line_filter=str(filter or "").strip(),
            include_verbosity=include_verbosity,
            message_contains=str(message_contains or "").strip(),
            since_timestamp=since_dt,
            until_timestamp=until_dt,
            since_line=since_line,
            dedupe=bool(dedupe),
            cursor=cursor_value,
            cursor_requested=bool(cursor),
        )
        if result.get("error"):
            raise ValueError(result["error"])

        return unreal_success(
            "Log snapshot captured: {} entries via {}".format(result["count"], result["method"]),
            prompt="Review log entries for errors, warnings, or Automation Test output.",
            max_lines=max_lines,
            filter=str(filter or "").strip(),
            message_contains=str(message_contains or "").strip(),
            since_timestamp=since_timestamp,
            until_timestamp=until_timestamp,
            since_line=since_line,
            dedupe=bool(dedupe),
            **result,
        )
    except Exception as exc:
        return unreal_from_exception(exc, "Failed to snapshot output log")
