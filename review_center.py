"""Native, payload-free Review Center for ActivityLogger operators."""

from __future__ import annotations

import json
import os
import stat
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from analysis_log import ANALYSIS_FORMAT_V2
from analysis_view import DEFAULT_OUTPUT_DIR, workload_view_path
from operator_controls import (
    health_report,
    record_review_outcome,
    set_manual_pause,
    storage_report,
)
from weekly_review import (
    INDEX_NAME,
    PROMPT_NAME,
    WEEKLY_PACK_FORMAT,
    create_weekly_review_pack,
    weekly_window_status,
)

try:
    import objc
    from AppKit import (
        NSAccessibilityPostNotification,
        NSAccessibilityHeadingRole,
        NSAccessibilityValueChangedNotification,
        NSAnyEventMask,
        NSApplication,
        NSApplicationActivationPolicyAccessory,
        NSBackingStoreBuffered,
        NSBezelStyleRounded,
        NSButton,
        NSDatePicker,
        NSDatePickerStyleTextFieldAndStepper,
        NSDefaultRunLoopMode,
        NSFont,
        NSLayoutAttributeLeading,
        NSLayoutConstraint,
        NSLineBreakByWordWrapping,
        NSMakePoint,
        NSMakeRect,
        NSMakeSize,
        NSNoBorder,
        NSObject,
        NSPopUpButton,
        NSScrollView,
        NSStackView,
        NSTextField,
        NSUserInterfaceLayoutOrientationHorizontal,
        NSUserInterfaceLayoutOrientationVertical,
        NSView,
        NSViewHeightSizable,
        NSViewWidthSizable,
        NSWindow,
        NSWindowStyleMaskClosable,
        NSWindowStyleMaskMiniaturizable,
        NSWindowStyleMaskResizable,
        NSWindowStyleMaskTitled,
        NSYearMonthDayDatePickerElementFlag,
        NSWorkspace,
    )
    from Foundation import NSDate, NSURL
    from PyObjCTools import AppHelper

    APPKIT_AVAILABLE = True
except ImportError:
    APPKIT_AVAILABLE = False


@dataclass(frozen=True)
class ReviewCenterSnapshot:
    health: str
    freshness: str
    pause_state: str
    manual_paused: bool
    can_toggle_pause: bool
    pack_state: str
    coverage: str
    can_prepare: bool
    can_show: bool
    storage: str


OUTCOME_VALUES = {
    "Found an idea to try": "accepted",
    "Tried a change": "tried",
    "No action": "ignored",
}
MAX_REVIEW_INDEX_BYTES = 1024 * 1024


def _open_private_file(path: Path) -> tuple[int, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or info.st_nlink != 1
        ):
            raise OSError("refusing unsafe review file")
        return fd, info
    except Exception:
        os.close(fd)
        raise


def _private_file_is_safe(path: Path) -> bool:
    try:
        fd, _info = _open_private_file(path)
    except OSError:
        return False
    os.close(fd)
    return True


def _private_index_bytes(path: Path) -> bytes | None:
    try:
        fd, before = _open_private_file(path)
    except OSError:
        return None
    try:
        if before.st_size > MAX_REVIEW_INDEX_BYTES:
            return None
        chunks: list[bytes] = []
        size = 0
        while chunk := os.read(fd, min(64 * 1024, MAX_REVIEW_INDEX_BYTES + 1 - size)):
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_REVIEW_INDEX_BYTES:
                return None
        after = os.fstat(fd)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
            before.st_mode,
            before.st_uid,
            before.st_nlink,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
            after.st_mode,
            after.st_uid,
            after.st_nlink,
        ) or size != before.st_size:
            return None
        return b"".join(chunks)
    except OSError:
        return None
    finally:
        os.close(fd)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _format_bytes(value: object) -> str:
    try:
        size = max(0, int(value))
    except (TypeError, ValueError):
        return "unknown"
    amount = float(size)
    for unit in ("bytes", "KB", "MB", "GB"):
        if amount < 1024 or unit == "GB":
            return f"{amount:.0f} {unit}" if unit == "bytes" else f"{amount:.1f} {unit}"
        amount /= 1024
    return "unknown"


def _health_issues(health: dict[str, object]) -> tuple[str, ...]:
    issues: list[str] = []
    if health.get("invalid_marker") is True:
        issues.append("the current log has an invalid marker")
    if health.get("format") != ANALYSIS_FORMAT_V2:
        issues.append("the current log format could not be verified")
    if health.get("intent_match") is not True:
        issues.append("the intent journal does not match the current log")

    expected_modes = {
        "log_dir_mode": frozenset({"700", "missing"}),
        "analysis_mode": frozenset({"600", "missing"}),
        "intent_mode": frozenset({"600", "missing"}),
        "ready_mode": frozenset({"600", "missing"}),
        "runtime_dir_mode": frozenset({"700", "missing"}),
        "lock_mode": frozenset({"600", "missing"}),
        "state_mode": frozenset({"600", "missing"}),
    }
    if any(
        name in health and health[name] not in allowed
        for name, allowed in expected_modes.items()
    ):
        issues.append("private file or directory permissions are unsafe")
    return tuple(issues)


class ReviewCenterModel:
    """Payload-free data and actions shared by the native window and tests."""

    def __init__(
        self,
        log_dir: Path,
        *,
        output_dir: Path = DEFAULT_OUTPUT_DIR,
        home: Path | None = None,
    ) -> None:
        self.log_dir = Path(log_dir)
        self.output_dir = Path(output_dir)
        self.home = home

    def snapshot(
        self,
        end: date,
        days: int,
        *,
        today: date | None = None,
    ) -> ReviewCenterSnapshot:
        current_day = today or datetime.now().astimezone().date()
        health = health_report(self.log_dir, current_day, home=self.home)
        storage = storage_report(
            self.log_dir,
            output_dir=self.output_dir,
            today=current_day,
        )
        window = weekly_window_status(
            self.log_dir,
            end,
            days,
            today=current_day,
        )

        running = health.get("running") is True
        manual_paused = health.get("manual_paused") is True
        capture_paused = health.get("capture_paused") is True
        health_issues = _health_issues(health)
        if health_issues:
            prefix = (
                "Logger is running, but health is degraded"
                if running
                else "Logger is not running, and health is degraded"
            )
            health_text = f"{prefix}: {'; '.join(health_issues)}."
        elif not running:
            health_text = "Logger is not running."
        elif capture_paused:
            health_text = "Logger is running. Capture is paused."
        else:
            health_text = "Logger is running. Capture is active."

        freshness_value = health.get("freshness_seconds")
        if isinstance(freshness_value, int):
            freshness = f"Last verified safe write was {freshness_value} seconds ago."
        else:
            freshness = "Last verified safe write is not available."

        if manual_paused:
            pause_state = "Manual privacy pause is on."
        elif running:
            pause_state = "Manual privacy pause is off."
        else:
            pause_state = "Manual privacy control is unavailable."

        pack_path = self.output_dir / window.pack_name
        pack_present = pack_path.exists() or pack_path.is_symlink()
        prepared_pack = self.prepared_pack(end, days, today=current_day)
        if prepared_pack is not None:
            pack_state = (
                f"Review files are ready for {window.start} through {window.end}."
            )
        elif pack_present:
            pack_state = "The selected review files are incomplete or unsafe."
        elif window.ready:
            pack_state = (
                f"Ready to create files for {window.start} through {window.end}."
            )
        else:
            issue_count = sum(item.state != "ready" for item in window.day_statuses)
            noun = "day needs" if issue_count == 1 else "days need"
            pack_state = f"Not ready. {issue_count} selected {noun} attention."

        storage_text = (
            f"{_format_bytes(storage.get('total_private_log_bytes'))} of private logs. "
            f"{storage.get('completed_days', 0)} completed day(s), "
            f"{storage.get('review_packs', 0)} review folder(s), "
            f"{storage.get('missing_readiness_proofs', 0)} missing safety check(s), "
            f"{storage.get('unsafe_files', 0)} unsafe item(s)."
        )
        coverage = ["File checks do not prove that every activity was captured."]
        state_help = {
            "active": "is still active. Choose an earlier end date.",
            "unsupported": "uses an older format. Choose newer dates.",
            "invalid": (
                "failed a safety check. Repair that day's files, then refresh."
            ),
            "missing": (
                "is missing required files. Restore them or choose other dates, "
                "then refresh."
            ),
            "unready": (
                "has not passed its safety check. Repair that day's files, then refresh."
            ),
        }
        coverage.extend(
            f"{item.day} {state_help.get(item.state, 'needs attention.')}"
            for item in window.day_statuses
            if item.state != "ready"
        )
        return ReviewCenterSnapshot(
            health=health_text,
            freshness=freshness,
            pause_state=pause_state,
            manual_paused=manual_paused,
            can_toggle_pause=running,
            pack_state=pack_state,
            coverage="\n".join(coverage),
            can_prepare=window.ready and not pack_present,
            can_show=prepared_pack is not None,
            storage=storage_text,
        )

    def prepared_pack(
        self,
        end: date,
        days: int,
        *,
        today: date | None = None,
    ) -> Path | None:
        """Return the exact selected pack only when every private path is safe."""
        if days not in (5, 7):
            return None
        window = weekly_window_status(self.log_dir, end, days, today=today)
        selected_days = tuple(
            end - timedelta(days=offset) for offset in range(days - 1, -1, -1)
        )
        if (
            window.start,
            window.end,
            window.days,
        ) != (
            selected_days[0].isoformat(),
            selected_days[-1].isoformat(),
            days,
        ):
            return None
        pack_dir = self.output_dir / window.pack_name
        for path in (self.output_dir, pack_dir):
            try:
                info = path.lstat()
            except OSError:
                return None
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o700
            ):
                return None

        workload_files = tuple(
            workload_view_path(pack_dir, selected_day) for selected_day in selected_days
        )
        expected_files = (pack_dir / PROMPT_NAME, *workload_files)
        indexed_names = {path.name for path in expected_files}
        known_names = indexed_names | {INDEX_NAME}
        try:
            extras = tuple(
                path for path in pack_dir.iterdir() if path.name not in known_names
            )
        except OSError:
            return None
        if any(not _private_file_is_safe(path) for path in extras):
            return None
        index_bytes = _private_index_bytes(pack_dir / INDEX_NAME)
        if index_bytes is None:
            return None
        try:
            index = json.loads(index_bytes.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError, RecursionError):
            return None
        if not isinstance(index, dict) or index.get("format") != WEEKLY_PACK_FORMAT:
            return None
        if index.get("window") != {
            "start": selected_days[0].isoformat(),
            "end": selected_days[-1].isoformat(),
            "calendar_days": days,
            "complete_fixed_window": True,
            "older_day_substitution": False,
        }:
            return None

        files = index.get("files")
        if (
            not isinstance(files, dict)
            or set(files) != indexed_names
            or not all(_is_sha256(digest) for digest in files.values())
        ):
            return None

        day_entries = index.get("days")
        if not isinstance(day_entries, list) or len(day_entries) != days:
            return None
        for entry, selected_day, workload_file in zip(
            day_entries,
            selected_days,
            workload_files,
            strict=True,
        ):
            if (
                not isinstance(entry, dict)
                or entry.get("day") != selected_day.isoformat()
            ):
                return None
            output = entry.get("output")
            sources = entry.get("sources")
            if (
                not isinstance(output, dict)
                or output.get("file") != workload_file.name
                or output.get("sha256") != files[workload_file.name]
                or not isinstance(sources, dict)
                or not sources
                or not all(_is_sha256(digest) for digest in sources.values())
            ):
                return None

        # Safe redaction is expected. Stored hashes describe creation time only,
        # so reopening must not compare them with edited file contents.
        if any(not _private_file_is_safe(path) for path in expected_files):
            return None
        return pack_dir

    def prepare(self, end: date, days: int):
        return create_weekly_review_pack(
            self.log_dir,
            self.output_dir,
            end=end,
            days=days,
        )

    def set_manual_pause(self, paused: bool):
        return set_manual_pause(paused, home=self.home)

    def record_outcome(
        self,
        week: date,
        outcome: str,
        value_result: str,
        notes: str,
    ) -> Path:
        return record_review_outcome(
            week,
            outcome,
            value_result,
            notes,
            output_dir=self.output_dir,
        )


if APPKIT_AVAILABLE:

    def _label(text: str, *, bold: bool = False, wrap: bool = False):
        field = NSTextField.labelWithString_(text)
        if bold:
            field.setFont_(NSFont.boldSystemFontOfSize_(13))
        if wrap:
            field.setLineBreakMode_(NSLineBreakByWordWrapping)
            field.setMaximumNumberOfLines_(0)
            field.setPreferredMaxLayoutWidth_(560)
        return field

    def _row(*views):
        stack = NSStackView.stackViewWithViews_(list(views))
        stack.setOrientation_(NSUserInterfaceLayoutOrientationHorizontal)
        stack.setSpacing_(8)
        return stack

    def _column(*views):
        stack = NSStackView.stackViewWithViews_(list(views))
        stack.setOrientation_(NSUserInterfaceLayoutOrientationVertical)
        stack.setAlignment_(NSLayoutAttributeLeading)
        stack.setSpacing_(7)
        return stack

    def _heading(text: str):
        field = _label(text, bold=True)
        field.setAccessibilityRole_(NSAccessibilityHeadingRole)
        field.setAccessibilityLabel_(text)
        return field

    def _button(title: str, target, action: bytes):
        button = NSButton.buttonWithTitle_target_action_(title, target, action)
        button.setBezelStyle_(NSBezelStyleRounded)
        return button

    def _show_review_prompt_in_finder(prompt: Path) -> None:
        NSWorkspace.sharedWorkspace().activateFileViewerSelectingURLs_(
            [NSURL.fileURLWithPath_(str(prompt))]
        )

    class ReviewCenterWindowController(NSObject):
        def initWithModel_(self, model):
            return self.initWithModel_pauseCallback_(model, None)

        def initWithModel_pauseCallback_(self, model, pause_callback):
            self = objc.super(ReviewCenterWindowController, self).init()
            if self is None:
                return None
            self.model = model
            self.pause_callback = pause_callback
            self.window_privacy_active = False
            self.busy = False
            self.last_snapshot = None
            self.initial_scroll_pending = True
            self._build_window()
            return self

        @objc.python_method
        def _build_window(self) -> None:
            mask = (
                NSWindowStyleMaskTitled
                | NSWindowStyleMaskClosable
                | NSWindowStyleMaskMiniaturizable
                | NSWindowStyleMaskResizable
            )
            self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, 680, 760),
                mask,
                NSBackingStoreBuffered,
                False,
            )
            self.window.setTitle_("ActivityLogger Review Center")
            self.window.setMinSize_(NSMakeSize(620, 620))
            self.window.setReleasedWhenClosed_(False)
            self.window.setDelegate_(self)
            self.window.center()

            title = _heading("Weekly Activity Review")
            title.setFont_(NSFont.boldSystemFontOfSize_(20))
            subtitle = _label(
                "Create private review files from recent activity. Use the files with "
                "a tool you trust to look for repeated work, friction, and useful "
                "small changes.",
                wrap=True,
            )
            self.limit_label = _label(
                "ActivityLogger creates the files. It does not analyze or send them.",
                wrap=True,
            )
            self.limit_label.setAccessibilityLabel_("Review limit")
            self.review_pause_notice = _label(
                "While this window is visible, it adds a privacy pause. Closing or "
                "minimizing removes this window's pause. Capture may stay paused for "
                "manual or secure reasons.",
                wrap=True,
            )
            self.review_pause_notice.setAccessibilityLabel_(
                "Review Center privacy pause"
            )

            self.step_one_heading = _heading("1. Create review files")
            step_one_text = _label(
                "Choose an end date and include 5 or 7 completed calendar days.",
                wrap=True,
            )
            self.end_picker = NSDatePicker.alloc().init()
            self.end_picker.setDatePickerStyle_(NSDatePickerStyleTextFieldAndStepper)
            self.end_picker.setDatePickerElements_(NSYearMonthDayDatePickerElementFlag)
            self.end_picker.setAccessibilityLabel_("Weekly review end date")
            yesterday = datetime.now().astimezone().date() - timedelta(days=1)
            self.date_limit = yesterday
            self.end_picker.setDateValue_(self._date_to_nsdate(yesterday))
            self.end_picker.setMaxDate_(self._date_to_nsdate(yesterday))
            self.end_picker.setTarget_(self)
            self.end_picker.setAction_(b"selectionAction:")

            self.days_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(0, 0, 100, 28), False
            )
            self.days_popup.addItemsWithTitles_(["5 days", "7 days"])
            self.days_popup.setAccessibilityLabel_("Weekly review period")
            self.days_popup.setTarget_(self)
            self.days_popup.setAction_(b"selectionAction:")
            self.prepare_button = _button(
                "Create review files", self, b"prepareAction:"
            )
            self.prepare_button.setAccessibilityHelp_(
                "Create private review files for the selected completed days."
            )
            self.prepare_help_label = _label("Checking selected days...", wrap=True)
            self.prepare_help_label.setAccessibilityLabel_(
                "Create review files availability"
            )
            self.pack_state_label = _label("Loading review file status...", wrap=True)
            self.pack_state_label.setAccessibilityLabel_("Review file status")
            self.coverage_label = _label("Loading source checks...", wrap=True)
            self.coverage_label.setAccessibilityLabel_("Source check details")

            self.step_two_heading = _heading("2. Review the files")
            step_two_text = _label(
                "Start with REVIEW_PROMPT.md in a trusted local tool. Review and redact "
                "private text before using any online tool.",
                wrap=True,
            )
            self.step_two_text = step_two_text
            pack_warning = _label(
                "These files may contain captured private text. Review and redact them "
                "before sharing.",
                wrap=True,
            )
            pack_warning.setAccessibilityLabel_("Weekly pack privacy warning")
            self.show_button = _button(
                "Show review files in Finder", self, b"showReviewAction:"
            )
            self.show_button.setAccessibilityHelp_(
                "Show the safe selected review folder and select REVIEW_PROMPT.md."
            )
            self.show_help_label = _label("Create Step 1 first.", wrap=True)
            self.show_help_label.setAccessibilityLabel_(
                "Show review files availability"
            )

            self.step_three_heading = _heading("3. Record what happened")
            step_three_text = _label(
                "After you review the files, save the result and any value you found.",
                wrap=True,
            )
            self.outcome_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(0, 0, 160, 28), False
            )
            self.outcome_popup.addItemsWithTitles_(["Choose a result", *OUTCOME_VALUES])
            self.outcome_popup.setAccessibilityLabel_("Weekly review outcome")
            self.outcome_popup.setTarget_(self)
            self.outcome_popup.setAction_(b"outcomeAction:")
            self.value_field = NSTextField.alloc().init()
            self.value_field.setPlaceholderString_(
                "Example: Saved 20 minutes each Friday"
            )
            self.value_field.setAccessibilityLabel_("Weekly review value result")
            self.notes_field = NSTextField.alloc().init()
            self.notes_field.setPlaceholderString_("Optional notes")
            self.notes_field.setAccessibilityLabel_("Weekly review notes")
            self.record_button = _button(
                "Save review result", self, b"recordOutcomeAction:"
            )
            self.record_button.setAccessibilityHelp_(
                "Choose a result after safe review files are ready."
            )
            self.record_help_label = _label("Create Step 1 first.", wrap=True)
            self.record_help_label.setAccessibilityLabel_(
                "Save review result availability"
            )

            self.action_status_label = _label("Loading local status...", wrap=True)
            self.action_status_label.setAccessibilityLabel_("Action status")
            self.action_status_label.setSelectable_(False)

            self.health_label = _label("Loading logger health...", wrap=True)
            self.health_label.setAccessibilityLabel_("Logger health")
            self.freshness_label = _label("Loading freshness...", wrap=True)
            self.freshness_label.setAccessibilityLabel_("Logger freshness")
            self.pause_state_label = _label("Loading manual pause...", wrap=True)
            self.pause_state_label.setAccessibilityLabel_("Manual privacy state")
            self.storage_label = _label("Loading storage summary...", wrap=True)
            self.storage_label.setAccessibilityLabel_("Private storage summary")
            self.pause_button = _button("Turn on manual pause", self, b"pauseAction:")
            self.pause_button.setAccessibilityHelp_(
                "Pause or resume capture through the shared manual privacy control."
            )
            self.refresh_button = _button("Refresh status", self, b"refreshAction:")
            self.refresh_button.setAccessibilityHelp_(
                "Refresh logger, review file, and storage status."
            )

            step_one = _column(
                self.step_one_heading,
                step_one_text,
                _row(
                    _label("Last day"),
                    self.end_picker,
                    _label("Period"),
                    self.days_popup,
                ),
                self.pack_state_label,
                self.coverage_label,
                self.prepare_button,
                self.prepare_help_label,
            )
            step_two = _column(
                self.step_two_heading,
                step_two_text,
                pack_warning,
                self.show_button,
                self.show_help_label,
            )
            step_three = _column(
                self.step_three_heading,
                step_three_text,
                _row(_label("Result"), self.outcome_popup),
                _label("What value did you get? (optional)"),
                self.value_field,
                _label("Notes (optional)"),
                self.notes_field,
                self.record_button,
                self.record_help_label,
            )
            logger_section = _column(
                _heading("Logger and private storage"),
                self.health_label,
                self.freshness_label,
                self.pause_state_label,
                self.storage_label,
                _row(self.pause_button, self.refresh_button),
            )
            views = [
                title,
                subtitle,
                self.limit_label,
                self.review_pause_notice,
                step_one,
                step_two,
                step_three,
                self.action_status_label,
                logger_section,
            ]
            root = NSStackView.stackViewWithViews_(views)
            root.setOrientation_(NSUserInterfaceLayoutOrientationVertical)
            root.setAlignment_(NSLayoutAttributeLeading)
            root.setSpacing_(18)
            root.setTranslatesAutoresizingMaskIntoConstraints_(False)
            content = self.window.contentView()
            self.scroll_view = NSScrollView.alloc().initWithFrame_(content.bounds())
            self.scroll_view.setBorderType_(NSNoBorder)
            self.scroll_view.setHasVerticalScroller_(True)
            self.scroll_view.setAutohidesScrollers_(True)
            self.scroll_view.setAutoresizingMask_(
                NSViewWidthSizable | NSViewHeightSizable
            )
            self.scroll_document = NSView.alloc().initWithFrame_(content.bounds())
            self.scroll_document.setAutoresizingMask_(NSViewWidthSizable)
            self.scroll_document.addSubview_(root)
            self.scroll_view.setDocumentView_(self.scroll_document)
            content.addSubview_(self.scroll_view)
            NSLayoutConstraint.activateConstraints_(
                [
                    root.leadingAnchor().constraintEqualToAnchor_constant_(
                        self.scroll_document.leadingAnchor(), 20
                    ),
                    root.trailingAnchor().constraintEqualToAnchor_constant_(
                        self.scroll_document.trailingAnchor(), -20
                    ),
                    root.topAnchor().constraintEqualToAnchor_constant_(
                        self.scroll_document.topAnchor(), 18
                    ),
                    root.bottomAnchor().constraintLessThanOrEqualToAnchor_constant_(
                        self.scroll_document.bottomAnchor(), -18
                    ),
                ]
            )
            for view in views:
                view.widthAnchor().constraintEqualToAnchor_(
                    root.widthAnchor()
                ).setActive_(True)
            for section, fields in (
                (
                    step_one,
                    (
                        step_one_text,
                        self.pack_state_label,
                        self.coverage_label,
                        self.prepare_help_label,
                    ),
                ),
                (
                    step_two,
                    (step_two_text, pack_warning, self.show_help_label),
                ),
                (
                    step_three,
                    (
                        step_three_text,
                        self.value_field,
                        self.notes_field,
                        self.record_help_label,
                    ),
                ),
                (
                    logger_section,
                    (
                        self.health_label,
                        self.freshness_label,
                        self.pause_state_label,
                        self.storage_label,
                    ),
                ),
            ):
                for field in fields:
                    field.widthAnchor().constraintEqualToAnchor_(
                        section.widthAnchor()
                    ).setActive_(True)
            self.root_stack = root
            self.pack_warning = pack_warning
            self._layout_scroll_content()
            self.window.setAutorecalculatesKeyViewLoop_(False)
            self.window.setInitialFirstResponder_(self.end_picker)
            controls = (
                self.end_picker,
                self.days_popup,
                self.prepare_button,
                self.show_button,
                self.outcome_popup,
                self.value_field,
                self.notes_field,
                self.record_button,
                self.pause_button,
                self.refresh_button,
            )
            for current, following in zip(controls, controls[1:]):
                current.setNextKeyView_(following)
            controls[-1].setNextKeyView_(controls[0])
            self._set_busy(False)

        @objc.python_method
        def _layout_scroll_content(self) -> None:
            clip = self.scroll_view.contentSize()
            needed = self.root_stack.fittingSize().height + 36
            self.scroll_document.setFrameSize_(
                NSMakeSize(clip.width, max(clip.height, needed))
            )

        @objc.python_method
        def _scroll_to_visual_top(self) -> None:
            clip = self.scroll_view.contentSize()
            document_height = self.scroll_document.frame().size.height
            point = NSMakePoint(0, max(0, document_height - clip.height))
            self.scroll_view.contentView().scrollToPoint_(point)
            self.scroll_view.reflectScrolledClipView_(self.scroll_view.contentView())

        @objc.python_method
        def _date_to_nsdate(self, value: date):
            stamp = (
                datetime.combine(
                    value,
                    datetime.min.time(),
                )
                .astimezone()
                .replace(hour=12)
            )
            return NSDate.dateWithTimeIntervalSince1970_(stamp.timestamp())

        @objc.python_method
        def _selected_date(self) -> date:
            stamp = self.end_picker.dateValue().timeIntervalSince1970()
            return datetime.fromtimestamp(stamp).astimezone().date()

        @objc.python_method
        def _selected_days(self) -> int:
            return (
                7 if str(self.days_popup.titleOfSelectedItem()).startswith("7") else 5
            )

        @objc.python_method
        def _refresh_date_limit(self, today: date | None = None) -> None:
            new_limit = (today or datetime.now().astimezone().date()) - timedelta(
                days=1
            )
            selected = self._selected_date()
            self.end_picker.setMaxDate_(self._date_to_nsdate(new_limit))
            if selected == self.date_limit:
                self.end_picker.setDateValue_(self._date_to_nsdate(new_limit))
            self.date_limit = new_limit

        @objc.python_method
        def _set_window_privacy(self, active: bool) -> None:
            if self.window_privacy_active == active:
                return
            if self.pause_callback is not None:
                self.pause_callback(active)
            self.window_privacy_active = active

        @objc.python_method
        def _set_action_status(self, text: str) -> None:
            self.action_status_label.setStringValue_(text)
            NSAccessibilityPostNotification(
                self.action_status_label,
                NSAccessibilityValueChangedNotification,
            )

        @objc.python_method
        def _set_busy(self, busy: bool) -> None:
            self.busy = busy
            if busy:
                self.window.makeFirstResponder_(None)
            self._update_action_controls()

        @objc.python_method
        def _restore_focus(self, control) -> None:
            if control is not None and control.isEnabled():
                self.window.makeFirstResponder_(control)

        @objc.python_method
        def _clear_result_fields(self) -> None:
            self.outcome_popup.selectItemAtIndex_(0)
            self.value_field.setStringValue_("")
            self.notes_field.setStringValue_("")
            self._update_action_controls()

        @objc.python_method
        def _selected_outcome(self) -> str | None:
            return OUTCOME_VALUES.get(str(self.outcome_popup.titleOfSelectedItem()))

        @objc.python_method
        def _update_action_controls(self) -> None:
            snapshot = self.last_snapshot
            prepared = snapshot is not None and snapshot.can_show
            can_prepare = snapshot is not None and snapshot.can_prepare
            chosen = self._selected_outcome() is not None
            available = not self.busy

            self.refresh_button.setEnabled_(available)
            self.pause_button.setEnabled_(
                available and snapshot is not None and snapshot.can_toggle_pause
            )
            self.prepare_button.setEnabled_(available and can_prepare)
            self.show_button.setEnabled_(available and prepared)
            self.record_button.setEnabled_(available and prepared and chosen)
            self.end_picker.setEnabled_(available)
            self.days_popup.setEnabled_(available)
            self.outcome_popup.setEnabled_(available and prepared)
            self.value_field.setEnabled_(available and prepared)
            self.notes_field.setEnabled_(available and prepared)

            if self.busy:
                prepare_help = show_help = record_help = "Please wait for this action."
            elif snapshot is None:
                prepare_help = "Checking selected days..."
                show_help = record_help = "Wait for the selected day check."
            else:
                blocked_existing = "incomplete or unsafe" in snapshot.pack_state
                if blocked_existing:
                    recovery = (
                        "Move the existing folder aside or repair it, or choose other "
                        "dates, then refresh."
                    )
                    prepare_help = show_help = record_help = recovery
                elif prepared:
                    prepare_help = "Review files already exist for these dates."
                    show_help = "Opens Finder and selects REVIEW_PROMPT.md."
                    record_help = (
                        "Choose a result first."
                        if not chosen
                        else "Saves this result locally."
                    )
                elif can_prepare:
                    prepare_help = "Ready. This creates private files only."
                    show_help = record_help = "Create the review files in Step 1 first."
                else:
                    prepare_help = snapshot.pack_state
                    show_help = record_help = (
                        "Fix the Step 1 issue or choose other dates, then refresh."
                    )
            for button, label, help_text in (
                (self.prepare_button, self.prepare_help_label, prepare_help),
                (self.show_button, self.show_help_label, show_help),
                (self.record_button, self.record_help_label, record_help),
            ):
                label.setStringValue_(help_text)
                button.setAccessibilityHelp_(help_text)

        @objc.python_method
        def _apply_snapshot(
            self,
            snapshot: ReviewCenterSnapshot,
            message: str,
            focus=None,
        ) -> None:
            self.last_snapshot = snapshot
            health = snapshot.health
            if (
                self.window_privacy_active
                and health == "Logger is running. Capture is active."
            ):
                health = "Logger is running. Capture is paused for this window."
            self.health_label.setStringValue_(health)
            self.freshness_label.setStringValue_(snapshot.freshness)
            self.pause_state_label.setStringValue_(snapshot.pause_state)
            self.pause_button.setTitle_(
                "Turn off manual pause"
                if snapshot.manual_paused
                else "Turn on manual pause"
            )
            self.pack_state_label.setStringValue_(snapshot.pack_state)
            self.coverage_label.setStringValue_(snapshot.coverage)
            self.storage_label.setStringValue_(snapshot.storage)
            self.window.contentView().layoutSubtreeIfNeeded()
            self._layout_scroll_content()
            if self.initial_scroll_pending:
                self._scroll_to_visual_top()
                self.initial_scroll_pending = False
            self._set_busy(False)
            self._set_action_status(message)
            self._restore_focus(focus)
            for field in (self.pack_state_label, self.coverage_label):
                NSAccessibilityPostNotification(
                    field,
                    NSAccessibilityValueChangedNotification,
                )

        @objc.python_method
        def _finish_with_snapshot(self, snapshot, message: str, focus=None) -> None:
            AppHelper.callAfter(self._apply_snapshot, snapshot, message, focus)

        @objc.python_method
        def _finish_error(self, action: str, error: Exception, focus=None) -> None:
            message = f"{action} failed ({type(error).__name__})."
            AppHelper.callAfter(self._apply_action_result, message, focus)

        @objc.python_method
        def _apply_action_result(self, message: str, focus=None) -> None:
            self._set_busy(False)
            self._set_action_status(message)
            self._restore_focus(focus)

        @objc.python_method
        def _finish_action(self, message: str, focus=None) -> None:
            AppHelper.callAfter(self._apply_action_result, message, focus)

        @objc.python_method
        def _apply_outcome_result(self) -> None:
            self._clear_result_fields()
            self._apply_action_result(
                "Review result saved locally.",
                self.outcome_popup,
            )

        @objc.python_method
        def _finish_outcome(self) -> None:
            AppHelper.callAfter(self._apply_outcome_result)

        @objc.python_method
        def _start_refresh(
            self, message: str = "Status refreshed.", focus=None
        ) -> None:
            if self.busy:
                return
            if focus is None:
                focus = self.end_picker
            end = self._selected_date()
            days = self._selected_days()
            self._set_busy(True)
            self._set_action_status("Reading local status...")

            def work() -> None:
                try:
                    snapshot = self.model.snapshot(end, days)
                except Exception as error:
                    self._finish_error("Refresh", error, focus)
                    return
                self._finish_with_snapshot(snapshot, message, focus)

            threading.Thread(
                target=work, daemon=True, name="review-center-refresh"
            ).start()

        def refreshAction_(self, _sender):
            self._start_refresh(focus=self.refresh_button)

        def selectionAction_(self, _sender):
            self._clear_result_fields()
            focus = (
                _sender
                if _sender in (self.end_picker, self.days_popup)
                else self.end_picker
            )
            self._start_refresh("Review dates updated.", focus=focus)

        def outcomeAction_(self, _sender):
            self._update_action_controls()
            if self._selected_outcome() is not None:
                self._set_action_status(
                    "Result selected. Add optional detail, then save."
                )
            else:
                self._set_action_status("Choose a result before saving.")

        def prepareAction_(self, _sender):
            if (
                self.busy
                or self.last_snapshot is None
                or not self.last_snapshot.can_prepare
            ):
                return
            end = self._selected_date()
            days = self._selected_days()
            self._set_busy(True)
            self._set_action_status("Creating private review files...")

            def work() -> None:
                try:
                    result = self.model.prepare(end, days)
                    snapshot = self.model.snapshot(end, days)
                except Exception as error:
                    self._finish_error("Prepare", error, self.prepare_button)
                    return
                self._finish_with_snapshot(
                    snapshot,
                    f"Created {result.pack_dir.name}. Continue to Step 2.",
                    self.show_button,
                )

            threading.Thread(
                target=work, daemon=True, name="review-center-prepare"
            ).start()

        def showReviewAction_(self, _sender):
            if self.busy:
                return
            end = self._selected_date()
            days = self._selected_days()
            try:
                pack_dir = self.model.prepared_pack(end, days)
                if pack_dir is None:
                    self._set_action_status(
                        "Review files are missing, incomplete, or unsafe. Move the "
                        "existing folder aside or repair it, or choose other dates, "
                        "then refresh."
                    )
                    return
                _show_review_prompt_in_finder(pack_dir / PROMPT_NAME)
            except Exception as error:
                self._set_action_status(
                    f"Show in Finder failed ({type(error).__name__})."
                )
                return
            self._set_action_status(
                "Finder selected REVIEW_PROMPT.md. Review and redact private text "
                "before sharing."
            )

        def pauseAction_(self, _sender):
            if self.busy:
                return
            pause = self.pause_button.title() != "Turn off manual pause"
            end = self._selected_date()
            days = self._selected_days()
            self._set_busy(True)
            self._set_action_status(
                "Applying manual privacy pause..."
                if pause
                else "Resuming manual privacy control..."
            )

            def work() -> None:
                try:
                    self.model.set_manual_pause(pause)
                    snapshot = self.model.snapshot(end, days)
                except Exception as error:
                    self._finish_error("Privacy control", error, self.pause_button)
                    return
                self._finish_with_snapshot(
                    snapshot,
                    "Manual privacy pause is on."
                    if pause
                    else "Manual privacy pause is off.",
                    self.pause_button,
                )

            threading.Thread(
                target=work, daemon=True, name="review-center-pause"
            ).start()

        def recordOutcomeAction_(self, _sender):
            if self.busy:
                return
            week = self._selected_date()
            days = self._selected_days()
            outcome = self._selected_outcome()
            if outcome is None:
                self._set_action_status("Choose a result first.")
                return
            try:
                prepared_pack = self.model.prepared_pack(week, days)
            except Exception as error:
                self._set_action_status(
                    f"Review file check failed ({type(error).__name__})."
                )
                return
            if prepared_pack is None:
                self._set_action_status(
                    "Safe review files are required before saving a result."
                )
                return
            value_result = str(self.value_field.stringValue())
            notes = str(self.notes_field.stringValue())
            self._set_busy(True)
            self._set_action_status("Saving the review result locally...")

            def work() -> None:
                try:
                    self.model.record_outcome(
                        week,
                        outcome,
                        value_result,
                        notes,
                    )
                except Exception as error:
                    self._finish_error("Outcome", error, self.record_button)
                    return
                self._finish_outcome()

            threading.Thread(
                target=work, daemon=True, name="review-center-outcome"
            ).start()

        @objc.python_method
        def show(self) -> None:
            self._refresh_date_limit()
            if self.window.isMiniaturized():
                self.window.deminiaturize_(None)
            self._set_window_privacy(True)
            self.window.makeKeyAndOrderFront_(None)
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            self.window.contentView().layoutSubtreeIfNeeded()
            self._layout_scroll_content()
            if self.initial_scroll_pending:
                self._scroll_to_visual_top()
            self._start_refresh("Review Center opened.", focus=self.end_picker)

        def windowShouldClose_(self, _sender):
            self.window.orderOut_(None)
            self._set_window_privacy(False)
            return False

        def windowDidBecomeKey_(self, _notification):
            self._set_window_privacy(True)
            if not self.busy and self.last_snapshot is not None:
                self._apply_snapshot(
                    self.last_snapshot,
                    "Review Center is active.",
                )

        def windowDidResignKey_(self, _notification):
            pass

        def windowDidMiniaturize_(self, _notification):
            self._set_window_privacy(False)

        def windowDidDeminiaturize_(self, _notification):
            self._set_window_privacy(True)

        def windowDidResize_(self, _notification):
            self._layout_scroll_content()

    class _ReviewCenterAppDelegate(NSObject):
        def initWithController_delay_(self, controller, delay):
            self = objc.super(_ReviewCenterAppDelegate, self).init()
            if self is None:
                return None
            self.controller = controller
            self.reopen_after = time.monotonic() + float(delay)
            return self

        def applicationShouldHandleReopen_hasVisibleWindows_(
            self,
            _application,
            _has_visible_windows,
        ):
            if time.monotonic() >= self.reopen_after:
                self.controller.show()
            return True

    class ReviewCenterRuntime:
        def __init__(self, model: ReviewCenterModel, pause_callback=None) -> None:
            self.app = NSApplication.sharedApplication()
            self.previous_delegate = self.app.delegate()
            if self.previous_delegate is not None:
                raise RuntimeError("cannot replace the existing application delegate")
            self.app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
            self.controller = (
                ReviewCenterWindowController.alloc().initWithModel_pauseCallback_(
                    model,
                    pause_callback,
                )
            )
            self.delegate = _ReviewCenterAppDelegate.alloc().initWithController_delay_(
                self.controller,
                2.0,
            )
            self.app.setDelegate_(self.delegate)
            self.app.finishLaunching()
            self.pump()

        def pump(self, limit: int = 100) -> None:
            for _ in range(limit):
                event = self.app.nextEventMatchingMask_untilDate_inMode_dequeue_(
                    NSAnyEventMask,
                    NSDate.distantPast(),
                    NSDefaultRunLoopMode,
                    True,
                )
                if event is None:
                    break
                self.app.sendEvent_(event)
            self.app.updateWindows()

        def close(self) -> None:
            try:
                self.controller.window.orderOut_(None)
            finally:
                try:
                    self.controller._set_window_privacy(False)
                finally:
                    if self.app.delegate() is self.delegate:
                        self.app.setDelegate_(self.previous_delegate)


else:
    ReviewCenterWindowController = None
    ReviewCenterRuntime = None


def create_review_center_runtime(
    log_dir: Path,
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    home: Path | None = None,
    pause_callback=None,
):
    if not APPKIT_AVAILABLE:
        raise RuntimeError("AppKit is unavailable")
    model = ReviewCenterModel(log_dir, output_dir=output_dir, home=home)
    return ReviewCenterRuntime(model, pause_callback=pause_callback)
