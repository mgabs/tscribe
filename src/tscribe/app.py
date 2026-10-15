"""macOS menu bar application for tscribe using rumps."""

from __future__ import annotations

import enum
import logging
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from tscribe.config import TscribeConfig
from tscribe.desktop import RESOURCE_DIR
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
            device=getattr(config, "device", None),
        )
        recorder = _create_recorder(rec_config)
        recorder.start(output_path, rec_config)
        stop_event.wait()
        return recorder.stop()


class AppState(str, enum.Enum):
    IDLE = "IDLE"
    RECORDING = "RECORDING"
    TRANSCRIBING = "TRANSCRIBING"
    SAVING = "SAVING"


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
        config: Optional[TscribeConfig] = None,
    ):
        self.config = config if config is not None else TscribeConfig.load(get_config_path())
        if recordings_dir is None:
            recordings_dir = get_recordings_dir(get_data_dir(self.config.storage.data_dir))
        self.mgr = SessionManager(recordings_dir)
        self.state = AppState.IDLE
        self.on_state_change = on_state_change
        self.on_notification = on_notification
        self.start_time: float = 0.0
        self.current_stem: Optional[str] = None
        self.current_wav: Optional[Path] = None
        self.diarize: bool = self.config.transcription.diarize
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

    def elapsed_seconds(self) -> float:
        if self.state == AppState.RECORDING and self.start_time > 0:
            return time.monotonic() - self.start_time
        return 0.0

    def start_recording(self, use_mic: bool = True, diarize: bool | None = None) -> None:
        if self.state != AppState.IDLE:
            return

        if diarize is not None:
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
        # Publish the stopping state before waking the worker; otherwise a fast
        # worker can finish and have its IDLE state overwritten by this thread.
        self.state = AppState.TRANSCRIBING if self.config.recording.auto_transcribe else AppState.SAVING
        if self.on_state_change:
            self.on_state_change(self.state)
        self._stop_event.set()

    def _run_recording_and_transcription(self, use_mic: bool) -> None:
        try:
            recorder = AudioRecorder()
            defaults = self.config.recording
            device = (defaults.default_device or None) if use_mic else None
            if device and device.isdigit():
                device = int(device)
            cfg = RecordingConfig(
                sample_rate=defaults.sample_rate,
                channels=defaults.channels,
                device=device,
                loopback=not use_mic,
            )
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

            if not defaults.auto_transcribe:
                if self.on_notification:
                    self.on_notification("tscribe", "Recording Saved", str(self.current_wav))
                return

            transcription = self.config.transcription
            transcriber = Transcriber(
                model_name=transcription.model,
                device="cuda" if transcription.gpu else "cpu",
            )
            result = transcriber.transcribe(
                self.current_wav,
                diarize=self.diarize,
                language=transcription.language,
                output_formats=transcription.output_formats,
            )

            self.mgr.update_metadata(
                self.current_stem, transcribed=True, model=transcription.model
            )

            dur_str = f"{int(rec_result.duration_seconds)}s"
            preview = result.to_txt()[:60]
            if len(result.to_txt()) > 60:
                preview += "..."

            if self.on_notification:
                self.on_notification("tscribe", f"Recording Finished ({dur_str})", preview)

        except Exception as e:
            logging.exception("Recording or transcription failed")
            if self.on_notification:
                self.on_notification("tscribe", "Error", str(e))
        finally:
            self.state = AppState.IDLE
            if self.on_state_change:
                self.on_state_change(self.state)


def _ensure_python_bundle_id() -> None:
    try:
        plist_path = Path(sys.executable).parent / "Info.plist"
        if not plist_path.exists():
            plist_path.write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                '<plist version="1.0">\n'
                '<dict>\n'
                '    <key>CFBundleIdentifier</key>\n'
                '    <string>com.tscribe.app</string>\n'
                '    <key>CFBundleName</key>\n'
                '    <string>tscribe</string>\n'
                '</dict>\n'
                '</plist>\n'
            )
    except Exception:
        pass


_ensure_python_bundle_id()

try:
    import rumps
except ImportError:
    rumps = None


class TscribeApp(rumps.App if rumps is not None else object):  # type: ignore[misc]
    """macOS status bar application using rumps."""

    def __init__(
        self, recordings_dir: Optional[Path] = None, diarize: bool | None = None,
        config: Optional[TscribeConfig] = None,
    ):
        if rumps is None:
            raise RuntimeError("rumps is required for TscribeApp.")
        super().__init__(
            name="tscribe", title=None, icon=str(RESOURCE_DIR / 'menu_icon.png'),
            template=True, quit_button=None,
        )
        self._events = queue.SimpleQueue()
        self._quit_when_idle = False
        try:
            from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
            NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        except Exception:
            pass
        if getattr(self, "_menu", None) is None:
            self._menu = rumps.rumps.Menu()
        self.title = None
        self.controller = TscribeController(
            recordings_dir=recordings_dir,
            on_state_change=self._on_state_change,
            on_notification=self._on_notification,
            config=config,
        )
        if diarize is not None:
            self.controller.diarize = diarize
        self._build_menu()

    def _build_menu(self):
        # Menu items: Record Mic, Record System, Stop, Diarize Checkbox, Copy, Open, Recent, Quit
        self.item_rec_mic = rumps.MenuItem("🔴 Record Microphone", callback=self.on_record_mic)
        self.item_rec_sys = rumps.MenuItem("💻 Record System Audio", callback=self.on_record_sys)
        stop_title = "⏹️ Stop & Transcribe" if self.controller.config.recording.auto_transcribe else "⏹️ Stop Recording"
        self.item_stop = rumps.MenuItem(stop_title, callback=self.on_stop)
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
            rumps.MenuItem("⚙️ Open Configuration", callback=self.on_open_config),
            rumps.MenuItem("📁 Open Recordings Folder", callback=self.on_open_recordings),
            None,
            rumps.MenuItem("❌ Quit tscribe", callback=self.on_quit),
        ]

        self.timer = rumps.Timer(self._on_timer_tick, 1)
        self.timer.start()

    def _refresh_recent_menu(self):
        if getattr(self.menu_recent, "_menu", None) is not None:
            self.menu_recent.clear()
        sessions = self.controller.mgr.list_sessions(limit=self.controller.config.app.recent_limit, sort_by="date")
        if not sessions:
            self.menu_recent.add(rumps.MenuItem("No past recordings"))
            return
        for s in sessions:
            dur = f"{int(s.duration_seconds or 0)}s"
            title = f"{s.stem} ({dur})"
            item = rumps.MenuItem(title, callback=lambda sender, stem=s.stem: self._open_session(stem))
            self.menu_recent.add(item)

    def _dispatch(self, callback, *args):
        if threading.current_thread() is threading.main_thread():
            callback(*args)
        else:
            self._events.put((callback, args))

    def _on_state_change(self, state):
        self._dispatch(self._handle_state_change, state)

    def _on_notification(self, title, subtitle, message):
        self._dispatch(self._handle_notification, title, subtitle, message)

    def _on_timer_tick(self, _):
        # rumps.Timer fires on the Cocoa run loop. Native menus and notifications
        # must only be touched here or from a main-thread menu callback.
        while True:
            try:
                callback, args = self._events.get_nowait()
            except queue.Empty:
                break
            callback(*args)
        if self._quit_when_idle and self.controller.state == AppState.IDLE:
            rumps.quit_application()
            return
        if self.controller.state == AppState.RECORDING:
            elapsed = self.controller.elapsed_seconds()
            self.title = (
                f"🔴 {format_elapsed_time(elapsed)}"
                if self.controller.config.app.show_elapsed_time else "🔴 Recording"
            )
        elif self.controller.state == AppState.TRANSCRIBING:
            self.title = "⏳ Transcribing..."
        elif self.controller.state == AppState.SAVING:
            self.title = "Saving..."
        else:
            self.title = None

    def _handle_state_change(self, state: AppState):
        self.item_diarize.set_callback(self.on_toggle_diarize if state == AppState.IDLE else None)
        if state == AppState.RECORDING:
            self.item_rec_mic.set_callback(None)
            self.item_rec_sys.set_callback(None)
            self.item_stop.set_callback(self.on_stop)
        elif state in (AppState.TRANSCRIBING, AppState.SAVING):
            self.item_rec_mic.set_callback(None)
            self.item_rec_sys.set_callback(None)
            self.item_stop.set_callback(None)
        else:
            self.item_rec_mic.set_callback(self.on_record_mic)
            self.item_rec_sys.set_callback(self.on_record_sys)
            self.item_stop.set_callback(None)
            self._refresh_recent_menu()

    def _handle_notification(self, title: str, subtitle: str, message: str):
        if not self.controller.config.app.notifications:
            return
        if rumps is not None:
            try:
                rumps.notification(title, subtitle, message)
            except Exception:
                pass

    def on_quit(self, _):
        if self.controller.state == AppState.IDLE:
            rumps.quit_application()
            return
        self._quit_when_idle = True
        if self.controller.state == AppState.RECORDING:
            self.controller.stop_recording()
        self._handle_notification("tscribe", "Finishing recording", "tscribe will quit when saving and transcription finish.")

    def on_open_config(self, _):
        path = get_config_path()
        if not path.exists():
            self.controller.config.save(path)
        subprocess.run(["open", "-t", str(path)])

    def on_open_recordings(self, _):
        subprocess.run(["open", str(self.controller.mgr.recordings_dir)])

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
            if copy_to_clipboard(session.txt_path.read_text()):
                self._handle_notification("tscribe", "", "Copied transcript to clipboard")
            else:
                self._handle_notification("tscribe", "Copy failed", "Could not copy transcript to clipboard.")

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
        super().run()

