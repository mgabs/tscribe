"""macOS menu bar application for tscribe using rumps."""

from __future__ import annotations

import enum
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from tscribe.config import TscribeConfig
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


try:
    import rumps
except ImportError:
    rumps = None


class TscribeApp(rumps.App if rumps is not None else object):  # type: ignore[misc]
    """macOS status bar application using rumps."""

    def __init__(self, recordings_dir: Optional[Path] = None, diarize: bool = False):
        if rumps is None:
            raise RuntimeError("rumps is required for TscribeApp.")
        super().__init__(name="tscribe", title="🎙️ tscribe")
        try:
            from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
            NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        except Exception:
            pass
        if getattr(self, "_menu", None) is None:
            self._menu = rumps.rumps.Menu()
        self.app = self
        self.title = "🎙️ tscribe"
        self.controller = TscribeController(
            recordings_dir=recordings_dir,
            on_state_change=self._handle_state_change,
            on_notification=self._handle_notification,
        )
        self.controller.diarize = diarize
        self._build_menu()

    def _build_menu(self):
        # Menu items: Record Mic, Record System, Stop, Diarize Checkbox, Copy, Open, Recent, Quit
        self.item_rec_mic = rumps.MenuItem("🔴 Record Microphone", callback=self.on_record_mic)
        self.item_rec_sys = rumps.MenuItem("💻 Record System Audio", callback=self.on_record_sys)
        self.item_stop = rumps.MenuItem("⏹️ Stop & Transcribe", callback=self.on_stop)
        self.item_stop.set_callback(None)  # Disabled initially

        self.item_diarize = rumps.MenuItem("✓ Diarize Speakers", callback=self.on_toggle_diarize)
        self.item_diarize.state = 1 if self.controller.diarize else 0

        self.item_copy = rumps.MenuItem("📋 Copy Last Transcript", callback=self.on_copy_last)
        self.item_open = rumps.MenuItem("📄 Open Last Transcript", callback=self.on_open_last)
        self.menu_recent = rumps.MenuItem("📂 Recent Recordings")
        self._refresh_recent_menu()

        self.menu = [
            self.item_rec_mic,
            self.item_rec_sys,
            self.item_stop,
            None,
            self.item_diarize,
            None,
            self.item_copy,
            self.item_open,
            self.menu_recent,
            None,
            rumps.MenuItem("❌ Quit tscribe", callback=rumps.quit_application),
        ]

        self.timer = rumps.Timer(self._on_timer_tick, 1)
        self.timer.start()

    def _refresh_recent_menu(self):
        if getattr(self.menu_recent, "_menu", None) is not None:
            self.menu_recent.clear()
        sessions = self.controller.mgr.list_sessions(limit=5, sort_by="date")
        if not sessions:
            self.menu_recent.add(rumps.MenuItem("No past recordings"))
            return
        for s in sessions:
            dur = f"{int(s.duration_seconds or 0)}s"
            title = f"{s.stem} ({dur})"
            item = rumps.MenuItem(title, callback=lambda sender, stem=s.stem: self._open_session(stem))
            self.menu_recent.add(item)

    def _on_timer_tick(self, _):
        if self.controller.state == AppState.RECORDING:
            elapsed = self.controller.elapsed_seconds()
            self.title = f"🔴 {format_elapsed_time(elapsed)}"
        elif self.controller.state == AppState.TRANSCRIBING:
            self.title = "⏳ Transcribing..."
        else:
            self.title = "🎙️ tscribe"

    def _handle_state_change(self, state: AppState):
        if state == AppState.RECORDING:
            self.item_rec_mic.set_callback(None)
            self.item_rec_sys.set_callback(None)
            self.item_stop.set_callback(self.on_stop)
        elif state == AppState.TRANSCRIBING:
            self.item_rec_mic.set_callback(None)
            self.item_rec_sys.set_callback(None)
            self.item_stop.set_callback(None)
        else:
            self.item_rec_mic.set_callback(self.on_record_mic)
            self.item_rec_sys.set_callback(self.on_record_sys)
            self.item_stop.set_callback(None)
            self._refresh_recent_menu()

    def _handle_notification(self, title: str, subtitle: str, message: str):
        if rumps is not None:
            try:
                rumps.notification(title, subtitle, message)
                return
            except Exception:
                pass
        full_msg = f"{subtitle}\n{message}".strip() if subtitle else message
        try:
            cmd = ["osascript", "-e", f'display notification "{full_msg}" with title "{title}"']
            subprocess.run(cmd, check=False)
        except Exception:
            pass

    def on_record_mic(self, _):
        self.controller.start_recording(use_mic=True, diarize=bool(self.item_diarize.state))

    def on_record_sys(self, _):
        self.controller.start_recording(use_mic=False, diarize=bool(self.item_diarize.state))

    def on_stop(self, _):
        self.controller.stop_recording()

    def on_toggle_diarize(self, sender):
        sender.state = 0 if sender.state else 1
        self.controller.diarize = bool(sender.state)

    def _get_last_session(self):
        sessions = self.controller.mgr.list_sessions(limit=1, sort_by="date")
        if sessions:
            return sessions[0]
        return self.controller.mgr.get_session("HEAD")

    def on_copy_last(self, _):
        session = self._get_last_session()
        if session and session.txt_path and session.txt_path.exists():
            copy_to_clipboard(session.txt_path.read_text())
            self._handle_notification("tscribe", "", "Copied transcript to clipboard")

    def on_open_last(self, _):
        session = self._get_last_session()
        if session and session.txt_path and session.txt_path.exists():
            subprocess.run(["open", str(session.txt_path)])
        elif session and session.wav_path and session.wav_path.exists():
            subprocess.run(["open", str(session.wav_path)])

    def _open_session(self, stem: str):
        session = self.controller.mgr.get_session(stem)
        if session and session.txt_path and session.txt_path.exists():
            subprocess.run(["open", str(session.txt_path)])
        elif session and session.wav_path and session.wav_path.exists():
            subprocess.run(["open", str(session.wav_path)])
        else:
            txt_path = self.controller.mgr.recordings_dir / f"{stem}.txt"
            if txt_path.exists():
                subprocess.run(["open", str(txt_path)])

    def run(self):
        try:
            from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
            NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        except Exception:
            pass
        self._handle_notification("tscribe", "Active in Menu Bar", "Click 🎙️ tscribe near clock (top right)")
        super().run()

