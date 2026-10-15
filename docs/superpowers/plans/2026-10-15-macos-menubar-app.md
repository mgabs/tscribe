# macOS Menu Bar App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a native macOS menu bar status item application for `tscribe` (`tscribe app`) supporting one-click microphone/system recording, live timer status, background transcription, speaker diarization toggle, and desktop `.app` launcher creation.

**Architecture:** A `rumps.App` instance running the Cocoa event loop on the main thread, coordinating with an asynchronous background worker thread that controls `AudioRecorder`, `SessionManager`, and `Transcriber`.

**Tech Stack:** Python 3.10+, `rumps` (Cocoa PyObjC), `click`, macOS CoreAudio / BlackHole.

**Spec:** [`docs/superpowers/specs/2026-10-15-macos-menubar-app-design.md`](file:///Users/mohammed.metawea/Workbench/interests/tscribe/docs/superpowers/specs/2026-10-15-macos-menubar-app-design.md)

## Global Constraints

- Only runs on macOS (`sys.platform == 'darwin'`).
- Running `tscribe app` on Linux or Windows must exit immediately with a clear error without importing Cocoa.
- Audio recording and Whisper transcription must never block the main Cocoa UI event loop.
- All shell commands must be prefixed with `rtk `.

## Review Focus

1. Starting a recording while another is active must be prevented by state checks.
2. Clicking "Stop" before any audio frames are written should cleanly handle zero-duration recordings without crashing.
3. Non-Darwin platforms running `tscribe app` must exit with `click.ClickException("The 'app' command is only supported on macOS.")`.
4. Copying to clipboard should handle empty or missing transcripts gracefully.
5. Desktop `.app` generation must create valid directory structure in `~/Applications/` with executable permissions.

---

### Task 1: Add Dependency & App State / Controller Logic

**Files:**
- Modify: `pyproject.toml`
- Create: `src/tscribe/app.py`
- Test: `tests/test_app_logic.py`

**Interfaces:**
- Consumes: `SessionManager`, `Transcriber`, `AudioRecorder`.
- Produces: `format_elapsed_time(seconds: float) -> str`, `AppState`, `copy_to_clipboard(text: str)`, `TscribeController`.

- [ ] **Step 1: Write failing tests for app controller logic**

```python
# tests/test_app_logic.py
import pytest
from tscribe.app import AppState, copy_to_clipboard, format_elapsed_time


def test_format_elapsed_time():
    assert format_elapsed_time(0.0) == "00:00"
    assert format_elapsed_time(45.2) == "00:45"
    assert format_elapsed_time(125.0) == "02:05"
    assert format_elapsed_time(3665.0) == "01:01:05"


def test_app_state_enum():
    assert AppState.IDLE.value == "IDLE"
    assert AppState.RECORDING.value == "RECORDING"
    assert AppState.TRANSCRIBING.value == "TRANSCRIBING"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk uv run pytest tests/test_app_logic.py -v`  
Expected: FAIL (`ModuleNotFoundError: No module named 'tscribe.app'`).

- [ ] **Step 3: Add `rumps` to `pyproject.toml` and implement `src/tscribe/app.py` core logic**

Add `"rumps>=0.4.0; sys_platform == 'darwin'"` to `pyproject.toml`, run `uv sync`, and create `src/tscribe/app.py`:

```python
# src/tscribe/app.py
from __future__ import annotations

import enum
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from tscribe.config import TscribeConfig
from tscribe.paths import get_config_path, get_data_dir, get_recordings_dir
from tscribe.session import SessionManager
from tscribe.transcriber import Transcriber


class AppState(str, enum.Enum):
    IDLE = "IDLE"
    RECORDING = "RECORDING"
    TRANSCRIBING = "TRANSCRIBING"


def format_elapsed_time(seconds: float) -> str:
    """Format elapsed seconds into MM:SS or HH:MM:SS."""
    sec = int(seconds)
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
        if self.on_state_change:
            self.on_state_change(self.state)

        # Worker starts recording
        # (AudioRecorder integration wrapped in thread)

    def stop_recording(self) -> None:
        if self.state != AppState.RECORDING:
            return
        self._stop_event.set()
        self.state = AppState.TRANSCRIBING
        if self.on_state_change:
            self.on_state_change(self.state)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk uv run pytest tests/test_app_logic.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add pyproject.toml uv.lock src/tscribe/app.py tests/test_app_logic.py
rtk git commit -m "feat(app): add controller and state helpers for menu bar app"
```

---

### Task 2: Build `TscribeApp(rumps.App)` Menu Bar UI

**Files:**
- Modify: `src/tscribe/app.py`
- Test: `tests/test_app_ui.py`

**Interfaces:**
- Consumes: `rumps.App`, `TscribeController`, `SessionManager`.
- Produces: `TscribeApp` runnable class with dynamic title timer and menu actions.

- [ ] **Step 1: Write tests for menu structure and callbacks**

```python
# tests/test_app_ui.py
from unittest.mock import MagicMock, patch
import pytest
from tscribe.app import AppState, TscribeApp, TscribeController


def test_tscribe_app_initial_state(tmp_path):
    with patch("rumps.App.__init__", return_value=None):
        app = TscribeApp(recordings_dir=tmp_path)
        app.title = "🎙️"
        assert app.controller.state == AppState.IDLE


def test_tscribe_app_timer_tick(tmp_path):
    with patch("rumps.App.__init__", return_value=None):
        app = TscribeApp(recordings_dir=tmp_path)
        app.controller.state = AppState.RECORDING
        app.controller.start_time = 100.0
        with patch("time.monotonic", return_value=125.0):
            app._on_timer_tick(None)
            assert "00:25" in app.title
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk uv run pytest tests/test_app_ui.py -v`  
Expected: FAIL (`AttributeError: 'TscribeApp' not defined`).

- [ ] **Step 3: Implement `TscribeApp` in `src/tscribe/app.py`**

```python
# append to src/tscribe/app.py
try:
    import rumps
except ImportError:
    rumps = None


class TscribeApp:
    """macOS status bar application using rumps."""

    def __init__(self, recordings_dir: Optional[Path] = None, diarize: bool = False):
        if rumps is None:
            raise RuntimeError("rumps is required for TscribeApp.")
        self.app = rumps.App(name="tscribe", title="🎙️")
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

        self.app.menu = [
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
            self.app.title = f"🔴 {format_elapsed_time(elapsed)}"
        elif self.controller.state == AppState.TRANSCRIBING:
            self.app.title = "⏳ Transcribing..."
        else:
            self.app.title = "🎙️"

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
        rumps.notification(title, subtitle, message)

    def on_record_mic(self, _):
        self.controller.start_recording(use_mic=True, diarize=bool(self.item_diarize.state))

    def on_record_sys(self, _):
        self.controller.start_recording(use_mic=False, diarize=bool(self.item_diarize.state))

    def on_stop(self, _):
        self.controller.stop_recording()

    def on_toggle_diarize(self, sender):
        sender.state = not sender.state
        self.controller.diarize = bool(sender.state)

    def on_copy_last(self, _):
        session = self.controller.mgr.get_session("HEAD")
        if session and session.txt_path and session.txt_path.exists():
            copy_to_clipboard(session.txt_path.read_text())
            rumps.notification("tscribe", "", "Copied transcript to clipboard")

    def on_open_last(self, _):
        session = self.controller.mgr.get_session("HEAD")
        if session and session.txt_path and session.txt_path.exists():
            subprocess.run(["open", str(session.txt_path)])

    def _open_session(self, stem: str):
        session = self.controller.mgr.get_session(stem)
        if session and session.txt_path and session.txt_path.exists():
            subprocess.run(["open", str(session.txt_path)])

    def run(self):
        self.app.run()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk uv run pytest tests/test_app_ui.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add src/tscribe/app.py tests/test_app_ui.py
rtk git commit -m "feat(app): implement TscribeApp menu bar UI and actions"
```

---

### Task 3: CLI Command `tscribe app` & Desktop Launcher

**Files:**
- Modify: `src/tscribe/cli.py`
- Test: `tests/test_cli_app.py`

**Interfaces:**
- Consumes: `TscribeApp`, Click CLI.
- Produces: `tscribe app [--diarize] [--install-desktop]`.

- [ ] **Step 1: Write CLI tests for platform check and options**

```python
# tests/test_cli_app.py
from unittest.mock import patch
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
        assert (tmp_path / "Applications" / "tscribe.app").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk uv run pytest tests/test_cli_app.py -v`  
Expected: FAIL (`No such command 'app'`).

- [ ] **Step 3: Implement `app` command in `src/tscribe/cli.py`**

```python
# append to src/tscribe/cli.py
@main.command()
@click.option("--diarize/--no-diarize", default=False, help="Enable speaker diarization by default.")
@click.option("--install-desktop", is_flag=True, help="Create ~/Applications/tscribe.app launcher.")
def app(diarize, install_desktop):
    """Launch macOS menu bar status item app."""
    if sys.platform != "darwin":
        raise click.ClickException("The 'app' command is only supported on macOS.")

    if install_desktop:
        app_dir = Path.home() / "Applications" / "tscribe.app" / "Contents" / "MacOS"
        app_dir.mkdir(parents=True, exist_ok=True)
        script_path = app_dir / "tscribe"
        # Executable launcher script
        script_content = f"""#!/bin/bash
exec {sys.executable} -m tscribe.cli app
"""
        script_path.write_text(script_content)
        script_path.chmod(0o755)
        click.echo(f"Installed desktop launcher: {Path.home() / 'Applications' / 'tscribe.app'}")
        return

    from tscribe.app import TscribeApp

    app_instance = TscribeApp(diarize=diarize)
    click.echo("Running tscribe in macOS menu bar... (Click ❌ Quit in menu to exit)")
    app_instance.run()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk uv run pytest tests/test_cli_app.py -v`  
Expected: PASS.

- [ ] **Step 5: Full test suite verification**

Run: `rtk uv run pytest -m "not slow"`  
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
rtk git add src/tscribe/cli.py tests/test_cli_app.py
rtk git commit -m "feat(cli): add tscribe app command and desktop launcher installer"
```
