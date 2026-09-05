"""Closed, payload-free messages shared by local controls and the native UI."""

from __future__ import annotations

import errno

from config import ConfigError


MESSAGES = {
    "logger_stopped": "ActivityLogger is not running. Start the signed app, then refresh.",
    "control_unconfirmed": "The privacy change was not confirmed. Refresh Daily status before trying again.",
    "invalid_window": "Choose 5 or 7 consecutive completed calendar days.",
    "incomplete_window": "The selected days are not ready. Check Daily status and Recovery help.",
    "day_unverified": "Analysis check failed. The day could not be verified. Check Recovery help before changing its files.",
    "day_not_completed": "Choose a completed calendar day, then try again.",
    "unsupported_format": "Choose completed days that use the current log format.",
    "pack_exists": "Review files already exist. Show them in Finder, or archive that review folder before creating it again.",
    "source_changed": "Source files changed during this action. Refresh and try again.",
    "outcome_invalid": "Choose a review result before saving.",
    "text_too_long": "Text is too long. Value note and notes must each be 4,000 characters or fewer.",
    "unsafe_file": "A private file is unsafe or unreadable. Check Recovery help before changing it.",
    "invalid_config": "The local config could not be loaded. Correct it before using default log paths.",
    "storage_failed": "Storage could not be updated. Check free space and private file permissions, then retry.",
    "missing_file": "A required local file is missing. Check the selected dates and Recovery help.",
}


class OperatorError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(MESSAGES[code])


def safe_error_message(error: BaseException) -> str:
    if isinstance(error, OperatorError):
        return MESSAGES.get(error.code, "The action failed. Refresh and check Recovery help.")
    if isinstance(error, ConfigError):
        return MESSAGES["invalid_config"]
    if isinstance(error, FileExistsError):
        return MESSAGES["pack_exists"]
    if isinstance(error, FileNotFoundError):
        return MESSAGES["missing_file"]
    if isinstance(error, PermissionError):
        return MESSAGES["unsafe_file"]
    if isinstance(error, OSError):
        if error.errno == errno.ESTALE:
            return MESSAGES["source_changed"]
        if error.errno == errno.ENOSPC:
            return "Storage is full. Free space without removing source logs, then retry."
        return MESSAGES["storage_failed"]
    return "The action failed. Refresh and check Recovery help."
