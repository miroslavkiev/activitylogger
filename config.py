"""ActivityLogger TOML config (F2).

Load once at process start. Key names match docs/specs/F2-config.md §6.
"""

from __future__ import annotations

import os
import stat
import sys
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

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
        }
    ),
    "privacy": frozenset({"secure_apps"}),
    "ax": frozenset({"ax_queue_maxsize", "ax_max_depth", "screen_compare_max_chars"}),
    "window_titles": frozenset({"activitywatch_enricher", "activitywatch_base_url"}),
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
    secure_apps: tuple[str, ...]
    ax_queue_maxsize: int
    ax_max_depth: int
    screen_compare_max_chars: int
    activitywatch_enricher: bool
    activitywatch_base_url: str
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
        secure_apps=DEFAULT_SECURE_APPS,
        ax_queue_maxsize=16,
        ax_max_depth=7,
        screen_compare_max_chars=4000,
        activitywatch_enricher=True,
        activitywatch_base_url="http://localhost:5600",
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
    return float(value)


def _require_int(section: str, key: str, value: Any) -> int:
    num = _require_number(section, key, value)
    if int(num) != num:
        raise ConfigError(f"{section}.{key} must be an integer")
    return int(num)


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
    if cfg.window_check_sec < 1:
        raise ConfigError("timing.window_check_sec must be >= 1")
    if cfg.flush_interval_sec < 1:
        raise ConfigError("timing.flush_interval_sec must be >= 1")
    if cfg.typing_pause_sec < 0.05:
        raise ConfigError("timing.typing_pause_sec must be >= 0.05")
    if cfg.secure_field_cache_sec < 0:
        raise ConfigError("timing.secure_field_cache_sec must be >= 0")
    if cfg.diag_min_interval_sec < 1:
        raise ConfigError("timing.diag_min_interval_sec must be >= 1")
    if cfg.ax_queue_maxsize < 1:
        raise ConfigError("ax.ax_queue_maxsize must be >= 1")
    if not (1 <= cfg.ax_max_depth <= 32):
        raise ConfigError("ax.ax_max_depth must be in 1..32")
    if cfg.screen_compare_max_chars < 100:
        raise ConfigError("ax.screen_compare_max_chars must be >= 100")
    if not (50 <= cfg.scroll_coalesce_ms <= 5000):
        raise ConfigError("features.scroll_coalesce_ms must be in 50..5000")
    url = cfg.activitywatch_base_url.strip()
    if not url:
        raise ConfigError("window_titles.activitywatch_base_url must be non-empty")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ConfigError(
            "window_titles.activitywatch_base_url must start with http:// or https://"
        )
    if not cfg.log_dir.is_absolute():
        raise ConfigError("paths.log_dir must be absolute after expansion")
    for item in cfg.secure_apps:
        if not isinstance(item, str):
            raise ConfigError("privacy.secure_apps must be a list of strings")


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

    privacy = data.get("privacy")
    if isinstance(privacy, Mapping) and "secure_apps" in privacy:
        raw = privacy["secure_apps"]
        if not isinstance(raw, list) or any(not isinstance(x, str) for x in raw):
            raise ConfigError("privacy.secure_apps must be a list of strings")
        values["secure_apps"] = tuple(raw)

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


def _read_toml(path: Path) -> Mapping[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"config file unreadable: {path}: {exc}") from exc
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ConfigError(f"invalid TOML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"invalid TOML root in {path}: expected table")
    return data


def _warn_permissions(path: Path, warn: WarnFn) -> None:
    try:
        mode = path.stat().st_mode
    except OSError:
        return
    if mode & (stat.S_IRGRP | stat.S_IROTH):
        warn(
            f"config: {path} is group- or world-readable; "
            "recommend mode 0600 for operational privacy"
        )


def ensure_log_dir(log_dir: Path) -> Path:
    """Create log_dir with mode 0700. Fatal on failure."""
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(log_dir, 0o700)
    except OSError as exc:
        raise ConfigError(f"cannot create log_dir {log_dir}: {exc}") from exc
    return log_dir


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
        return cfg

    _warn_permissions(resolved, warn_fn)
    data = _read_toml(resolved)
    _collect_unknown(data, warn_fn)
    cfg = replace(_merge_toml(data, base), config_path=resolved)

    env_log = os.environ.get("ACTIVITYLOGGER_LOG_DIR")
    if env_log:
        cfg = replace(cfg, log_dir=_expand_log_dir(env_log))

    _validate(cfg)
    return cfg


def startup_diag_line(cfg: AppConfig) -> str:
    """One diagnostics line per F2 §7.3."""
    path_s = str(cfg.config_path) if cfg.config_path else "defaults"
    return (
        f"config_path={path_s} log_dir={cfg.log_dir} "
        f"activitywatch_enricher={cfg.activitywatch_enricher} "
        f"browser_url_capture={cfg.browser_url_capture} "
        f"capture_triggers_enabled={cfg.capture_triggers_enabled} "
        f"scroll_coalesce_enabled={cfg.scroll_coalesce_enabled}"
    )
