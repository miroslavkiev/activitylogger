"""F2 config load tests (TC-F2-01 …)."""

from __future__ import annotations

import os
import stat
import sys
from dataclasses import fields
from pathlib import Path

import pytest

import config as cfg
import interleaved_logger as il
from config import DEFAULT_SECURE_APPS


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
    assert loaded.secure_apps == DEFAULT_SECURE_APPS
    assert loaded.unsafe_full_browser_urls is False
    assert loaded.ax_max_depth == 7
    assert loaded.activitywatch_enricher is True
    assert loaded.activitywatch_allow_remote is False
    assert loaded.browser_url_capture is False
    assert loaded.capture_triggers_enabled is False
    assert loaded.scroll_coalesce_enabled is False
    assert loaded.scroll_coalesce_ms == 400
    assert loaded.secure_app_check_sec == 0.15
    assert loaded.ax_max_children == 40
    assert loaded.ax_scan_debounce_sec == 3.0
    assert loaded.aw_backoff_sec == 45.0
    assert loaded.max_keystrokes == 2000
    assert loaded.max_events == 500
    assert loaded.max_sections == 200
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


def test_secure_apps_are_normalized_and_empty_entries_rejected(tmp_path):
    conf = _write_toml(
        tmp_path / "config.toml",
        '[privacy]\nsecure_apps = ["  VaultWarden  ", "PASSWORDS"]\n',
    )
    assert cfg.load_config(conf).secure_apps == ("vaultwarden", "passwords")

    _write_toml(conf, '[privacy]\nsecure_apps = ["vault", "   "]\n')
    with pytest.raises(cfg.ConfigError, match="non-empty"):
        cfg.load_config(conf)


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


@pytest.mark.parametrize(
    "body,key",
    [
        ("[timing]\ntyping_pause_sec = nan\n", "typing_pause_sec"),
        ("[timing]\nsecure_field_cache_sec = inf\n", "secure_field_cache_sec"),
        ("[timing]\nwindow_check_sec = 3601\n", "window_check_sec"),
        ("[buffers]\nmax_events = 100001\n", "max_events"),
    ],
)
def test_nonfinite_and_impractical_numbers_are_rejected(tmp_path, body, key):
    conf = _write_toml(tmp_path / "config.toml", body)
    with pytest.raises(cfg.ConfigError, match=key):
        cfg.load_config(conf)


def test_config_file_security_checks(tmp_path, monkeypatch):
    conf = _write_toml(tmp_path / "config.toml", "[timing]\nflush_interval_sec = 30\n")

    conf.chmod(0o666)
    with pytest.raises(cfg.ConfigError, match="writable"):
        cfg.load_config(conf)

    conf.chmod(0o644)
    warnings: list[str] = []
    cfg.load_config(conf, warn=warnings.append)
    assert any("readable" in warning for warning in warnings)

    monkeypatch.setattr(cfg.os, "getuid", lambda: conf.stat().st_uid + 1)
    with pytest.raises(cfg.ConfigError, match="owned"):
        cfg.load_config(conf)


def test_config_symlink_is_rejected(tmp_path):
    if not getattr(os, "O_NOFOLLOW", 0):
        pytest.skip("O_NOFOLLOW is unavailable")
    target = _write_toml(tmp_path / "target.toml", "[timing]\nflush_interval_sec = 30\n")
    link = tmp_path / "config.toml"
    link.symlink_to(target)
    with pytest.raises(cfg.ConfigError, match="unreadable"):
        cfg.load_config(link)


def test_log_dir_creation_and_existing_private_directory(tmp_path):
    log_dir = tmp_path / "new" / "logs"
    assert cfg.ensure_log_dir(log_dir) == log_dir
    assert stat.S_IMODE(log_dir.stat().st_mode) == 0o700
    assert cfg.ensure_log_dir(log_dir) == log_dir


def test_log_dir_rejects_symlink_file_shared_mode_and_foreign_owner(tmp_path, monkeypatch):
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(cfg.ConfigError, match="symlink"):
        cfg.ensure_log_dir(link)

    leaf = tmp_path / "leaf"
    leaf.write_text("not a directory", encoding="utf-8")
    with pytest.raises(cfg.ConfigError, match="not a directory"):
        cfg.ensure_log_dir(leaf)

    shared = tmp_path / "shared"
    shared.mkdir(mode=0o755)
    shared.chmod(0o755)
    with pytest.raises(cfg.ConfigError, match="refusing to chmod"):
        cfg.ensure_log_dir(shared)
    assert stat.S_IMODE(shared.stat().st_mode) == 0o755

    foreign = tmp_path / "foreign"
    foreign.mkdir(mode=0o700)
    monkeypatch.setattr(cfg.os, "getuid", lambda: foreign.stat().st_uid + 1)
    with pytest.raises(cfg.ConfigError, match="owned"):
        cfg.ensure_log_dir(foreign)


def test_activitywatch_requires_loopback_without_explicit_opt_in(tmp_path):
    conf = _write_toml(
        tmp_path / "config.toml",
        '[window_titles]\nactivitywatch_base_url = "https://collector.example"\n',
    )
    with pytest.raises(cfg.ConfigError, match="loopback"):
        cfg.load_config(conf)

    _write_toml(
        conf,
        "[window_titles]\n"
        'activitywatch_base_url = "https://collector.example"\n'
        "activitywatch_allow_remote = true\n",
    )
    assert cfg.load_config(conf).activitywatch_allow_remote is True


@pytest.mark.parametrize(
    "url",
    (
        "http://user@localhost:5600",
        "http://user:password@localhost:5600",
        "https://user:password@collector.example",
    ),
)
def test_activitywatch_rejects_userinfo_even_with_remote_opt_in(tmp_path, url):
    conf = _write_toml(
        tmp_path / "config.toml",
        "[window_titles]\n"
        f'activitywatch_base_url = "{url}"\n'
        "activitywatch_allow_remote = true\n",
    )
    with pytest.raises(cfg.ConfigError, match="userinfo"):
        cfg.load_config(conf)


def test_unsafe_flags_are_visible_in_warnings_and_startup_diagnostics(tmp_path):
    conf = _write_toml(
        tmp_path / "config.toml",
        "[privacy]\n"
        "unsafe_full_browser_urls = true\n"
        "[window_titles]\n"
        'activitywatch_base_url = "https://collector.example"\n'
        "activitywatch_allow_remote = true\n",
    )
    warnings: list[str] = []
    loaded = cfg.load_config(conf, warn=warnings.append)
    joined = "\n".join(warnings)
    assert "WARNING privacy.unsafe_full_browser_urls=true" in joined
    assert "WARNING window_titles.activitywatch_allow_remote=true" in joined

    diagnostics = cfg.startup_diag_line(loaded)
    assert "unsafe_full_browser_urls=True" in diagnostics
    assert "activitywatch_allow_remote=True" in diagnostics


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
    resolve_lib = (repo_root / "scripts" / "lib" / "resolve_repo_root.sh").read_text(
        encoding="utf-8"
    )
    assert 'REPO="${HOME}/scripts/activitylogger"' not in text
    assert "/Users/mk" not in text
    assert "resolve_repo_root.sh" in text
    assert "dirname" in text or "dirname" in resolve_lib
    assert "ACTIVITYLOGGER_REPO" in resolve_lib
    assert "open -W" in text


# --- TC-F2-15 (install template) ---


def test_tc_f2_15_install_template_substitution(tmp_path, monkeypatch):
    repo_root = Path(__file__).resolve().parents[1]
    template = repo_root / "com.mk.activitylogger.plist.template"
    install = repo_root / "scripts" / "install_launch_agent.sh"
    assert template.exists()
    assert install.exists()
    assert "@REPO@" in template.read_text(encoding="utf-8")

    install_text = install.read_text(encoding="utf-8")
    assert 'verify_activitylogger_app "$APP"' in install_text
    assert "render_launch_agent.py" in install_text

    # Rendering is independently testable in a clean checkout. The install
    # script retains strict app verification before invoking this renderer.
    out_plist = tmp_path / "com.mk.activitylogger.plist"
    import subprocess

    subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "render_launch_agent.py"),
            str(template),
            str(out_plist),
            str(repo_root),
        ],
        check=True,
        cwd=str(tmp_path),
    )
    body = out_plist.read_text(encoding="utf-8")
    repo_s = str(repo_root)
    assert repo_s in body
    assert "@REPO@" not in body
    assert f"{repo_s}/logs/launchd-stdout.log" in body
    assert f"{repo_s}/logs/launchd-stderr.log" in body
    assert f"{repo_s}/start_logger.sh" in body


def test_hardening_knobs_round_trip(tmp_path, monkeypatch):
    _clear_discovery_env(monkeypatch)
    conf = tmp_path / "config.toml"
    _write_toml(
        conf,
        "\n".join(
            [
                "[timing]",
                "secure_app_check_sec = 0.2",
                "[ax]",
                "ax_max_children = 12",
                "ax_scan_debounce_sec = 1.5",
                "[window_titles]",
                "aw_backoff_sec = 60",
                "[buffers]",
                "max_keystrokes = 500",
                "max_events = 50",
                "max_sections = 20",
                "",
            ]
        ),
    )
    loaded = cfg.load_config(conf)
    assert loaded.secure_app_check_sec == 0.2
    assert loaded.ax_max_children == 12
    assert loaded.ax_scan_debounce_sec == 1.5
    assert loaded.aw_backoff_sec == 60.0
    assert loaded.max_keystrokes == 500
    assert loaded.max_events == 50
    assert loaded.max_sections == 20
    il.apply_config(loaded)
    assert il.SECURE_APP_CHECK_SEC == 0.2
    assert il.AX_MAX_CHILDREN == 12
    assert il.AX_SCAN_DEBOUNCE_SEC == 1.5
    assert il.AW_BACKOFF_SEC == 60.0
    assert il.MAX_KEYSTROKES == 500
    assert il.MAX_EVENTS == 50
    assert il.MAX_SECTIONS == 20
    assert il._state.config is loaded
    assert il._APP_CONFIG is loaded


def test_buffers_max_keystrokes_floor(tmp_path, monkeypatch):
    _clear_discovery_env(monkeypatch)
    conf = tmp_path / "config.toml"
    _write_toml(conf, "[buffers]\nmax_keystrokes = 10\n")
    with pytest.raises(cfg.ConfigError, match="max_keystrokes"):
        cfg.load_config(conf)


def test_config_example_secure_apps_match_defaults(tmp_path, monkeypatch):
    """config.example.toml privacy.secure_apps matches DEFAULT_SECURE_APPS."""
    _clear_discovery_env(monkeypatch)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    example = Path(__file__).resolve().parents[1] / "config.example.toml"
    loaded = cfg.load_config(example)
    assert loaded.secure_apps == cfg.default_config(home=home).secure_apps
    assert loaded.secure_apps == DEFAULT_SECURE_APPS


def test_config_example_toml_matches_default_config(tmp_path, monkeypatch):
    """Repo-root config.example.toml matches default_config() (except config_path)."""
    _clear_discovery_env(monkeypatch)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    example = Path(__file__).resolve().parents[1] / "config.example.toml"
    loaded = cfg.load_config(example)
    expected = cfg.default_config(home=home)
    for f in fields(cfg.AppConfig):
        if f.name == "config_path":
            continue
        assert getattr(loaded, f.name) == getattr(expected, f.name), f.name
    assert loaded.config_path == example.resolve()
