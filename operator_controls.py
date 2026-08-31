"""Private, payload-free operator controls and reports."""

from __future__ import annotations

import fcntl
import json
import os
import pwd
import re
import signal
import stat
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from analysis_log import (
    ANALYSIS_ONLY_START_DAY,
    analysis_paths,
    intent_path,
    ready_path,
    validate_day_ready,
)
from analysis_view import DEFAULT_OUTPUT_DIR
from scripts.check_analysis_day import check_day

RUNTIME_STATE_SCHEMA = 1
RUNTIME_DIR_NAME = "ActivityLogger"
LOCK_NAME = "activitylogger.lock"
STATE_NAME = "operator_state.json"
OUTCOMES_NAME = "weekly_review_outcomes.md"
_DAY_NAME = re.compile(r"^daily_log_(\d{4}-\d{2}-\d{2})\.md$")
_PACK_NAME = re.compile(
    r"^weekly_review_\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}_(?:5|7)d$"
)
_OUTCOMES = frozenset({"accepted", "ignored", "tried"})


@dataclass(frozen=True)
class ProcessState:
    running: bool
    pid: int | None


def runtime_dir(home: Path | None = None) -> Path:
    base = home or Path(pwd.getpwuid(os.getuid()).pw_dir)
    return base / "Library" / "Application Support" / RUNTIME_DIR_NAME


def _ensure_private_dir(path: Path, *, parents: bool = False) -> Path:
    if path.is_symlink():
        raise OSError("refusing symlinked private directory")
    path.mkdir(mode=0o700, parents=parents, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise OSError("refusing unsafe private directory")
    os.chmod(path, 0o700)
    return path


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_runtime_state(
    *,
    running: bool,
    manual_paused: bool,
    capture_paused: bool,
    control_revision: int,
    home: Path | None = None,
) -> Path:
    root = _ensure_private_dir(runtime_dir(home), parents=True)
    destination = root / STATE_NAME
    document = {
        "schema": RUNTIME_STATE_SCHEMA,
        "pid": os.getpid(),
        "running": running,
        "manual_paused": manual_paused,
        "capture_paused": capture_paused,
        "control_revision": control_revision,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    fd, raw_path = tempfile.mkstemp(dir=root, prefix=f".{STATE_NAME}.", suffix=".tmp")
    staged = Path(raw_path)
    try:
        os.fchmod(fd, 0o600)
        data = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()
        offset = 0
        while offset < len(data):
            written = os.write(fd, data[offset:])
            if written <= 0:
                raise OSError("short runtime state write")
            offset += written
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.replace(staged, destination)
        os.chmod(destination, 0o600, follow_symlinks=False)
        _fsync_dir(root)
    finally:
        try:
            staged.unlink()
        except FileNotFoundError:
            pass
    return destination


def _read_private_json(path: Path) -> dict[str, object] | None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or info.st_mode & 0o077
            or info.st_size > 4096
        ):
            raise OSError("refusing unsafe private state")
        raw = os.read(fd, 4097)
    finally:
        os.close(fd)
    value = json.loads(raw)
    return value if isinstance(value, dict) else None


def read_runtime_state(home: Path | None = None) -> dict[str, object] | None:
    try:
        state = _read_private_json(runtime_dir(home) / STATE_NAME)
        if state is None or state.get("schema") != RUNTIME_STATE_SCHEMA:
            return None
        return state
    except (OSError, UnicodeError, ValueError, TypeError):
        return None


def initial_manual_pause(home: Path | None = None) -> bool:
    """Keep a prior pause, and fail closed if an existing state is unreadable."""
    path = runtime_dir(home) / STATE_NAME
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    state = read_runtime_state(home)
    if state is None or type(state.get("manual_paused")) is not bool:
        return True
    return bool(state["manual_paused"])


def process_state(home: Path | None = None) -> ProcessState:
    path = runtime_dir(home) / LOCK_NAME
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return ProcessState(False, None)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or info.st_mode & 0o077
        ):
            return ProcessState(False, None)
        raw = os.read(fd, 32).decode("ascii", "strict").strip()
        pid = int(raw)
        if pid <= 0:
            return ProcessState(False, None)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            try:
                os.kill(pid, 0)
            except (ProcessLookupError, PermissionError):
                return ProcessState(False, None)
            return ProcessState(True, pid)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return ProcessState(False, None)
    except (OSError, UnicodeError, ValueError):
        return ProcessState(False, None)
    finally:
        os.close(fd)


def set_manual_pause(paused: bool, *, home: Path | None = None, timeout: float = 5.0) -> dict[str, object]:
    process = process_state(home)
    if not process.running or process.pid is None:
        raise RuntimeError("ActivityLogger is not running")
    before = read_runtime_state(home) or {}
    revision = int(before.get("control_revision", -1))
    os.kill(process.pid, signal.SIGUSR1 if paused else signal.SIGUSR2)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = read_runtime_state(home)
        if (
            state is not None
            and state.get("pid") == process.pid
            and state.get("manual_paused") is paused
            and int(state.get("control_revision", -1)) > revision
        ):
            return state
        if not process_state(home).running:
            break
        time.sleep(0.05)
    raise RuntimeError("manual privacy control was not confirmed")


def _mode(path: Path) -> str:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return "missing"
    if info.st_uid != os.getuid() or stat.S_ISLNK(info.st_mode):
        return "unsafe"
    return f"{stat.S_IMODE(info.st_mode):03o}"


def health_report(log_dir: Path, day: date, *, home: Path | None = None) -> dict[str, object]:
    process = process_state(home)
    analysis_file, invalid_file = analysis_paths(log_dir, day)
    intent_file = intent_path(log_dir, day)
    proof_file = ready_path(log_dir, day)
    report: dict[str, object] = {
        "running": process.running,
        "pid": process.pid,
        "day": day.isoformat(),
        "format": "unknown",
        "intent_match": False,
        "invalid_marker": invalid_file.exists(),
        "readiness": validate_day_ready(log_dir, day),
        "last_safe_write": "unknown",
        "freshness_seconds": "unknown",
        "log_dir_mode": _mode(log_dir),
        "analysis_mode": _mode(analysis_file),
        "intent_mode": _mode(intent_file),
        "ready_mode": _mode(proof_file),
        "runtime_dir_mode": _mode(runtime_dir(home)),
        "lock_mode": _mode(runtime_dir(home) / LOCK_NAME),
        "state_mode": _mode(runtime_dir(home) / STATE_NAME),
    }
    state = read_runtime_state(home)
    report["manual_paused"] = state.get("manual_paused") if state else "unknown"
    report["capture_paused"] = state.get("capture_paused") if state else "unknown"
    if (
        report["log_dir_mode"] != "700"
        or report["analysis_mode"] != "600"
        or report["intent_mode"] != "600"
    ):
        return report
    try:
        checked = check_day(log_dir, day)
        report["format"] = checked.format_name
        report["intent_match"] = checked.intent_match
        report["invalid_marker"] = checked.invalid_marker
        if checked.strict_parse and checked.intent_match and checked.stable_snapshot:
            safe_write = max(analysis_file.stat().st_mtime, intent_file.stat().st_mtime)
            report["last_safe_write"] = datetime.fromtimestamp(safe_write).astimezone().isoformat(timespec="seconds")
            report["freshness_seconds"] = max(0, int(time.time() - safe_write))
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        pass
    return report


def _private_tree_size(root: Path) -> tuple[int, int]:
    total = 0
    unsafe = 0
    if not root.is_dir():
        return total, unsafe
    info = root.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
    ):
        return 0, 1
    for current, directories, files in os.walk(root, followlinks=False):
        base = Path(current)
        directories[:] = [name for name in directories if not (base / name).is_symlink()]
        for name in files:
            path = base / name
            try:
                info = path.lstat()
            except OSError:
                unsafe += 1
                continue
            if stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o077:
                total += info.st_size
            else:
                unsafe += 1
    return total, unsafe


def storage_report(
    log_dir: Path,
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    today: date | None = None,
) -> dict[str, object]:
    current_day = today or datetime.now().astimezone().date()
    days: list[date] = []
    if log_dir.is_dir():
        for path in log_dir.iterdir():
            match = _DAY_NAME.fullmatch(path.name)
            if match and path.is_file() and not path.is_symlink():
                days.append(date.fromisoformat(match.group(1)))
    days.sort()
    completed = [day for day in days if day < current_day]
    missing_ready = [
        day
        for day in completed
        if day >= ANALYSIS_ONLY_START_DAY and not validate_day_ready(log_dir, day)
    ]
    total_bytes, unsafe_files = _private_tree_size(log_dir)
    packs = 0
    if output_dir.is_dir() and not output_dir.is_symlink():
        packs = sum(
            1
            for path in output_dir.iterdir()
            if path.is_dir()
            and _PACK_NAME.fullmatch(path.name)
            and (path / "INDEX.json").is_file()
        )
    return {
        "total_private_log_bytes": total_bytes,
        "unsafe_files": unsafe_files,
        "oldest_day": days[0].isoformat() if days else "none",
        "newest_day": days[-1].isoformat() if days else "none",
        "completed_days": len(completed),
        "review_packs": packs,
        "missing_readiness_proofs": len(missing_ready),
        "missing_readiness_days": ",".join(day.isoformat() for day in missing_ready) or "none",
    }


def record_review_outcome(
    week: date,
    outcome: str,
    value_result: str,
    notes: str,
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> Path:
    if outcome not in _OUTCOMES:
        raise ValueError("outcome must be accepted, ignored, or tried")
    if len(value_result) > 4000 or len(notes) > 4000:
        raise ValueError("review outcome text is too long")
    dash_map = {0x2014: "-", 0x2013: "-"}
    value_result = value_result.translate(dash_map)
    notes = notes.translate(dash_map)
    root = _ensure_private_dir(output_dir)
    destination = root / OUTCOMES_NAME
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(destination, flags, 0o600)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or info.st_mode & 0o077
        ):
            raise OSError("refusing unsafe review outcome file")
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        empty = info.st_size == 0
        entry = {
            "week": week.isoformat(),
            "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "outcome": outcome,
            "value_result": value_result,
            "notes": notes,
        }
        text = ("# Weekly review outcomes\n\n" if empty else "") + f"- {json.dumps(entry, ensure_ascii=False, sort_keys=True)}\n"
        data = text.encode("utf-8")
        offset = 0
        while offset < len(data):
            written = os.write(fd, data[offset:])
            if written <= 0:
                raise OSError("short review outcome write")
            offset += written
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_dir(root)
    return destination
