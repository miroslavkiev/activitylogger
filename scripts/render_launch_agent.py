#!/usr/bin/env python3
"""Render the Launch Agent template safely with plistlib."""

from __future__ import annotations

import argparse
import os
import plistlib
import tempfile
from pathlib import Path
from typing import Any, Optional


def replace_repo(value: Any, repo: str) -> Any:
    if isinstance(value, str):
        return value.replace("@REPO@", repo)
    if isinstance(value, list):
        return [replace_repo(item, repo) for item in value]
    if isinstance(value, dict):
        return {key: replace_repo(item, repo) for key, item in value.items()}
    return value


def render(template: Path, destination: Path, repo: Path) -> None:
    with template.open("rb") as source:
        data = replace_repo(plistlib.load(source), str(repo.resolve()))
    if "@REPO@" in repr(data):
        raise ValueError("unresolved @REPO@ placeholder")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
            temporary = Path(output.name)
            plistlib.dump(data, output, fmt=plistlib.FMT_XML, sort_keys=False)
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("template", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("repo", type=Path)
    args = parser.parse_args()
    render(args.template, args.destination, args.repo)


if __name__ == "__main__":
    main()
