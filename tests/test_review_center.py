from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import interleaved_logger as il
import review_center as rc


def _status(*, ready: bool = True, pack_name: str = "weekly_review_test_5d"):
    states = (SimpleNamespace(day="2026-08-27", state="ready"),)
    if not ready:
        states = (SimpleNamespace(day="2026-08-27", state="missing"),)
    return SimpleNamespace(
        start="2026-08-27",
        end="2026-08-31",
        days=5,
        day_statuses=states,
        ready=ready,
        warnings=(
            "Ready proof confirms integrity, not capture coverage.",
            *(("2026-08-27 is missing.",) if not ready else ()),
        ),
        pack_name=pack_name,
    )


def _reports(monkeypatch, *, manual_paused: bool = False) -> None:
    monkeypatch.setattr(
        rc,
        "health_report",
        lambda *_args, **_kwargs: {
            "running": True,
            "manual_paused": manual_paused,
            "capture_paused": manual_paused,
            "freshness_seconds": 12,
            "format": rc.ANALYSIS_FORMAT_V2,
            "intent_match": True,
            "invalid_marker": False,
            "log_dir_mode": "700",
            "analysis_mode": "600",
            "intent_mode": "600",
            "ready_mode": "missing",
            "runtime_dir_mode": "700",
            "lock_mode": "600",
            "state_mode": "600",
        },
    )
    monkeypatch.setattr(
        rc,
        "storage_report",
        lambda *_args, **_kwargs: {
            "total_private_log_bytes": 2048,
            "completed_days": 5,
            "review_packs": 1,
            "missing_readiness_proofs": 0,
            "unsafe_files": 0,
        },
    )


def test_snapshot_is_payload_free_and_reuses_operator_reports(tmp_path, monkeypatch):
    _reports(monkeypatch)
    monkeypatch.setattr(rc, "weekly_window_status", lambda *_args, **_kwargs: _status())
    snapshot = rc.ReviewCenterModel(
        tmp_path / "logs",
        output_dir=tmp_path / "review",
        home=tmp_path / "home",
    ).snapshot(date(2026, 8, 31), 5, today=date(2026, 9, 1))

    assert snapshot.health == "Logger is running. Capture is active."
    assert snapshot.freshness == "Last verified safe write was 12 seconds ago."
    assert snapshot.pause_state == "Manual privacy pause is off."
    assert snapshot.pack_state == "Ready to prepare 2026-08-27 through 2026-08-31."
    assert snapshot.can_prepare is True
    assert snapshot.storage.startswith("2.0 KB in private logs.")
    rendered = "\n".join(
        (
            snapshot.health,
            snapshot.freshness,
            snapshot.pause_state,
            snapshot.pack_state,
            snapshot.coverage,
            snapshot.storage,
        )
    )
    assert "captured secret" not in rendered


def test_snapshot_reports_missing_days_and_existing_pack(tmp_path, monkeypatch):
    _reports(monkeypatch, manual_paused=True)
    monkeypatch.setattr(
        rc,
        "weekly_window_status",
        lambda *_args, **_kwargs: _status(ready=False),
    )
    model = rc.ReviewCenterModel(tmp_path / "logs", output_dir=tmp_path / "review")
    missing = model.snapshot(date(2026, 8, 31), 5, today=date(2026, 9, 1))

    assert missing.manual_paused is True
    assert missing.pack_state == "Not ready. 1 selected day(s) need attention."
    assert "2026-08-27 is missing." in missing.coverage
    assert missing.can_prepare is False

    pack = tmp_path / "review" / "weekly_review_test_5d"
    pack.mkdir(parents=True)
    (pack / rc.INDEX_NAME).write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        rc,
        "weekly_window_status",
        lambda *_args, **_kwargs: _status(),
    )
    prepared = model.snapshot(date(2026, 8, 31), 5, today=date(2026, 9, 1))
    assert prepared.pack_state == "Prepared: weekly_review_test_5d"
    assert prepared.can_prepare is False


@pytest.mark.parametrize(
    ("health_change", "expected"),
    (
        ({"invalid_marker": True}, "invalid marker"),
        ({"intent_match": False}, "intent journal does not match"),
        ({"analysis_mode": "644"}, "permissions are unsafe"),
    ),
)
def test_snapshot_reports_degraded_log_health(
    tmp_path,
    monkeypatch,
    health_change,
    expected,
):
    _reports(monkeypatch)
    healthy_report = rc.health_report(tmp_path / "logs", date(2026, 9, 1))
    healthy_report.update(health_change)
    monkeypatch.setattr(
        rc,
        "health_report",
        lambda *_args, **_kwargs: healthy_report,
    )
    monkeypatch.setattr(rc, "weekly_window_status", lambda *_args, **_kwargs: _status())

    snapshot = rc.ReviewCenterModel(tmp_path / "logs").snapshot(
        date(2026, 8, 31),
        5,
        today=date(2026, 9, 1),
    )

    assert "health is degraded" in snapshot.health
    assert expected in snapshot.health
    assert "Capture is active" not in snapshot.health


def test_missing_optional_files_are_not_called_unsafe_permissions(
    tmp_path,
    monkeypatch,
):
    _reports(monkeypatch)
    report = rc.health_report(tmp_path / "logs", date(2026, 9, 1))
    report.update(
        {
            "ready_mode": "missing",
            "lock_mode": "missing",
            "state_mode": "missing",
        }
    )
    monkeypatch.setattr(rc, "health_report", lambda *_args, **_kwargs: report)
    monkeypatch.setattr(rc, "weekly_window_status", lambda *_args, **_kwargs: _status())

    snapshot = rc.ReviewCenterModel(tmp_path / "logs").snapshot(
        date(2026, 8, 31),
        5,
        today=date(2026, 9, 1),
    )

    assert "permissions are unsafe" not in snapshot.health


def test_actions_delegate_to_existing_modules(tmp_path, monkeypatch):
    calls = []
    result = SimpleNamespace(pack_dir=tmp_path / "review" / "pack")
    monkeypatch.setattr(
        rc,
        "create_weekly_review_pack",
        lambda *args, **kwargs: calls.append(("prepare", args, kwargs)) or result,
    )
    monkeypatch.setattr(
        rc,
        "set_manual_pause",
        lambda paused, **kwargs: calls.append(("pause", paused, kwargs)) or {},
    )
    monkeypatch.setattr(
        rc,
        "record_review_outcome",
        lambda *args, **kwargs: calls.append(("outcome", args, kwargs))
        or tmp_path / "outcomes.md",
    )
    model = rc.ReviewCenterModel(
        tmp_path / "logs",
        output_dir=tmp_path / "review",
        home=tmp_path / "home",
    )

    assert model.prepare(date(2026, 8, 31), 5) is result
    model.set_manual_pause(True)
    model.record_outcome(date(2026, 8, 31), "tried", "saved time", "local")

    assert calls[0][0] == "prepare"
    assert calls[0][2]["days"] == 5
    assert calls[1] == ("pause", True, {"home": tmp_path / "home"})
    assert calls[2][0] == "outcome"
    assert calls[2][2]["output_dir"] == tmp_path / "review"


def test_review_window_pause_blocks_capture_without_changing_manual_pause(
    reset_logger_state,
):
    reset_logger_state()
    il._set_pause(manual=True)
    il._set_pause(review=True)
    il._set_pause(review=False)
    assert il._pause_manual is True
    assert il.is_paused() is True

    il._set_pause(manual=False)
    il._set_pause(review=True)
    il.add_event("captured secret")
    assert il._current_events == []
    il._set_pause(review=False)
    assert il.is_paused() is False


def test_pause_edges_publish_fresh_payload_free_runtime_state(
    reset_logger_state,
    monkeypatch,
):
    reset_logger_state()
    published = []
    monkeypatch.setattr(
        il,
        "write_runtime_state",
        lambda **state: published.append(state),
    )

    il._set_pause(field=True)
    assert il._manual_state_dirty.is_set()
    il._apply_pending_manual_control()
    il._set_pause(field=False)
    assert il._manual_state_dirty.is_set()
    il._apply_pending_manual_control()

    assert [state["capture_paused"] for state in published] == [True, False]
    assert all(state["manual_paused"] is False for state in published)


def test_pause_edge_during_publish_keeps_state_dirty(
    reset_logger_state,
    monkeypatch,
):
    reset_logger_state()
    il._manual_state_dirty.set()

    def publish(**_state):
        il._set_pause(review=True)
        return True

    monkeypatch.setattr(il, "_publish_runtime_state", publish)
    il._apply_pending_manual_control()

    assert il._pause_review_center is True
    assert il._manual_state_dirty.is_set()


@pytest.mark.skipif(not rc.APPKIT_AVAILABLE, reason="AppKit is unavailable")
def test_native_window_constructs_hidden_with_accessible_controls(tmp_path):
    from AppKit import NSApplication

    NSApplication.sharedApplication()
    controller = rc.ReviewCenterWindowController.alloc().initWithModel_(
        rc.ReviewCenterModel(tmp_path / "logs", output_dir=tmp_path / "review")
    )
    try:
        assert controller.window.title() == "ActivityLogger Review Center"
        assert controller.window.isVisible() is False
        assert controller.end_picker.accessibilityLabel() == "Weekly review end date"
        assert controller.days_popup.accessibilityLabel() == "Weekly review period"
        assert controller.outcome_popup.accessibilityLabel() == "Weekly review outcome"
        assert controller.value_field.accessibilityLabel() == "Weekly review value result"
        assert controller.notes_field.accessibilityLabel() == "Weekly review notes"
        assert controller.pack_warning.accessibilityLabel() == "Weekly pack privacy warning"
        assert controller.pause_button.title() == "Turn on manual pause"
        assert controller.pause_button.nextKeyView() is controller.refresh_button
        assert controller.refresh_button.nextKeyView() is controller.end_picker
        assert controller.end_picker.nextKeyView() is controller.days_popup
        assert controller.days_popup.nextKeyView() is controller.prepare_button
        assert controller.prepare_button.nextKeyView() is controller.outcome_popup
        assert controller.outcome_popup.nextKeyView() is controller.value_field
        assert controller.value_field.nextKeyView() is controller.notes_field
        assert controller.notes_field.nextKeyView() is controller.record_button
        assert controller.window.makeFirstResponder_(controller.prepare_button)
        controller._set_busy(True)
        assert controller.prepare_button.isEnabled() is False
        assert controller.window.firstResponder() is not controller.prepare_button
    finally:
        controller.window.orderOut_(None)


@pytest.mark.skipif(not rc.APPKIT_AVAILABLE, reason="AppKit is unavailable")
def test_native_window_privacy_and_completed_day_limit_refresh(tmp_path):
    from AppKit import NSApplication

    NSApplication.sharedApplication()
    privacy = []
    controller = (
        rc.ReviewCenterWindowController.alloc().initWithModel_pauseCallback_(
            rc.ReviewCenterModel(tmp_path / "logs"),
            privacy.append,
        )
    )
    try:
        old_limit = controller.date_limit
        controller._set_window_privacy(True)
        controller._set_window_privacy(True)
        controller._apply_snapshot(
            rc.ReviewCenterSnapshot(
                health="Logger is running. Capture is active.",
                freshness="Fresh.",
                pause_state="Manual privacy pause is off.",
                manual_paused=False,
                can_toggle_pause=True,
                pack_state="Ready.",
                coverage="Coverage warning.",
                can_prepare=True,
                storage="Private storage.",
            ),
            "Updated.",
        )
        assert "paused for Review Center" in controller.health_label.stringValue()
        assert (
            controller.pause_state_label.stringValue()
            == "Review Center privacy pause is on."
        )
        controller._apply_snapshot(
            rc.ReviewCenterSnapshot(
                health="Logger is running, but health is degraded: invalid marker.",
                freshness="Freshness unavailable.",
                pause_state="Manual privacy pause is off.",
                manual_paused=False,
                can_toggle_pause=True,
                pack_state="Ready.",
                coverage="Coverage warning.",
                can_prepare=True,
                storage="Private storage.",
            ),
            "Updated.",
        )
        assert "health is degraded" in controller.health_label.stringValue()
        assert "paused for Review Center" in controller.health_label.stringValue()
        controller.windowDidResignKey_(None)
        controller.windowDidBecomeKey_(None)
        controller.windowDidMiniaturize_(None)
        assert privacy == [True, False, True, False]

        controller._refresh_date_limit(old_limit + timedelta(days=2))
        assert controller.date_limit == old_limit + timedelta(days=1)
        assert controller._selected_date() == controller.date_limit
    finally:
        controller.window.orderOut_(None)


@pytest.mark.skipif(not rc.APPKIT_AVAILABLE, reason="AppKit is unavailable")
def test_snapshot_announces_pack_state_and_scrolls_long_coverage(
    tmp_path,
    monkeypatch,
):
    from AppKit import NSApplication

    NSApplication.sharedApplication()
    announced = []
    monkeypatch.setattr(
        rc,
        "NSAccessibilityPostNotification",
        lambda field, notification: announced.append((field, notification)),
    )
    controller = rc.ReviewCenterWindowController.alloc().initWithModel_(
        rc.ReviewCenterModel(tmp_path / "logs")
    )
    try:
        coverage = "\n".join(f"2026-08-{day:02d} is missing." for day in range(20, 32))
        controller._apply_snapshot(
            rc.ReviewCenterSnapshot(
                health="Logger is running.",
                freshness="Fresh.",
                pause_state="Manual privacy pause is off.",
                manual_paused=False,
                can_toggle_pause=True,
                pack_state="Not ready.",
                coverage=coverage,
                can_prepare=False,
                storage="Private storage.",
            ),
            "Selection updated.",
        )
        fields = [field for field, _notification in announced]
        assert controller.pack_state_label in fields
        assert controller.coverage_label in fields
        assert controller.scroll_view.hasVerticalScroller() is True
        assert (
            controller.scroll_document.frame().size.height
            >= controller.scroll_view.contentSize().height
        )
        assert controller.root_stack.hasAmbiguousLayout() is False
    finally:
        controller.window.orderOut_(None)


@pytest.mark.skipif(not rc.APPKIT_AVAILABLE, reason="AppKit is unavailable")
def test_runtime_show_close_and_exit_enforce_privacy(tmp_path, monkeypatch):
    monkeypatch.setattr(
        rc.ReviewCenterWindowController,
        "_start_refresh",
        lambda self, message="Status refreshed.": None,
    )
    privacy = []
    runtime = rc.ReviewCenterRuntime(
        rc.ReviewCenterModel(tmp_path / "logs"),
        pause_callback=privacy.append,
    )
    try:
        assert runtime.controller.window.isVisible() is False
        runtime.controller.show()
        assert runtime.controller.window.isVisible() is True
        assert privacy == [True]
        runtime.controller.windowDidResignKey_(None)
        runtime.controller.windowDidBecomeKey_(None)
        assert privacy == [True, False, True]
        assert runtime.controller.windowShouldClose_(None) is False
        assert privacy == [True, False, True, False]
        assert runtime.controller.window.isVisible() is False
    finally:
        runtime.close()
    assert privacy == [True, False, True, False]


@pytest.mark.skipif(not rc.APPKIT_AVAILABLE, reason="AppKit is unavailable")
def test_runtime_exit_clears_active_window_privacy(tmp_path, monkeypatch):
    monkeypatch.setattr(
        rc.ReviewCenterWindowController,
        "_start_refresh",
        lambda self, message="Status refreshed.": None,
    )
    privacy = []
    runtime = rc.ReviewCenterRuntime(
        rc.ReviewCenterModel(tmp_path / "logs"),
        pause_callback=privacy.append,
    )

    runtime.controller.show()
    assert privacy == [True]
    runtime.close()

    assert privacy == [True, False]
    assert runtime.controller.window.isVisible() is False


@pytest.mark.skipif(not rc.APPKIT_AVAILABLE, reason="AppKit is unavailable")
def test_reopen_delegate_ignores_startup_then_shows(monkeypatch):
    shown = []
    controller = SimpleNamespace(show=lambda: shown.append(True))
    now = [100.0]
    monkeypatch.setattr(rc.time, "monotonic", lambda: now[0])
    delegate = rc._ReviewCenterAppDelegate.alloc().initWithController_delay_(
        controller,
        2.0,
    )

    assert delegate.applicationShouldHandleReopen_hasVisibleWindows_(None, False)
    assert shown == []
    now[0] = 102.1
    assert delegate.applicationShouldHandleReopen_hasVisibleWindows_(None, False)
    assert shown == [True]


def test_bundle_is_gui_capable_without_a_dock_icon():
    spec = Path("ActivityLoggerNative.spec").read_text(encoding="utf-8")
    assert "'review_center'" in spec
    assert "'LSBackgroundOnly': False" in spec
    assert "'LSUIElement': True" in spec
