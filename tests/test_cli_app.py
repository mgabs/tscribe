import stat
import shlex
import plistlib
import sys
from unittest.mock import ANY, MagicMock, patch

from click.testing import CliRunner

from tscribe.cli import main


def test_cli_app_non_darwin_raises():
    runner = CliRunner()
    with patch("sys.platform", "linux"):
        res = runner.invoke(main, ["app"])
        assert res.exit_code != 0
        assert "only supported on macOS" in res.output


def test_cli_app_install_desktop(tmp_path):
    runner = CliRunner()
    with patch("sys.platform", "darwin"), patch("pathlib.Path.home", return_value=tmp_path):
        res = runner.invoke(main, ["app", "--install-desktop"])
        assert res.exit_code == 0
        assert "Installed desktop launcher" in res.output

        app_dir = tmp_path / "Applications" / "tscribe.app"
        script_path = app_dir / "Contents" / "MacOS" / "tscribe"
        assert app_dir.exists()
        assert script_path.exists()

        content = script_path.read_text()
        assert shlex.split(content.splitlines()[1])[:5] == ['exec', sys.executable, '-m', 'tscribe', 'app']
        info = plistlib.loads((app_dir / 'Contents' / 'Info.plist').read_bytes())
        assert info['LSUIElement'] is True
        assert info['NSMicrophoneUsageDescription']
        assert (app_dir / 'Contents' / 'Resources' / 'AppIcon.icns').is_file()
        # Check executable permissions
        mode = script_path.stat().st_mode
        assert bool(mode & stat.S_IXUSR)


def test_cli_app_runs_tscribe_app():
    runner = CliRunner()
    with patch("sys.platform", "darwin"):
        with patch("tscribe.app.TscribeApp") as mock_app_cls:
            mock_app = MagicMock()
            mock_app_cls.return_value = mock_app

            res = runner.invoke(main, ["app", "--diarize"])
            assert res.exit_code == 0
            assert "Running tscribe in macOS menu bar" in res.output

            mock_app_cls.assert_called_once_with(diarize=True, config=ANY)
            mock_app.run.assert_called_once()


def test_cli_app_loads_shared_config(tmp_path):
    from tscribe.paths import get_config_path
    path = get_config_path()
    path.parent.mkdir(parents=True)
    path.write_text('[transcription]\nmodel = "tiny"\ndiarize = true\n[app]\nnotifications = false\n')
    with patch('sys.platform', 'darwin'), patch('tscribe.app.TscribeApp') as app:
        result = CliRunner().invoke(main, ['app'])
        assert result.exit_code == 0
        assert app.call_args.kwargs['diarize'] is None
        config = app.call_args.kwargs['config']
        assert config.transcription.model == 'tiny'
        assert config.transcription.diarize is True
        assert config.app.notifications is False


def test_cli_app_invalid_config(tmp_path):
    from tscribe.paths import get_config_path
    path = get_config_path()
    path.parent.mkdir(parents=True)
    path.write_text('[app]\nrecent_limit = 0\n')
    with patch('sys.platform', 'darwin'), patch('tscribe.app.TscribeApp') as app:
        result = CliRunner().invoke(main, ['app'])
        assert result.exit_code != 0
        assert 'Cannot load config' in result.output
        app.assert_not_called()
