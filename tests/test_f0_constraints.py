"""F0 constraint guards: launch/signing, keystrokes, privacy, artifact, bans."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import clean_markdown_log as cleaner
import interleaved_logger as il
from config import DEFAULT_SECURE_APPS

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _reset_logger_state(reset_logger_state):
    reset_logger_state()
    yield


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


# --- K1: launch + signing + TCC docs ---


def test_start_logger_uses_open_dash_w_on_app_bundle():
    text = _read("start_logger.sh")
    assert re.search(r"/usr/bin/open\s+-W\b", text)
    assert "ActivityLoggerNative.app" in text
    # Final launch must be open -W on $APP (bundle path set above; not bare open).
    active = [
        ln.strip()
        for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert any(
        re.search(r"/usr/bin/open\s+-W\b", ln) and ("$APP" in ln or "ActivityLoggerNative.app" in ln)
        for ln in active
    )


def test_start_logger_does_not_exec_inner_macos_binary():
    text = _read("start_logger.sh")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert "Contents/MacOS/ActivityLoggerNative" not in stripped
        assert not re.search(
            r"\bexec\b.*Contents/MacOS/ActivityLoggerNative", stripped
        )


def test_launch_agent_plist_invokes_start_logger_not_python():
    # Checked-in artifact is the @REPO@ template (F2); install script writes the live plist.
    text = _read("com.mk.activitylogger.plist.template")
    assert "<string>com.mk.activitylogger</string>" in text
    assert "@REPO@/start_logger.sh" in text
    assert "/bin/bash" in text
    assert "/Users/mk/scripts/activitylogger" not in text
    # ProgramArguments must not point at Python capture.
    assert "python3" not in text
    assert "interleaved_logger.py" not in text
    args = re.findall(
        r"<key>ProgramArguments</key>\s*<array>(.*?)</array>",
        text,
        flags=re.DOTALL,
    )
    assert args, "ProgramArguments missing"
    arg_block = args[0]
    assert "/bin/bash" in arg_block
    assert "start_logger.sh" in arg_block
    assert "python" not in arg_block.lower()
    install = _read("scripts/install_launch_agent.sh")
    assert "com.mk.activitylogger.plist.template" in install
    assert "resolve_repo_root.sh" in install
    assert "ACTIVITYLOGGER_REPO" in _read("scripts/lib/resolve_repo_root.sh")


def test_rebuild_script_invokes_sign_app():
    text = _read("scripts/rebuild_and_restart.sh")
    assert "scripts/sign_app.sh" in text or "sign_app.sh" in text
    # PyInstaller build must precede certificate signing.
    py_pos = text.lower().find("pyinstaller")
    sign_pos = text.find("sign_app.sh")
    assert py_pos != -1, "rebuild script must invoke PyInstaller"
    assert sign_pos != -1, "rebuild script must invoke sign_app.sh"
    assert py_pos < sign_pos, "sign_app.sh must run after PyInstaller"


def test_rebuild_script_fails_without_certificate_leaf():
    text = _read("scripts/rebuild_and_restart.sh")
    leaf_lib = _read("scripts/lib/require_certificate_leaf.sh")
    # Rebuild sources shared DR gate and fails when leaf is missing.
    assert "require_certificate_leaf.sh" in text
    assert "require_certificate_leaf" in text
    assert re.search(
        r"grep\s+-q\s+['\"]certificate leaf['\"]",
        leaf_lib,
    ), "expected grep -q 'certificate leaf' in require_certificate_leaf.sh"
    gate = re.search(
        r"if\s+!\s+DR=\"\$\(require_certificate_leaf\s+\"\$APP\"\)\".*?"
        r"exit\s+1",
        text,
        flags=re.DOTALL,
    )
    assert gate, "DR gate must exit 1 when certificate leaf is missing"


def test_tcc_docs_forbid_adhoc_and_python_launchd():
    agents = _read("AGENTS.md")
    tcc = _read("docs/MACOS_TCC.md")
    agents_l = agents.lower()
    tcc_l = tcc.lower()
    # open -W launch chain
    assert "open -W" in agents
    assert "open -W" in tcc
    # Forbid ad-hoc production signing
    assert "ad-hoc" in agents_l
    assert "ad-hoc" in tcc_l
    # Forbid launchd → Python capture
    assert "launchd" in agents_l and "python" in agents_l
    assert "never launchd" in agents_l or "launchd → python" in agents_l
    assert "python3 interleaved_logger.py" in tcc_l or (
        "do not change the launch agent back to" in tcc_l
        and "python3" in tcc_l
    )
    # Same-identity cert rebuild does not need TCC re-grant
    assert "re-grant" in agents_l
    assert "re-grant" in tcc_l
    assert "certificate" in agents_l and "certificate" in tcc_l
    assert (
        "do **not** ask for tcc re-grant" in agents_l
        or "do not ask for tcc re-grant" in agents_l
    )
    assert (
        "do not tell the user to re-grant tcc" in tcc_l
        or "should **not** need tcc refresh" in tcc_l
        or "should not need tcc refresh" in tcc_l
    )


# --- K2: keystrokes + hotkeys ---


def test_on_press_appends_printable_char():
    key = SimpleNamespace(char="a", vk=None)
    with patch.object(il, "sync_secure_field_from_focus", return_value=False):
        il.on_press(key)
    with il._lock:
        assert il._current_keystrokes == ["a"]


def test_on_press_encodes_enter_tab_esc_markers():
    pytest.importorskip("pynput")
    from pynput.keyboard import Key

    with patch.object(il, "sync_secure_field_from_focus", return_value=False):
        il.on_press(Key.enter)
        il.on_press(Key.tab)
        il.on_press(Key.esc)
    with il._lock:
        assert "\n[ENTER]\n" in il._current_keystrokes
        assert "[TAB]" in il._current_keystrokes
        assert "[ESC]" in il._current_keystrokes


def test_on_press_encodes_modifier_hotkey():
    pytest.importorskip("pynput")
    from pynput.keyboard import Key

    with patch.object(il, "sync_secure_field_from_focus", return_value=False):
        il.on_press(Key.cmd)
        il.on_press(SimpleNamespace(char="c", vk=None))
    with il._lock:
        assert "[CMD+C]" in il._current_keystrokes

    # Non-Shift mods join in sorted order (CMD before CTRL).
    with il._lock:
        il._current_keystrokes.clear()
        il._current_modifiers.clear()
    with patch.object(il, "sync_secure_field_from_focus", return_value=False):
        il.on_press(Key.ctrl)
        il.on_press(Key.cmd)
        il.on_press(SimpleNamespace(char="v", vk=None))
    with il._lock:
        assert "[CMD+CTRL+V]" in il._current_keystrokes


def test_on_press_noop_when_paused():
    il._set_pause(field=True)
    key = SimpleNamespace(char="x", vk=None)
    with patch.object(il, "sync_secure_field_from_focus", return_value=True):
        il.on_press(key)
    with il._lock:
        assert il._current_keystrokes == []


def test_recompute_clears_modifiers_on_pause_edge():
    with il._lock:
        il._current_modifiers.add("CMD")
        il._current_modifiers.add("CTRL")
        il._current_keystrokes.append("z")
    il._set_pause(field=True)
    with il._lock:
        assert il._current_modifiers == set()
        assert il._current_keystrokes == []


# --- K3: secure apps ---


def test_secure_apps_set_locked_baseline():
    assert set(DEFAULT_SECURE_APPS).issubset(il.SECURE_APPS)


def test_is_secure_app_name_positive_and_negative():
    positives = [
        ("1Password", "Vault"),
        ("Bitwarden", "Login"),
        ("Keychain Access", "Login Items"),
        ("KeePassXC", "Database"),
        ("LastPass", "Vault"),
        ("Passwords", "iCloud"),
        ("Safari", "Bitwarden — Login"),
    ]
    for app, title in positives:
        assert il._is_secure_app_name(app, title), f"expected secure: {app!r}/{title!r}"
    assert not il._is_secure_app_name("Safari", "Example")
    assert not il._is_secure_app_name("Terminal", "bash")


# --- K4: markdown artifact ---


def test_get_filepath_is_daily_markdown_only(tmp_path, monkeypatch):
    monkeypatch.setattr(il, "LOG_DIR", tmp_path)
    path = il._get_filepath()
    assert path.parent == tmp_path
    assert path.name.startswith("daily_log_")
    assert path.suffix == ".md"
    assert path.name.endswith(".md")
    assert ".jsonl" not in path.name
    assert ".sqlite" not in path.name


def test_log_dir_mode_is_0o700(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir(exist_ok=True)
    log_dir.chmod(0o755)
    monkeypatch.setattr(il, "LOG_DIR", log_dir)
    il._get_filepath()
    mode = log_dir.stat().st_mode & 0o777
    assert mode == 0o700


def test_no_jsonl_or_sqlite_writer_symbols_in_capture_module():
    src = _read("interleaved_logger.py")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in {"sqlite3"}
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in {"sqlite3"}
    # No production JSONL/SQLite daily-log writer symbols
    assert "sqlite3" not in src
    assert re.search(r"\.jsonl\b", src) is None
    assert "jsonlines" not in src.lower()
    assert "CREATE TABLE" not in src
    assert re.search(r"\bsqlite3\.(connect|Cursor)\b", src) is None


# --- K5: cleaner + prompt ---


def test_cleaner_module_entrypoint_remains():
    assert callable(cleaner.compress_repeated_lines_in_code_block)
    assert callable(cleaner.compress_traceback_blocks)
    assert callable(cleaner.main)


def test_gemini_prompt_file_exists():
    path = REPO / "prompts" / "gemini-automation-analysis.md"
    assert path.is_file()
    assert path.stat().st_size > 0


def test_cleaner_has_no_secret_redaction_pass():
    names = [n for n in dir(cleaner) if not n.startswith("_")]
    redactish = [n for n in names if "redact" in n.lower() or "secret" in n.lower()]
    assert redactish == [], f"unexpected redaction API: {redactish}"
    src = _read("clean_markdown_log.py")
    assert "secret_redaction" not in src.lower()
    assert "redact_secrets" not in src.lower()


# --- K6: process model ---


def test_capture_core_is_single_module_process_entry():
    spec = _read("ActivityLoggerNative.spec")
    assert "Analysis(" in spec
    # Analysis scripts list must be exactly the interleaved_logger capture entry.
    match = re.search(
        r"Analysis\(\s*\[([^\]]*)\]",
        spec,
        flags=re.DOTALL,
    )
    assert match, "Analysis([...]) scripts list missing"
    scripts = re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))
    assert scripts == ["interleaved_logger.py"], scripts


def test_no_second_capture_daemon_script_required():
    # F2: checked-in Launch Agent is the @REPO@ template only (no absolute root plist).
    assert list(REPO.glob("*.plist")) == [], "retire absolute root plists; use .plist.template"
    template = REPO / "com.mk.activitylogger.plist.template"
    assert template.is_file(), "missing Launch Agent template"
    text = template.read_text(encoding="utf-8")
    assert "<string>com.mk.activitylogger</string>" in text
    assert "@REPO@/start_logger.sh" in text
    # No second always-on capture agent in-repo.
    other = []
    for p in list(REPO.rglob("*.plist")) + list(REPO.rglob("*.plist.template")):
        if p.resolve() == template.resolve():
            continue
        body = p.read_text(encoding="utf-8")
        if "com.mk.activitylogger" in body and "Label" in body:
            other.append(p)
    assert other == [], f"extra capture Launch Agent plists: {other}"
    agents = _read("AGENTS.md").lower()
    readme = _read("README.md").lower() if (REPO / "README.md").exists() else ""
    docs = agents + "\n" + readme
    # Docs keep the single .app / open -W capture path; no second daemon required.
    assert "activityloggernative.app" in docs or "open -w" in docs
    assert "second capture" not in docs
    assert "always-on capture process" not in docs
    assert "media daemon" not in docs


# --- B1–B3: bans ---


def test_no_screen_recording_api_imports_in_capture_module():
    src = _read("interleaved_logger.py")
    banned = [
        "ScreenCaptureKit",
        "CGWindowListCreateImage",
        "CGDisplayCreateImage",
        "screencapture",
        "Quartz.CoreGraphics",
    ]
    for name in banned:
        assert name not in src, f"banned Screen Recording symbol present: {name}"


def test_no_audio_capture_pipeline_in_capture_module():
    src = _read("interleaved_logger.py")
    banned = [
        "sounddevice",
        "pyaudio",
        "AVAudioEngine",
        "AVCaptureDevice",
        "microphone",
        "wave.open",
    ]
    lower = src.lower()
    for name in banned:
        assert name.lower() not in lower, f"banned audio symbol present: {name}"


def test_no_ocr_pipeline_dependency_required_for_capture():
    src = _read("interleaved_logger.py")
    banned = ["pytesseract", "easyocr", "VNRecognizeTextRequest", "tesseract"]
    for name in banned:
        assert name not in src, f"banned OCR dependency present: {name}"
    req = REPO / "requirements.txt"
    if req.exists():
        req_text = req.read_text(encoding="utf-8").lower()
        assert "pytesseract" not in req_text
        assert "easyocr" not in req_text
