"""Cross-platform path resolution for tscribe data directories."""

import os
from pathlib import Path


def get_data_dir(config_override: str = "") -> Path:
    """Resolve the tscribe data directory.

    Priority: config_override > TSCRIBE_DATA_DIR env var > ~/.tscribe.
    """
    if config_override:
        return Path(config_override).expanduser()

    env_dir = os.environ.get("TSCRIBE_DATA_DIR")
    if env_dir:
        return Path(env_dir).expanduser()

    return Path.home() / ".tscribe"


def get_recordings_dir(data_dir: Path) -> Path:
    return data_dir / "recordings"


def get_config_path(data_dir: Path | None = None) -> Path:
    """Select one config file, independently of storage.data_dir.

    An explicit file wins. Existing legacy files are kept in place; new
    installations use $XDG_CONFIG_HOME/tscribe/config.toml (or ~/.config).
    Passing data_dir explicitly retains the legacy path helper behavior.
    """
    if data_dir is not None:
        return data_dir / "config.toml"
    explicit = os.environ.get("TSCRIBE_CONFIG_FILE")
    if explicit:
        return Path(explicit).expanduser()
    if os.environ.get("TSCRIBE_DATA_DIR"):
        return get_data_dir() / "config.toml"
    legacy = get_data_dir() / "config.toml"
    if legacy.is_file():
        return legacy
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config").expanduser()
    return config_home / "tscribe" / "config.toml"


def ensure_dirs(data_dir: Path) -> None:
    """Create all required subdirectories if they don't exist."""
    get_recordings_dir(data_dir).mkdir(parents=True, exist_ok=True)
