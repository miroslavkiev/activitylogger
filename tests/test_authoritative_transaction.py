from __future__ import annotations

import base64
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

import analysis_log as al


DAY = date(2026, 8, 27)


def _records(
    payload: str = "work", *, day: date = DAY
) -> tuple[al.AnalysisRecord, ...]:
    captured = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).replace(
        hour=9
    )
    return (
        al.AnalysisRecord(
            heading="Editor - Task",
            kind="type",
            payload=payload,
            captured_at=captured,
            trigger="file_flush",
            section_captured_at=captured,
            section_start=True,
        ),
    )


def _log_dir(tmp_path: Path) -> Path:
    path = tmp_path / "logs"
    path.mkdir(mode=0o700, parents=True)
    return path


def _pending(log_dir: Path) -> Path:
    return log_dir / "analysis_shadow" / "authoritative_pending.json"


def _manifest(log_dir: Path) -> dict[str, object]:
    return json.loads(_pending(log_dir).read_bytes())


def _target(log_dir: Path, day: date, role: str) -> dict[str, object]:
    return next(
        target
        for target in _manifest(log_dir)["targets"]
        if target["day"] == day.isoformat() and target["role"] == role
    )


def test_prepare_owns_before_detach_and_commit_is_exact_and_occurrence_unique(tmp_path):
    log_dir = _log_dir(tmp_path)
    records = _records()

    assert al.prepare_authoritative_transaction(log_dir, ((DAY, records),), "test") == {
        DAY: "Editor - Task"
    }
    first_id = _manifest(log_dir)["transaction_id"]
    canonical = al.analysis_paths(log_dir, DAY)[0]
    assert _pending(log_dir).is_file()
    assert not canonical.exists()
    assert not al.intent_path(log_dir, DAY).exists()

    assert al.commit_authoritative_transaction(log_dir) == {DAY: "Editor - Task"}
    assert not _pending(log_dir).exists()
    assert (
        al.parse_records(
            canonical.read_text(encoding="utf-8"),
            day=DAY,
            expected_format=al.ANALYSIS_FORMAT_V2,
        )
        == records
    )
    assert al._intents_match_records(
        al.read_intents(al.intent_path(log_dir, DAY)), records
    )

    al.prepare_authoritative_transaction(log_dir, ((DAY, records),), "test")
    second_id = _manifest(log_dir)["transaction_id"]
    al.commit_authoritative_transaction(log_dir)
    intents = al.read_intents(al.intent_path(log_dir, DAY))
    assert first_id != second_id
    assert intents[0][0] != intents[1][0]
    assert al.validate_authoritative_day(log_dir, DAY) == "Editor - Task"


def test_recovery_replaces_an_exact_planned_partial_suffix(tmp_path):
    log_dir = _log_dir(tmp_path)
    records = _records("recover")
    al.prepare_authoritative_transaction(log_dir, ((DAY, records),), "test")
    canonical_target = next(
        target
        for target in _manifest(log_dir)["targets"]
        if target["role"] == "canonical"
    )
    canonical = al.analysis_paths(log_dir, DAY)[0]
    suffix = base64.b64decode(canonical_target["append_base64"])
    canonical.write_bytes(suffix[: len(suffix) // 2])
    os.chmod(canonical, 0o600)

    al.recover_authoritative_transaction(log_dir)

    assert canonical.stat().st_size == canonical_target["final_size"]
    assert al.validate_authoritative_day(log_dir, DAY) == "Editor - Task"
    assert not _pending(log_dir).exists()


def test_multi_day_partial_commit_recovers_every_target_once(tmp_path):
    log_dir = _log_dir(tmp_path)
    next_day = DAY + timedelta(days=1)
    groups = (
        (DAY, _records("first")),
        (next_day, _records("second", day=next_day)),
    )
    al.prepare_authoritative_transaction(log_dir, groups, "test")
    first_target = _target(log_dir, DAY, "canonical")
    al._apply_target(log_dir, first_target)

    assert al.recover_authoritative_transaction(log_dir) == {
        DAY: "Editor - Task",
        next_day: "Editor - Task",
    }
    assert al.recover_authoritative_transaction(log_dir) == {}
    for day, records in groups:
        parsed = al.parse_records(
            al.analysis_paths(log_dir, day)[0].read_text(encoding="utf-8"),
            day=day,
            expected_format=al.ANALYSIS_FORMAT_V2,
        )
        assert parsed == records


def test_partial_intent_recovers_after_canonical_is_exact_final(tmp_path):
    log_dir = _log_dir(tmp_path)
    al.prepare_authoritative_transaction(log_dir, ((DAY, _records()),), "test")
    canonical_target = _target(log_dir, DAY, "canonical")
    intent_target = _target(log_dir, DAY, "intent")
    al._apply_target(log_dir, canonical_target)
    intent_suffix = base64.b64decode(intent_target["append_base64"])
    intent = al.intent_path(log_dir, DAY)
    intent.parent.mkdir(mode=0o700, exist_ok=True)
    intent.write_bytes(intent_suffix[: len(intent_suffix) // 2])
    os.chmod(intent, 0o600)

    al.recover_authoritative_transaction(log_dir)

    assert al.validate_authoritative_day(log_dir, DAY) == "Editor - Task"
    assert len(al.read_intents(intent)) == 1


def test_exact_final_targets_are_idempotent_without_another_write(
    tmp_path, monkeypatch
):
    log_dir = _log_dir(tmp_path)
    al.prepare_authoritative_transaction(log_dir, ((DAY, _records()),), "test")
    for target in _manifest(log_dir)["targets"]:
        al._apply_target(log_dir, target)
    monkeypatch.setattr(
        al,
        "_write_all",
        lambda *_args: pytest.fail("exact final target was written again"),
    )

    assert al.commit_authoritative_transaction(log_dir) == {DAY: "Editor - Task"}
    assert not _pending(log_dir).exists()


def test_missing_planned_target_is_not_recreated_and_later_recovers(tmp_path):
    log_dir = _log_dir(tmp_path)
    al.prepare_authoritative_transaction(log_dir, ((DAY, _records("one")),), "test")
    al.commit_authoritative_transaction(log_dir)
    intent = al.intent_path(log_dir, DAY)
    original_intent = intent.read_bytes()
    al.prepare_authoritative_transaction(log_dir, ((DAY, _records("two")),), "test")
    intent.unlink()

    with pytest.raises(OSError, match="missing"):
        al.commit_authoritative_transaction(log_dir)

    assert not intent.exists()
    intent.write_bytes(original_intent)
    os.chmod(intent, 0o600)
    al.recover_authoritative_transaction(log_dir)
    parsed = al.parse_records(
        al.analysis_paths(log_dir, DAY)[0].read_text(encoding="utf-8"),
        day=DAY,
        expected_format=al.ANALYSIS_FORMAT_V2,
    )
    assert [record.payload for record in parsed] == ["one", "two"]


def test_recovery_fails_closed_for_an_unplanned_target_state(tmp_path):
    log_dir = _log_dir(tmp_path)
    al.prepare_authoritative_transaction(log_dir, ((DAY, _records()),), "test")
    canonical = al.analysis_paths(log_dir, DAY)[0]
    canonical.write_bytes(b"not a planned prefix")
    os.chmod(canonical, 0o600)

    with pytest.raises(OSError, match="planned state"):
        al.commit_authoritative_transaction(log_dir)

    assert canonical.read_bytes() == b"not a planned prefix"
    assert _pending(log_dir).is_file()


def test_partial_utf8_suffix_is_replaced_as_exact_bytes(tmp_path):
    log_dir = _log_dir(tmp_path)
    al.prepare_authoritative_transaction(log_dir, ((DAY, _records("café")),), "test")
    target = _target(log_dir, DAY, "canonical")
    suffix = base64.b64decode(target["append_base64"])
    split = suffix.index("é".encode("utf-8")) + 1
    canonical = al.analysis_paths(log_dir, DAY)[0]
    canonical.write_bytes(suffix[:split])
    os.chmod(canonical, 0o600)

    al.recover_authoritative_transaction(log_dir)

    assert "café" in canonical.read_text(encoding="utf-8")


def test_corrupt_unsafe_and_multiple_pending_artifacts_fail_closed(tmp_path):
    corrupt_dir = _log_dir(tmp_path / "corrupt")
    al.prepare_authoritative_transaction(corrupt_dir, ((DAY, _records()),), "test")
    document = _manifest(corrupt_dir)
    document["transaction_id"] = "0" * 32
    _pending(corrupt_dir).write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="digest"):
        al.recover_authoritative_transaction(corrupt_dir)
    assert _pending(corrupt_dir).exists()

    unsafe_dir = _log_dir(tmp_path / "unsafe")
    shadow = unsafe_dir / "analysis_shadow"
    shadow.mkdir(mode=0o700)
    source = unsafe_dir / "source"
    source.write_text("private", encoding="utf-8")
    _pending(unsafe_dir).symlink_to(source)
    with pytest.raises(OSError):
        al.recover_authoritative_transaction(unsafe_dir)
    assert _pending(unsafe_dir).is_symlink()

    multiple_dir = _log_dir(tmp_path / "multiple")
    al.prepare_authoritative_transaction(multiple_dir, ((DAY, _records()),), "test")
    parent = _pending(multiple_dir).parent
    (parent / ".authoritative_pending.json.one.tmp").write_bytes(b"one")
    (parent / ".authoritative_pending.json.two.tmp").write_bytes(b"two")
    with pytest.raises(OSError, match="multiple"):
        al.recover_authoritative_transaction(multiple_dir)
    assert _pending(multiple_dir).exists()

    orphan_dir = _log_dir(tmp_path / "orphan")
    orphan_shadow = orphan_dir / "analysis_shadow"
    orphan_shadow.mkdir(mode=0o700)
    orphan = orphan_shadow / ".authoritative_pending.json.publish.tmp"
    orphan.write_bytes(b"private")
    os.chmod(orphan, 0o600)
    with pytest.raises(OSError, match="orphan"):
        al.recover_authoritative_transaction(orphan_dir)
    assert orphan.exists()


def test_oversized_pending_manifest_fails_before_read(tmp_path):
    log_dir = _log_dir(tmp_path)
    pending = _pending(log_dir)
    pending.parent.mkdir(mode=0o700)
    with pending.open("wb") as handle:
        handle.truncate(al.MAX_PENDING_MANIFEST_BYTES + 1)
    os.chmod(pending, 0o600)

    with pytest.raises(OSError, match="size limit"):
        al.recover_authoritative_transaction(log_dir)

    assert pending.stat().st_size == al.MAX_PENDING_MANIFEST_BYTES + 1


def test_prepare_rejects_duplicate_and_mixed_cutover_groups(tmp_path):
    duplicate_dir = _log_dir(tmp_path / "duplicate")
    with pytest.raises(ValueError, match="repeats"):
        al.prepare_authoritative_transaction(
            duplicate_dir,
            ((DAY, _records("one")), (DAY, _records("two"))),
            "test",
        )
    assert not _pending(duplicate_dir).exists()

    mixed_dir = _log_dir(tmp_path / "mixed")
    with pytest.raises(ValueError, match="precedes"):
        al.prepare_authoritative_transaction(
            mixed_dir,
            ((DAY, _records()), (DAY - timedelta(days=1), _records())),
            "test",
        )
    assert not _pending(mixed_dir).exists()


def test_prepare_write_and_link_failures_leave_no_owner(tmp_path, monkeypatch):
    write_dir = _log_dir(tmp_path / "write")
    monkeypatch.setattr(
        al, "_write_all", lambda *_args: (_ for _ in ()).throw(OSError("write"))
    )
    with pytest.raises(OSError, match="write"):
        al.prepare_authoritative_transaction(write_dir, ((DAY, _records()),), "test")
    assert not al.authoritative_transaction_pending(write_dir)
    assert al._pending_temp_paths(write_dir) == ()

    monkeypatch.undo()
    link_dir = _log_dir(tmp_path / "link")
    monkeypatch.setattr(
        al.os, "link", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("link"))
    )
    with pytest.raises(OSError, match="link"):
        al.prepare_authoritative_transaction(link_dir, ((DAY, _records()),), "test")
    assert not al.authoritative_transaction_pending(link_dir)
    assert al._pending_temp_paths(link_dir) == ()


def test_post_link_fsync_and_unlink_failures_leave_one_recoverable_owner(
    tmp_path, monkeypatch
):
    fsync_dir = _log_dir(tmp_path / "fsync")
    real_fsync_directory = al._fsync_directory
    calls = 0

    def fail_second_directory_sync(path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("fsync")
        real_fsync_directory(path)

    monkeypatch.setattr(al, "_fsync_directory", fail_second_directory_sync)
    with pytest.raises(OSError, match="fsync"):
        al.prepare_authoritative_transaction(fsync_dir, ((DAY, _records()),), "test")
    assert al.authoritative_transaction_pending(fsync_dir)
    monkeypatch.setattr(al, "_fsync_directory", real_fsync_directory)
    assert al.recover_authoritative_transaction(fsync_dir) == {DAY: "Editor - Task"}

    unlink_dir = _log_dir(tmp_path / "unlink")
    real_unlink = Path.unlink
    failed = False

    def fail_publish_unlink(path, *args, **kwargs):
        nonlocal failed
        if path.name == ".authoritative_pending.json.publish.tmp" and not failed:
            failed = True
            raise OSError("unlink")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_publish_unlink)
    with pytest.raises(OSError, match="unlink"):
        al.prepare_authoritative_transaction(unlink_dir, ((DAY, _records()),), "test")
    assert al.authoritative_transaction_pending(unlink_dir)
    monkeypatch.setattr(Path, "unlink", real_unlink)
    assert al.recover_authoritative_transaction(unlink_dir) == {DAY: "Editor - Task"}


def test_prepare_rejects_a_wrong_format_canonical(tmp_path):
    log_dir = _log_dir(tmp_path)
    canonical = al.analysis_paths(log_dir, DAY)[0]
    canonical.write_text(
        f"# Work Log - {DAY.isoformat()}\n\n"
        f"> format: {al.ANALYSIS_FORMAT_V1}\n"
        "> generated locally by ActivityLogger test\n",
        encoding="utf-8",
    )
    os.chmod(canonical, 0o600)
    intent = al.intent_path(log_dir, DAY)
    intent.parent.mkdir(mode=0o700)
    intent.write_text("# ActivityLogger analysis trial intents\n<!-- header-end -->\n")
    os.chmod(intent, 0o600)

    with pytest.raises(ValueError, match="format"):
        al.prepare_authoritative_transaction(log_dir, ((DAY, _records()),), "test")

    assert not _pending(log_dir).exists()


def test_ready_proof_is_payload_free_and_bound_to_both_files(tmp_path):
    log_dir = _log_dir(tmp_path)
    al.prepare_authoritative_transaction(log_dir, ((DAY, _records()),), "test")
    al.commit_authoritative_transaction(log_dir)

    proof_path = al.publish_day_ready(log_dir, DAY)
    proof = json.loads(proof_path.read_bytes())
    assert set(proof) == al._READY_KEYS
    assert "work" not in proof_path.read_text(encoding="utf-8")
    assert al.validate_day_ready(log_dir, DAY)

    with al.analysis_paths(log_dir, DAY)[0].open("ab") as handle:
        handle.write(b"\n")
    assert not al.validate_day_ready(log_dir, DAY)
