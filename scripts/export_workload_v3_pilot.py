#!/usr/bin/env python3
"""Export one completed canonical v2 day to a private v3 workload pilot."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from analysis_view import DEFAULT_OUTPUT_DIR, export_workload_day  # noqa: E402
from config import load_config  # noqa: E402
from operator_errors import safe_error_message  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export a completed canonical v2 day to a private v3 workload pilot."
    )
    parser.add_argument(
        "--day",
        type=date.fromisoformat,
        default=datetime.now().astimezone().date() - timedelta(days=1),
    )
    parser.add_argument("--log-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    try:
        log_dir = args.log_dir or load_config().log_dir
        result = export_workload_day(log_dir, args.output_dir, args.day)
    except Exception as exc:
        print(f"error={safe_error_message(exc)}", file=sys.stderr)
        return 1
    print(f"day={result.day}")
    print(f"output={(args.output_dir / result.output_file).resolve()}")
    print(f"source_events={result.source_events}")
    print(f"workload_events={result.workload_events}")
    print(f"exact_evidence_events={result.exact_evidence_events}")
    print(f"click_events={result.click_events}")
    print(f"click_groups={result.click_groups}")
    print(f"summarized_markers={result.summarized_markers}")
    print(f"spans={result.spans}")
    print(f"source_bytes={result.analysis_bytes}")
    print(f"output_bytes={result.output_bytes}")
    print(f"byte_reduction={result.byte_reduction:.1%}")
    print(f"source_token_proxy={(result.analysis_bytes + 3) // 4}")
    print(f"output_token_proxy={(result.output_bytes + 3) // 4}")
    print("token_proxy=ceil(utf8-bytes/4), not a model tokenizer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
