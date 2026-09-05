#!/usr/bin/env python3
"""Create one private weekly review pack from verified workload summaries."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from analysis_view import USER_PRIVATE_OUTPUT_DIR as DEFAULT_OUTPUT_DIR  # noqa: E402
from config import load_config  # noqa: E402
from operator_errors import safe_error_message  # noqa: E402
from weekly_review import create_weekly_review_pack  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a private review pack for an exact completed calendar window."
    )
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--days", choices=(5, 7), default=7, type=int)
    parser.add_argument("--log-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    try:
        log_dir = args.log_dir or load_config().log_dir
        result = create_weekly_review_pack(
            log_dir,
            args.output_dir,
            end=args.end,
            days=args.days,
        )
    except Exception as exc:
        print(f"error={safe_error_message(exc)}", file=sys.stderr)
        return 1
    print(f"start={result.start}")
    print(f"end={result.end}")
    print(f"days={result.days}")
    print(f"pack={result.pack_dir}")
    print(f"index={result.index_file}")
    print(f"source_events={result.source_events}")
    print(f"workload_events={result.workload_events}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
