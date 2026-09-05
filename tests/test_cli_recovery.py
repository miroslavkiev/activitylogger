"""Local recovery commands must not depend on a working default config."""

import importlib
from datetime import date
from types import SimpleNamespace

import pytest

from config import ConfigError


SCRIPTS = (
    "activityloggerctl", "check_analysis_day", "export_weekly_review",
    "export_compact_analysis", "export_workload_v3_pilot", "review_analysis_trial",
)


def broken_config():
    raise ConfigError("private config content must never be shown")


@pytest.mark.parametrize("name", SCRIPTS)
def test_help_does_not_load_config(name, monkeypatch, capsys):
    module = importlib.import_module(f"scripts.{name}")
    monkeypatch.setattr(module, "load_config", broken_config)
    monkeypatch.setattr("sys.argv", [name, "--help"])
    with pytest.raises(SystemExit) as stopped:
        module.main()
    assert stopped.value.code == 0
    assert "usage:" in capsys.readouterr().out


def test_pause_resume_and_review_do_not_load_config(monkeypatch, tmp_path, capsys):
    from scripts import activityloggerctl as cli
    monkeypatch.setattr(cli, "load_config", broken_config)
    calls = []
    def pause(value):
        calls.append(value)
        return {"manual_paused": value, "capture_paused": value, "control_revision": 1}
    monkeypatch.setattr(cli, "set_manual_pause", pause)
    for command in ("pause", "resume"):
        monkeypatch.setattr("sys.argv", ["ctl", command])
        assert cli.main() == 0
    assert calls == [True, False]
    received = []
    def outcome(*args, **kwargs):
        received.append((args, kwargs))
        return tmp_path / "review_outcomes.jsonl"
    monkeypatch.setattr(cli, "record_review_outcome", outcome)
    monkeypatch.setattr("sys.argv", ["ctl", "review", "--week", "2026-09-04",
                                    "--days", "5", "--outcome", "tried"])
    assert cli.main() == 0
    assert received[0][1]["days"] == 5
    assert str(tmp_path) in capsys.readouterr().out


@pytest.mark.parametrize("name,function,arguments,result", [
    ("export_compact_analysis", "export_compact_day", [], dict(day="2026-09-04", output_file="compact.md", event_count=1, timeline_events=0, absolute_timeline_rows=0, delta_timeline_rows=0, analysis_bytes=100, output_bytes=50, byte_reduction=.5)),
    ("export_workload_v3_pilot", "export_workload_day", [], dict(day="2026-09-04", output_file="work.md", source_events=1, workload_events=1, exact_evidence_events=1, click_events=0, click_groups=0, summarized_markers=0, spans=1, analysis_bytes=100, output_bytes=50, byte_reduction=.5)),
    ("export_weekly_review", "create_weekly_review_pack", ["--end", "2026-09-04"], dict(start="2026-08-29", end="2026-09-04", days=7, pack_dir="pack", index_file="INDEX.md", source_events=1, workload_events=1)),
    ("review_analysis_trial", "validate_trial", [], dict(ok=True, event_count=1, byte_reduction=.5, coverage_hours=1, max_heartbeat_gap_hours=0, errors=[])),
])
def test_explicit_log_dir_bypasses_bad_config(name, function, arguments, result, monkeypatch, tmp_path):
    cli = importlib.import_module(f"scripts.{name}")
    monkeypatch.setattr(cli, "load_config", broken_config)
    calls = []
    def run(log_dir, *args, **kwargs):
        calls.append(log_dir)
        return SimpleNamespace(**result)
    monkeypatch.setattr(cli, function, run)
    monkeypatch.setattr("sys.argv", [name, "--log-dir", str(tmp_path), *arguments])
    assert cli.main() == 0
    assert calls == [tmp_path]


def test_check_explicit_path_and_bad_default_are_safe(monkeypatch, tmp_path, capsys):
    from scripts import check_analysis_day as cli
    monkeypatch.setattr(cli, "load_config", broken_config)
    def check(log_dir, day):
        assert log_dir == tmp_path
        assert day == date(2026, 9, 4)
        return cli.DayIntegrity("activitylogger-analysis-v2", True, True, False,
                                True, 1, 1, 0, 0, 0, 0)
    monkeypatch.setattr(cli, "check_day", check)
    monkeypatch.setattr("sys.argv", ["check", "--day", "2026-09-04", "--log-dir", str(tmp_path)])
    assert cli.main() == 0
    monkeypatch.setattr("sys.argv", ["check", "--day", "2026-09-04"])
    assert cli.main() == 1
    error = capsys.readouterr().err
    assert "config could not be loaded" in error
    assert "private config content" not in error


def test_check_cannot_report_success_during_pending_transaction(tmp_path):
    import analysis_log as analysis
    from scripts.check_analysis_day import check_day
    from tests.test_analysis_cutover_consumers import DAY, _write_v2_day
    log_dir = tmp_path / "logs"
    _write_v2_day(log_dir)
    assert check_day(log_dir, DAY).ok
    pending = analysis._pending_transaction_path(log_dir)
    pending.write_text("{}\n")
    pending.chmod(0o600)
    result = check_day(log_dir, DAY)
    assert result.strict_parse and result.intent_match
    assert not result.ok
