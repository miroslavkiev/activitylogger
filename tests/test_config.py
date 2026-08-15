"""F2 config load tests (TC-F2-01 …)."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

import config as cfg
import interleaved_logger as il


DEFAULT_SECURE = [
    "1password",
    "bitwarden",
    "keychain",
    "keepass",
    "lastpass",
    "passwords",
]


def _clear_discovery_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ACTIVITYLOGGER_CONFIG", raising=False)
    monkeypatch.delenv("ACTIVITYLOGGER_LOG_DIR", raising=False)
    monkeypatch.delenv("ACTIVITYLOGGER_REPO", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)


def _write_toml(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# --- TC-F2-01 ---


def test_tc_f2_01_defaults_when_file_missing(tmp_path, monkeypatch):
    _clear_discovery_env(monkeypatch)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(cfg.sys, "frozen", False, raising=False)
    # Avoid accidental repo config.toml via walk: point module file to empty tree
    fake_mod = tmp_path / "empty" / "config.py"
    fake_mod.parent.mkdir(parents=True)
    fake_mod.write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(cfg, "__file__", str(fake_mod))

    loaded = cfg.load_config()

    assert loaded.log_dir == home / "scripts" / "activitylogger" / "logs"
    assert loaded.window_check_sec == 5
    assert loaded.flush_interval_sec == 30
    assert loaded.typing_pause_sec == 0.5
    assert list(loaded.secure_apps) == DEFAULT_SECURE
    assert loaded.ax_max_depth == 7
    assert loaded.activitywatch_enricher is True
    assert loaded.browser_url_capture is False
    assert loaded.capture_triggers_enabled is False
    assert loaded.scroll_coalesce_enabled is False
    assert loaded.scroll_coalesce_ms == 400
    assert loaded.config_path is None


# --- TC-F2-02 ---


def test_tc_f2_02_xdg_overrides_log_dir(tmp_path, monkeypatch):
    _clear_discovery_env(monkeypatch)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    xdg = tmp_path / "xdg"
    mylogs = tmp_path / "mylogs"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    _write_toml(
        xdg / "activitylogger" / "config.toml",
        f'[paths]\nlog_dir = "{mylogs}"\n',
    )
    monkeypatch.setattr(cfg.sys, "frozen", False, raising=False)

    loaded = cfg.load_config()
    assert loaded.log_dir == mylogs.resolve()


# --- TC-F2-03 ---


def test_tc_f2_03_activitylogger_config_wins_over_xdg(tmp_path, monkeypatch):
    _clear_discovery_env(monkeypatch)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    _write_toml(
        xdg / "activitylogger" / "config.toml",
        "[timing]\nflush_interval_sec = 10\n",
    )
    alt = tmp_path / "alt.toml"
    _write_toml(alt, "[timing]\nflush_interval_sec = 99\n")
    monkeypatch.setenv("ACTIVITYLOGGER_CONFIG", str(alt))

    loaded = cfg.load_config()
    assert loaded.flush_interval_sec == 99


# --- TC-F2-04 ---


def test_tc_f2_04_tilde_expansion(tmp_path, monkeypatch):
    _clear_discovery_env(monkeypatch)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    conf = tmp_path / "c.toml"
    _write_toml(conf, '[paths]\nlog_dir = "~/custom/alogs"\n')
    monkeypatch.setenv("ACTIVITYLOGGER_CONFIG", str(conf))

    loaded = cfg.load_config()
    assert loaded.log_dir == home / "custom" / "alogs"


# --- TC-F2-05 ---


def test_tc_f2_05_invalid_toml_fatal(tmp_path, monkeypatch):
    _clear_discovery_env(monkeypatch)
    bad = tmp_path / "bad.toml"
    bad.write_text("[[[not valid", encoding="utf-8")
    monkeypatch.setenv("ACTIVITYLOGGER_CONFIG", str(bad))

    with pytest.raises(cfg.ConfigError, match="(?i)toml|parse"):
        cfg.load_config()


# --- TC-F2-06 ---


def test_tc_f2_06_validation_ranges(tmp_path, monkeypatch):
    _clear_discovery_env(monkeypatch)
    conf = tmp_path / "c.toml"
    _write_toml(conf, "[timing]\nwindow_check_sec = 0\n")
    monkeypatch.setenv("ACTIVITYLOGGER_CONFIG", str(conf))

    with pytest.raises(cfg.ConfigError, match="window_check_sec"):
        cfg.load_config()


# --- TC-F2-07 ---


def test_tc_f2_07_unknown_key_warning(tmp_path, monkeypatch):
    _clear_discovery_env(monkeypatch)
    conf = tmp_path / "c.toml"
    _write_toml(conf, "[features]\nnot_a_real_flag = true\n")
    monkeypatch.setenv("ACTIVITYLOGGER_CONFIG", str(conf))
    warnings: list[str] = []

    loaded = cfg.load_config(warn=warnings.append)
    assert loaded.browser_url_capture is False
    assert any("not_a_real_flag" in w for w in warnings)


# --- TC-F2-08 ---


def test_tc_f2_08_secure_apps_from_config(tmp_path, monkeypatch):
    _clear_discovery_env(monkeypatch)
    conf = tmp_path / "c.toml"
    _write_toml(conf, '[privacy]\nsecure_apps = ["vaultwarden"]\n')
    monkeypatch.setenv("ACTIVITYLOGGER_CONFIG", str(conf))

    loaded = cfg.load_config()
    il.apply_config(loaded)

    assert il._is_secure_app_name("Vaultwarden App", "x")
    assert not il._is_secure_app_name("1Password", "Vault")

    # Restore defaults for other tests
    il.apply_config(cfg.default_config(home=Path.home()))


# --- TC-F2-09 ---


def test_tc_f2_09_env_log_dir_override(tmp_path, monkeypatch):
    _clear_discovery_env(monkeypatch)
    conf = tmp_path / "c.toml"
    _write_toml(conf, '[paths]\nlog_dir = "/from/file"\n')
    monkeypatch.setenv("ACTIVITYLOGGER_CONFIG", str(conf))
    monkeypatch.setenv("ACTIVITYLOGGER_LOG_DIR", "/from/env")

    loaded = cfg.load_config()
    assert loaded.log_dir == Path("/from/env")


# --- TC-F2-10 ---


def test_tc_f2_10_explicit_empty_secure_apps(tmp_path, monkeypatch):
    _clear_discovery_env(monkeypatch)
    conf = tmp_path / "c.toml"
    _write_toml(conf, "[privacy]\nsecure_apps = []\n")
    monkeypatch.setenv("ACTIVITYLOGGER_CONFIG", str(conf))

    loaded = cfg.load_config()
    assert list(loaded.secure_apps) == []


# --- TC-F2-11 ---


def test_tc_f2_11_feature_key_round_trip(tmp_path, monkeypatch):
    _clear_discovery_env(monkeypatch)
    conf = tmp_path / "c.toml"
    _write_toml(
        conf,
        """
[window_titles]
activitywatch_enricher = false

[timing]
typing_pause_sec = 0.8

[features]
browser_url_capture = true
capture_triggers_enabled = true
scroll_coalesce_enabled = true
scroll_coalesce_ms = 100
""",
    )
    monkeypatch.setenv("ACTIVITYLOGGER_CONFIG", str(conf))

    loaded = cfg.load_config()
    assert loaded.activitywatch_enricher is False
    assert loaded.browser_url_capture is True
    assert loaded.capture_triggers_enabled is True
    assert loaded.scroll_coalesce_enabled is True
    assert loaded.scroll_coalesce_ms == 100
    assert loaded.typing_pause_sec == 0.8


# --- TC-F2-12 ---


def test_tc_f2_12_missing_activitylogger_config_path(tmp_path, monkeypatch):
    _clear_discovery_env(monkeypatch)
    monkeypatch.setenv("ACTIVITYLOGGER_CONFIG", str(tmp_path / "missing.toml"))

    with pytest.raises(cfg.ConfigError):
        cfg.load_config()


# --- TC-F2-16 ---


def test_tc_f2_16_frozen_skips_repo_walk(tmp_path, monkeypatch):
    _clear_discovery_env(monkeypatch)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    # Simulate a repo-like tree next to a fake config module
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "config.toml").write_text(
        "[timing]\nflush_interval_sec = 77\n", encoding="utf-8"
    )
    (repo / "ActivityLoggerNative.spec").write_text("# stub\n", encoding="utf-8")
    fake_mod = repo / "config.py"
    fake_mod.write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(cfg, "__file__", str(fake_mod))
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    loaded = cfg.load_config()
    assert loaded.flush_interval_sec == 30
    assert loaded.config_path is None


# --- TC-F2-17 ---


def test_tc_f2_17_unreadable_discovered_file_fatal(tmp_path, monkeypatch):
    _clear_discovery_env(monkeypatch)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    conf = xdg / "activitylogger" / "config.toml"
    _write_toml(conf, "[timing]\nflush_interval_sec = 30\n")
    conf.chmod(0o000)

    try:
        with pytest.raises(cfg.ConfigError):
            cfg.load_config()
    finally:
        conf.chmod(0o600)


# --- TC-F2-18 ---


def test_tc_f2_18_no_jsonl_sqlite_surface(tmp_path, monkeypatch):
    _clear_discovery_env(monkeypatch)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    fake_mod = tmp_path / "empty" / "config.py"
    fake_mod.parent.mkdir(parents=True)
    fake_mod.write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(cfg, "__file__", str(fake_mod))
    monkeypatch.setattr(cfg.sys, "frozen", False, raising=False)

    loaded = cfg.load_config()
    field_names = set(loaded.__dataclass_fields__)
    joined = " ".join(field_names).lower()
    assert "jsonl" not in joined
    assert "sqlite" not in joined
    for name in field_names:
        val = getattr(loaded, name)
        if isinstance(val, Path):
            assert val.suffix not in {".jsonl", ".sqlite", ".db"}
        if isinstance(val, str):
            assert ".jsonl" not in val.lower()
            assert ".sqlite" not in val.lower()


# --- TC-F2-19 ---


def test_tc_f2_19_scroll_coalesce_ms_floor(tmp_path, monkeypatch):
    _clear_discovery_env(monkeypatch)
    conf = tmp_path / "c.toml"
    _write_toml(conf, "[features]\nscroll_coalesce_ms = 10\n")
    monkeypatch.setenv("ACTIVITYLOGGER_CONFIG", str(conf))

    with pytest.raises(cfg.ConfigError, match="scroll_coalesce_ms"):
        cfg.load_config()


# --- Rejected aliases (MASTER §4 / F2 §6.2) ---


def test_rejected_aliases_are_unknown_not_primary(tmp_path, monkeypatch):
    """Aliases must not map to canonical fields; warn and keep defaults."""
    _clear_discovery_env(monkeypatch)
    conf = tmp_path / "alias.toml"
    _write_toml(
        conf,
        "\n".join(
            [
                "[timing]",
                "typing_pause_ms = 800",
                "file_flush_sec = 10",
                "[window_titles]",
                "aw_enabled = false",
                "aw_base_url = \"http://evil.example\"",
                "[activitywatch]",
                "enabled = false",
                "[features]",
                "browser_url_enabled = true",
            ]
        )
        + "\n",
    )
    monkeypatch.setenv("ACTIVITYLOGGER_CONFIG", str(conf))
    warnings: list[str] = []
    loaded = cfg.load_config(warn=warnings.append)
    assert loaded.typing_pause_sec == 0.5
    assert loaded.flush_interval_sec == 30
    assert loaded.activitywatch_enricher is True
    assert loaded.activitywatch_base_url == "http://localhost:5600"
    assert loaded.browser_url_capture is False
    joined = " ".join(warnings)
    assert "typing_pause_ms" in joined
    assert "file_flush_sec" in joined
    assert "aw_enabled" in joined or "activitywatch" in joined
    assert "browser_url_enabled" in joined


# --- TC-F2-14 (start_logger repo resolution) ---


def test_tc_f2_14_start_logger_repo_resolution(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "start_logger.sh"
    text = script.read_text(encoding="utf-8")
    assert 'REPO="${HOME}/scripts/activitylogger"' not in text
    assert "/Users/mk" not in text
    assert "dirname" in text
    assert "ACTIVITYLOGGER_REPO" in text
    assert "open -W" in text


# --- TC-F2-15 (install template) ---


def test_tc_f2_15_install_template_substitution(tmp_path, monkeypatch):
    repo_root = Path(__file__).resolve().parents[1]
    template = repo_root / "com.mk.activitylogger.plist.template"
    install = repo_root / "scripts" / "install_launch_agent.sh"
    assert template.exists()
    assert install.exists()
    assert "@REPO@" in template.read_text(encoding="utf-8")

    out_plist = tmp_path / "com.mk.activitylogger.plist"
    env = os.environ.copy()
    env["ACTIVITYLOGGER_REPO"] = "/tmp/al"
    env["ACTIVITYLOGGER_PLIST_OUT"] = str(out_plist)
    import subprocess

    subprocess.run(
        ["bash", str(install)],
        check=True,
        env=env,
        cwd=str(tmp_path),
    )
    body = out_plist.read_text(encoding="utf-8")
    assert "/tmp/al" in body
    assert "@REPO@" not in body
    assert "/Users/mk/scripts/activitylogger" not in body
    assert "/tmp/al/logs/launchd-stdout.log" in body
    assert "/tmp/al/logs/launchd-stderr.log" in body
