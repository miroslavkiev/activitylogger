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

Steps inside:

1. `pyinstaller ActivityLoggerNative.spec --noconfirm`
2. `./scripts/sign_app.sh` (creates keychain identity + `.codesign/identity.p12` on first run)
3. Abort if `codesign -d -r-` lacks `certificate leaf`
4. `launchctl kickstart -k gui/$(id -u)/com.mk.activitylogger`

**Agents must use this script** after logger code changes. Bare `pyinstaller` alone is a process bug.

### First-time TCC (once per machine / once per new signing cert)

1. Run `./scripts/rebuild_and_restart.sh` so the `.app` is certificate-signed
2. System Settings → Privacy & Security → **Accessibility** → add the `.app`
3. Same under **Input Monitoring**
4. Type something; within ~30s `daily_log_*.md` should grow

After that, certificate-signed rebuilds with the **same** cert should **not** need TCC refresh.

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
