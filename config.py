"""ActivityLogger TOML config (F2).

Load once at process start. Key names match docs/specs/F2-config.md §6.
"""

from __future__ import annotations

import ipaddress
import math
import os
import stat
import sys
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Optional
from urllib.parse import urlsplit

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - 3.9/3.10
    try:
        import tomli as tomllib  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise ModuleNotFoundError(
            "TOML support requires Python 3.11+ (tomllib) or the 'tomli' package"
        ) from exc


WarnFn = Callable[[str], None]


class ConfigError(Exception):
    """Fatal config discovery, parse, or validation error."""


DEFAULT_SECURE_APPS: tuple[str, ...] = (
    "1password",
    "bitwarden",
    "keychain",
    "keepass",
    "lastpass",
    "passwords",
)

# section -> allowed keys
_KNOWN_KEYS: dict[str, frozenset[str]] = {
    "paths": frozenset({"log_dir"}),
    "timing": frozenset(
        {
            "window_check_sec",
            "flush_interval_sec",
            "typing_pause_sec",
            "secure_field_cache_sec",
            "diag_min_interval_sec",
            "secure_app_check_sec",
        }
    ),
    "privacy": frozenset({"secure_apps", "unsafe_full_browser_urls"}),
    "ax": frozenset(
        {
            "ax_queue_maxsize",
            "ax_max_depth",
            "screen_compare_max_chars",
            "ax_max_children",
            "ax_scan_debounce_sec",
        }
    ),
    "window_titles": frozenset(
        {
            "activitywatch_enricher",
            "activitywatch_base_url",
            "activitywatch_allow_remote",
            "aw_backoff_sec",
        }
    ),
    "buffers": frozenset({"max_keystrokes", "max_events", "max_sections"}),
    "features": frozenset(
        {
            "browser_url_capture",
            "capture_triggers_enabled",
            "scroll_coalesce_enabled",
            "scroll_coalesce_ms",
        }
    ),
}


@dataclass(frozen=True)
class AppConfig:
    log_dir: Path
    window_check_sec: int
    flush_interval_sec: int
    typing_pause_sec: float
    secure_field_cache_sec: float
    diag_min_interval_sec: float
    secure_app_check_sec: float
    secure_apps: tuple[str, ...]
    unsafe_full_browser_urls: bool
    ax_queue_maxsize: int
    ax_max_depth: int
    screen_compare_max_chars: int
    ax_max_children: int
    ax_scan_debounce_sec: float
    activitywatch_enricher: bool
    activitywatch_base_url: str
    activitywatch_allow_remote: bool
    aw_backoff_sec: float
    max_keystrokes: int
    max_events: int
    max_sections: int
    browser_url_capture: bool
    capture_triggers_enabled: bool
    scroll_coalesce_enabled: bool
    scroll_coalesce_ms: int
    config_path: Optional[Path] = None


def _resolve_home() -> Path:
    base = os.environ.get("HOME") or str(Path.home())
    if not Path(base).exists():
        try:
            import pwd

            base = pwd.getpwuid(os.getuid()).pw_dir
        except Exception:
            base = "/tmp"
    return Path(base)


def default_config(*, home: Optional[Path] = None) -> AppConfig:
    """Built-in defaults matching pre-F2 constants (F2 §6.2)."""
    base = home if home is not None else _resolve_home()
    return AppConfig(
        log_dir=base / "scripts" / "activitylogger" / "logs",
        window_check_sec=5,
        flush_interval_sec=30,
        typing_pause_sec=0.5,
        secure_field_cache_sec=0.35,
        diag_min_interval_sec=30.0,
        secure_app_check_sec=0.15,
        secure_apps=DEFAULT_SECURE_APPS,
        unsafe_full_browser_urls=False,
        ax_queue_maxsize=16,
        ax_max_depth=7,
        screen_compare_max_chars=4000,
        ax_max_children=40,
        ax_scan_debounce_sec=3.0,
        activitywatch_enricher=True,
        activitywatch_base_url="http://localhost:5600",
        activitywatch_allow_remote=False,
        aw_backoff_sec=45.0,
        max_keystrokes=2000,
        max_events=500,
        max_sections=200,
        browser_url_capture=False,
        capture_triggers_enabled=False,
        scroll_coalesce_enabled=False,
        scroll_coalesce_ms=400,
        config_path=None,
    )


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _xdg_config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "activitylogger" / "config.toml"
    return _resolve_home() / ".config" / "activitylogger" / "config.toml"


def _find_repo_config() -> Optional[Path]:
    """Walk parents from this module for repo config.toml (source runs only)."""
    start = Path(__file__).resolve().parent
    for directory in [start, *start.parents]:
        candidate = directory / "config.toml"
        if not candidate.is_file():
            continue
        if (directory / "ActivityLoggerNative.spec").exists() or (directory / ".git").exists():
            return candidate
    return None


def discover_config_path() -> Optional[Path]:
    """Resolve one config file path per F2 §7.1. None means defaults only."""
    env_path = os.environ.get("ACTIVITYLOGGER_CONFIG")
    if env_path is not None and env_path.strip() != "":
        path = Path(env_path).expanduser()
        if not path.is_file():
            raise ConfigError(f"ACTIVITYLOGGER_CONFIG is set but missing or not a file: {path}")
        return path

    xdg = _xdg_config_path()
    if xdg.is_file():
        return xdg

    repo_env = os.environ.get("ACTIVITYLOGGER_REPO")
    if repo_env:
        repo_cfg = Path(repo_env).expanduser() / "config.toml"
        if repo_cfg.is_file():
            return repo_cfg

    if not _is_frozen():
        found = _find_repo_config()
        if found is not None:
            return found

    return None


def _expand_log_dir(raw: str) -> Path:
    text = str(raw).strip()
    if text.startswith("~/") or text == "~":
        path = _resolve_home() / text[2:] if text.startswith("~/") else _resolve_home()
    else:
        path = Path(text).expanduser()
    if not path.is_absolute():
        raise ConfigError(f"paths.log_dir must be absolute after expansion, got: {path}")
    return path


def _require_bool(section: str, key: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{section}.{key} must be a TOML boolean, got {type(value).__name__}")
    return value


def _require_number(section: str, key: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{section}.{key} must be a number, got {type(value).__name__}")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ConfigError(f"{section}.{key} must be finite") from exc
    if not math.isfinite(number):
        raise ConfigError(f"{section}.{key} must be finite")
    return number


def _require_int(section: str, key: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{section}.{key} must be a number, got {type(value).__name__}")
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        raise ConfigError(f"{section}.{key} must be an integer")
    return int(value)


def _require_str(section: str, key: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{section}.{key} must be a string, got {type(value).__name__}")
    return value


def _collect_unknown(data: Mapping[str, Any], warn: WarnFn) -> None:
    unknown: list[str] = []
    for section, body in data.items():
        if not isinstance(body, Mapping):
            unknown.append(str(section))
            continue
        allowed = _KNOWN_KEYS.get(section)
        if allowed is None:
            for key in body:
                unknown.append(f"{section}.{key}")
            continue
        for key in body:
            if key not in allowed:
                unknown.append(f"{section}.{key}")
    if unknown:
        warn(f"config: unknown keys ignored: {', '.join(sorted(unknown))}")


def _validate(cfg: AppConfig) -> None:
    bounds = (
        ("timing.window_check_sec", cfg.window_check_sec, 1, 3600),
        ("timing.flush_interval_sec", cfg.flush_interval_sec, 1, 3600),
        ("timing.typing_pause_sec", cfg.typing_pause_sec, 0.05, 60),
        ("timing.secure_field_cache_sec", cfg.secure_field_cache_sec, 0, 60),
        ("timing.diag_min_interval_sec", cfg.diag_min_interval_sec, 1, 86400),
        ("timing.secure_app_check_sec", cfg.secure_app_check_sec, 0.05, 60),
        ("ax.ax_queue_maxsize", cfg.ax_queue_maxsize, 1, 10000),
        ("ax.ax_max_depth", cfg.ax_max_depth, 1, 32),
        ("ax.screen_compare_max_chars", cfg.screen_compare_max_chars, 100, 1000000),
        ("ax.ax_max_children", cfg.ax_max_children, 1, 10000),
        ("ax.ax_scan_debounce_sec", cfg.ax_scan_debounce_sec, 0, 3600),
        ("window_titles.aw_backoff_sec", cfg.aw_backoff_sec, 1, 86400),
        ("buffers.max_keystrokes", cfg.max_keystrokes, 100, 1000000),
        ("buffers.max_events", cfg.max_events, 10, 100000),
        ("buffers.max_sections", cfg.max_sections, 10, 10000),
        ("features.scroll_coalesce_ms", cfg.scroll_coalesce_ms, 50, 5000),
    )
    for name, value, minimum, maximum in bounds:
        try:
            valid = math.isfinite(float(value)) and minimum <= value <= maximum
        except (TypeError, ValueError, OverflowError):
            valid = False
        if not valid:
            raise ConfigError(f"{name} must be in {minimum}..{maximum}")
    url = cfg.activitywatch_base_url.strip()
    if not url:
        raise ConfigError("window_titles.activitywatch_base_url must be non-empty")
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
    except ValueError as exc:
        raise ConfigError("window_titles.activitywatch_base_url is invalid") from exc
    if parsed.scheme not in {"http", "https"} or not host:
        raise ConfigError(
            "window_titles.activitywatch_base_url must be an HTTP(S) URL with a host"
        )
    if parsed.username is not None or parsed.password is not None:
        raise ConfigError(
            "window_titles.activitywatch_base_url must not contain userinfo"
        )
    if not cfg.activitywatch_allow_remote:
        normalized_host = host.casefold().rstrip(".")
        try:
            is_loopback = ipaddress.ip_address(normalized_host).is_loopback
        except ValueError:
            is_loopback = normalized_host == "localhost"
        if not is_loopback:
            raise ConfigError(
                "window_titles.activitywatch_base_url must use a loopback host unless "
                "activitywatch_allow_remote is true"
            )
    if not cfg.log_dir.is_absolute():
        raise ConfigError("paths.log_dir must be absolute after expansion")
    for item in cfg.secure_apps:
        if not isinstance(item, str) or not item:
            raise ConfigError("privacy.secure_apps entries must be non-empty strings")


def _merge_toml(data: Mapping[str, Any], base: AppConfig) -> AppConfig:
    values: dict[str, Any] = {
        f.name: getattr(base, f.name) for f in fields(AppConfig) if f.name != "config_path"
    }

    paths = data.get("paths")
    if isinstance(paths, Mapping) and "log_dir" in paths:
        values["log_dir"] = _expand_log_dir(_require_str("paths", "log_dir", paths["log_dir"]))

    timing = data.get("timing")
    if isinstance(timing, Mapping):
        if "window_check_sec" in timing:
            values["window_check_sec"] = _require_int(
                "timing", "window_check_sec", timing["window_check_sec"]
            )
        if "flush_interval_sec" in timing:
            values["flush_interval_sec"] = _require_int(
                "timing", "flush_interval_sec", timing["flush_interval_sec"]
            )
        if "typing_pause_sec" in timing:
            values["typing_pause_sec"] = _require_number(
                "timing", "typing_pause_sec", timing["typing_pause_sec"]
            )
        if "secure_field_cache_sec" in timing:
            values["secure_field_cache_sec"] = _require_number(
                "timing", "secure_field_cache_sec", timing["secure_field_cache_sec"]
            )
        if "diag_min_interval_sec" in timing:
            values["diag_min_interval_sec"] = _require_number(
                "timing", "diag_min_interval_sec", timing["diag_min_interval_sec"]
            )
        if "secure_app_check_sec" in timing:
            values["secure_app_check_sec"] = _require_number(
                "timing", "secure_app_check_sec", timing["secure_app_check_sec"]
            )

    privacy = data.get("privacy")
    if isinstance(privacy, Mapping):
        if "secure_apps" in privacy:
            raw = privacy["secure_apps"]
            if not isinstance(raw, list) or any(not isinstance(x, str) for x in raw):
                raise ConfigError("privacy.secure_apps must be a list of strings")
            normalized = tuple(item.strip().casefold() for item in raw)
            if any(not item for item in normalized):
                raise ConfigError("privacy.secure_apps entries must be non-empty strings")
            values["secure_apps"] = normalized
        if "unsafe_full_browser_urls" in privacy:
            values["unsafe_full_browser_urls"] = _require_bool(
                "privacy", "unsafe_full_browser_urls", privacy["unsafe_full_browser_urls"]
            )

    ax = data.get("ax")
    if isinstance(ax, Mapping):
        if "ax_queue_maxsize" in ax:
            values["ax_queue_maxsize"] = _require_int(
                "ax", "ax_queue_maxsize", ax["ax_queue_maxsize"]
            )
        if "ax_max_depth" in ax:
            values["ax_max_depth"] = _require_int("ax", "ax_max_depth", ax["ax_max_depth"])
        if "screen_compare_max_chars" in ax:
            values["screen_compare_max_chars"] = _require_int(
                "ax", "screen_compare_max_chars", ax["screen_compare_max_chars"]
            )
        if "ax_max_children" in ax:
            values["ax_max_children"] = _require_int(
                "ax", "ax_max_children", ax["ax_max_children"]
            )
        if "ax_scan_debounce_sec" in ax:
            values["ax_scan_debounce_sec"] = _require_number(
                "ax", "ax_scan_debounce_sec", ax["ax_scan_debounce_sec"]
            )

    wt = data.get("window_titles")
    if isinstance(wt, Mapping):
        if "activitywatch_enricher" in wt:
            values["activitywatch_enricher"] = _require_bool(
                "window_titles", "activitywatch_enricher", wt["activitywatch_enricher"]
            )
        if "activitywatch_base_url" in wt:
            values["activitywatch_base_url"] = _require_str(
                "window_titles", "activitywatch_base_url", wt["activitywatch_base_url"]
            )
        if "activitywatch_allow_remote" in wt:
            values["activitywatch_allow_remote"] = _require_bool(
                "window_titles",
                "activitywatch_allow_remote",
                wt["activitywatch_allow_remote"],
            )
        if "aw_backoff_sec" in wt:
            values["aw_backoff_sec"] = _require_number(
                "window_titles", "aw_backoff_sec", wt["aw_backoff_sec"]
            )

    buffers = data.get("buffers")
    if isinstance(buffers, Mapping):
        if "max_keystrokes" in buffers:
            values["max_keystrokes"] = _require_int(
                "buffers", "max_keystrokes", buffers["max_keystrokes"]
            )
        if "max_events" in buffers:
            values["max_events"] = _require_int(
                "buffers", "max_events", buffers["max_events"]
            )
        if "max_sections" in buffers:
            values["max_sections"] = _require_int(
                "buffers", "max_sections", buffers["max_sections"]
            )

    features = data.get("features")
    if isinstance(features, Mapping):
        if "browser_url_capture" in features:
            values["browser_url_capture"] = _require_bool(
                "features", "browser_url_capture", features["browser_url_capture"]
            )
        if "capture_triggers_enabled" in features:
            values["capture_triggers_enabled"] = _require_bool(
                "features",
                "capture_triggers_enabled",
                features["capture_triggers_enabled"],
            )
        if "scroll_coalesce_enabled" in features:
            values["scroll_coalesce_enabled"] = _require_bool(
                "features",
                "scroll_coalesce_enabled",
                features["scroll_coalesce_enabled"],
            )
        if "scroll_coalesce_ms" in features:
            values["scroll_coalesce_ms"] = _require_int(
                "features", "scroll_coalesce_ms", features["scroll_coalesce_ms"]
            )

    return AppConfig(**values, config_path=None)


def _read_toml(path: Path, warn: WarnFn) -> Mapping[str, Any]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = -1
    try:
        fd = os.open(path, flags)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ConfigError(f"config path is not a regular file: {path}")
        if info.st_uid != os.getuid():
            raise ConfigError(f"config file must be owned by the current user: {path}")
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ConfigError(f"config file must not be group- or world-writable: {path}")
        if info.st_mode & (stat.S_IRGRP | stat.S_IROTH):
            warn(
                f"config: {path} is group- or world-readable; "
                "recommend mode 0600 for operational privacy"
            )
        if info.st_size > 1024 * 1024:
            raise ConfigError(f"config file exceeds 1 MiB: {path}")
        with os.fdopen(fd, "rb") as config_file:
            fd = -1
            raw = config_file.read(1024 * 1024 + 1)
    except OSError as exc:
        raise ConfigError(f"config file unreadable: {path}: {exc}") from exc
    finally:
        if fd >= 0:
            os.close(fd)
    if len(raw) > 1024 * 1024:
        raise ConfigError(f"config file exceeds 1 MiB: {path}")
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ConfigError(f"invalid TOML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"invalid TOML root in {path}: expected table")
    return data


def ensure_log_dir(log_dir: Path) -> Path:
    """Create a private owned log_dir without mutating shared directories."""
    created = False
    fd = -1
    try:
        try:
            info = log_dir.lstat()
        except FileNotFoundError:
            log_dir.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            try:
                os.mkdir(log_dir, 0o700)
                created = True
            except FileExistsError:
                pass
            info = log_dir.lstat()

        if stat.S_ISLNK(info.st_mode):
            raise ConfigError(f"log_dir must not be a symlink: {log_dir}")
        if not stat.S_ISDIR(info.st_mode):
            raise ConfigError(f"log_dir is not a directory: {log_dir}")

        flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        fd = os.open(log_dir, flags)
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode):
            raise ConfigError(f"log_dir is not a directory: {log_dir}")
        if info.st_uid != os.getuid():
            raise ConfigError(f"log_dir must be owned by the current user: {log_dir}")

        mode = stat.S_IMODE(info.st_mode)
        if created:
            os.fchmod(fd, 0o700)
        elif mode != 0o700:
            raise ConfigError(
                f"refusing to chmod existing non-private log_dir {log_dir} "
                f"(mode {mode:04o})"
            )
    except OSError as exc:
        raise ConfigError(f"cannot safely create log_dir {log_dir}: {exc}") from exc
    finally:
        if fd >= 0:
            os.close(fd)
    return log_dir


def _warn_unsafe_config(cfg: AppConfig, warn: WarnFn) -> None:
    if cfg.unsafe_full_browser_urls:
        warn(
            "config: WARNING privacy.unsafe_full_browser_urls=true may log "
            "sensitive URL query values"
        )
    if cfg.activitywatch_allow_remote:
        warn(
            "config: WARNING window_titles.activitywatch_allow_remote=true sends "
            "ActivityWatch requests beyond the local host"
        )


def load_config(
    path: Optional[Path] = None,
    *,
    warn: Optional[WarnFn] = None,
) -> AppConfig:
    """Load AppConfig from path or discovery order (F2 §7).

    If ``path`` is given, that file is required (same fatal rules as
    ACTIVITYLOGGER_CONFIG).
    """
    warn_fn: WarnFn = warn if warn is not None else (lambda _msg: None)
    base = default_config()

    if path is not None:
        resolved: Optional[Path] = Path(path).expanduser()
        if not resolved.is_file():
            raise ConfigError(f"config path missing or not a file: {resolved}")
    else:
        resolved = discover_config_path()

    if resolved is None:
        cfg = base
        env_log = os.environ.get("ACTIVITYLOGGER_LOG_DIR")
        if env_log:
            cfg = replace(cfg, log_dir=_expand_log_dir(env_log))
        _validate(cfg)
        _warn_unsafe_config(cfg, warn_fn)
        return cfg

    data = _read_toml(resolved, warn_fn)
    _collect_unknown(data, warn_fn)
    cfg = replace(_merge_toml(data, base), config_path=resolved)

    env_log = os.environ.get("ACTIVITYLOGGER_LOG_DIR")
    if env_log:
        cfg = replace(cfg, log_dir=_expand_log_dir(env_log))

    _validate(cfg)
    _warn_unsafe_config(cfg, warn_fn)
    return cfg


def startup_diag_line(cfg: AppConfig) -> str:
    """One diagnostics line per F2 §7.3."""
    path_s = str(cfg.config_path) if cfg.config_path else "defaults"
    return (
        f"config_path={path_s} log_dir={cfg.log_dir} "
        f"activitywatch_enricher={cfg.activitywatch_enricher} "
        f"activitywatch_allow_remote={cfg.activitywatch_allow_remote} "
        f"browser_url_capture={cfg.browser_url_capture} "
        f"unsafe_full_browser_urls={cfg.unsafe_full_browser_urls} "
        f"capture_triggers_enabled={cfg.capture_triggers_enabled} "
        f"scroll_coalesce_enabled={cfg.scroll_coalesce_enabled}"
    )
