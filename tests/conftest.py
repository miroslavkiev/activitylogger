"""Shared pytest fixtures for ActivityLogger tests."""

from __future__ import annotations

from pathlib import Path
import os
import pwd
from typing import Any, Callable

import pytest

import interleaved_logger as il
from tests.helpers import apply_reset_logger_state, enable_features, seed_keys

# Re-export for any leftover call sites.
_seed_keys = seed_keys

__all__ = [
    "apply_reset_logger_state",
    "enable_features",
    "reset_logger_state",
    "seed_keys",
    "_seed_keys",
]


@pytest.fixture(autouse=True)
def isolated_operator_home(tmp_path: Path, monkeypatch) -> Path:
    """Keep default runtime state and locks away from the operator's live home."""
    isolated_home = tmp_path / "operator-home"
    isolated_home.mkdir(mode=0o700)
    original_getpwuid = pwd.getpwuid
    current_uid = os.getuid()

    def getpwuid(uid):
        entry = original_getpwuid(uid)
        if uid == current_uid:
            values = list(entry)
            values[5] = str(isolated_home)
            return pwd.struct_passwd(values)
        return entry

    monkeypatch.setattr(pwd, "getpwuid", getpwuid)
    return isolated_home


@pytest.fixture
def reset_logger_state(tmp_path: Path, monkeypatch) -> Callable[..., None]:
    """Factory: call with optional AppConfig field overrides, then clear state.

    Use as autouse in a module::

        @pytest.fixture(autouse=True)
        def _reset_logger_state(reset_logger_state):
            reset_logger_state(typing_pause_sec=0.5)
            yield
    """

    monkeypatch.setattr(il, "_frontmost_app_identity", lambda: None)

    def _reset(**config_overrides: Any) -> None:
        apply_reset_logger_state(tmp_path, **config_overrides)

    return _reset
