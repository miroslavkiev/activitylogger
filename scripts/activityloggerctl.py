#!/usr/bin/env python3
"""Local operator controls for ActivityLogger."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from analysis_view import USER_PRIVATE_OUTPUT_DIR as DEFAULT_OUTPUT_DIR  # noqa: E402
from config import load_config  # noqa: E402
from operator_errors import safe_error_message  # noqa: E402
from operator_controls import (  # noqa: E402
    health_report,
    record_review_outcome,
    set_manual_pause,
    storage_report,
)


def _print_report(report: dict[str, object]) -> None:
    for key, value in report.items():
        print(f"{key}={str(value).lower() if isinstance(value, bool) else value}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Private local ActivityLogger controls.")
    parser.add_argument("--log-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    commands = parser.add_subparsers(dest="command", required=True)
    health = commands.add_parser("health", help="Show payload-free runtime and day health.")
    health.add_argument("--day", type=date.fromisoformat, default=None)
    commands.add_parser("storage", help="Show payload-free private storage totals.")
    commands.add_parser("pause", help="Pause every capture channel.")
    commands.add_parser("resume", help="Clear only the manual privacy pause.")
    review = commands.add_parser("review", help="Record a local weekly review outcome.")
    review.add_argument("--week", type=date.fromisoformat, required=True)
    review.add_argument("--days", type=int, choices=(5, 7), default=None,
                        help="Exact review window. Omit only for an older outcome with no known window.")
    review.add_argument("--outcome", choices=("accepted", "ignored", "tried"), required=True)
    review.add_argument("--value-result", default="")
    review.add_argument("--notes", default="")
    args = parser.parse_args()
    try:
        if args.command == "health":
            log_dir = args.log_dir or load_config().log_dir
            _print_report(health_report(log_dir, args.day or datetime.now().astimezone().date()))
        elif args.command == "storage":
            log_dir = args.log_dir or load_config().log_dir
            _print_report(storage_report(log_dir, output_dir=args.output_dir))
        elif args.command in {"pause", "resume"}:
            state = set_manual_pause(args.command == "pause")
            _print_report(
                {
                    "manual_paused": state["manual_paused"],
                    "capture_paused": state["capture_paused"],
                    "control_revision": state["control_revision"],
                }
            )
        else:
            output = record_review_outcome(
                args.week,
                args.outcome,
                args.value_result,
                args.notes,
                days=args.days,
                output_dir=args.output_dir,
            )
            print(f"output={output.resolve()}")
    except Exception as exc:
        print(f"error={safe_error_message(exc)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
