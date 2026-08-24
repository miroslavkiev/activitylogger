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
    _intents_match_records,
    analysis_format_for_day,
    intent_path,
    parse_records,
    read_intents,
    shadow_paths,
)
from config import load_config  # noqa: E402


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

    @property
    def ok(self) -> bool:
        return (
            self.strict_parse
            and self.intent_match
            and not self.invalid_marker
            and self.stable_snapshot
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
    analysis_file, invalid_file = shadow_paths(log_dir, day)
    intent_file = intent_path(log_dir, day)
    analysis_bytes = analysis_file.read_bytes()
    intent_bytes = intent_file.read_bytes()
    text = analysis_bytes.decode("utf-8")
    format_name = _format_name(text)
    expected_format = analysis_format_for_day(day)
    if format_name != expected_format:
        raise ValueError("analysis format does not match its configured day")
    records = parse_records(text, day=day, expected_format=expected_format)
    intents = read_intents(intent_file)
    stable = (
        analysis_file.read_bytes() == analysis_bytes
        and intent_file.read_bytes() == intent_bytes
    )
    return DayIntegrity(
        format_name=format_name,
        strict_parse=True,
        intent_match=_intents_match_records(intents, records),
        invalid_marker=invalid_file.exists(),
        stable_snapshot=stable,
        events=len(records),
        heartbeats=sum(record.kind == "heartbeat" for record in records),
        session_starts=sum(record.kind == "session_start" for record in records),
        session_stops=sum(record.kind == "session_stop" for record in records),
        privacy_starts=sum(record.kind == "privacy_pause_start" for record in records),
        privacy_ends=sum(record.kind == "privacy_pause_end" for record in records),
    )


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
    analysis_file, invalid_file = shadow_paths(log_dir, day)
    try:
        format_name = _format_name(analysis_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        format_name = "unknown"
    return format_name, invalid_file.exists()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check one analysis day without printing captured content."
    )
    parser.add_argument(
        "--day",
        type=date.fromisoformat,
        default=datetime.now().astimezone().date(),
    )
    parser.add_argument("--log-dir", type=Path, default=load_config().log_dir)
    args = parser.parse_args()
    try:
        result = check_day(args.log_dir, args.day)
    except Exception as exc:
        format_name, invalid_marker = _failure_metadata(args.log_dir, args.day)
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
        print(f"error=analysis check failed [{type(exc).__name__}]", file=sys.stderr)
        return 1
    _print_result(args.day, result)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
