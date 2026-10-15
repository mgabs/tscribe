import stat
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
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
        assert f"exec {sys.executable} -m tscribe.cli app" in content
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

            mock_app_cls.assert_called_once_with(diarize=True)
            mock_app.run.assert_called_once()
