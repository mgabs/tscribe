"""Tests for path resolution."""

from pathlib import Path

from tscribe.paths import (
    ensure_dirs,
    get_config_path,
    get_data_dir,
    get_recordings_dir,
)


def test_data_dir_default():
    from pathlib import Path

    data_dir = get_data_dir()
    assert data_dir == Path.home() / ".tscribe"


def test_data_dir_config_override(tmp_path):
    override = str(tmp_path / "custom")
    data_dir = get_data_dir(config_override=override)
    assert data_dir == tmp_path / "custom"


def test_data_dir_env_override(tmp_path, monkeypatch):
    env_path = str(tmp_path / "env_dir")
    monkeypatch.setenv("TSCRIBE_DATA_DIR", env_path)
    data_dir = get_data_dir()
    assert data_dir == tmp_path / "env_dir"


def test_config_override_takes_precedence_over_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TSCRIBE_DATA_DIR", str(tmp_path / "env"))
    data_dir = get_data_dir(config_override=str(tmp_path / "config"))
    assert data_dir == tmp_path / "config"


def test_subdirectory_helpers(tmp_path):
    assert get_recordings_dir(tmp_path) == tmp_path / "recordings"
    assert get_config_path(tmp_path) == tmp_path / "config.toml"


def test_ensure_dirs(tmp_path):
    ensure_dirs(tmp_path)
    assert (tmp_path / "recordings").is_dir()


def test_ensure_dirs_idempotent(tmp_path):
    ensure_dirs(tmp_path)
    ensure_dirs(tmp_path)  # Should not raise
    assert (tmp_path / "recordings").is_dir()


def test_default_config_location(tmp_path):
    assert get_config_path() == tmp_path / '.config' / 'tscribe' / 'config.toml'


def test_existing_legacy_config_wins(tmp_path):
    legacy = tmp_path / '.tscribe' / 'config.toml'
    legacy.parent.mkdir()
    legacy.touch()
    xdg = tmp_path / '.config' / 'tscribe' / 'config.toml'
    xdg.parent.mkdir(parents=True)
    xdg.touch()
    assert get_config_path() == legacy


def test_explicit_config_wins(tmp_path, monkeypatch):
    monkeypatch.setenv('TSCRIBE_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('TSCRIBE_CONFIG_FILE', '~/custom/config.toml')
    assert get_config_path() == Path('~/custom/config.toml').expanduser()


def test_legacy_data_env_config(tmp_path, monkeypatch):
    monkeypatch.setenv('TSCRIBE_DATA_DIR', str(tmp_path / 'data'))
    assert get_config_path() == tmp_path / 'data' / 'config.toml'


def test_xdg_config_home(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'settings'))
    assert get_config_path() == tmp_path / 'settings' / 'tscribe' / 'config.toml'


def test_expand_storage_home(tmp_path):
    assert get_data_dir('~/Recordings') == Path('~/Recordings').expanduser()


def test_default_config_without_xdg_env(tmp_path, monkeypatch):
    monkeypatch.delenv('XDG_CONFIG_HOME')
    assert get_config_path() == tmp_path / '.config' / 'tscribe' / 'config.toml'


def test_default_config_with_empty_xdg_env(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', '')
    assert get_config_path() == tmp_path / '.config' / 'tscribe' / 'config.toml'


def test_ensure_dirs_creates_nested_parents(tmp_path):
    data_dir = tmp_path / 'new' / 'nested' / 'data'
    ensure_dirs(data_dir)
    assert (data_dir / 'recordings').is_dir()
