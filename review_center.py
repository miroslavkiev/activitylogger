"""Native, payload-free Review Center for ActivityLogger operators."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from analysis_log import ANALYSIS_FORMAT_V2
from analysis_view import DEFAULT_OUTPUT_DIR
from operator_controls import (
    health_report,
    record_review_outcome,
    set_manual_pause,
    storage_report,
)
from weekly_review import INDEX_NAME, create_weekly_review_pack, weekly_window_status

try:
    import objc
    from AppKit import (
        NSAccessibilityPostNotification,
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
    )
    from Foundation import NSDate
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
    storage: str


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
        elif capture_paused:
            pause_state = "A secure app or secure field is keeping capture paused."
        elif running:
            pause_state = "Manual privacy pause is off."
        else:
            pause_state = "Manual privacy control is unavailable."

        pack_path = self.output_dir / window.pack_name
        pack_present = pack_path.exists() or pack_path.is_symlink()
        pack_complete = (
            pack_path.is_dir()
            and not pack_path.is_symlink()
            and (pack_path / INDEX_NAME).is_file()
            and not (pack_path / INDEX_NAME).is_symlink()
        )
        if pack_complete:
            pack_state = f"Prepared: {window.pack_name}"
        elif pack_present:
            pack_state = "The selected pack path exists but is not a complete pack."
        elif window.ready:
            pack_state = f"Ready to prepare {window.start} through {window.end}."
        else:
            issue_count = sum(
                item.state != "ready" for item in window.day_statuses
            )
            pack_state = f"Not ready. {issue_count} selected day(s) need attention."

        storage_text = (
            f"{_format_bytes(storage.get('total_private_log_bytes'))} in private logs. "
            f"{storage.get('completed_days', 0)} completed day(s), "
            f"{storage.get('review_packs', 0)} review pack(s), "
            f"{storage.get('missing_readiness_proofs', 0)} missing readiness proof(s), "
            f"{storage.get('unsafe_files', 0)} unsafe item(s)."
        )
        return ReviewCenterSnapshot(
            health=health_text,
            freshness=freshness,
            pause_state=pause_state,
            manual_paused=manual_paused,
            can_toggle_pause=running,
            pack_state=pack_state,
            coverage="\n".join(window.warnings),
            can_prepare=window.ready and not pack_present,
            storage=storage_text,
        )

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


    def _button(title: str, target, action: bytes):
        button = NSButton.buttonWithTitle_target_action_(title, target, action)
        button.setBezelStyle_(NSBezelStyleRounded)
        return button


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
                NSMakeRect(0, 0, 620, 720),
                mask,
                NSBackingStoreBuffered,
                False,
            )
            self.window.setTitle_("ActivityLogger Review Center")
            self.window.setMinSize_(NSMakeSize(520, 660))
            self.window.setReleasedWhenClosed_(False)
            self.window.setDelegate_(self)
            self.window.center()

            title = _label("ActivityLogger Review Center", bold=True)
            title.setFont_(NSFont.boldSystemFontOfSize_(20))
            subtitle = _label(
                "Private local controls and summaries. Captured text is never shown here. "
                "Capture stays paused while this window is active.",
                wrap=True,
            )

            self.health_label = _label("Loading logger health...", wrap=True)
            self.health_label.setAccessibilityLabel_("Logger health")
            self.freshness_label = _label("Loading freshness...", wrap=True)
            self.freshness_label.setAccessibilityLabel_("Logger freshness")
            self.pause_state_label = _label("Loading privacy state...", wrap=True)
            self.pause_state_label.setAccessibilityLabel_("Manual privacy state")
            self.pause_button = _button(
                "Turn on manual pause", self, b"pauseAction:"
            )
            self.pause_button.setAccessibilityHelp_(
                "Pause or resume capture through the shared privacy control."
            )
            self.refresh_button = _button("Refresh", self, b"refreshAction:")

            self.end_picker = NSDatePicker.alloc().init()
            self.end_picker.setDatePickerStyle_(
                NSDatePickerStyleTextFieldAndStepper
            )
            self.end_picker.setDatePickerElements_(
                NSYearMonthDayDatePickerElementFlag
            )
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
                "Prepare weekly pack", self, b"prepareAction:"
            )
            pack_warning = _label(
                "Weekly packs contain private captured text. Review and redact a pack "
                "before using it outside this Mac.",
                wrap=True,
            )
            pack_warning.setAccessibilityLabel_("Weekly pack privacy warning")
            self.pack_state_label = _label("Loading weekly pack state...", wrap=True)
            self.pack_state_label.setAccessibilityLabel_("Weekly pack status")
            self.coverage_label = _label("Loading coverage warnings...", wrap=True)
            self.coverage_label.setAccessibilityLabel_("Coverage warnings")

            self.storage_label = _label("Loading storage summary...", wrap=True)
            self.storage_label.setAccessibilityLabel_("Private storage summary")

            self.outcome_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(0, 0, 120, 28), False
            )
            self.outcome_popup.addItemsWithTitles_(["tried", "accepted", "ignored"])
            self.outcome_popup.setAccessibilityLabel_("Weekly review outcome")
            self.value_field = NSTextField.alloc().init()
            self.value_field.setPlaceholderString_("Value result")
            self.value_field.setAccessibilityLabel_("Weekly review value result")
            self.notes_field = NSTextField.alloc().init()
            self.notes_field.setPlaceholderString_("Notes")
            self.notes_field.setAccessibilityLabel_("Weekly review notes")
            self.record_button = _button(
                "Record weekly outcome", self, b"recordOutcomeAction:"
            )

            self.action_status_label = _label("Ready.", wrap=True)
            self.action_status_label.setAccessibilityLabel_("Action status")
            self.action_status_label.setSelectable_(True)

            views = [
                title,
                subtitle,
                _label("Logger", bold=True),
                self.health_label,
                self.freshness_label,
                self.pause_state_label,
                _row(self.pause_button, self.refresh_button),
                _label("Weekly pack", bold=True),
                _row(
                    _label("End date"),
                    self.end_picker,
                    _label("Period"),
                    self.days_popup,
                ),
                self.pack_state_label,
                self.coverage_label,
                pack_warning,
                self.prepare_button,
                _label("Private storage", bold=True),
                self.storage_label,
                _label("Weekly outcome", bold=True),
                _row(_label("Outcome"), self.outcome_popup),
                _label("Value result"),
                self.value_field,
                _label("Notes"),
                self.notes_field,
                self.record_button,
                self.action_status_label,
            ]
            root = NSStackView.stackViewWithViews_(views)
            root.setOrientation_(NSUserInterfaceLayoutOrientationVertical)
            root.setAlignment_(NSLayoutAttributeLeading)
            root.setSpacing_(7)
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
            for view in (
                subtitle,
                self.health_label,
                self.freshness_label,
                self.pause_state_label,
                self.pack_state_label,
                self.coverage_label,
                pack_warning,
                self.storage_label,
                self.value_field,
                self.notes_field,
                self.action_status_label,
            ):
                view.widthAnchor().constraintEqualToAnchor_(
                    root.widthAnchor()
                ).setActive_(True)
            self.root_stack = root
            self.pack_warning = pack_warning
            self._layout_scroll_content()
            self.window.setAutorecalculatesKeyViewLoop_(True)
            self.window.setInitialFirstResponder_(self.end_picker)
            controls = (
                self.pause_button,
                self.refresh_button,
                self.end_picker,
                self.days_popup,
                self.prepare_button,
                self.outcome_popup,
                self.value_field,
                self.notes_field,
                self.record_button,
                self.action_status_label,
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
        def _date_to_nsdate(self, value: date):
            stamp = datetime.combine(
                value,
                datetime.min.time(),
            ).astimezone().replace(hour=12)
            return NSDate.dateWithTimeIntervalSince1970_(stamp.timestamp())

        @objc.python_method
        def _selected_date(self) -> date:
            stamp = self.end_picker.dateValue().timeIntervalSince1970()
            return datetime.fromtimestamp(stamp).astimezone().date()

        @objc.python_method
        def _selected_days(self) -> int:
            return 7 if str(self.days_popup.titleOfSelectedItem()).startswith("7") else 5

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
                self.window.makeFirstResponder_(self.action_status_label)
            self.refresh_button.setEnabled_(not busy)
            self.pause_button.setEnabled_(
                not busy
                and self.last_snapshot is not None
                and self.last_snapshot.can_toggle_pause
            )
            self.prepare_button.setEnabled_(
                not busy
                and self.last_snapshot is not None
                and self.last_snapshot.can_prepare
            )
            self.record_button.setEnabled_(not busy)
            self.end_picker.setEnabled_(not busy)
            self.days_popup.setEnabled_(not busy)
            self.outcome_popup.setEnabled_(not busy)
            self.value_field.setEnabled_(not busy)
            self.notes_field.setEnabled_(not busy)

        @objc.python_method
        def _apply_snapshot(self, snapshot: ReviewCenterSnapshot, message: str) -> None:
            self.last_snapshot = snapshot
            health = snapshot.health
            pause_state = snapshot.pause_state
            if self.window_privacy_active:
                if "health is degraded" in health:
                    health = f"{health} Capture is paused for Review Center."
                else:
                    health = "Logger is running. Capture is paused for Review Center."
                pause_state = (
                    "Review Center privacy pause is on. Manual privacy pause is also on."
                    if snapshot.manual_paused
                    else "Review Center privacy pause is on."
                )
            self.health_label.setStringValue_(health)
            self.freshness_label.setStringValue_(snapshot.freshness)
            self.pause_state_label.setStringValue_(pause_state)
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
            self._set_busy(False)
            self._set_action_status(message)
            for field in (self.pack_state_label, self.coverage_label):
                NSAccessibilityPostNotification(
                    field,
                    NSAccessibilityValueChangedNotification,
                )

        @objc.python_method
        def _finish_with_snapshot(self, snapshot, message: str) -> None:
            AppHelper.callAfter(self._apply_snapshot, snapshot, message)

        @objc.python_method
        def _finish_error(self, action: str, error: Exception) -> None:
            message = f"{action} failed ({type(error).__name__})."
            AppHelper.callAfter(self._apply_action_result, message)

        @objc.python_method
        def _apply_action_result(self, message: str) -> None:
            self._set_busy(False)
            self._set_action_status(message)

        @objc.python_method
        def _finish_action(self, message: str) -> None:
            AppHelper.callAfter(self._apply_action_result, message)

        @objc.python_method
        def _start_refresh(self, message: str = "Status refreshed.") -> None:
            if self.busy:
                return
            end = self._selected_date()
            days = self._selected_days()
            self._set_busy(True)
            self._set_action_status("Reading local status...")

            def work() -> None:
                try:
                    snapshot = self.model.snapshot(end, days)
                except Exception as error:
                    self._finish_error("Refresh", error)
                    return
                self._finish_with_snapshot(snapshot, message)

            threading.Thread(target=work, daemon=True, name="review-center-refresh").start()

        def refreshAction_(self, _sender):
            self._start_refresh()

        def selectionAction_(self, _sender):
            self._start_refresh("Selection updated.")

        def prepareAction_(self, _sender):
            if self.busy:
                return
            end = self._selected_date()
            days = self._selected_days()
            self._set_busy(True)
            self._set_action_status("Preparing the private weekly pack...")

            def work() -> None:
                try:
                    result = self.model.prepare(end, days)
                    snapshot = self.model.snapshot(end, days)
                except Exception as error:
                    self._finish_error("Prepare", error)
                    return
                self._finish_with_snapshot(
                    snapshot,
                    f"Prepared {result.pack_dir.name}.",
                )

            threading.Thread(target=work, daemon=True, name="review-center-prepare").start()

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
                    self._finish_error("Privacy control", error)
                    return
                self._finish_with_snapshot(
                    snapshot,
                    "Manual privacy pause is on."
                    if pause
                    else "Manual privacy pause is off.",
                )

            threading.Thread(target=work, daemon=True, name="review-center-pause").start()

        def recordOutcomeAction_(self, _sender):
            if self.busy:
                return
            week = self._selected_date()
            outcome = str(self.outcome_popup.titleOfSelectedItem())
            value_result = str(self.value_field.stringValue())
            notes = str(self.notes_field.stringValue())
            self._set_busy(True)
            self._set_action_status("Recording the weekly outcome locally...")

            def work() -> None:
                try:
                    self.model.record_outcome(
                        week,
                        outcome,
                        value_result,
                        notes,
                    )
                except Exception as error:
                    self._finish_error("Outcome", error)
                    return
                self._finish_action("Weekly outcome recorded locally.")

            threading.Thread(target=work, daemon=True, name="review-center-outcome").start()

        @objc.python_method
        def show(self) -> None:
            self._refresh_date_limit()
            self._set_window_privacy(True)
            self.window.makeKeyAndOrderFront_(None)
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            self._start_refresh("Review Center opened.")

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
            self._set_window_privacy(False)

        def windowDidMiniaturize_(self, _notification):
            self._set_window_privacy(False)

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
