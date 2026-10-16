"""Native macOS bundle metadata, discovery, and installation."""

from __future__ import annotations

import plistlib
from pathlib import Path

from tscribe import __version__

RESOURCE_DIR = Path(__file__).resolve().parent / 'resources'


def bundle_info() -> dict:
    return {
        'CFBundleExecutable': 'tscribe-native',
        'CFBundleIdentifier': 'com.tscribe.app',
        'CFBundleName': 'tscribe',
        'CFBundleDisplayName': 'tscribe',
        'CFBundlePackageType': 'APPL',
        'CFBundleShortVersionString': __version__,
        'CFBundleVersion': __version__,
        'CFBundleIconFile': 'AppIcon',
        'LSUIElement': False,
        'LSMinimumSystemVersion': '14.0',
        'TscribeNativeUI': True,
        'NSAudioCaptureUsageDescription': 'tscribe captures system sound to create local transcripts.',
        'NSHighResolutionCapable': True,
        'NSMicrophoneUsageDescription': 'tscribe records microphone audio to create local transcripts.',
    }


def is_native_app(path: Path) -> bool:
    try:
        with (path / 'Contents/Info.plist').open('rb') as stream:
            info = plistlib.load(stream)
        return info.get('TscribeNativeUI') is True and (path / 'Contents/MacOS/tscribe-native').is_file()
    except (OSError, ValueError, plistlib.InvalidFileException):
        return False


def find_native_app(prefer_build: bool = False) -> Path | None:
    import os
    candidates = []
    if os.environ.get('TSCRIBE_APP_PATH'):
        candidates.append(Path(os.environ['TSCRIBE_APP_PATH']).expanduser())
    built = Path(__file__).resolve().parents[2] / 'dist/tscribe.app'
    if prefer_build:
        candidates.append(built)
    candidates.extend([
        Path.home() / 'Applications/tscribe.app',
        Path('/Applications/tscribe.app'),
        built,
    ])
    return next((path for path in candidates if is_native_app(path)), None)


def install_native_app(source: Path) -> Path:
    """Install a built native app, retaining any existing app as a backup."""
    import subprocess
    import uuid
    if not is_native_app(source):
        raise ValueError('The source is not a native tscribe app bundle')
    destination = Path.home() / 'Applications/tscribe.app'
    if source.resolve() == destination.resolve():
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = destination.parent / f'.tscribe-install-{uuid.uuid4().hex}'
    subprocess.run(['ditto', str(source), str(staged)], check=True)
    if destination.exists():
        destination.rename(destination.parent / f'.tscribe-backup-{uuid.uuid4().hex}')
    staged.rename(destination)
    return destination
