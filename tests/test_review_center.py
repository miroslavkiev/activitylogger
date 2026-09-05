from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import interleaved_logger as il
import review_center as rc


def _status(*, ready: bool = True, pack_name: str = "weekly_review_2026-08-27_2026-08-31_5d"):
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
            "runtime_state_valid": True,
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


def _private_pack(
    root: Path,
    name: str = "weekly_review_2026-08-27_2026-08-31_5d",
    *,
    end: date = date(2026, 8, 31),
    days: int = 5,
) -> Path:
    root.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    pack = root / name
    pack.mkdir(mode=0o700)
    pack.chmod(0o700)
    selected_days = tuple(
        end - timedelta(days=offset) for offset in range(days - 1, -1, -1)
    )
    digest = "0" * 64
    workload_files = tuple(
        rc.workload_view_path(pack, selected_day) for selected_day in selected_days
    )
    prompt = pack / rc.PROMPT_NAME
    prompt.write_text("# Review\n")
    prompt.chmod(0o600)
    for path in workload_files:
        path.write_text(f"> private review for {path.stem}\n")
        path.chmod(0o600)
    index = {
        "format": rc.WEEKLY_PACK_FORMAT,
        "window": {
            "start": selected_days[0].isoformat(),
            "end": selected_days[-1].isoformat(),
            "calendar_days": days,
            "complete_fixed_window": True,
            "older_day_substitution": False,
        },
        "files": {
            rc.PROMPT_NAME: digest,
            **{path.name: digest for path in workload_files},
        },
        "days": [
            {
                "day": selected_day.isoformat(),
                "output": {"file": path.name, "sha256": digest},
                "sources": {f"source_{selected_day.isoformat()}.md": digest},
            }
            for selected_day, path in zip(selected_days, workload_files, strict=True)
        ],
    }
    index_path = pack / rc.INDEX_NAME
    index_path.write_text(json.dumps(index))
    index_path.chmod(0o600)
    return pack


def test_snapshot_is_payload_free_and_reuses_operator_reports(tmp_path, monkeypatch):
    _reports(monkeypatch)
    monkeypatch.setattr(rc, "weekly_window_status", lambda *_args, **_kwargs: _status())
    snapshot = rc.ReviewCenterModel(
        tmp_path / "logs",
        output_dir=tmp_path / "review",
        home=tmp_path / "home",
    ).snapshot(date(2026, 8, 31), 5, today=date(2026, 9, 1))

    assert snapshot.health == "Logger is running."
    assert snapshot.capture_state == "active"
    assert snapshot.freshness == "Last verified safe write was 12 seconds ago."
    assert snapshot.pause_state == "Manual privacy pause is off."
    assert (
        snapshot.pack_state
        == "Ready to create files for 2026-08-27 through 2026-08-31."
    )
    assert snapshot.can_prepare is True
    assert snapshot.can_show is False
    assert snapshot.storage.startswith("2.0 KB of private logs.")
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
    assert missing.pack_state == "Not ready. 1 selected day needs attention."
    assert "Restore them or choose other dates" in missing.coverage
    assert missing.can_prepare is False

    _private_pack(tmp_path / "review")
    monkeypatch.setattr(
        rc,
        "weekly_window_status",
        lambda *_args, **_kwargs: _status(),
    )
    prepared = model.snapshot(date(2026, 8, 31), 5, today=date(2026, 9, 1))
    assert prepared.pack_state == (
        "Review files are ready for 2026-08-27 through 2026-08-31."
    )
    assert prepared.can_prepare is False
    assert prepared.can_show is True


@pytest.mark.parametrize(
    ("state", "guidance"),
    (
        ("active", "Choose an earlier end date"),
        ("unsupported", "Choose newer dates"),
        ("invalid", "Use Recovery help"),
        ("missing", "Restore them or choose other dates"),
        ("unready", "Use Recovery help"),
    ),
)
def test_snapshot_turns_day_states_into_plain_actions(
    tmp_path,
    monkeypatch,
    state,
    guidance,
):
    _reports(monkeypatch)
    status = _status()
    status.day_statuses = (SimpleNamespace(day="2026-08-27", state=state),)
    status.ready = False
    monkeypatch.setattr(rc, "weekly_window_status", lambda *_args, **_kwargs: status)

    snapshot = rc.ReviewCenterModel(
        tmp_path / "logs", output_dir=tmp_path / "review"
    ).snapshot(
        date(2026, 8, 31),
        5,
        today=date(2026, 9, 1),
    )

    assert guidance in snapshot.coverage
    assert snapshot.pack_state == "Not ready. 1 selected day needs attention."


def test_snapshot_uses_plural_for_multiple_day_issues(tmp_path, monkeypatch):
    _reports(monkeypatch)
    status = _status()
    status.day_statuses = (
        SimpleNamespace(day="2026-08-27", state="missing"),
        SimpleNamespace(day="2026-08-28", state="unready"),
    )
    status.ready = False
    monkeypatch.setattr(rc, "weekly_window_status", lambda *_args, **_kwargs: status)

    snapshot = rc.ReviewCenterModel(
        tmp_path / "logs", output_dir=tmp_path / "review"
    ).snapshot(
        date(2026, 8, 31),
        5,
        today=date(2026, 9, 1),
    )

    assert snapshot.pack_state == "Not ready. 2 selected days need attention."


def test_prepared_pack_returns_only_exact_private_complete_pack(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        rc,
        "weekly_window_status",
        lambda _log_dir, _end, days, **_kwargs: _status(
            pack_name=f"weekly_review_test_{days}d"
        ),
    )
    root = tmp_path / "review"
    pack = _private_pack(root)
    model = rc.ReviewCenterModel(tmp_path / "logs", output_dir=root)

    assert model.prepared_pack(date(2026, 8, 31), 5) == pack
    assert model.prepared_pack(date(2026, 8, 31), 7) is None


@pytest.mark.parametrize(
    "unsafe_part",
    (
        "missing_output",
        "output_file",
        "output_symlink",
        "output_mode",
        "missing_pack",
        "pack_file",
        "pack_symlink",
        "pack_mode",
        "missing_index",
        "index_directory",
        "index_symlink",
        "index_mode",
        "missing_prompt",
        "prompt_directory",
        "prompt_symlink",
        "prompt_mode",
    ),
)
def test_prepared_pack_rejects_missing_or_unsafe_paths(
    tmp_path,
    monkeypatch,
    unsafe_part,
):
    monkeypatch.setattr(rc, "weekly_window_status", lambda *_args, **_kwargs: _status())
    root = tmp_path / "review"

    if unsafe_part == "missing_output":
        pass
    elif unsafe_part == "output_file":
        root.write_text("not a directory")
        root.chmod(0o600)
    elif unsafe_part == "output_symlink":
        target = tmp_path / "real-review"
        _private_pack(target)
        root.symlink_to(target, target_is_directory=True)
    else:
        pack = _private_pack(root)
        index = pack / rc.INDEX_NAME
        prompt = pack / rc.PROMPT_NAME
        if unsafe_part == "output_mode":
            root.chmod(0o750)
        elif unsafe_part == "missing_pack":
            for path in pack.iterdir():
                path.unlink()
            pack.rmdir()
        elif unsafe_part == "pack_file":
            for path in pack.iterdir():
                path.unlink()
            pack.rmdir()
            pack.write_text("not a directory")
            pack.chmod(0o600)
        elif unsafe_part == "pack_symlink":
            for path in pack.iterdir():
                path.unlink()
            pack.rmdir()
            target = tmp_path / "real-pack"
            _private_pack(tmp_path / "other", target.name)
            pack.symlink_to(tmp_path / "other" / target.name, target_is_directory=True)
        elif unsafe_part == "pack_mode":
            pack.chmod(0o750)
        elif unsafe_part == "missing_index":
            index.unlink()
        elif unsafe_part == "index_directory":
            index.unlink()
            index.mkdir(mode=0o700)
        elif unsafe_part == "index_symlink":
            target = tmp_path / "index-target"
            target.write_text("{}")
            target.chmod(0o600)
            index.unlink()
            index.symlink_to(target)
        elif unsafe_part == "index_mode":
            index.chmod(0o640)
        elif unsafe_part == "missing_prompt":
            prompt.unlink()
        elif unsafe_part == "prompt_directory":
            prompt.unlink()
            prompt.mkdir(mode=0o700)
        elif unsafe_part == "prompt_symlink":
            target = tmp_path / "prompt-target"
            target.write_text("# Review")
            target.chmod(0o600)
            prompt.unlink()
            prompt.symlink_to(target)
        elif unsafe_part == "prompt_mode":
            prompt.chmod(0o644)

    model = rc.ReviewCenterModel(tmp_path / "logs", output_dir=root)
    assert model.prepared_pack(date(2026, 8, 31), 5) is None


def test_prepared_pack_rejects_foreign_ownership(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "weekly_window_status", lambda *_args, **_kwargs: _status())
    root = tmp_path / "review"
    _private_pack(root)
    monkeypatch.setattr(rc.os, "getuid", lambda: root.stat().st_uid + 1)

    model = rc.ReviewCenterModel(tmp_path / "logs", output_dir=root)
    assert model.prepared_pack(date(2026, 8, 31), 5) is None


@pytest.mark.parametrize(
    "problem",
    (
        "malformed_index",
        "wrong_format",
        "wrong_window",
        "wrong_file_names",
        "bad_file_digest",
        "wrong_day",
        "bad_output_digest",
        "bad_source_digest",
        "missing_workload",
        "workload_mode",
        "workload_hardlink",
        "index_hardlink",
        "prompt_hardlink",
        "unsafe_extra",
    ),
)
def test_prepared_pack_rejects_bad_structure_or_listed_files(
    tmp_path,
    monkeypatch,
    problem,
):
    monkeypatch.setattr(rc, "weekly_window_status", lambda *_args, **_kwargs: _status())
    root = tmp_path / "review"
    pack = _private_pack(root)
    index_path = pack / rc.INDEX_NAME
    prompt = pack / rc.PROMPT_NAME
    workloads = sorted(pack.glob("v3_pilot_*.md"))
    index = json.loads(index_path.read_text())

    if problem == "malformed_index":
        index_path.write_text("{")
    elif problem == "wrong_format":
        index["format"] = "wrong"
    elif problem == "wrong_window":
        index["window"]["end"] = "2026-08-30"
    elif problem == "wrong_file_names":
        index["files"].pop(workloads[0].name)
    elif problem == "bad_file_digest":
        index["files"][rc.PROMPT_NAME] = "not-a-digest"
    elif problem == "wrong_day":
        index["days"][0]["day"] = "2026-08-26"
    elif problem == "bad_output_digest":
        index["days"][0]["output"]["sha256"] = "1" * 64
    elif problem == "bad_source_digest":
        source = next(iter(index["days"][0]["sources"]))
        index["days"][0]["sources"][source] = "bad"
    elif problem == "missing_workload":
        workloads[0].unlink()
    elif problem == "workload_mode":
        workloads[0].chmod(0o640)
    elif problem == "workload_hardlink":
        target = tmp_path / "workload-target"
        workloads[0].replace(target)
        os.link(target, workloads[0])
    elif problem == "index_hardlink":
        target = tmp_path / "index-target"
        index_path.replace(target)
        os.link(target, index_path)
    elif problem == "prompt_hardlink":
        target = tmp_path / "prompt-target"
        prompt.replace(target)
        os.link(target, prompt)
    elif problem == "unsafe_extra":
        (pack / "unsafe-extra").symlink_to(tmp_path / "outside")
    if problem not in {"malformed_index", "index_hardlink"}:
        index_path.write_text(json.dumps(index))
        index_path.chmod(0o600)

    model = rc.ReviewCenterModel(tmp_path / "logs", output_dir=root)
    assert model.prepared_pack(date(2026, 8, 31), 5) is None


def test_prepared_pack_accepts_safe_user_redaction(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "weekly_window_status", lambda *_args, **_kwargs: _status())
    root = tmp_path / "review"
    pack = _private_pack(root)
    (pack / rc.PROMPT_NAME).write_text("# Redacted prompt\n")
    first_workload = sorted(pack.glob("v3_pilot_*.md"))[0]
    first_workload.write_text("[private text redacted]\n")
    for extra_name, text in (
        (".DS_Store", "Finder metadata"),
        ("REVIEW_PROMPT.md.backup", "Safe local backup"),
    ):
        extra = pack / extra_name
        extra.write_text(text)
        extra.chmod(0o600)

    model = rc.ReviewCenterModel(tmp_path / "logs", output_dir=root)
    assert model.prepared_pack(date(2026, 8, 31), 5) == pack


def test_prepared_pack_rejects_oversized_index_without_reading_it(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(rc, "weekly_window_status", lambda *_args, **_kwargs: _status())
    root = tmp_path / "review"
    pack = _private_pack(root)
    index_path = pack / rc.INDEX_NAME
    index_path.write_bytes(b"x" * (rc.MAX_REVIEW_INDEX_BYTES + 1))
    index_path.chmod(0o600)
    reads = []
    original_read = rc.os.read

    def tracked_read(fd, size):
        reads.append((fd, size))
        return original_read(fd, size)

    monkeypatch.setattr(rc.os, "read", tracked_read)
    model = rc.ReviewCenterModel(tmp_path / "logs", output_dir=root)

    assert model.prepared_pack(date(2026, 8, 31), 5) is None
    assert reads == []


def test_prepared_pack_reads_only_the_capped_index_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "weekly_window_status", lambda *_args, **_kwargs: _status())
    root = tmp_path / "review"
    pack = _private_pack(root)
    finder_extra = pack / ".DS_Store"
    finder_extra.write_bytes(b"f" * 4096)
    finder_extra.chmod(0o600)
    index_size = (pack / rc.INDEX_NAME).stat().st_size
    workload_bytes = sum(path.stat().st_size for path in pack.glob("v3_pilot_*.md"))
    assert workload_bytes > 0 and finder_extra.stat().st_size > 0
    bytes_read = []
    original_read = rc.os.read

    def tracked_read(fd, size):
        data = original_read(fd, size)
        bytes_read.append(len(data))
        return data

    monkeypatch.setattr(rc.os, "read", tracked_read)
    model = rc.ReviewCenterModel(tmp_path / "logs", output_dir=root)

    assert model.prepared_pack(date(2026, 8, 31), 5) == pack
    assert sum(bytes_read) == index_size


def test_prepared_pack_rejects_expected_fifo_without_blocking(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "weekly_window_status", lambda *_args, **_kwargs: _status())
    root = tmp_path / "review"
    pack = _private_pack(root)
    fifo = sorted(pack.glob("v3_pilot_*.md"))[0]
    fifo.unlink()
    os.mkfifo(fifo, 0o600)
    original_open = rc.os.open

    def guarded_open(path, flags, *args, **kwargs):
        if Path(path) == fifo:
            assert flags & os.O_NONBLOCK
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(rc.os, "open", guarded_open)
    model = rc.ReviewCenterModel(tmp_path / "logs", output_dir=root)

    assert model.prepared_pack(date(2026, 8, 31), 5) is None


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
        lambda *args, **kwargs: (
            calls.append(("outcome", args, kwargs)) or tmp_path / "outcomes.md"
        ),
    )
    model = rc.ReviewCenterModel(
        tmp_path / "logs",
        output_dir=tmp_path / "review",
        home=tmp_path / "home",
    )

    assert model.prepare(date(2026, 8, 31), 5) is result
    model.set_manual_pause(True)
    monkeypatch.setattr(model, "prepared_pack", lambda *_args: result.pack_dir)
    model.record_outcome(date(2026, 8, 31), 5, "tried", "saved time", "local")

    assert calls[0][0] == "prepare"
    assert calls[0][2]["days"] == 5
    assert calls[1] == ("pause", True, {"home": tmp_path / "home"})
    assert calls[2][0] == "outcome"
    assert calls[2][2]["output_dir"] == tmp_path / "review"
    assert calls[2][2]["days"] == 5


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


def _snapshot(
    *,
    can_prepare: bool,
    can_show: bool,
    health: str = "Logger is running.",
    pack_state: str | None = None,
    pack_status: str | None = None,
) -> rc.ReviewCenterSnapshot:
    return rc.ReviewCenterSnapshot(
        health=health,
        freshness="Fresh.",
        pause_state="Manual privacy pause is off.",
        manual_paused=False,
        can_toggle_pause=True,
        pack_state=pack_state
        or ("Ready." if can_prepare else "Review files are ready."),
        coverage="File checks do not prove full capture.",
        can_prepare=can_prepare,
        can_show=can_show,
        storage="Private storage.",
        capture_state="active",
        pack_status=pack_status or ("prepared" if can_show else "ready" if can_prepare else "unready"),
    )


@pytest.mark.skipif(not rc.APPKIT_AVAILABLE, reason="AppKit is unavailable")
def test_native_window_constructs_hidden_with_accessible_controls(tmp_path):
    from AppKit import NSAccessibilityHeadingRole, NSApplication

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
        assert (
            controller.value_field.accessibilityLabel() == "Weekly review value result"
        )
        assert controller.notes_field.accessibilityLabel() == "Weekly review notes"
        assert (
            controller.pack_warning.accessibilityLabel()
            == "Weekly pack privacy warning"
        )
        assert controller.step_one_heading.stringValue() == "1. Create review files"
        assert controller.step_two_heading.stringValue() == "2. Review the files"
        assert controller.step_three_heading.stringValue() == (
            "3. Record what happened"
        )
        assert (
            controller.step_one_heading.accessibilityRole()
            == NSAccessibilityHeadingRole
        )
        assert "does not analyze or send" in controller.limit_label.stringValue()
        assert "Closing or minimizing" in controller.review_pause_notice.stringValue()
        assert "may stay paused" in controller.review_pause_notice.stringValue()
        assert "trusted local tool" in controller.step_two_text.stringValue()
        assert "before using any online tool" in controller.step_two_text.stringValue()
        assert controller.pause_button.title() == "Turn on manual pause"
        assert [item.label() for item in controller.tab_view.tabViewItems()] == [
            "Daily status", "Weekly review"
        ]
        assert controller.tab_view.selectedTabViewItem().identifier() == "daily"
        assert controller.tab_view.selectedTabViewItem().initialFirstResponder() is controller.pause_button
        assert controller.pause_button.nextKeyView() is controller.refresh_button
        assert controller.refresh_button.nextKeyView() is controller.recovery_button
        assert controller.recovery_button.nextKeyView() is controller.tab_view
        controller.tab_view.selectTabViewItemAtIndex_(1)
        assert controller.tab_view.selectedTabViewItem().initialFirstResponder() is controller.end_picker
        assert controller.end_picker.nextKeyView() is controller.days_popup
        assert controller.notes_field.nextKeyView() is controller.record_button
        assert controller.record_button.nextKeyView() is controller.clear_draft_button
        assert controller.clear_draft_button.nextKeyView() is controller.show_results_button
        assert controller.show_results_button.nextKeyView() is controller.tab_view
        assert controller.action_status_label not in {
            controller.end_picker,
            controller.days_popup,
            controller.prepare_button,
            controller.show_button,
            controller.outcome_popup,
            controller.value_field,
            controller.notes_field,
            controller.record_button,
            controller.pause_button,
            controller.refresh_button,
        }
        assert controller.window.makeFirstResponder_(controller.prepare_button)
        controller._set_busy(True)
        assert controller.prepare_button.isEnabled() is False
        assert controller.window.firstResponder() is not controller.prepare_button
    finally:
        controller.window.orderOut_(None)


@pytest.mark.skipif(not rc.APPKIT_AVAILABLE, reason="AppKit is unavailable")
def test_guided_actions_enable_in_sequence_and_result_has_no_default(tmp_path):
    from AppKit import NSApplication

    NSApplication.sharedApplication()
    controller = rc.ReviewCenterWindowController.alloc().initWithModel_(
        rc.ReviewCenterModel(tmp_path / "logs", output_dir=tmp_path / "review")
    )
    try:
        assert rc.OUTCOME_VALUES == {
            "Found an idea to try": "accepted",
            "Tried a change": "tried",
            "No action": "ignored",
        }
        assert controller.outcome_popup.titleOfSelectedItem() == "Choose a result"
        assert controller._selected_outcome() is None
        controller._apply_snapshot(
            _snapshot(can_prepare=True, can_show=False),
            "Ready.",
        )
        assert controller.prepare_button.isEnabled() is True
        assert controller.show_button.isEnabled() is False
        assert controller.outcome_popup.isEnabled() is False
        assert controller.record_button.isEnabled() is False
        assert "Step 1" in controller.show_help_label.stringValue()

        controller._apply_snapshot(
            _snapshot(can_prepare=False, can_show=True),
            "Created.",
        )
        assert controller.prepare_button.isEnabled() is False
        assert controller.show_button.isEnabled() is True
        assert controller.outcome_popup.isEnabled() is True
        assert controller.record_button.isEnabled() is False
        assert "Choose a result" in controller.record_help_label.stringValue()

        controller.outcome_popup.selectItemWithTitle_("Found an idea to try")
        controller.outcomeAction_(None)
        assert controller._selected_outcome() == "accepted"
        assert controller.record_button.isEnabled() is True
        assert controller.record_help_label.stringValue() == (
            "Saves this result locally."
        )

        controller.outcome_popup.selectItemAtIndex_(0)
        controller.outcomeAction_(None)
        assert controller.record_button.isEnabled() is False
        assert controller.action_status_label.stringValue() == (
            "Choose a result before saving."
        )

        controller._apply_snapshot(
            _snapshot(
                can_prepare=False,
                can_show=False,
                pack_state="The selected review files are incomplete or unsafe.",
                pack_status="blocked",
            ),
            "Blocked.",
        )
        for label in (
            controller.prepare_help_label,
            controller.show_help_label,
            controller.record_help_label,
        ):
            assert "Use Recovery help" in label.stringValue()
            assert "Step 1 first" not in label.stringValue()
    finally:
        controller.window.orderOut_(None)


@pytest.mark.skipif(not rc.APPKIT_AVAILABLE, reason="AppKit is unavailable")
def test_show_in_finder_rechecks_pack_at_action_time(tmp_path, monkeypatch):
    from AppKit import NSApplication

    NSApplication.sharedApplication()
    model = rc.ReviewCenterModel(tmp_path / "logs", output_dir=tmp_path / "review")
    controller = rc.ReviewCenterWindowController.alloc().initWithModel_(model)
    shown = []
    safe_pack = tmp_path / "review" / "weekly_review_2026-08-27_2026-08-31_5d"
    monkeypatch.setattr(rc, "_show_review_prompt_in_finder", shown.append)
    try:
        controller._apply_snapshot(
            _snapshot(can_prepare=False, can_show=True),
            "Created.",
        )
        monkeypatch.setattr(model, "prepared_pack", lambda *_args, **_kwargs: safe_pack)
        controller.showReviewAction_(None)
        assert shown == [safe_pack / rc.PROMPT_NAME]

        monkeypatch.setattr(model, "prepared_pack", lambda *_args, **_kwargs: None)
        controller.showReviewAction_(None)
        assert shown == [safe_pack / rc.PROMPT_NAME]
        assert "missing, incomplete, or unsafe" in (
            controller.action_status_label.stringValue()
        )
    finally:
        controller.window.orderOut_(None)


@pytest.mark.skipif(not rc.APPKIT_AVAILABLE, reason="AppKit is unavailable")
def test_date_or_period_change_preserves_draft_and_original_window(tmp_path, monkeypatch):
    from AppKit import NSApplication

    NSApplication.sharedApplication()
    controller = rc.ReviewCenterWindowController.alloc().initWithModel_(
        rc.ReviewCenterModel(tmp_path / "logs", output_dir=tmp_path / "review")
    )
    refreshed = []
    monkeypatch.setattr(controller, "_start_refresh", lambda *args, **kwargs: refreshed.append(args))
    try:
        controller.tab_view.selectTabViewItemAtIndex_(1)
        controller._apply_snapshot(_snapshot(can_prepare=False, can_show=True), "Created.")
        original = controller.displayed_selection
        controller.outcome_popup.selectItemWithTitle_("Tried a change")
        controller.value_field.setStringValue_("Old value")
        controller.notes_field.setStringValue_("Old note")
        controller.end_picker.setDateValue_(controller._date_to_nsdate(original[0] - timedelta(days=1)))
        controller.selectionAction_(controller.end_picker)
        assert controller._selected_date() == original[0]
        controller.days_popup.selectItemAtIndex_(1)
        controller.selectionAction_(controller.days_popup)
        assert controller._selected_days() == original[1]
        assert controller.value_field.stringValue() == "Old value"
        assert controller.notes_field.stringValue() == "Old note"
        assert controller.outcome_popup.titleOfSelectedItem() == "Tried a change"
        assert "Save or clear this draft" in controller.action_status_label.stringValue()
        assert refreshed == []
        controller.clearDraftAction_(None)
        assert not controller._has_draft()
        controller.days_popup.selectItemAtIndex_(1)
        controller.selectionAction_(controller.days_popup)
        assert controller.displayed_selection == (original[0], 7)
        assert len(refreshed) == 1
    finally:
        controller.window.orderOut_(None)


@pytest.mark.skipif(not rc.APPKIT_AVAILABLE, reason="AppKit is unavailable")
def test_async_actions_restore_useful_keyboard_focus(tmp_path, monkeypatch):
    from AppKit import NSApplication

    class ImmediateThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    state = {
        "snapshot": _snapshot(can_prepare=True, can_show=False),
        "fail": False,
    }

    def snapshot(*_args, **_kwargs):
        if state["fail"]:
            raise RuntimeError("test error")
        return state["snapshot"]

    model = SimpleNamespace(
        snapshot=snapshot,
        prepare=lambda *_args, **_kwargs: SimpleNamespace(
            pack_dir=tmp_path / "review" / "pack"
        ),
        set_manual_pause=lambda _paused: None,
    )
    monkeypatch.setattr(rc.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(
        rc.AppHelper, "callAfter", lambda callback, *args: callback(*args)
    )
    NSApplication.sharedApplication()
    controller = rc.ReviewCenterWindowController.alloc().initWithModel_(model)
    try:
        controller._apply_snapshot(state["snapshot"], "Ready.")
        controller.refreshAction_(None)
        assert controller.window.firstResponder() is controller.refresh_button

        state["fail"] = True
        controller.refreshAction_(None)
        assert controller.window.firstResponder() is controller.refresh_button
        state["fail"] = False

        controller.tab_view.selectTabViewItemAtIndex_(1)
        state["snapshot"] = _snapshot(can_prepare=False, can_show=True)
        controller._apply_snapshot(
            _snapshot(can_prepare=True, can_show=False),
            "Ready.",
        )
        controller.prepareAction_(None)
        assert controller.window.firstResponder() is controller.show_button

        controller.tab_view.selectTabViewItemAtIndex_(0)
        controller.pauseAction_(None)
        assert controller.window.firstResponder() is controller.pause_button
    finally:
        controller.window.orderOut_(None)


@pytest.mark.skipif(not rc.APPKIT_AVAILABLE, reason="AppKit is unavailable")
def test_successful_result_save_maps_and_clears_fields(tmp_path, monkeypatch):
    from AppKit import NSApplication

    class ImmediateThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    calls = []
    safe_pack = tmp_path / "review" / "weekly_review_2026-08-27_2026-08-31_5d"
    model = SimpleNamespace(
        prepared_pack=lambda *_args, **_kwargs: safe_pack,
        record_outcome=lambda *args: calls.append(args),
    )
    monkeypatch.setattr(rc.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(
        rc.AppHelper, "callAfter", lambda callback, *args: callback(*args)
    )
    NSApplication.sharedApplication()
    controller = rc.ReviewCenterWindowController.alloc().initWithModel_(model)
    try:
        controller.tab_view.selectTabViewItemAtIndex_(1)
        controller._apply_snapshot(
            _snapshot(can_prepare=False, can_show=True),
            "Created.",
        )
        controller.outcome_popup.selectItemWithTitle_("Tried a change")
        controller.outcomeAction_(None)
        controller.value_field.setStringValue_("Saved time")
        controller.notes_field.setStringValue_("Kept it local")
        controller.recordOutcomeAction_(None)

        assert calls == [
            (
                controller._selected_date(),
                controller._selected_days(),
                "tried",
                "Saved time",
                "Kept it local",
            )
        ]
        assert controller.outcome_popup.titleOfSelectedItem() == "Choose a result"
        assert controller.value_field.stringValue() == ""
        assert controller.notes_field.stringValue() == ""
        assert controller.record_button.isEnabled() is False
        assert controller.window.firstResponder() is controller.show_results_button
    finally:
        controller.window.orderOut_(None)


@pytest.mark.skipif(not rc.APPKIT_AVAILABLE, reason="AppKit is unavailable")
def test_native_window_privacy_and_completed_day_limit_refresh(tmp_path):
    from AppKit import NSApplication

    NSApplication.sharedApplication()
    privacy = []
    controller = rc.ReviewCenterWindowController.alloc().initWithModel_pauseCallback_(
        rc.ReviewCenterModel(tmp_path / "logs"),
        privacy.append,
    )
    try:
        old_limit = controller.date_limit
        controller._set_window_privacy(True)
        controller._set_window_privacy(True)
        controller._apply_snapshot(
            _snapshot(can_prepare=True, can_show=False),
            "Updated.",
        )
        assert controller.health_label.stringValue() == "Logger is running."
        assert controller.capture_label.stringValue() == "Capture is paused: Review Center window."
        assert controller.pause_state_label.stringValue() == (
            "Manual privacy pause is off."
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
                can_show=False,
                storage="Private storage.",
            ),
            "Updated.",
        )
        assert controller.health_label.stringValue() == (
            "Logger is running, but health is degraded: invalid marker."
        )
        controller._apply_snapshot(
            _snapshot(
                can_prepare=True,
                can_show=False,
                health="Logger is not running.",
            ),
            "Updated.",
        )
        assert controller.health_label.stringValue() == "Logger is not running."
        controller.windowDidResignKey_(None)
        assert privacy == [True]
        controller.windowDidBecomeKey_(None)
        assert privacy == [True]
        controller.windowDidMiniaturize_(None)
        assert privacy == [True, False]
        controller.windowDidDeminiaturize_(None)
        assert privacy == [True, False, True]

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
    from AppKit import NSApplication, NSMakeRect

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
        controller.tab_view.selectTabViewItemAtIndex_(1)
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
                can_show=False,
                storage="Private storage.",
            ),
            "Selection updated.",
        )
        fields = [field for field, _notification in announced]
        assert controller.pack_state_label in fields
        assert controller.coverage_label in fields
        assert controller.scroll_view.hasVerticalScroller() is True
        minimum = controller.window.minSize()
        frame = controller.window.frame()
        controller.window.setFrame_display_(
            NSMakeRect(
                frame.origin.x,
                frame.origin.y,
                minimum.width,
                minimum.height,
            ),
            False,
        )
        controller.window.contentView().layoutSubtreeIfNeeded()
        controller._layout_scroll_content()
        assert (
            controller.scroll_document.frame().size.height
            >= controller.scroll_view.contentSize().height
        )
        assert controller.root_stack.fittingSize().width <= (
            controller.scroll_view.contentSize().width - 32
        )
        assert controller.scroll_document.isFlipped() is False
        controller._scroll_to_visual_top()
        expected_top = max(
            0,
            controller.scroll_document.frame().size.height
            - controller.scroll_view.contentSize().height,
        )
        assert controller.scroll_view.contentView().bounds().origin.y == pytest.approx(
            expected_top
        )
        assert controller.root_stack.hasAmbiguousLayout() is False
    finally:
        controller.window.orderOut_(None)


@pytest.mark.skipif(not rc.APPKIT_AVAILABLE, reason="AppKit is unavailable")
def test_runtime_show_close_and_exit_enforce_privacy(tmp_path, monkeypatch):
    monkeypatch.setattr(
        rc.ReviewCenterWindowController,
        "_start_refresh",
        lambda self, message="Status refreshed.", focus=None: None,
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
        expected_top = max(
            0,
            runtime.controller.scroll_document.frame().size.height
            - runtime.controller.scroll_view.contentSize().height,
        )
        assert (
            runtime.controller.scroll_view.contentView().bounds().origin.y
            == pytest.approx(expected_top)
        )
        runtime.controller.windowDidResignKey_(None)
        runtime.controller.windowDidBecomeKey_(None)
        assert privacy == [True]
        runtime.controller.windowDidMiniaturize_(None)
        assert privacy == [True, False]
        runtime.controller.windowDidDeminiaturize_(None)
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
        lambda self, message="Status refreshed.", focus=None: None,
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


@pytest.mark.parametrize("valid,manual,capture", [(False, False, False), (True, None, None), (False, True, True)])
def test_snapshot_keeps_unknown_runtime_state_explicit(tmp_path, monkeypatch, valid, manual, capture):
    _reports(monkeypatch)
    report = rc.health_report(tmp_path, date(2026, 9, 1))
    report.update(runtime_state_valid=valid, manual_paused=manual, capture_paused=capture)
    monkeypatch.setattr(rc, "health_report", lambda *_args, **_kwargs: report)
    monkeypatch.setattr(rc, "weekly_window_status", lambda *_args, **_kwargs: _status())
    snapshot = rc.ReviewCenterModel(tmp_path / "logs").snapshot(date(2026, 8, 31), 5)
    assert snapshot.capture_state == "unknown"
    assert snapshot.manual_paused is None
    assert snapshot.pause_state == "Manual privacy state is unverified."
    assert "active" not in rc._capture_status(snapshot.capture_state, (), False)
    assert rc._capture_status(snapshot.capture_state, (), True) == (
        "Capture is paused: Review Center window. Other capture state is unverified."
    )


def test_snapshot_shares_one_request_cache_and_keeps_independent_results(tmp_path, monkeypatch):
    _reports(monkeypatch)
    report = rc.health_report(tmp_path, date(2026, 9, 1))
    caches = []

    def health(*_args, inspections, **_kwargs):
        caches.append(inspections)
        return report

    def storage(*_args, inspections, **_kwargs):
        caches.append(inspections)
        raise OSError("captured private text must not be shown")

    def weekly(*_args, inspections, **_kwargs):
        caches.append(inspections)
        status = _status()
        status.day_statuses[0].quality = {
            "source_bytes": 2048, "workload_events": 12,
            "warnings": ("4 events have system context.",),
        }
        return status

    monkeypatch.setattr(rc, "health_report", health)
    monkeypatch.setattr(rc, "storage_report", storage)
    monkeypatch.setattr(rc, "weekly_window_status", weekly)
    snapshot = rc.ReviewCenterModel(tmp_path / "logs", output_dir=tmp_path / "out").snapshot(date(2026, 8, 31), 5)
    assert len(caches) == 3 and all(cache is caches[0] for cache in caches)
    assert snapshot.can_toggle_pause and snapshot.can_prepare
    assert snapshot.health == "Logger is running."
    assert "unavailable" in snapshot.storage
    assert "captured private text" not in str(snapshot)
    assert "12 observed workload events" in snapshot.quality
    assert "2026-08-27: 4 events have system context" in snapshot.quality
    assert snapshot.checked_at != "Not checked"


def test_snapshot_reports_incomplete_review_folders(tmp_path, monkeypatch):
    _reports(monkeypatch)
    monkeypatch.setattr(rc, "weekly_window_status", lambda *_args, **_kwargs: _status())
    monkeypatch.setattr(rc, "storage_report", lambda *_args, **_kwargs: {"incomplete_review_packs": 2})
    snapshot = rc.ReviewCenterModel(tmp_path / "logs", output_dir=tmp_path / "review").snapshot(date(2026, 8, 31), 5)
    assert "2 incomplete review folder(s)." in snapshot.problems


@pytest.mark.skipif(not rc.APPKIT_AVAILABLE, reason="AppKit is unavailable")
def test_native_status_separates_check_time_from_runtime_state_age(tmp_path):
    from AppKit import NSApplication
    from dataclasses import replace

    NSApplication.sharedApplication()
    controller = rc.ReviewCenterWindowController.alloc().initWithModel_(rc.ReviewCenterModel(tmp_path))
    try:
        controller._apply_snapshot(replace(
            _snapshot(can_prepare=False, can_show=False), checked_at="2026-09-05T12:03:00+02:00",
            runtime_state_updated_at="2026-09-05T12:00:00+02:00",
            runtime_state_age_seconds=180,
        ), "Refreshed.")
        text = controller.checked_label.stringValue()
        assert "Status checked: 2026-09-05T12:03:00+02:00" in text
        assert "Runtime state updated: 2026-09-05T12:00:00+02:00" in text
        assert "180 seconds old at check time" in text
    finally:
        controller.window.orderOut_(None)


@pytest.mark.skipif(not rc.APPKIT_AVAILABLE, reason="AppKit is unavailable")
@pytest.mark.parametrize("change", ["date", "period", "rollover", "clock_rollback", "same_window"])
def test_failed_refresh_keeps_only_matching_review_window_state(tmp_path, monkeypatch, change):
    from AppKit import NSApplication
    from dataclasses import replace

    pending = []

    class DeferredThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target

        def start(self):
            pending.append(self.target)

    def snapshot(*_args):
        raise OSError("synthetic private failure")

    monkeypatch.setattr(rc.threading, "Thread", DeferredThread)
    monkeypatch.setattr(rc.AppHelper, "callAfter", lambda callback, *args: callback(*args))
    NSApplication.sharedApplication()
    controller = rc.ReviewCenterWindowController.alloc().initWithModel_(SimpleNamespace(snapshot=snapshot))
    try:
        before = replace(_snapshot(can_prepare=False, can_show=True), can_show_results=True)
        controller._apply_snapshot(before, "Ready.")
        original = controller.displayed_selection
        if change == "date":
            controller.end_picker.setDateValue_(controller._date_to_nsdate(original[0] - timedelta(days=1)))
            controller.selectionAction_(controller.end_picker)
        elif change == "period":
            controller.days_popup.selectItemAtIndex_(1)
            controller.selectionAction_(controller.days_popup)
        else:
            if change != "same_window":
                controller._refresh_date_limit(original[0] + timedelta(days=2) if change == "rollover" else original[0])
            controller._start_refresh()
        changed = change != "same_window"
        assert controller.last_snapshot.can_show is (not changed)
        assert controller.show_button.isEnabled() is False
        if changed:
            assert controller.last_snapshot.pack_status == "unavailable"
            assert controller.pack_state_label.stringValue() != before.pack_state
            assert "not been checked" in controller.quality_label.stringValue()
        pending.pop(0)()
        assert controller.busy is False
        assert controller.show_button.isEnabled() is (not changed)
        assert controller.outcome_popup.isEnabled() is (not changed)
        assert controller.value_field.isEnabled() is (not changed)
        assert controller.prepare_button.isEnabled() is False
        assert controller.record_button.isEnabled() is False
        assert controller.last_snapshot.health == before.health
        assert controller.pause_button.isEnabled() is True
        assert controller.show_results_button.isEnabled() is True
        assert "synthetic private failure" not in controller.action_status_label.stringValue()
        assert controller.window.isVisible() is False
    finally:
        controller.window.orderOut_(None)


@pytest.mark.skipif(not rc.APPKIT_AVAILABLE, reason="AppKit is unavailable")
def test_native_refresh_discards_old_selection_after_clock_rollback(tmp_path, monkeypatch):
    from AppKit import NSApplication

    pending = []

    class DeferredThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target

        def start(self):
            pending.append(self.target)

    checked = []

    def snapshot(end, days):
        checked.append((end, days))
        return _snapshot(can_prepare=True, can_show=False)

    monkeypatch.setattr(rc.threading, "Thread", DeferredThread)
    monkeypatch.setattr(rc.AppHelper, "callAfter", lambda callback, *args: callback(*args))
    NSApplication.sharedApplication()
    controller = rc.ReviewCenterWindowController.alloc().initWithModel_(SimpleNamespace(snapshot=snapshot))
    try:
        original = controller.displayed_selection
        controller._start_refresh()
        controller._refresh_date_limit(original[0])
        assert controller._selected_date() == original[0] - timedelta(days=1)
        pending.pop(0)()
        assert controller.last_snapshot is None
        assert controller.busy is True
        assert controller.prepare_button.isEnabled() is False
        pending.pop(0)()
        assert checked == [original, (original[0] - timedelta(days=1), original[1])]
        assert controller.displayed_selection == checked[-1]
        assert controller.busy is False
        assert controller.prepare_button.isEnabled() is True
    finally:
        controller.window.orderOut_(None)


@pytest.mark.parametrize("days", [5, 7])
def test_model_integrates_real_reports_and_exact_window_results(tmp_path, days):
    log_dir = tmp_path / "logs"
    log_dir.mkdir(mode=0o700)
    malformed = log_dir / "daily_log_2026-02-31.md"
    malformed.write_text("synthetic content")
    malformed.chmod(0o600)
    end = date(2026, 9, 1)
    output_dir = tmp_path / "review"
    pack = _private_pack(output_dir, rc.weekly_pack_name(end, days), end=end, days=days)
    model = rc.ReviewCenterModel(log_dir, output_dir=output_dir, home=tmp_path / "home")

    snapshot = model.snapshot(end, days, today=end + timedelta(days=1))
    assert snapshot.capture_state == "stopped"
    assert snapshot.manual_paused is None
    assert "unavailable" not in snapshot.health
    assert "unavailable" not in snapshot.storage
    assert "1 file(s) with an invalid date." in snapshot.problems
    assert snapshot.pack_status == "prepared"
    assert snapshot.can_show is True
    assert snapshot.can_show_results is False

    destination = model.record_outcome(end, days, "accepted", "Useful action", "Synthetic note")
    row = json.loads(destination.read_text().splitlines()[-1][2:])
    assert row["window"] == {
        "start": (end - timedelta(days=days - 1)).isoformat(),
        "end": end.isoformat(), "calendar_days": days,
    }
    assert row["pack"] == pack.name
    assert model.saved_results() == destination
    assert model.snapshot(end, days, today=end + timedelta(days=1)).can_show_results is True


def test_prepared_pack_reopens_without_source_checks_and_results_are_private(tmp_path, monkeypatch):
    root = tmp_path / "review"
    pack = _private_pack(root)
    monkeypatch.setattr(rc, "weekly_window_status", lambda *_args, **_kwargs: pytest.fail("No source scan on reopen"))
    model = rc.ReviewCenterModel(tmp_path / "missing-sources", output_dir=root)
    assert model.prepared_pack(date(2026, 8, 31), 5) == pack
    result = root / rc.OUTCOMES_NAME
    result.write_text("private result text")
    result.chmod(0o600)
    monkeypatch.setattr(rc.os, "read", lambda *_args: pytest.fail("Do not read result payload for Finder"))
    assert model.saved_results() == result
    result.chmod(0o640)
    assert model.saved_results() is None


@pytest.mark.skipif(not rc.APPKIT_AVAILABLE, reason="AppKit is unavailable")
def test_native_tabs_keep_privacy_and_drafts_safe_at_rollover_and_text_limits(tmp_path):
    from AppKit import NSApplication

    NSApplication.sharedApplication()
    privacy = []
    controller = rc.ReviewCenterWindowController.alloc().initWithModel_pauseCallback_(
        rc.ReviewCenterModel(tmp_path / "logs"), privacy.append,
    )
    try:
        controller._set_window_privacy(True)
        controller.tab_view.selectTabViewItemAtIndex_(1)
        controller._apply_snapshot(_snapshot(can_prepare=False, can_show=True), "Ready.")
        original = controller.displayed_selection
        controller.outcome_popup.selectItemAtIndex_(1)
        controller.value_field.setStringValue_("x" * 4000)
        controller.controlTextDidChange_(None)
        assert controller.record_button.isEnabled()
        controller.value_field.setStringValue_("x" * 4001)
        controller.controlTextDidChange_(None)
        assert not controller.record_button.isEnabled()
        controller.recordOutcomeAction_(None)
        assert "4,000" in controller.action_status_label.stringValue()
        assert len(controller.value_field.stringValue()) == 4001
        controller._refresh_date_limit(original[0] + timedelta(days=2))
        assert controller._selected_date() == original[0]
        assert controller.displayed_selection == original
        controller.value_field.setStringValue_("kept")
        controller._refresh_date_limit(original[0])
        assert controller._selected_date() == original[0]
        assert controller.value_field.stringValue() == "kept"
        assert not controller.record_button.isEnabled()
        controller.tab_view.selectTabViewItemAtIndex_(0)
        controller.tab_view.selectTabViewItemAtIndex_(1)
        assert privacy == [True]
    finally:
        controller.window.orderOut_(None)
        controller._set_window_privacy(False)


@pytest.mark.skipif(not rc.APPKIT_AVAILABLE, reason="AppKit is unavailable")
def test_native_safe_finder_recovery_and_closed_error_messages(tmp_path, monkeypatch):
    from AppKit import NSApplication

    NSApplication.sharedApplication()
    selected = []
    safe_path = tmp_path / "results.md"
    model = SimpleNamespace(saved_results=lambda: safe_path)
    controller = rc.ReviewCenterWindowController.alloc().initWithModel_(model)
    monkeypatch.setattr(rc, "_show_review_prompt_in_finder", selected.append)
    monkeypatch.setattr(rc.AppHelper, "callAfter", lambda callback, *args: callback(*args))
    guide = tmp_path / "docs" / "V2_RECOVERY.md"
    guide.parent.mkdir()
    guide.write_text("Local recovery guide")
    monkeypatch.setattr(rc.sys, "_MEIPASS", str(tmp_path), raising=False)
    opened = []
    workspace = SimpleNamespace(openURL_=lambda url: opened.append(str(url.path())) or True)
    monkeypatch.setattr(rc, "NSWorkspace", SimpleNamespace(sharedWorkspace=lambda: workspace))
    try:
        controller.showResultsAction_(None)
        assert selected == [safe_path]
        model.saved_results = lambda: None
        controller.showResultsAction_(None)
        assert selected == [safe_path]
        controller.recoveryAction_(None)
        assert opened == [str(guide)]
        controller._finish_error("Outcome", rc.OperatorError("text_too_long"))
        assert "4,000" in controller.action_status_label.stringValue()
        controller._finish_error("Refresh", ValueError("captured private text"))
        assert "captured private text" not in controller.action_status_label.stringValue()
        assert "Recovery help" in controller.action_status_label.stringValue()
    finally:
        controller.window.orderOut_(None)
