import subprocess
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from tscribe.app import AppState, AudioRecorder, copy_to_clipboard, format_elapsed_time, TscribeController
from tscribe.recorder.base import RecordingResult


def test_format_elapsed_time():
    assert format_elapsed_time(0.0) == "00:00"
    assert format_elapsed_time(45.2) == "00:45"
    assert format_elapsed_time(125.0) == "02:05"
    assert format_elapsed_time(3665.0) == "01:01:05"


def test_app_state_enum():
    assert AppState.IDLE.value == "IDLE"
    assert AppState.RECORDING.value == "RECORDING"
    assert AppState.TRANSCRIBING.value == "TRANSCRIBING"


def test_copy_to_clipboard_empty():
    assert copy_to_clipboard("") is False
    assert copy_to_clipboard(None) is False


def test_copy_to_clipboard_success():
    with patch("subprocess.Popen") as mock_popen:
        proc = MagicMock()
        proc.communicate.return_value = (b"", b"")
        proc.returncode = 0
        mock_popen.return_value = proc
        assert copy_to_clipboard("test transcript") is True
        mock_popen.assert_called_once_with(["pbcopy"], stdin=subprocess.PIPE)
        proc.communicate.assert_called_once_with(b"test transcript")


def test_copy_to_clipboard_os_error():
    with patch("subprocess.Popen", side_effect=OSError("Command not found")):
        assert copy_to_clipboard("test") is False


def test_controller_initial_state(tmp_path):
    controller = TscribeController(recordings_dir=tmp_path)
    assert controller.state == AppState.IDLE
    assert controller.elapsed_seconds() == 0.0


def test_controller_elapsed_seconds(tmp_path):
    controller = TscribeController(recordings_dir=tmp_path)
    controller.state = AppState.RECORDING
    controller.start_time = 100.0
    with patch("time.monotonic", return_value=115.5):
        assert controller.elapsed_seconds() == pytest.approx(15.5)


def test_controller_state_transitions(tmp_path):
    state_changes = []
    notifications = []

    def on_state(state):
        state_changes.append(state)

    def on_notify(title, subtitle, msg):
        notifications.append((title, subtitle, msg))

    controller = TscribeController(
        recordings_dir=tmp_path,
        on_state_change=on_state,
        on_notification=on_notify,
    )

    mock_result = RecordingResult(
        path=tmp_path / "rec.wav",
        duration_seconds=5.0,
        sample_rate=16000,
        channels=1,
        device_name="default",
        source_type="microphone",
    )

    mock_rec_instance = MagicMock()

    def fake_record(output_path, config, stop_event):
        stop_event.wait(timeout=1.0)
        return mock_result

    mock_rec_instance.record.side_effect = fake_record

    with patch("tscribe.app.AudioRecorder", return_value=mock_rec_instance), \
         patch("tscribe.app.Transcriber") as mock_transcriber_cls:
        mock_transcriber = mock_transcriber_cls.return_value
        mock_tx_result = MagicMock()
        mock_tx_result.to_txt.return_value = "Hello world transcript."
        mock_tx_result.to_json.return_value = {"segments": []}
        mock_transcriber.transcribe.return_value = mock_tx_result

        controller.start_recording(use_mic=True, diarize=False)
        assert controller.state == AppState.RECORDING
        assert AppState.RECORDING in state_changes

        # Redundant start_recording while already recording should be ignored
        controller.start_recording(use_mic=True)
        assert controller.state == AppState.RECORDING

        # Stop recording
        controller.stop_recording()
        assert controller.state == AppState.TRANSCRIBING
        assert AppState.TRANSCRIBING in state_changes

        # Wait for worker thread to complete
        if controller._worker_thread:
            controller._worker_thread.join(timeout=2.0)

        # Worker should finish transcription and transition to IDLE
        assert controller.state == AppState.IDLE
        assert state_changes[-1] == AppState.IDLE
        assert len(notifications) == 1
        assert "Recording Finished" in notifications[0][1]


def test_controller_zero_duration_stop(tmp_path):
    state_changes = []
    notifications = []

    controller = TscribeController(
        recordings_dir=tmp_path,
        on_state_change=state_changes.append,
        on_notification=lambda t, s, m: notifications.append((t, s, m)),
    )

    zero_result = RecordingResult(
        path=tmp_path / "rec.wav",
        duration_seconds=0.0,
        sample_rate=16000,
        channels=1,
        device_name="default",
        source_type="microphone",
    )

    mock_rec_instance = MagicMock()
    mock_rec_instance.record.return_value = zero_result

    with patch("tscribe.app.AudioRecorder", return_value=mock_rec_instance), \
         patch("tscribe.app.Transcriber") as mock_transcriber_cls:
        controller.start_recording()
        controller.stop_recording()
        if controller._worker_thread:
            controller._worker_thread.join(timeout=2.0)

        assert controller.state == AppState.IDLE
        # Transcriber should not be called for zero duration
        mock_transcriber_cls.return_value.transcribe.assert_not_called()
        assert any("Cancelled" in n[1] for n in notifications)
