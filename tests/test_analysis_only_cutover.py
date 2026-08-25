from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

import analysis_log as al
import interleaved_logger as il


@pytest.fixture(autouse=True)
def _reset(reset_logger_state, monkeypatch):
    reset_logger_state()
    monkeypatch.setattr(il, "recover_authoritative_transaction", lambda _root: {})
    yield


def _section(label: str, captured_at: datetime, *, kind: str = "type") -> dict:
    return {
        "heading": "App - Window",
        "events": [
            al.CapturedEvent(
                label,
                kind=kind,
                payload=label,
                captured_at=captured_at,
            )
        ],
        "timestamp": captured_at.strftime("%H:%M:%S"),
        "captured_at": captured_at,
        "_trigger": "timeline" if kind == "heartbeat" else "file_flush",
        "analysis_only": kind == "heartbeat",
    }


def test_cutover_boundary_uses_captured_local_day():
    assert il._analysis_only_day(date(2026, 8, 26)) is False
    assert il._analysis_only_day(date(2026, 8, 27)) is True


def test_legacy_writer_rejects_cutover_and_mismatched_captured_days(tmp_path, monkeypatch):
    monkeypatch.setattr(il, "LOG_DIR", tmp_path)
    before = datetime(2026, 8, 26, 23, 59, tzinfo=timezone.utc)
    cutover = datetime(2026, 8, 27, 9, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="legacy writer is disabled"):
        il._write_section_group(cutover.date(), cutover, [_section("blocked", cutover)])
    with pytest.raises(ValueError, match="legacy writer is disabled"):
        il._write_section_group(date(2026, 8, 26), cutover, [_section("blocked", cutover)])
    with pytest.raises(ValueError, match="legacy writer is disabled"):
        il._write_section_group(before.date(), before, [_section("blocked", cutover)])

    assert not list(tmp_path.glob("daily_log_*.md"))


def test_startup_validates_only_analysis_only_day(monkeypatch):
    calls = []
    monkeypatch.setattr(
        il,
        "recover_authoritative_transaction",
        lambda _root: {date(2026, 8, 27): "Recovered"},
    )
    monkeypatch.setattr(
        il,
        "validate_authoritative_day",
        lambda _root, day: calls.append(day) or "Validated",
    )
    before = date(2026, 8, 26)
    cutover = date(2026, 8, 27)

    assert il._initialize_analysis_persistence(before)[cutover] == "Recovered"
    assert calls == []
    assert il._initialize_analysis_persistence(cutover)[cutover] == "Validated"
    assert calls == [cutover]


def test_mixed_flush_routes_each_captured_day_once(monkeypatch):
    before = datetime(2026, 8, 26, 23, 59, tzinfo=timezone.utc)
    after = datetime(2026, 8, 27, 0, 1, tzinfo=timezone.utc)
    il._sections.extend([_section("before", before), _section("after", after)])
    calls: list[tuple[str, object]] = []

    def prepare_trial(_root, day, snapshots, _version):
        calls.append(("trial", day))
        return "trial", al.records_from_sections(snapshots)

    def prepare_authoritative(_root, groups, _version):
        assert [section["events"][0].payload for section in il._sections] == [
            "after",
        ]
        calls.append(
            (
                "prepare",
                [
                    (day, [record.payload for record in records])
                    for day, records in groups
                ],
            )
        )
        return {after.date(): "App - Window"}

    def commit(_root):
        assert il._sections == []
        calls.append(("commit", after.date()))
        return {after.date(): "App - Window"}

    monkeypatch.setattr(il, "prepare_trial_intent", prepare_trial)
    monkeypatch.setattr(il, "prepare_authoritative_transaction", prepare_authoritative)
    monkeypatch.setattr(il, "commit_authoritative_transaction", commit)
    monkeypatch.setattr(
        il,
        "_write_section_group",
        lambda day, _at, _sections: calls.append(("legacy", day)) or True,
    )
    monkeypatch.setattr(
        il,
        "_write_analysis_group",
        lambda day, _snapshots, _trial: calls.append(("shadow", day)),
    )
    monkeypatch.setattr(
        il,
        "publish_day_ready",
        lambda *_args: pytest.fail("ordinary records cannot publish readiness"),
    )

    assert il.flush_to_file() is True
    assert calls == [
        ("trial", before.date()),
        ("legacy", before.date()),
        ("shadow", before.date()),
        ("prepare", [(after.date(), ["after"])]),
        ("commit", after.date()),
    ]


def test_authoritative_prepare_failure_keeps_buffer_and_stops(monkeypatch):
    captured = datetime(2026, 8, 27, 12, tzinfo=timezone.utc)
    section = _section("kept", captured)
    il._sections.append(section)
    monkeypatch.setattr(
        il,
        "prepare_authoritative_transaction",
        lambda *_args: (_ for _ in ()).throw(OSError("prepare")),
    )
    monkeypatch.setattr(
        il,
        "_write_section_group",
        lambda *_args: pytest.fail("legacy writer used after cutover"),
    )
    monkeypatch.setattr(
        il,
        "_write_analysis_group",
        lambda *_args: pytest.fail("shadow writer used after cutover"),
    )

    assert il.flush_to_file() is False
    assert il._sections == [section]
    assert not il._fatal_worker_event.is_set()
    assert not il._stop_event.is_set()
    assert il.flush_to_file() is False
    assert il._sections == [section]
    assert not il._fatal_worker_event.is_set()
    assert not il._stop_event.is_set()


def test_prepare_failure_after_publication_detaches_owned_records(monkeypatch):
    after = datetime(2026, 8, 27, 0, 1, tzinfo=timezone.utc)
    il._sections.append(_section("owned", after))
    real_prepare = il.prepare_authoritative_transaction

    def fail_after_publication(*args):
        real_prepare(*args)
        raise OSError("after publication")

    monkeypatch.setattr(
        il,
        "prepare_authoritative_transaction",
        fail_after_publication,
    )
    monkeypatch.setattr(
        il,
        "_write_section_group",
        lambda *_args: pytest.fail("writer started after uncertain prepare"),
    )

    assert il.flush_to_file() is False
    assert il._sections == []
    assert al.authoritative_transaction_pending(il.LOG_DIR) is True
    assert il._fatal_worker_event.is_set()
    assert il._stop_event.is_set()
    al.recover_authoritative_transaction(il.LOG_DIR)
    canonical = al.analysis_paths(il.LOG_DIR, after.date())[0]
    assert [record.payload for record in al.parse_records(canonical.read_text())] == [
        "owned"
    ]


def test_mixed_prepare_failure_keeps_legacy_fsync_without_duplicate(
    tmp_path, monkeypatch
):
    before = datetime(2026, 8, 26, 23, 59, tzinfo=timezone.utc)
    after = datetime(2026, 8, 27, 0, 1, tzinfo=timezone.utc)
    il._sections.extend([_section("before", before), _section("after", after)])
    monkeypatch.setattr(
        il,
        "prepare_authoritative_transaction",
        lambda *_args: (_ for _ in ()).throw(OSError("before publication")),
    )

    assert il.flush_to_file() is False
    legacy = tmp_path / "logs" / "daily_log_2026-08-26.md"
    assert legacy.read_text().count("before") == 1
    assert [section["events"][0].payload for section in il._sections] == ["after"]
    assert not il._fatal_worker_event.is_set()

    monkeypatch.setattr(
        il, "prepare_authoritative_transaction", lambda *_args: {after.date(): None}
    )
    monkeypatch.setattr(
        il,
        "commit_authoritative_transaction",
        lambda _root: {after.date(): "App - Window"},
    )
    assert il.flush_to_file() is True
    assert legacy.read_text().count("before") == 1


def test_authoritative_commit_failure_never_restores_owned_records(monkeypatch):
    captured = datetime(2026, 8, 27, 12, tzinfo=timezone.utc)
    il._sections.append(_section("owned", captured))
    monkeypatch.setattr(
        il, "prepare_authoritative_transaction", lambda *_args: {captured.date(): None}
    )
    monkeypatch.setattr(
        il,
        "commit_authoritative_transaction",
        lambda _root: (_ for _ in ()).throw(OSError("commit")),
    )
    monkeypatch.setattr(
        il,
        "_write_section_group",
        lambda *_args: pytest.fail("legacy writer used after cutover"),
    )
    monkeypatch.setattr(
        il,
        "_write_analysis_group",
        lambda *_args: pytest.fail("shadow writer used after cutover"),
    )

    assert il.flush_to_file() is False
    assert il._sections == []
    assert il._fatal_worker_event.is_set()
    assert il._stop_event.is_set()


def test_mixed_commit_failure_keeps_legacy_records_durable(tmp_path, monkeypatch):
    before = datetime(2026, 8, 26, 23, 59, tzinfo=timezone.utc)
    after = datetime(2026, 8, 27, 0, 1, tzinfo=timezone.utc)
    il._sections.extend([_section("before", before), _section("owned", after)])
    monkeypatch.setattr(
        il,
        "prepare_authoritative_transaction",
        lambda *_args: {after.date(): None},
    )
    monkeypatch.setattr(
        il,
        "commit_authoritative_transaction",
        lambda _root: (_ for _ in ()).throw(OSError("commit")),
    )
    assert il.flush_to_file() is False
    legacy = tmp_path / "logs" / "daily_log_2026-08-26.md"
    assert "before" in legacy.read_text()
    assert il._sections == []
    assert il._fatal_worker_event.is_set()
    assert il._stop_event.is_set()


def test_mixed_legacy_failure_prevents_authoritative_detach(monkeypatch):
    before = datetime(2026, 8, 26, 23, 59, tzinfo=timezone.utc)
    after = datetime(2026, 8, 27, 0, 1, tzinfo=timezone.utc)
    il._sections.extend([_section("before", before), _section("after", after)])
    monkeypatch.setattr(
        il,
        "prepare_authoritative_transaction",
        lambda *_args: pytest.fail("authority started before legacy fsync"),
    )
    monkeypatch.setattr(
        il,
        "commit_authoritative_transaction",
        lambda _root: {after.date(): "App - Window"},
    )
    monkeypatch.setattr(il, "_write_section_group", lambda *_args: False)
    monkeypatch.setattr(il, "_write_analysis_group", lambda *_args: None)

    assert il.flush_to_file() is False
    assert [section["events"][0].payload for section in il._sections] == [
        "before",
        "after",
    ]
    assert not il._fatal_worker_event.is_set()


def test_mixed_legacy_exception_keeps_only_uncommitted_groups(tmp_path, monkeypatch):
    first = datetime(2026, 8, 25, 23, 59, tzinfo=timezone.utc)
    second = datetime(2026, 8, 26, 23, 59, tzinfo=timezone.utc)
    after = datetime(2026, 8, 27, 0, 1, tzinfo=timezone.utc)
    il._sections.extend(
        [
            _section("first", first),
            _section("second", second),
            _section("after", after),
        ]
    )
    real_write = il._write_section_group

    def write(day, captured_at, sections):
        if day == second.date():
            raise OSError("second day")
        return real_write(day, captured_at, sections)

    monkeypatch.setattr(il, "_write_section_group", write)
    monkeypatch.setattr(
        il,
        "prepare_authoritative_transaction",
        lambda *_args: pytest.fail("authority started before all legacy fsyncs"),
    )

    assert il.flush_to_file() is False
    assert "first" in (
        tmp_path / "logs" / "daily_log_2026-08-25.md"
    ).read_text()
    assert [section["events"][0].payload for section in il._sections] == [
        "second",
        "after",
    ]


def test_next_day_heartbeat_publishes_previous_day_after_commit(monkeypatch):
    heartbeat_at = datetime(2026, 8, 28, 0, 35, tzinfo=timezone.utc)
    il._sections.append(_section("", heartbeat_at, kind="heartbeat"))
    events: list[tuple[str, object]] = []
    monkeypatch.setattr(
        il,
        "prepare_authoritative_transaction",
        lambda *_args: events.append(("prepare", heartbeat_at.date())) or {},
    )
    monkeypatch.setattr(
        il,
        "commit_authoritative_transaction",
        lambda _root: events.append(("commit", heartbeat_at.date())) or {},
    )
    monkeypatch.setattr(
        il,
        "publish_day_ready",
        lambda _root, day: events.append(("ready", day)),
    )
    monkeypatch.setattr(il, "authoritative_day_present", lambda *_args: True)

    assert il.flush_to_file() is True
    assert events == [
        ("prepare", heartbeat_at.date()),
        ("commit", heartbeat_at.date()),
        ("ready", date(2026, 8, 27)),
    ]


def test_ready_proof_failure_stops_after_durable_commit(monkeypatch):
    heartbeat_at = datetime(2026, 8, 28, 0, 35, tzinfo=timezone.utc)
    il._sections.append(_section("", heartbeat_at, kind="heartbeat"))
    monkeypatch.setattr(
        il, "prepare_authoritative_transaction", lambda *_args: {}
    )
    monkeypatch.setattr(il, "commit_authoritative_transaction", lambda _root: {})
    monkeypatch.setattr(il, "authoritative_day_present", lambda *_args: True)
    monkeypatch.setattr(il, "validate_day_ready", lambda *_args: False)
    monkeypatch.setattr(
        il,
        "publish_day_ready",
        lambda *_args: (_ for _ in ()).throw(OSError("proof")),
    )

    assert il.flush_to_file() is False
    assert il._sections == []
    assert il._fatal_worker_event.is_set()
    assert il._stop_event.is_set()


def test_heartbeat_skips_ready_proof_for_absent_previous_day(monkeypatch):
    heartbeat_at = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    il._sections.append(_section("", heartbeat_at, kind="heartbeat"))
    monkeypatch.setattr(
        il, "prepare_authoritative_transaction", lambda *_args: {}
    )
    monkeypatch.setattr(il, "commit_authoritative_transaction", lambda _root: {})
    monkeypatch.setattr(il, "authoritative_day_present", lambda *_args: False)
    monkeypatch.setattr(
        il,
        "publish_day_ready",
        lambda *_args: pytest.fail("absent day cannot publish readiness"),
    )

    assert il.flush_to_file() is True
    assert not il._fatal_worker_event.is_set()
