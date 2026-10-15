"""Verify installation metadata without launching Cocoa or recording audio."""

import plistlib
import shlex
from pathlib import Path

from tscribe import __version__
from tscribe.desktop import RESOURCE_DIR, bundle_info, install_desktop_launcher


def test_packaged_resources():
    for name in ('menu_icon.png', 'menu_icon@2x.png', 'AppIcon.icns'):
        assert (RESOURCE_DIR / name).is_file()


def test_launcher_quotes_python_path(tmp_path, monkeypatch):
    python = str(tmp_path / 'Python Installation' / 'bin' / 'python')
    monkeypatch.setattr('tscribe.desktop.sys.executable', python)
    destination = install_desktop_launcher(tmp_path / 'My Apps' / 'tscribe.app')
    executable = destination / 'Contents' / 'MacOS' / 'tscribe'
    words = shlex.split(executable.read_text().splitlines()[1])
    assert words == ['exec', python, '-m', 'tscribe', 'app', '$@']
    info = plistlib.loads((destination / 'Contents' / 'Info.plist').read_bytes())
    assert info == bundle_info()
    assert info['LSUIElement'] is True
    assert info['CFBundleVersion'] == __version__
    assert info['NSMicrophoneUsageDescription']


def test_project_and_cli_versions_match():
    from tscribe.config import tomllib
    project = tomllib.loads((Path(__file__).parents[1] / 'pyproject.toml').read_text())
    assert project['project']['version'] == __version__
