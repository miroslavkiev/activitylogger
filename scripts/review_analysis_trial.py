#!/usr/bin/env python3
"""Validate one complete ActivityLogger analysis trial day without showing payloads."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from analysis_log import validate_trial  # noqa: E402
from config import load_config  # noqa: E402
from operator_errors import safe_error_message  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--day",
        type=date.fromisoformat,
        default=datetime.now().astimezone().date() - timedelta(days=1),
    )
    parser.add_argument("--log-dir", type=Path, default=None)
    args = parser.parse_args()
    try:
        log_dir = args.log_dir or load_config().log_dir
        result = validate_trial(log_dir, args.day)
    except Exception as exc:
        print(f"error={safe_error_message(exc)}", file=sys.stderr)
        return 1
    print(f"day={args.day.isoformat()}")
    print(f"ok={str(result.ok).lower()}")
    print(f"events={result.event_count}")
    print(f"byte_reduction={result.byte_reduction:.1%}")
    print(f"heartbeat_coverage_hours={result.coverage_hours:.1f}")
    print(f"max_heartbeat_gap_hours={result.max_heartbeat_gap_hours:.1f}")
    for error in result.errors:
        print(f"error={error}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
