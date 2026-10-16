"""Verify installation metadata without launching Cocoa or recording audio."""

import plistlib
from pathlib import Path

from tscribe import __version__
from tscribe.desktop import RESOURCE_DIR, bundle_info


def test_native_bundle_metadata_and_icon():
    assert (RESOURCE_DIR / 'AppIcon.icns').is_file()
    info = bundle_info()
    assert info['CFBundleExecutable'] == 'tscribe-native'
    assert info['TscribeNativeUI'] is True
    assert info['LSUIElement'] is False
    assert info['CFBundleVersion'] == __version__
    assert info['NSMicrophoneUsageDescription']
    assert info['NSAudioCaptureUsageDescription']


def test_project_and_cli_versions_match():
    from tscribe.config import tomllib
    project = tomllib.loads((Path(__file__).parents[1] / 'pyproject.toml').read_text())
    assert project['project']['version'] == __version__


def test_native_app_discovery_prefers_installed_unless_installing(tmp_path, monkeypatch):
    from tscribe import desktop

    installed = tmp_path / 'Applications/tscribe.app'
    built = Path(desktop.__file__).resolve().parents[2] / 'dist/tscribe.app'
    monkeypatch.delenv('TSCRIBE_APP_PATH', raising=False)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(desktop, 'is_native_app', lambda path: path in (installed, built))
    assert desktop.find_native_app() == installed
    assert desktop.find_native_app(prefer_build=True) == built


def test_native_app_explicit_override_has_priority(tmp_path, monkeypatch):
    from tscribe import desktop

    override = tmp_path / 'custom.app'
    monkeypatch.setenv('TSCRIBE_APP_PATH', str(override))
    monkeypatch.setattr(desktop, 'is_native_app', lambda path: True)
    assert desktop.find_native_app(prefer_build=True) == override


def test_native_app_requires_marker_and_executable(tmp_path):
    from tscribe.desktop import is_native_app

    bundle = tmp_path / 'tscribe.app'
    contents = bundle / 'Contents'
    contents.mkdir(parents=True)
    plist = contents / 'Info.plist'
    plist.write_bytes(plistlib.dumps({'CFBundleExecutable': 'tscribe'}))
    assert not is_native_app(bundle)
    plist.write_bytes(plistlib.dumps(bundle_info()))
    assert not is_native_app(bundle)
    executable = contents / 'MacOS/tscribe-native'
    executable.parent.mkdir()
    executable.touch()
    assert is_native_app(bundle)
    plist.write_text('invalid plist')
    assert not is_native_app(bundle)


def test_native_install_preserves_previous_app(tmp_path, monkeypatch):
    import shutil
    from tscribe.desktop import install_native_app

    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    source = tmp_path / 'dist/tscribe.app'
    (source / 'Contents/MacOS').mkdir(parents=True)
    (source / 'Contents/MacOS/tscribe-native').write_text('new app')
    (source / 'Contents/Info.plist').write_bytes(plistlib.dumps(bundle_info()))
    installed = tmp_path / 'Applications/tscribe.app'
    installed.mkdir(parents=True)
    (installed / 'previous').touch()

    def copy_bundle(arguments, check):
        assert arguments[0] == 'ditto' and check
        shutil.copytree(arguments[1], arguments[2])

    monkeypatch.setattr('subprocess.run', copy_bundle)
    assert install_native_app(source) == installed
    assert (installed / 'Contents/MacOS/tscribe-native').read_text() == 'new app'
    backups = list(installed.parent.glob('.tscribe-backup-*'))
    assert len(backups) == 1
    assert (backups[0] / 'previous').is_file()
    assert not list(installed.parent.glob('.tscribe-install-*'))
