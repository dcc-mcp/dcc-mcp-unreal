"""Standard-library-only protection for shared Unreal build resources."""

from __future__ import annotations

import contextlib
import errno
import os
import time
from pathlib import Path
from typing import Mapping, Optional


class BuildInterruptedError(RuntimeError):
    """Build descendants may remain alive after an interrupted invocation."""

    def __init__(self, message: str, *, primary_error: Optional[BaseException] = None):
        super().__init__(message)
        self.primary_error = primary_error


def child_build_environment(overrides: Optional[Mapping[str, str]] = None) -> dict[str, str]:
    environment = os.environ.copy()
    if overrides:
        environment.update(overrides)
    for name in tuple(environment):
        if name.casefold() == "uebp_uatmutexnowait":
            environment.pop(name)
    return environment


def ubt_user_config_path() -> Optional[Path]:
    if os.name == "nt":
        import ctypes

        folder = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x001A, None, 0, folder) != 0 or not folder.value:
            raise OSError("Cannot resolve the ApplicationData folder used by UnrealBuildTool")
        appdata = folder.value
    else:
        appdata = os.environ.get("APPDATA")
    return Path(appdata) / "Unreal Engine" / "UnrealBuildTool" / "BuildConfiguration.xml" if appdata else None


@contextlib.contextmanager
def ubt_user_config_lock(config_path: Path, timeout: float = 120):
    """Serialize builds that read or temporarily replace the same user config."""
    lock_path = config_path.with_name("dcc-mcp-build.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError("Timed out waiting for UBT user config lock: {}".format(lock_path)) from exc
                time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def write_durable_file(path: Path, data: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


@contextlib.contextmanager
def ubt_user_config_guard(config_path: Optional[Path], *, clear: bool = False, timeout: float = 120):
    """Guard readers and legacy writers; interrupted builds require manual recovery."""
    if config_path is None:
        yield
        return
    backup_path = config_path.with_suffix(".xml.dcc-mcp-backup")
    pending_path = config_path.with_suffix(".xml.dcc-mcp-new")
    active_path = config_path.with_suffix(".xml.dcc-mcp-active")
    empty_config = (
        '<?xml version="1.0" encoding="utf-8" ?>\n'
        '<Configuration xmlns="https://www.unrealengine.com/BuildConfiguration">\n'
        "</Configuration>\n"
    ).encode("utf-8")
    with ubt_user_config_lock(config_path, timeout):
        # shortcut: hard-killed builds need manual recovery after their UAT children stop.
        if any(path.exists() for path in (backup_path, pending_path, active_path)):
            raise RuntimeError(
                "Unfinished UBT build; stop its UAT children before reconciling {} and {}".format(
                    config_path, backup_path
                )
            )
        write_durable_file(active_path, b"Build in progress; stop UAT children before recovering this transaction.\n")
        restore = True
        try:
            if clear and config_path.exists():
                original = config_path.read_bytes()
                write_durable_file(pending_path, original)
                os.replace(pending_path, backup_path)
                write_durable_file(pending_path, empty_config)
                os.replace(pending_path, config_path)
                print("[build-uplugin] Temporarily cleared cross-version UBT config: {}".format(config_path))
            yield
        except BaseException as exc:
            # Cancellation cannot prove that AutomationTool's descendants have stopped.
            restore = isinstance(exc, Exception) and not isinstance(exc, BuildInterruptedError)
            raise
        finally:
            if restore:
                if backup_path.exists():
                    if not config_path.exists() or config_path.read_bytes() not in (empty_config, original):
                        raise RuntimeError(
                            "UBT config changed during build; original preserved at {}".format(backup_path)
                        )
                    os.replace(backup_path, config_path)
                    print("[build-uplugin] Restored UBT config: {}".format(config_path))
                pending_path.unlink(missing_ok=True)
                active_path.unlink()
