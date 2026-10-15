"""macOS menu bar application for tscribe using rumps."""

from __future__ import annotations

import enum
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from tscribe.config import RecordingDefaults, TscribeConfig
from tscribe.paths import get_config_path, get_data_dir, get_recordings_dir
from tscribe.recorder.base import RecordingConfig, RecordingResult
from tscribe.session import SessionManager
from tscribe.transcriber import Transcriber


class AudioRecorder:
    """Wrapper around tscribe audio recorders for simple start/stop execution."""

    def record(self, output_path: Path, config: Any, stop_event: threading.Event) -> RecordingResult:
        from tscribe.cli import _create_recorder

        rec_config = RecordingConfig(
            sample_rate=getattr(config, "sample_rate", 16000),
            channels=getattr(config, "channels", 1),
            loopback=getattr(config, "loopback", False),
        )
        recorder = _create_recorder(rec_config)
        recorder.start(output_path, rec_config)
        stop_event.wait()
        return recorder.stop()


class AppState(str, enum.Enum):
    IDLE = "IDLE"
    RECORDING = "RECORDING"
    TRANSCRIBING = "TRANSCRIBING"


def format_elapsed_time(seconds: float) -> str:
    """Format elapsed seconds into MM:SS or HH:MM:SS."""
    sec = max(0, int(seconds))
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def copy_to_clipboard(text: str) -> bool:
    """Copy text to macOS clipboard via pbcopy."""
    if not text:
        return False
    try:
        proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        proc.communicate(text.encode("utf-8"))
        return proc.returncode == 0
    except OSError:
        return False


class TscribeController:
    """Coordinates background audio recording and transcription for the menu bar app."""

    def __init__(
        self,
        recordings_dir: Optional[Path] = None,
        on_state_change: Optional[Callable[[AppState], None]] = None,
        on_notification: Optional[Callable[[str, str, str], None]] = None,
    ):
        if recordings_dir is None:
            cfg = TscribeConfig.load(get_config_path(get_data_dir()))
            recordings_dir = get_recordings_dir(get_data_dir(cfg.storage.data_dir))
        self.mgr = SessionManager(recordings_dir)
        self.state = AppState.IDLE
        self.on_state_change = on_state_change
        self.on_notification = on_notification
        self.start_time: float = 0.0
        self.current_stem: Optional[str] = None
        self.current_wav: Optional[Path] = None
        self.diarize: bool = False
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

    def elapsed_seconds(self) -> float:
        if self.state == AppState.RECORDING and self.start_time > 0:
            return time.monotonic() - self.start_time
        return 0.0

    def start_recording(self, use_mic: bool = True, diarize: bool = False) -> None:
        if self.state != AppState.IDLE:
            return

        self.diarize = diarize
        self.state = AppState.RECORDING
        self.start_time = time.monotonic()
        self._stop_event.clear()

        self.current_stem = self.mgr.generate_session_stem()
        self.current_wav = self.mgr.recordings_dir / f"{self.current_stem}.wav"

        if self.on_state_change:
            self.on_state_change(self.state)

        self._worker_thread = threading.Thread(
            target=self._run_recording_and_transcription,
            args=(use_mic,),
            daemon=True,
        )
        self._worker_thread.start()

    def stop_recording(self) -> None:
        if self.state != AppState.RECORDING:
            return
        self._stop_event.set()
        self.state = AppState.TRANSCRIBING
        if self.on_state_change:
            self.on_state_change(self.state)

    def _run_recording_and_transcription(self, use_mic: bool) -> None:
        try:
            recorder = AudioRecorder()
            cfg = RecordingConfig(sample_rate=16000, channels=1, loopback=not use_mic)
            rec_result = recorder.record(
                output_path=self.current_wav,
                config=cfg,
                stop_event=self._stop_event,
            )

            if not rec_result or rec_result.duration_seconds <= 0:
                if self.on_notification:
                    self.on_notification("tscribe", "Cancelled", "Recording was empty or cancelled.")
                return

            metadata = self.mgr.create_metadata(rec_result)
            self.mgr.write_metadata(self.current_stem, metadata)

            transcriber = Transcriber()
            result = transcriber.transcribe(
                self.current_wav,
                diarize=self.diarize,
                output_formats=["txt", "json"],
            )

            txt_path = self.mgr.recordings_dir / f"{self.current_stem}.txt"
            txt_path.write_text(result.to_txt())
            json_path = self.mgr.recordings_dir / f"{self.current_stem}.json"
            import json as json_mod

            json_path.write_text(json_mod.dumps(result.to_json(), indent=2))
            self.mgr.update_metadata(self.current_stem, transcribed=True)

            dur_str = f"{int(rec_result.duration_seconds)}s"
            preview = result.to_txt()[:60]
            if len(result.to_txt()) > 60:
                preview += "..."

            if self.on_notification:
                self.on_notification("tscribe", f"Recording Finished ({dur_str})", preview)

        except Exception as e:
            if self.on_notification:
                self.on_notification("tscribe", "Error", str(e))
        finally:
            self.state = AppState.IDLE
            if self.on_state_change:
                self.on_state_change(self.state)
