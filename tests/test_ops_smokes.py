"""Ops smoke checks: codesign DR and Launch Agent install ProgramArguments."""

from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "dist" / "ActivityLoggerNative.app"
INSTALL = REPO / "scripts" / "install_launch_agent.sh"


def test_codesign_dr_has_certificate_leaf():
    if not APP.is_dir():
        pytest.skip(f"missing {APP}")
    result = subprocess.run(
        ["codesign", "-d", "-r-", str(APP)],
        check=False,
        capture_output=True,
        text=True,
    )
    # codesign writes designated requirement to stderr.
    out = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 0, out
    assert "certificate leaf" in out, out


def test_install_launch_agent_program_args_smoke(tmp_path):
    dest_dir = tmp_path / "LaunchAgents"
    dest_dir.mkdir()
    out_plist = dest_dir / "com.mk.activitylogger.plist"
    env = os.environ.copy()
    env["ACTIVITYLOGGER_REPO"] = str(REPO)
    env["ACTIVITYLOGGER_PLIST_OUT"] = str(out_plist)
    subprocess.run(
        ["bash", str(INSTALL)],
        check=True,
        env=env,
        cwd=str(tmp_path),
    )
    with out_plist.open("rb") as fh:
        data = plistlib.load(fh)
    args = data["ProgramArguments"]
    assert args[0] == "/bin/bash"
    assert len(args) == 2
    assert args[1].endswith("start_logger.sh")
    joined = " ".join(args).lower()
    assert "python" not in joined
    assert "interleaved_logger.py" not in joined
