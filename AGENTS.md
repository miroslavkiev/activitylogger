# ActivityLogger — agent / maintainer notes

## Canonical runtime

Production = `dist/ActivityLoggerNative.app` via Launch Agent `start_logger.sh` → `open -W`.
Never launchd → Python for pynput on macOS 26+/27.

Full guide: [`docs/MACOS_TCC.md`](docs/MACOS_TCC.md)

## Config (operator)

```bash
mkdir -p ~/.config/activitylogger
cp config.example.toml ~/.config/activitylogger/config.toml
chmod 700 ~/.config/activitylogger
chmod 600 ~/.config/activitylogger/config.toml
```

Edit feature flags in `~/.config/activitylogger/config.toml`.

- **Config-only change:** `launchctl kickstart -k gui/$(id -u)/com.mk.activitylogger`  
  Do **not** run a full rebuild for config edits.
- **Logger source change:** `./scripts/rebuild_and_restart.sh`

## After code changes (mandatory)

```bash
./scripts/rebuild_and_restart.sh
```

This builds, **certificate-signs** (stable TCC — not ad-hoc cdhash), verifies
`certificate leaf` in the designated requirement, and kickstarts the agent.

Do **not** leave an ad-hoc-signed `.app`. Do **not** ask for TCC re-grant after a
successful certificate-signed rebuild with the same `ActivityLogger Code Signing` identity.

Smoke-check: typing updates `logs/daily_log_*.md` within ~30s.
