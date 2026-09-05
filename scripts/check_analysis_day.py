#!/usr/bin/env python3
"""Check one analysis day without printing captured content."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from analysis_log import (  # noqa: E402
    ANALYSIS_FORMAT_V1,
    ANALYSIS_FORMAT_V2,
    analysis_paths,
    inspect_analysis_day,
)
from config import load_config  # noqa: E402
from operator_errors import OperatorError, safe_error_message  # noqa: E402
from private_files import read_private_bytes  # noqa: E402


KNOWN_FORMATS = frozenset(
    {ANALYSIS_FORMAT_V1, ANALYSIS_FORMAT_V2}
)


@dataclass(frozen=True)
class DayIntegrity:
    format_name: str
    strict_parse: bool
    intent_match: bool
    invalid_marker: bool
    stable_snapshot: bool
    events: int
    heartbeats: int
    session_starts: int
    session_stops: int
    privacy_starts: int
    privacy_ends: int
    integrity_ok: bool = True

    @property
    def ok(self) -> bool:
        return (
            self.strict_parse
            and self.intent_match
            and not self.invalid_marker
            and self.stable_snapshot
            and self.integrity_ok
        )


def _format_name(text: str) -> str:
    prefix = "> format: "
    values = [
        line[len(prefix) :]
        for line in text.splitlines()
        if line.startswith(prefix)
    ]
    if len(values) != 1 or values[0] not in KNOWN_FORMATS:
        raise ValueError("analysis format header is missing, repeated, or unknown")
    return values[0]


def check_day(log_dir: Path, day: date) -> DayIntegrity:
    inspection = inspect_analysis_day(log_dir, day)
    return DayIntegrity(**{
        field: getattr(inspection, field) for field in DayIntegrity.__dataclass_fields__
    })


def _print_result(day: date, result: DayIntegrity) -> None:
    print(f"day={day.isoformat()}")
    print(f"format={result.format_name}")
    print(f"strict_parse={str(result.strict_parse).lower()}")
    print(f"intent_match={str(result.intent_match).lower()}")
    print(f"invalid_marker={str(result.invalid_marker).lower()}")
    print(f"stable_snapshot={str(result.stable_snapshot).lower()}")
    print(f"events={result.events}")
    print(f"heartbeats={result.heartbeats}")
    print(f"session_starts={result.session_starts}")
    print(f"session_stops={result.session_stops}")
    print(f"privacy_starts={result.privacy_starts}")
    print(f"privacy_ends={result.privacy_ends}")
    print(f"ok={str(result.ok).lower()}")


def _failure_metadata(log_dir: Path, day: date) -> tuple[str, bool]:
    analysis_file, invalid_file = analysis_paths(log_dir, day)
    try:
        format_name = _format_name(read_private_bytes(analysis_file).decode("utf-8"))
    except (OSError, UnicodeError, ValueError):
        format_name = "unknown"
    return format_name, invalid_file.exists() or invalid_file.is_symlink()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check one analysis day without printing captured content."
    )
    parser.add_argument(
        "--day",
        type=date.fromisoformat,
        default=datetime.now().astimezone().date(),
    )
    parser.add_argument("--log-dir", type=Path, default=None)
    args = parser.parse_args()
    log_dir = args.log_dir
    try:
        log_dir = log_dir or load_config().log_dir
        result = check_day(log_dir, args.day)
    except Exception as exc:
        format_name, invalid_marker = (
            _failure_metadata(log_dir, args.day) if log_dir else ("unknown", False)
        )
        print(f"day={args.day.isoformat()}")
        print(f"format={format_name}")
        print("strict_parse=false")
        print("intent_match=false")
        print(f"invalid_marker={str(invalid_marker).lower()}")
        print("stable_snapshot=false")
        print("events=0")
        print("heartbeats=0")
        print("session_starts=0")
        print("session_stops=0")
        print("privacy_starts=0")
        print("privacy_ends=0")
        print("ok=false")
        print(f"error={safe_error_message(exc)}", file=sys.stderr)
        return 1
    _print_result(args.day, result)
    if not result.ok:
        print(f"error={safe_error_message(OperatorError('day_unverified'))}", file=sys.stderr)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
