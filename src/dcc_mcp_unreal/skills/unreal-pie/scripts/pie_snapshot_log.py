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
    match = _CATEGORY_RE.search(line)
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
    counts: OrderedDict[tuple[str, str], int] = OrderedDict()
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
            if key in counts:
                counts[key] += 1
                for item in accepted:
                    if item[0] == key:
                        accepted.remove(item)
                        accepted.append([key, output])
                        break
            else:
                counts[key] = 1
                accepted.append([key, output])
                while len(counts) > len(accepted):
                    counts.popitem(last=False)
        else:
            accepted.append([key, output])
    entries = [item[1] for item in accepted]
    occurrence_counts = [counts.get(item[0], 1) if dedupe else 1 for item in accepted]
    return {
        "entries": entries,
        "count": len(entries),
        "occurrence_counts": occurrence_counts,
        # Keep both spellings discoverable for clients that model a singular
        # occurrence_count field while preserving the list-oriented contract.
        "occurrence_count": occurrence_counts,
        "next_cursor": str(total_lines),
        "cursor": str(total_lines),
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
) -> dict:
    """Collect recent log entries using the best available method.

    Tries, in order:
    1. Log file from project Saved/Logs directory.
    2. The unreal.log API (UE 5.0+).
    """
    import unreal  # noqa: PLC0415

    method = "none"
    log_path = ""
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
                return {**result, "method": "log_file", "log_path": log_path}
    except Exception:
        pass
    if hasattr(unreal, "log") and hasattr(unreal.log, "get_log"):
        try:
            try:
                raw = unreal.log.get_log()
            except TypeError:
                raw = unreal.log.get_log(max_lines)
            lines = raw.splitlines() if isinstance(raw, str) else list(raw or [])
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
            return {**result, "method": "unreal.log.get_log", "log_path": ""}
        except Exception:
            pass
    cursor = str(since_line)
    return {
        "method": method,
        "log_path": log_path,
        "entries": [],
        "count": 0,
        "occurrence_counts": [],
        "occurrence_count": [],
        "next_cursor": cursor,
        "cursor": cursor,
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
        cursor_value = None
        if cursor:
            if not str(cursor).isdigit():
                raise ValueError("cursor must be numeric")
            cursor_value = int(cursor)
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
        )

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
