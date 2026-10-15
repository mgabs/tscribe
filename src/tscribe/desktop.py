"""macOS desktop launcher installation and packaged resource paths."""

from __future__ import annotations

import plistlib
import shlex
import shutil
import sys
from pathlib import Path

from tscribe import __version__

RESOURCE_DIR = Path(__file__).resolve().parent / 'resources'


def bundle_info() -> dict:
    return {
        'CFBundleExecutable': 'tscribe',
        'CFBundleIdentifier': 'com.tscribe.app',
        'CFBundleName': 'tscribe',
        'CFBundleDisplayName': 'tscribe',
        'CFBundlePackageType': 'APPL',
        'CFBundleShortVersionString': __version__,
        'CFBundleVersion': __version__,
        'CFBundleIconFile': 'AppIcon',
        'LSUIElement': True,
        'NSHighResolutionCapable': True,
        'NSMicrophoneUsageDescription': 'tscribe records microphone audio to create local transcripts.',
    }


def install_desktop_launcher(destination: Path | None = None) -> Path:
    """Install a small launcher for an existing Python installation."""
    destination = destination or Path.home() / 'Applications' / 'tscribe.app'
    contents = destination / 'Contents'
    executable = contents / 'MacOS' / 'tscribe'
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text(
        '#!/bin/sh\n'
        f'exec {shlex.quote(sys.executable)} -m tscribe app "$@"\n'
    )
    executable.chmod(0o755)
    resources = contents / 'Resources'
    resources.mkdir(parents=True, exist_ok=True)
    shutil.copy2(RESOURCE_DIR / 'AppIcon.icns', resources / 'AppIcon.icns')
    with (contents / 'Info.plist').open('wb') as stream:
        plistlib.dump(bundle_info(), stream)
    return destination
