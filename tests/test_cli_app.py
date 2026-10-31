"""Native app routing without launching macOS UI or recording audio."""
import subprocess
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from tscribe.cli import main


def test_cli_app_non_darwin_raises():
    with patch('sys.platform', 'linux'):
        result = CliRunner().invoke(main, ['app'])
    assert result.exit_code != 0
    assert 'only supported on macOS' in result.output


@pytest.mark.parametrize('options, forwarded', [
    ([], []),
    (['--diarize'], ['--args', '--diarize']),
    (['--no-diarize'], ['--args', '--no-diarize']),
    (['--diarize-engine', 'wespeaker'], ['--args', '--diarize-engine', 'wespeaker']),
])
def test_cli_opens_native_app(tmp_path, options, forwarded):
    bundle = tmp_path / 'tscribe.app'
    with patch('sys.platform', 'darwin'), patch('tscribe.desktop.find_native_app', return_value=bundle), patch('subprocess.run') as run:
        result = CliRunner().invoke(main, ['app', *options])
    assert result.exit_code == 0
    run.assert_called_once_with(['open', str(bundle), *forwarded], check=True)
    assert 'native tscribe' in result.output


def test_cli_app_install_does_not_launch(tmp_path):
    built = tmp_path / 'dist/tscribe.app'
    installed = tmp_path / 'Applications/tscribe.app'
    with patch('sys.platform', 'darwin'), patch('tscribe.desktop.find_native_app', return_value=built) as find, patch('tscribe.desktop.install_native_app', return_value=installed) as install, patch('subprocess.run') as launch:
        result = CliRunner().invoke(main, ['app', '--install-desktop'])
    assert result.exit_code == 0
    assert str(installed) in result.output
    find.assert_called_once_with(prefer_build=True)
    install.assert_called_once_with(built)
    launch.assert_not_called()


def test_cli_native_app_missing_has_build_instructions():
    with patch('sys.platform', 'darwin'), patch('tscribe.desktop.find_native_app', return_value=None):
        result = CliRunner().invoke(main, ['app'])
    assert result.exit_code != 0
    assert 'build_native.py' in result.output


@pytest.mark.parametrize('error', [OSError('Launch Services unavailable'), subprocess.CalledProcessError(1, 'open')])
def test_cli_launch_failure_is_actionable(tmp_path, error):
    with patch('sys.platform', 'darwin'), patch('tscribe.desktop.find_native_app', return_value=tmp_path / 'tscribe.app'), patch('subprocess.run', side_effect=error):
        result = CliRunner().invoke(main, ['app'])
    assert result.exit_code != 0
    assert 'Could not launch native app' in result.output
