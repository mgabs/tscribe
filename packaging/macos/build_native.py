"""Build a Swift application with a bundled headless Python transcription worker."""
from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from build_lock import build_lock

ROOT = Path(__file__).resolve().parents[2]


def run(*arguments):
    subprocess.run([str(arg) for arg in arguments], cwd=ROOT, check=True)


def main(destination: Path | None = None):
    if sys.platform != 'darwin':
        raise SystemExit('Build the native app on macOS.')
    run(sys.executable, ROOT / 'packaging/macos/build_audio_dsp.py')
    worker_dist = ROOT / 'build/worker-dist'
    run(sys.executable, '-m', 'PyInstaller', '--noconfirm',
        '--distpath', worker_dist, '--workpath', ROOT / 'build/pyinstaller',
        ROOT / 'packaging/macos/worker.spec')
    run('swift', 'build', '--disable-sandbox', '--package-path', ROOT / 'macos', '--scratch-path', ROOT / 'build/swift', '-c', 'release')
    from tscribe.desktop import RESOURCE_DIR, bundle_info
    destination = destination or ROOT / 'dist/tscribe.app'
    # Preserve the last complete app until its replacement is signed and verified.
    with tempfile.TemporaryDirectory(prefix='tscribe-stage-', dir=ROOT / 'build') as staging:
        staged = Path(staging) / 'tscribe.app'
        contents = staged / 'Contents'
        executable = contents / 'MacOS/tscribe-native'
        executable.parent.mkdir(parents=True)
        resources = contents / 'Resources'
        resources.mkdir()
        shutil.copy2(ROOT / 'build/swift/release/tscribe-native', executable)
        shutil.copy2(RESOURCE_DIR / 'AppIcon.icns', resources / 'AppIcon.icns')
        run('ditto', worker_dist / 'tscribe-worker', resources / 'Worker')
        with (contents / 'Info.plist').open('wb') as stream:
            plistlib.dump(bundle_info(), stream)
        identity = os.environ.get('TSCRIBE_CODESIGN_IDENTITY', '-')
        options = ['--options', 'runtime'] if identity != '-' else []
        # PyInstaller signs its native libraries; sign the new host and bundle last.
        run('codesign', '--force', '--sign', identity, *options, executable)
        run('codesign', '--force', '--sign', identity, *options, staged)
        run('codesign', '--verify', '--deep', '--strict', staged)
        destination.parent.mkdir(parents=True, exist_ok=True)
        previous = Path(staging) / 'previous.app'
        if destination.exists():
            destination.rename(previous)
        try:
            staged.rename(destination)
        except OSError:
            if previous.exists():
                previous.rename(destination)
            raise
    print(f'Built native app: {destination}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Build at another path, preserving the current dist app.')
    arguments = parser.parse_args()
    with build_lock():
        main(arguments.output.resolve() if arguments.output else None)
