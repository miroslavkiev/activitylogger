"""Shared pytest fixtures for ActivityLogger tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest

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


@pytest.fixture
def reset_logger_state(tmp_path: Path) -> Callable[..., None]:
    """Factory: call with optional AppConfig field overrides, then clear state.

    Use as autouse in a module::

        @pytest.fixture(autouse=True)
        def _reset_logger_state(reset_logger_state):
            reset_logger_state(typing_pause_sec=0.5)
            yield
    """

    def _reset(**config_overrides: Any) -> None:
        apply_reset_logger_state(tmp_path, **config_overrides)

    return _reset
