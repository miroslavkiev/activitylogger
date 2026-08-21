# F2 configuration contract

**Status:** implemented and source-verified on 2026-08-21.

## Discovery and lifetime

Config loads once at process startup. Discovery order is:

1. Non-empty `ACTIVITYLOGGER_CONFIG`, which is fatal if missing.
2. `$XDG_CONFIG_HOME/activitylogger/config.toml`, or `~/.config/activitylogger/config.toml`.
3. `$ACTIVITYLOGGER_REPO/config.toml` for an explicit repo path.
4. A repository `config.toml` discovered from a non-frozen source run.
5. Built-in defaults.

There is no hot reload. Run `./scripts/restart_logger.sh` after a config-only edit so restart health includes fresh exact-process proof.

## Trust rules

Config is trusted operator input only when the opened target is a regular, current-user-owned file. The loader uses no-follow opening where available and rejects a final symlink, foreign ownership, and group or world write permission. Group or world readability produces a privacy warning and mode `600` remains the operator recommendation.

Malformed TOML, wrong types, invalid URLs, invalid secure-app entries, and out-of-range known values are fatal. Unknown sections and keys warn and are ignored for forward compatibility. Numbers must be finite.

## Canonical schema and defaults

```toml
[paths]
log_dir = "~/scripts/activitylogger/logs"

[timing]
window_check_sec = 5
flush_interval_sec = 30
typing_pause_sec = 0.5
secure_field_cache_sec = 0.35
diag_min_interval_sec = 30.0
secure_app_check_sec = 0.15

[privacy]
unsafe_full_browser_urls = false
secure_apps = ["1password", "bitwarden", "keychain", "keepass", "lastpass", "passwords"]

[ax]
ax_queue_maxsize = 16
ax_max_depth = 7
screen_compare_max_chars = 4000
ax_max_children = 40
ax_scan_debounce_sec = 3.0

[window_titles]
activitywatch_enricher = true
activitywatch_base_url = "http://localhost:5600"
activitywatch_allow_remote = false
aw_backoff_sec = 45.0

[buffers]
max_keystrokes = 2000
max_events = 500
max_sections = 200

[features]
browser_url_capture = false
capture_triggers_enabled = false
scroll_coalesce_enabled = false
scroll_coalesce_ms = 400
```

## Numeric bounds

| Key | Accepted range |
|---|---:|
| `timing.window_check_sec` | 1 to 3600 |
| `timing.flush_interval_sec` | 1 to 3600 |
| `timing.typing_pause_sec` | 0.05 to 60 |
| `timing.secure_field_cache_sec` | 0 to 60 |
| `timing.diag_min_interval_sec` | 1 to 86400 |
| `timing.secure_app_check_sec` | 0.05 to 60 |
| `ax.ax_queue_maxsize` | 1 to 10000 |
| `ax.ax_max_depth` | 1 to 32 |
| `ax.screen_compare_max_chars` | 100 to 1000000 |
| `ax.ax_max_children` | 1 to 10000 |
| `ax.ax_scan_debounce_sec` | 0 to 3600 |
| `window_titles.aw_backoff_sec` | 1 to 86400 |
| `buffers.max_keystrokes` | 100 to 1000000 |
| `buffers.max_events` | 10 to 100000 |
| `buffers.max_sections` | 10 to 10000 |
| `features.scroll_coalesce_ms` | 50 to 5000 |

## Network and URL safeguards

ActivityWatch requires an HTTP or HTTPS URL with a host and no user information. Without `activitywatch_allow_remote`, the host must be loopback. Enabling remote access emits a warning.

Safe browser URL capture is the default even when capture is enabled. It removes user information and fragments and neutralizes all query names and values. `unsafe_full_browser_urls = true` emits a warning and must be treated as a deliberate privacy-risk choice.

## Path overrides

`ACTIVITYLOGGER_LOG_DIR` may override the log directory. It must resolve to an absolute safe path. Signing password environment variables are unrelated to config and are rejected by the signing scripts.
