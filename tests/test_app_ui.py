from unittest.mock import MagicMock, patch
import pytest
from tscribe.app import AppState, TscribeApp, TscribeController


def test_tscribe_app_initial_state(tmp_path):
    with patch("rumps.App.__init__", return_value=None):
        app = TscribeApp(recordings_dir=tmp_path)
        app.title = "🎙️"
        assert app.controller.state == AppState.IDLE
        assert app.title == "🎙️"
        assert app.item_rec_mic.callback == app.on_record_mic
        assert app.item_rec_sys.callback == app.on_record_sys
        assert app.item_stop.callback is None
        assert app.item_diarize.state == 0


def test_tscribe_app_timer_tick(tmp_path):
    with patch("rumps.App.__init__", return_value=None):
        app = TscribeApp(recordings_dir=tmp_path)
        app.controller.state = AppState.RECORDING
        app.controller.start_time = 100.0
        with patch("time.monotonic", return_value=125.0):
            app._on_timer_tick(None)
            assert "00:25" in app.title

        app.controller.state = AppState.TRANSCRIBING
        app._on_timer_tick(None)
        assert "Transcribing" in app.title

        app.controller.state = AppState.IDLE
        app._on_timer_tick(None)
        assert "🎙️" in app.title


def test_tscribe_app_state_changes(tmp_path):
    with patch("rumps.App.__init__", return_value=None):
        app = TscribeApp(recordings_dir=tmp_path)

        # When RECORDING
        app._handle_state_change(AppState.RECORDING)
        assert app.item_rec_mic.callback is None
        assert app.item_rec_sys.callback is None
        assert app.item_stop.callback == app.on_stop

        # When TRANSCRIBING
        app._handle_state_change(AppState.TRANSCRIBING)
        assert app.item_rec_mic.callback is None
        assert app.item_rec_sys.callback is None
        assert app.item_stop.callback is None

        # When IDLE
        app._handle_state_change(AppState.IDLE)
        assert app.item_rec_mic.callback == app.on_record_mic
        assert app.item_rec_sys.callback == app.on_record_sys
        assert app.item_stop.callback is None


def test_tscribe_app_open_session_calls_subprocess(tmp_path):
    with patch("rumps.App.__init__", return_value=None):
        app = TscribeApp(recordings_dir=tmp_path)
        txt = tmp_path / "session_123.txt"
        txt.write_text("Test transcript")

        with patch("subprocess.run") as mock_run:
            app._open_session("session_123")
            mock_run.assert_called_once_with(["open", str(txt)])


def test_tscribe_app_actions(tmp_path):
    with patch("rumps.App.__init__", return_value=None):
        app = TscribeApp(recordings_dir=tmp_path)

        with patch.object(app.controller, "start_recording") as mock_start:
            app.on_record_mic(None)
            mock_start.assert_called_once_with(use_mic=True, diarize=False)

        with patch.object(app.controller, "start_recording") as mock_start:
            app.on_record_sys(None)
            mock_start.assert_called_once_with(use_mic=False, diarize=False)

        with patch.object(app.controller, "stop_recording") as mock_stop:
            app.on_stop(None)
            mock_stop.assert_called_once()

        sender = MagicMock()
        sender.state = 0
        app.on_toggle_diarize(sender)
        assert sender.state == 1
        assert app.controller.diarize is True

        with patch("rumps.notification") as mock_notify:
            app._handle_notification("title", "subtitle", "message")
            mock_notify.assert_called_once_with("title", "subtitle", "message")


def test_tscribe_app_copy_and_open_last(tmp_path):
    with patch("rumps.App.__init__", return_value=None):
        app = TscribeApp(recordings_dir=tmp_path)
        txt = tmp_path / "2026-01-01-120000.txt"
        txt.write_text("Hello transcript")
        wav = tmp_path / "2026-01-01-120000.wav"
        wav.touch()

        with patch("tscribe.app.copy_to_clipboard") as mock_copy, patch("rumps.notification") as mock_notify:
            app.on_copy_last(None)
            mock_copy.assert_called_once_with("Hello transcript")
            mock_notify.assert_called_once_with("tscribe", "", "Copied transcript to clipboard")

        with patch("subprocess.run") as mock_run:
            app.on_open_last(None)
            mock_run.assert_called_once_with(["open", str(txt)])


def test_tscribe_app_missing_rumps(monkeypatch):
    monkeypatch.setattr("tscribe.app.rumps", None)
    with pytest.raises(RuntimeError, match="rumps is required"):
        TscribeApp()


def test_tscribe_app_run(tmp_path):
    with patch("rumps.App.__init__", return_value=None), patch("rumps.App.run") as mock_run:
        app = TscribeApp(recordings_dir=tmp_path)
        app.run()
        mock_run.assert_called_once()

