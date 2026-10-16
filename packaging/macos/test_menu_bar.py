"""Run real menu-bar integration checks in a temporary, isolated Mac app."""
from __future__ import annotations

import json
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from build_lock import ROOT, build_lock


def main():
    if sys.platform != 'darwin':
        raise SystemExit('Menu bar integration checks require macOS with a logged-in desktop.')
    subprocess.run(['swift', 'build', '--disable-sandbox', '--package-path', str(ROOT / 'macos'), '--scratch-path', str(ROOT / 'build/swift'), '-c', 'release'], check=True)
    from tscribe.desktop import bundle_info

    with tempfile.TemporaryDirectory(prefix='tscribe-menu-test-') as directory:
        workspace = Path(directory)
        app = workspace / 'tscribe Menu Test.app'
        executable = app / 'Contents/MacOS/tscribe-native'
        executable.parent.mkdir(parents=True)
        shutil.copy2(ROOT / 'build/swift/release/tscribe-native', executable)
        info = bundle_info()
        # Never activate, terminate, or read files from the user's running app.
        info['CFBundleIdentifier'] = 'com.tscribe.menu-integration-test'
        info['CFBundleName'] = 'tscribe Menu Test'
        info['CFBundleDisplayName'] = 'tscribe Menu Test'
        with (app / 'Contents/Info.plist').open('wb') as stream:
            plistlib.dump(info, stream)
        subprocess.run(['codesign', '--force', '--sign', '-', str(app)], check=True)
        report = workspace / 'report.json'
        arguments = ['open', '-n', '-W']
        for key, value in {
            'TSCRIBE_PYTHON_EXECUTABLE': sys.executable,
            'TSCRIBE_CONFIG_FILE': str(workspace / 'config.toml'),
            'TSCRIBE_DATA_DIR': str(workspace / 'data'),
            'TSCRIBE_LOG_DIR': str(workspace / 'logs'),
        }.items():
            arguments.extend(['--env', f'{key}={value}'])
        arguments.extend([str(app), '--args', '--smoke-report', str(report), '--smoke-menu-bar'])
        try:
            subprocess.run(arguments, check=True, timeout=60)
            result = json.loads(report.read_text())
        finally:
            # Stop just this temporary test app if an AppKit/menu check hung.
            subprocess.run(['pkill', '-TERM', '-f', str(executable)], check=False)
        expected = [
            'window_visible', 'worker_ready', 'status_item_visible', 'menu_opens',
            'hidden_to_menu_bar', 'window_restored', 'keyboard_minimize_to_menu_bar',
            'minimize_shortcut_registered', 'close_to_menu_bar', 'closed_window_restored',
            'status_item_survives_window_close',
        ]
        failed = [key for key in expected if result.get(key) is not True]
        print(json.dumps(result, indent=2))
        if failed:
            raise SystemExit(f'Menu bar integration checks failed: {", ".join(failed)}. Check desktop/menu-bar visibility; an allocated status item is not proof of a visible icon.')
        print('Menu bar integration checks passed (no microphone or system audio was recorded).')


if __name__ == '__main__':
    with build_lock():
        main()
