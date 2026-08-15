# macOS TCC, launchd, and ActivityLogger

**Audience:** future you / Cursor agents working in this repo.  
**Host observed:** macOS 27.0 (build 26A5388g, Tahoe-line), Darwin 27, arm64.

## The mistake (do not repeat)

Running the logger as:

```text
launchd → bash → /usr/bin/python3 (CLT Python.app) → pynput
```

and trying to “fix” input capture by adding Python / Terminal to
**Accessibility** or **Input Monitoring**.

That path fails on modern macOS even when Settings toggles look correct:

- `AXIsProcessTrusted()` stays `False`
- stderr: `This process is not trusted! Input event monitoring will not be possible…`
- Clipboard / ActivityWatch may still work (different APIs), which is misleading

## Why

1. **launchd does not inherit Terminal’s TCC grants.** Interactive Terminal ≠ Launch Agent.
2. **Tahoe-era macOS wants a real `.app` bundle** for Accessibility grants. Bare Mach-O /
   interpreter paths are often rejected or ineffective in System Settings.
3. **TCC keys on code identity (csreq), not “the script file”.**
   - Ad-hoc (`codesign --sign -`) → DR pinned to **cdhash** → **every rebuild** needs TCC re-grant.
   - Self-signed Code Signing cert → DR pinned to **certificate leaf** → rebuilds keep TCC.
4. **pynput’s trust check is Accessibility (`AXIsProcessTrusted`)**, not only Input Monitoring.

References (research, Aug 2026):

- Cron + pynput: grant the **scheduler** identity — [SO 73367162](https://stackoverflow.com/questions/73367162/input-event-monitoring-will-not-be-possible-until-it-is-added-to-accessibility)
- TCC cdhash trap / self-signed cert — [nick-liu.com](https://nick-liu.com/posts/tcc-cdhash-trap/)
- Tahoe: prefer `.app` + stable signing — [skhd CODE_SIGNING](https://github.com/jackielii/skhd.zig/blob/main/docs/CODE_SIGNING.md)
- Launch via Launch Services (`open`) — [cyberforks TCC post](https://blog.cyberforks.com/posts/tcc-code-signing-ai-agents/)

## Correct production setup

| Piece | Value |
|--------|--------|
| Binary | `dist/ActivityLoggerNative.app` |
| Launch Agent | `com.mk.activitylogger` → `start_logger.sh` → `open -W` the `.app` |
| TCC targets | **ActivityLoggerNative.app** in Accessibility **and** Input Monitoring |
| Rebuild | **`./scripts/rebuild_and_restart.sh`** (required) |
| Signing | `scripts/sign_app.sh` — identity `ActivityLogger Code Signing` (auto-created) |

### Canonical rebuild (always)

```bash
./scripts/rebuild_and_restart.sh
```

Steps inside (internal only — do not run as standalone operator steps):

1. PyInstaller build of `ActivityLoggerNative.spec` (only via this script)
2. `./scripts/sign_app.sh` (creates keychain identity + `.codesign/identity.p12` on first run)
3. Abort if `codesign -d -r-` lacks `certificate leaf`
4. `launchctl kickstart -k gui/$(id -u)/com.mk.activitylogger`

**Agents must use this script** after logger code changes. Bare PyInstaller alone is a process bug.

### Install / replace Launch Agent (paths)

Do not commit a machine-absolute `com.mk.activitylogger.plist`.  
Use the template and install script:

```bash
./scripts/install_launch_agent.sh
launchctl bootout gui/$(id -u)/com.mk.activitylogger 2>/dev/null || true
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.mk.activitylogger.plist
launchctl enable gui/$(id -u)/com.mk.activitylogger
launchctl kickstart -k gui/$(id -u)/com.mk.activitylogger
```

`start_logger.sh` resolves the repo from its own directory (or `ACTIVITYLOGGER_REPO`).

### Capture config (`config.toml`)

Defaults match the signed app. Optional operator file:

```bash
mkdir -p ~/.config/activitylogger
cp config.example.toml ~/.config/activitylogger/config.toml
chmod 700 ~/.config/activitylogger
chmod 600 ~/.config/activitylogger/config.toml
```

Edit feature flags in that file. Config loads once at process start.

| Change type | Action |
|-------------|--------|
| Config only | `launchctl kickstart -k gui/$(id -u)/com.mk.activitylogger` — **no** rebuild |
| Logger source / binary | `./scripts/rebuild_and_restart.sh` |

### First-time TCC (once per machine / once per new signing cert)

1. Run `./scripts/rebuild_and_restart.sh` so the `.app` is certificate-signed
2. System Settings → Privacy & Security → **Accessibility** → add the `.app`
3. Same under **Input Monitoring**
4. Type something; within ~30s `daily_log_*.md` should grow

After that, certificate-signed rebuilds with the **same** cert should **not** need TCC refresh.

### Optional Automation (browser URL capture only)

Base capture needs **Accessibility** + **Input Monitoring** only.
Default config keeps `features.browser_url_capture = false`. With the flag OFF, the logger
does **not** send Apple Events for URL read and should not prompt for Automation.

When `features.browser_url_capture = true` and the Apple Events path runs,
macOS may ask for **Automation** so ActivityLoggerNative can control Safari /
Chrome / other scriptable browsers.

1. Set `features.browser_url_capture = true` in `~/.config/activitylogger/config.toml`
2. Config-only: `launchctl kickstart -k gui/$(id -u)/com.mk.activitylogger`  
   (If the binary also changed, use `./scripts/rebuild_and_restart.sh` instead.)
3. Bring the browser to front; approve Automation prompts when shown
   (System Settings → Privacy & Security → **Automation** → ActivityLoggerNative)
4. Navigate to a new URL; within ~ one `window_check_sec`, the daily log gains a
   `> [URL]:` line

AX-only success for a browser may avoid an Automation prompt for that browser.
Chrome-family capture often needs Automation.
Screen Recording is **not** required and must not be used for URL capture.

### Verify signing (after every rebuild)

```bash
codesign -d -r- dist/ActivityLoggerNative.app
# GOOD:  certificate leaf = H"..."
# BAD:   designated => cdhash H"..."     # ad-hoc — will break TCC next time
```

Trust proof for capture: **keystrokes in the daily log**, not stderr silence
(`open -W` often does not attach app stderr to `launchd-stderr.log`).

## Anti-patterns

- Do not leave an ad-hoc-signed `.app` after a rebuild
- Do not tell the user to re-grant TCC after a successful certificate-signed rebuild
- Do not change the Launch Agent back to `python3 interleaved_logger.py`
- Do not grant only `/usr/bin/python3` / `Python.app` for launchd capture
- Do not `exec` `Contents/MacOS/ActivityLoggerNative` from the plist — use `open -W`
- Do not run Login Item **and** Launch Agent together (single-instance lock)

## Interactive debug

One-off Terminal run: `python3 interleaved_logger.py` (Terminal needs TCC). Not the Launch Agent path.
