"""CLI entry point for tscribe."""

import collections
import signal
import sys
import threading
import time

from pathlib import Path
import click

from tscribe import __version__


def _load_config():
    from tscribe.config import TscribeConfig
    from tscribe.paths import get_config_path

    path = get_config_path()
    try:
        return TscribeConfig.load(path)
    except (ValueError, OSError) as exc:
        raise click.ClickException(f"Cannot load config {path}: {exc}") from exc


def _session_manager(cfg=None, ensure: bool = False):
    """Build a SessionManager for the configured recordings directory."""
    from tscribe.paths import ensure_dirs, get_data_dir, get_recordings_dir
    from tscribe.session import SessionManager

    cfg = cfg or _load_config()
    data_dir = get_data_dir(cfg.storage.data_dir)
    if ensure:
        ensure_dirs(data_dir)
    return SessionManager(get_recordings_dir(data_dir))


def _ref_map(mgr) -> dict[str, str]:
    """Map session stems to HEAD/HEAD~N refs (newest first)."""
    sessions = mgr.list_sessions(limit=None, sort_by="date")
    return {s.stem: (f"HEAD~{i}" if i else "HEAD") for i, s in enumerate(sessions)}


def _transcription_progress(current: float, total: float, start_time: float) -> None:
    """Render an in-place progress bar for transcription."""
    frac = min(current / total, 1.0) if total > 0 else 0.0
    elapsed = time.monotonic() - start_time

    cur_m, cur_s = divmod(int(current), 60)
    tot_m, tot_s = divmod(int(total), 60)

    filled = int(frac * 30)
    bar = "█" * filled + "░" * (30 - filled)

    icon = click.style("⟳", fg="yellow")

    if current > 0 and elapsed > 0:
        rate = current / elapsed
        remaining = (total - current) / rate
        eta_m, eta_s = divmod(int(remaining), 60)
        eta_str = f"  ETA {eta_m:02d}:{eta_s:02d}"
    else:
        eta_str = ""

    click.echo(
        f"\r  {icon} {cur_m:02d}:{cur_s:02d}/{tot_m:02d}:{tot_s:02d}  |{bar}|{eta_str}  ",
        nl=False,
    )


def _default_loopback() -> bool:
    """Whether to default to loopback (system audio) recording."""
    if sys.platform == "linux":
        from tscribe.pipewire_devices import is_pipewire_available

        return is_pipewire_available()
    if sys.platform == "win32":
        try:
            import pyaudiowpatch  # noqa: F401

            return True  # WASAPI loopback available for any output device
        except ImportError:
            pass
    if sys.platform in ("win32", "darwin"):
        try:
            from tscribe.devices import list_devices

            return any(d.is_loopback for d in list_devices(loopback_only=True))
        except Exception:
            return False
    return False


def _macos_loopback_preflight():
    """Check macOS loopback prerequisites; guide, warn, or offer auto-switch.

    Returns (loopback_ok, original_device):
      loopback_ok: True if loopback recording can proceed, False to fall back to mic.
      original_device: The output device name to restore after recording, or None.
    """
    import shutil
    import subprocess

    from tscribe.devices import list_devices

    loopback_devices = list_devices(loopback_only=True)
    if not loopback_devices:
        click.echo(
            click.style("Warning: ", fg="yellow")
            + "No loopback audio device found — recording from microphone instead."
        )
        click.echo(
            "To capture system audio on macOS, see: "
            "docs/macos-system-audio.md"
        )
        return False, None

    # BlackHole (or similar) is available
    if not shutil.which("SwitchAudioSource"):
        click.echo()
        click.echo(
            click.style("Tip: ", fg="cyan")
            + "Install switchaudio-osx to let tscribe auto-switch your audio output "
            "for loopback recording:"
        )
        click.echo("  brew install switchaudio-osx")
        click.echo()
        return True, None

    # SwitchAudioSource is available — try to auto-switch
    try:
        current = subprocess.check_output(
            ["SwitchAudioSource", "-c"], text=True
        ).strip()
        output_devices = subprocess.check_output(
            ["SwitchAudioSource", "-a", "-t", "output"], text=True
        ).strip().splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return True, None

    multi_output = None
    for dev in output_devices:
        if "multi-output" in dev.lower():
            multi_output = dev.strip()
            break

    if not multi_output:
        click.echo(
            click.style("Note: ", fg="yellow")
            + "No Multi-Output Device found. Create one in Audio MIDI Setup "
            "to enable auto-switching."
        )
        click.echo("See: docs/macos-system-audio.md")
        return True, None

    if current.lower() == multi_output.lower():
        return True, None  # already using it

    if click.confirm(
        f"Switch audio output to '{multi_output}' for system audio capture? "
        f"(will restore '{current}' on stop)"
    ):
        try:
            subprocess.check_call(
                ["SwitchAudioSource", "-s", multi_output],
                stdout=subprocess.DEVNULL,
            )
            click.echo(f"Switched output to '{multi_output}'.")
            return True, current
        except subprocess.CalledProcessError:
            click.echo(
                click.style("Warning: ", fg="yellow")
                + "Failed to switch audio output. Recording anyway."
            )
            return True, None

    return True, None


def _macos_restore_audio(device_name):
    """Restore macOS audio output to the given device."""
    import subprocess

    try:
        subprocess.check_call(
            ["SwitchAudioSource", "-s", device_name],
            stdout=subprocess.DEVNULL,
        )
        click.echo(f"Restored audio output to '{device_name}'.")
    except (subprocess.CalledProcessError, FileNotFoundError):
        click.echo(
            click.style("Warning: ", fg="yellow")
            + f"Failed to restore audio output to '{device_name}'."
        )


def _create_recorder(rec_config):
    """Create the appropriate recorder based on platform and config.

    Linux + PipeWire → PipewireRecorder
    Windows + loopback → WasapiRecorder (WASAPI loopback via PyAudioWPatch)
    Everything else → SounddeviceRecorder
    """
    if sys.platform == "linux":
        from tscribe.pipewire_devices import is_pipewire_available

        if is_pipewire_available():
            from tscribe.recorder.pipewire_recorder import PipewireRecorder

            return PipewireRecorder()

    if sys.platform == "win32" and rec_config.loopback:
        try:
            from tscribe.recorder.wasapi_recorder import WasapiRecorder

            return WasapiRecorder()
        except ImportError:
            pass

    from tscribe.recorder.sounddevice_recorder import SounddeviceRecorder

    return SounddeviceRecorder()


def _auto_transcribe(
    cfg,
    wav_path,
    stem,
    session_mgr,
    diarize: bool | None = None,
    diarize_engine: str | None = None,
    num_speakers: int | None = None,
    names: str | None = None,
):
    """Run transcription after recording. Handles errors gracefully."""
    from tscribe.transcriber import Transcriber

    model_name = cfg.transcription.model
    should_diarize = diarize if diarize is not None else cfg.transcription.diarize

    click.echo(f"Transcribing with model '{model_name}'...")
    try:
        transcriber = Transcriber(model_name=model_name, device="cuda" if cfg.transcription.gpu else "cpu")
        t_start = time.monotonic()

        def _progress(cur: float, total: float) -> None:
            _transcription_progress(cur, total, t_start)

        result = transcriber.transcribe(
            wav_path,
            language=cfg.transcription.language,
            output_formats=cfg.transcription.output_formats,
            progress_callback=_progress,
            diarize=should_diarize,
            diarize_engine=diarize_engine or cfg.transcription.diarize_engine,
            num_speakers=num_speakers,
            names=names,
        )
        click.echo()
        session_mgr.update_metadata(stem, transcribed=True, model=model_name)
        click.echo(f"Transcription complete: {len(result.segments)} segments.")

        if getattr(cfg.transcription, "prompt_speaker_labels", False) and not names and should_diarize:
            from tscribe.diarization import extract_speaker_samples, remap_transcript_speakers
            samples = extract_speaker_samples(result)
            if len(samples) >= 2:
                import sys
                if sys.stdin.isatty():
                    click.echo(f"\nFound {len(samples)} speakers. Label them now:")
                    mapping = {}
                    for spk in samples:
                        preview = spk['sample_text'][:40]
                        if len(spk['sample_text']) > 40:
                            preview += "..."
                        val = click.prompt(f"  {spk['raw_speaker']} (\"{preview}\")", default=spk["speaker"])
                        mapping[spk["raw_speaker"]] = val.strip()
                    remapped = remap_transcript_speakers(result, mapping)
                    json_path = wav_path.with_suffix(".json")
                    if json_path.exists():
                        json_path.write_text(json.dumps(remapped.to_json(), indent=2), encoding="utf-8")
                    for ext, render in (("txt", remapped.to_txt), ("srt", remapped.to_srt), ("vtt", remapped.to_vtt)):
                        out_path = wav_path.with_suffix(f".{ext}")
                        if out_path.exists():
                            out_path.write_text(render(), encoding="utf-8")
                    session_mgr.update_metadata(stem, speaker_map=mapping)
                    click.echo("Updated speaker labels.")
    except Exception as e:
        click.echo(f"\nTranscription failed: {e}")


@click.group()
@click.version_option(version=__version__, prog_name="tscribe")
def main():
    """Record audio and transcribe with whisper."""


@main.command()
@click.option("--device", "-d", default=None, help="Audio device name or index.")
@click.option("--loopback/--mic", default=None,
              help="Record system audio (default) or microphone.")
@click.option("--output", "-o", type=click.Path(), default=None, help="Output file path.")
@click.option("--no-transcribe", is_flag=True, help="Don't auto-transcribe after recording.")
@click.option("--sample-rate", type=int, default=None, help="Sample rate in Hz.")
@click.option("--channels", type=int, default=None, help="Number of channels.")
@click.option("--diarize/--no-diarize", default=None, help="Enable speaker diarization.")
@click.option("--diarize-engine", type=click.Choice(["nemotron", "wespeaker"]), default=None, help="Diarization engine (default: config, else nemotron).")
@click.option("--speakers", type=int, default=None, help="Expected number of speakers.")
@click.option("--names", default=None, help="Comma-separated speaker names (e.g. 'Alice,Bob').")
def record(device, loopback, output, no_transcribe, sample_rate, channels, diarize, diarize_engine, speakers, names):
    """Record audio from system audio (default) or microphone."""
    from tscribe.recorder import RecordingConfig

    cfg = _load_config()
    session_mgr = _session_manager(cfg, ensure=True)
    stem = session_mgr.generate_session_stem()

    if output:
        wav_path = Path(output)
    else:
        wav_path = session_mgr.recordings_dir / f"{stem}.wav"

    device = device or cfg.recording.default_device or None

    if loopback is None:
        loopback = False if device else _default_loopback()

    # macOS loopback preflight: detect BlackHole/SwitchAudioSource, guide user
    original_audio_output = None
    if sys.platform == "darwin" and loopback and not device:
        loopback_ok, original_audio_output = _macos_loopback_preflight()
        if not loopback_ok:
            loopback = False

    rec_config = RecordingConfig(
        sample_rate=sample_rate or cfg.recording.sample_rate,
        channels=channels or cfg.recording.channels,
        device=int(device) if device and device.isdigit() else device,
        loopback=loopback,
    )

    recorder = _create_recorder(rec_config)
    stop_event = threading.Event()

    interrupt_count = 0
    original_handler = signal.getsignal(signal.SIGINT)

    def handle_sigint(sig, frame):
        nonlocal interrupt_count
        interrupt_count += 1
        if interrupt_count >= 2:
            click.echo("\nForced exit.")
            sys.exit(1)
        click.echo("\nStopping recording...")
        stop_event.set()

    signal.signal(signal.SIGINT, handle_sigint)

    try:
        recorder.start(wav_path, rec_config)
        source = "system audio" if loopback else "microphone"
        click.echo(f"Recording {source} to {wav_path} (Ctrl+C to stop)...")

        blocks = " ▁▂▃▄▅▆▇█"
        history = collections.deque([0.0] * 20, maxlen=20)

        while not stop_event.is_set():
            elapsed = recorder.elapsed_seconds
            minutes, secs = divmod(int(elapsed), 60)
            lvl = min(recorder.level ** 0.4, 1.0)
            history.append(lvl)
            meter = "".join(blocks[int(v * 8)] for v in history)
            led = click.style("●", fg="red", blink=True)
            click.echo(f"\r  {led} REC {minutes:02d}:{secs:02d}  {meter}", nl=False)
            stop_event.wait(0.25)

        result = recorder.stop()
        if original_audio_output:
            _macos_restore_audio(original_audio_output)
            original_audio_output = None
        click.echo(f"\nRecording saved: {result.path} ({result.duration_seconds:.1f}s)")

        meta = session_mgr.create_metadata(result)
        session_mgr.write_metadata(stem, meta)

        if not no_transcribe and cfg.recording.auto_transcribe:
            _auto_transcribe(
                cfg,
                wav_path,
                stem,
                session_mgr,
                diarize=diarize,
                diarize_engine=diarize_engine,
                num_speakers=speakers,
                names=names,
            )

    finally:
        signal.signal(signal.SIGINT, original_handler)
        if original_audio_output:
            _macos_restore_audio(original_audio_output)


def _download_audio(url, output_dir):
    """Download audio from a URL using yt-dlp. Returns path to WAV file."""
    try:
        import yt_dlp
    except ImportError:
        raise click.ClickException(
            "yt-dlp is required for URL transcription. "
            "Install it with: uv pip install yt-dlp"
        )

    output_template = str(Path(output_dir) / "%(title)s.%(ext)s")
    opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "wav",
        }],
        "quiet": True,
        "no_warnings": True,
    }

    click.echo("Downloading audio from URL...")
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    # yt-dlp replaces special chars in filenames; use the prepared filename
    wav_path = Path(ydl.prepare_filename(info)).with_suffix(".wav")
    if not wav_path.exists():
        raise click.ClickException(f"Download failed: expected {wav_path.name}")

    click.echo(f"Downloaded: {wav_path.name}")
    return wav_path


@main.command()
@click.argument("source", default="HEAD")
@click.option("--model", "-m", default=None, help="Whisper model size.")
@click.option("--language", default=None, help="Language code (default: auto-detect).")
@click.option("--output", "-o", type=click.Path(), default=None, help="Output path prefix (optional transcript extension).")
@click.option("--format", "fmt", default=None, help="Output format: txt,json,srt,vtt,all")
@click.option("--gpu/--no-gpu", default=None, help="Request NVIDIA CUDA acceleration; fall back to CPU if unavailable.")
@click.option("--diarize/--no-diarize", default=None, help="Enable speaker diarization.")
@click.option("--diarize-engine", type=click.Choice(["nemotron", "wespeaker"]), default=None, help="Diarization engine (default: config, else nemotron).")
@click.option("--speakers", type=int, default=None, help="Expected number of speakers.")
@click.option("--names", default=None, help="Comma-separated speaker names (e.g. 'Alice,Bob').")
def transcribe(source, model, language, output, fmt, gpu, diarize, diarize_engine, speakers, names):
    """Transcribe an audio file, URL, or previous recording.

    \b
    SOURCE can be:
      - A local file path
      - A URL (YouTube, etc.) — requires yt-dlp
      - A recording ref: HEAD, HEAD~N, or a session stem
    """
    import tempfile
    import wave
    from datetime import datetime, timezone

    from tscribe.constants import VALID_OUTPUT_FORMATS
    from tscribe.transcriber import Transcriber

    cfg = _load_config()

    model_name = model or cfg.transcription.model
    lang = language or cfg.transcription.language

    if fmt:
        if fmt == "all":
            output_formats = list(VALID_OUTPUT_FORMATS)
        else:
            output_formats = [f.strip() for f in fmt.split(",")]
    else:
        output_formats = cfg.transcription.output_formats

    invalid_formats = set(output_formats) - set(VALID_OUTPUT_FORMATS)
    if invalid_formats:
        raise click.ClickException(f"Unknown output formats: {', '.join(sorted(invalid_formats))}")
    output_options = {}
    if output:
        output_base = Path(output).expanduser()
        if output_base.suffix.lstrip('.') in VALID_OUTPUT_FORMATS:
            output_base = output_base.with_suffix('')
        output_options['output_base'] = output_base

    is_ref = source == "HEAD" or source.startswith("HEAD~")
    is_url = "://" in source

    if is_ref:
        mgr = _session_manager(cfg, ensure=True)
        session = _resolve_session(source, mgr)
        audio_path = session.wav_path
        stem = session.stem
    elif is_url:
        mgr = _session_manager(cfg, ensure=True)
        with tempfile.TemporaryDirectory(prefix="tscribe_") as tmp_dir:
            downloaded = _download_audio(source, tmp_dir)
            stem, audio_path = mgr.import_external(downloaded)

        # Create metadata from the WAV file
        duration = 0.0
        sample_rate = 16000
        channels = 1
        try:
            with wave.open(str(audio_path), "rb") as wf:
                sample_rate = wf.getframerate()
                channels = wf.getnchannels()
                duration = wf.getnframes() / sample_rate
        except Exception:
            pass

        meta = {
            "created": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": duration,
            "sample_rate": sample_rate,
            "channels": channels,
            "device": "url",
            "source_type": "url",
            "source_url": source,
            "transcribed": False,
            "model": None,
            "original_path": None,
        }
        mgr.write_metadata(stem, meta)
    else:
        # Try as file path first, fall back to session stem
        audio_path = Path(source)
        if not audio_path.exists():
            # Maybe it's a session stem (e.g. 2025-01-15-143022)
            mgr = _session_manager(cfg, ensure=True)
            session = mgr.get_session(source)
            if session:
                audio_path = session.wav_path
                stem = session.stem
            else:
                raise click.ClickException(f"File not found: {source}")
        else:
            stem = None
            mgr = None

    device = "cuda" if (gpu if gpu is not None else cfg.transcription.gpu) else "cpu"
    transcriber = Transcriber(model_name=model_name, device=device)

    should_diarize = diarize if diarize is not None else cfg.transcription.diarize

    click.echo(f"Transcribing {audio_path.name} with model '{model_name}'...")
    t_start = time.monotonic()

    def _progress(cur: float, total: float) -> None:
        _transcription_progress(cur, total, t_start)

    result = transcriber.transcribe(
        audio_path,
        language=lang,
        output_formats=output_formats,
        progress_callback=_progress,
        diarize=should_diarize,
        diarize_engine=diarize_engine or cfg.transcription.diarize_engine,
        num_speakers=speakers,
        names=names,
        **output_options,
    )
    click.echo()

    # Update metadata if this was a URL import
    if mgr and stem:
        mgr.update_metadata(stem, transcribed=True, model=model_name)

    click.echo(f"Transcription complete: {len(result.segments)} segments.")
    for fmt_name in output_formats:
        base = output_options.get("output_base", audio_path.with_suffix(""))
        out_path = Path(f"{base}.{fmt_name}")
        if out_path.exists():
            click.echo(f"  {out_path}")


def _hyperlink(url: str, text: str | None = None) -> str:
    """Format a URL as a clickable OSC 8 hyperlink if stdout is a TTY."""
    if not sys.stdout.isatty():
        return text or url
    display = text or url
    return f"\033]8;;{url}\033\\{display}\033]8;;\033\\"


def _stem_date_str(stem: str) -> str:
    """Format a session stem with a two-char day-of-week suffix."""
    from datetime import datetime

    try:
        dt = datetime.strptime(stem[:17], "%Y-%m-%d-%H%M%S")
        day = dt.strftime("%a")[:2]
        return f"{stem} {day}"
    except ValueError:
        return stem


@main.command(name="list")
@click.option("--limit", "-n", default=20, help="Number of entries to show.")
@click.option("--search", "-s", default=None, help="Search transcript text.")
@click.option("--sort", "sort_by", default="date", type=click.Choice(["date", "duration", "name"]),
              help="Sort field.")
@click.option("--no-header", is_flag=True, help="Omit table header.")
def list_recordings(limit, search, sort_by, no_header):
    """List past recordings and their transcription status."""
    mgr = _session_manager()
    ref_map = _ref_map(mgr)

    sessions = mgr.list_sessions(limit=limit, sort_by=sort_by, search=search)
    if not sessions:
        click.echo("No recordings found.")
        return

    if not no_header:
        click.echo(f"{'REF':<7} {'Date':<22} {'Dur':>8} {'Tx':>2}  {'Source'}")
        click.echo("-" * 54)

    for s in sessions:
        ref = ref_map.get(s.stem, "?")
        date_str = _stem_date_str(s.stem)
        if s.duration_seconds is not None:
            m, sec = divmod(int(s.duration_seconds), 60)
            h, m = divmod(m, 60)
            dur_str = f"{h:02d}:{m:02d}:{sec:02d}"
        else:
            dur_str = "---"
        meta = s.metadata or {}
        source_type = meta.get("source_type", "?")
        if source_type == "url":
            url = meta.get("source_url", "")
            source = _hyperlink(url) if url else "url"
        elif source_type == "file":
            source = meta.get("original_path", "file")
        else:
            source = source_type
        trans_str = "Y" if s.transcribed else "N"
        click.echo(f"{ref:<7} {date_str:<22} {dur_str:>8} {trans_str:>2}  {source}")


@main.command()
@click.argument("query")
@click.option("--limit", "-n", default=20, help="Max sessions to show.")
@click.option("--sort", "sort_by", default="date",
              type=click.Choice(["date", "duration", "name"]), help="Sort field.")
def search(query, limit, sort_by):
    """Search transcript text for a keyword or phrase.

    \b
    Examples:
      tscribe search "action items"
      tscribe search meeting -n 50
    """
    mgr = _session_manager()
    ref_map = _ref_map(mgr)

    results = mgr.search_transcripts(query, limit=limit, sort_by=sort_by)
    if not results:
        click.echo("No matches found.")
        return

    for session, lines in results:
        ref = ref_map.get(session.stem, "?")
        click.echo(f"── {_stem_date_str(session.stem)} ({ref}) ──")
        for line in lines:
            click.echo(line)
        click.echo()

    count = len(results)
    click.echo(f"{count} match{'es' if count != 1 else ''} found.")


def _open_file(path) -> None:
    """Open a file with the OS default program."""
    import subprocess as sp

    if sys.platform == "darwin":
        sp.Popen(["open", str(path)])
    elif sys.platform == "win32":
        import os as _os
        _os.startfile(str(path))
    else:
        sp.Popen(["xdg-open", str(path)])


def _play_audio(wav_path, total_duration):
    """Play a WAV file with progress bar using sounddevice or external player."""
    import wave

    import numpy as np

    # Try sounddevice first (works everywhere PortAudio is available)
    try:
        import sounddevice as sd

        with wave.open(str(wav_path), "rb") as wf:
            sample_rate = wf.getframerate()
            channels = wf.getnchannels()
            n_frames = wf.getnframes()
            raw = wf.readframes(n_frames)

        data = np.frombuffer(raw, dtype=np.int16).reshape(-1, channels)
        total = n_frames / sample_rate

        position = [0]  # mutable for callback access
        finished = threading.Event()

        def callback(outdata, frames, time_info, status):
            start = position[0]
            end = min(start + frames, len(data))
            chunk = end - start
            if chunk <= 0:
                outdata[:] = 0
                finished.set()
                raise sd.CallbackStop
            outdata[:chunk] = data[start:end]
            if chunk < frames:
                outdata[chunk:] = 0
            position[0] = end

        stream = sd.OutputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype="int16",
            callback=callback,
        )
        stream.start()
        try:
            while not finished.is_set():
                elapsed = position[0] / sample_rate
                _render_play_progress(elapsed, total)
                finished.wait(0.25)
            _render_play_progress(total, total)
            click.echo()
        except KeyboardInterrupt:
            click.echo("\nStopped.")
        finally:
            stream.stop()
            stream.close()
        return
    except (OSError, ImportError):
        pass

    # Fallback to external players
    import shutil
    import subprocess as sp

    player = None
    if sys.platform == "linux":
        for cmd in ["pw-play", "aplay"]:
            if shutil.which(cmd):
                player = [cmd]
                break
    elif sys.platform == "darwin":
        if shutil.which("afplay"):
            player = ["afplay"]
    if player is None and shutil.which("ffplay"):
        player = ["ffplay", "-nodisp", "-autoexit"]

    if player is None:
        raise click.ClickException("No audio player available. Install sounddevice or ffplay.")

    total = total_duration or 0.0
    proc = sp.Popen(player + [str(wav_path)])
    try:
        start_t = time.monotonic()
        while proc.poll() is None:
            elapsed = time.monotonic() - start_t
            if total > 0:
                _render_play_progress(elapsed, total)
            time.sleep(0.25)
        click.echo()
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait()
        click.echo("\nStopped.")


def _render_play_progress(elapsed, total):
    """Render an in-place playback progress bar."""
    minutes, secs = divmod(int(elapsed), 60)
    t_min, t_sec = divmod(int(total), 60)
    frac = min(elapsed / total, 1.0) if total > 0 else 0.0
    filled = int(frac * 30)
    bar = "█" * filled + "░" * (30 - filled)
    play_icon = click.style("▶", fg="green")
    click.echo(
        f"\r  {play_icon} {minutes:02d}:{secs:02d}/{t_min:02d}:{t_sec:02d}  |{bar}|",
        nl=False,
    )


def _resolve_session(ref, mgr):
    """Resolve a HEAD/HEAD~N/stem reference to a SessionInfo."""
    if ref in ("HEAD", "last"):
        index = 0
    elif ref.startswith("HEAD~"):
        try:
            index = int(ref[5:])
        except ValueError:
            raise click.ClickException(f"Invalid ref: {ref}")
    else:
        session = mgr.get_session(ref)
        if session is None:
            raise click.ClickException(f"Recording not found: {ref}")
        return session

    sessions = mgr.list_sessions(limit=index + 1, sort_by="date")
    if index >= len(sessions):
        raise click.ClickException(
            f"Recording {ref} not found (only {len(sessions)} recording(s) exist)."
        )
    return sessions[index]


@main.command()
@click.argument("ref", default="HEAD")
def play(ref):
    """Play a recording.

    REF can be HEAD (most recent), HEAD~N (Nth previous), or a session stem.

    \b
    Examples:
      tscribe play            Play most recent recording
      tscribe play HEAD~1     Play previous recording
      tscribe play 2025-01-15-143022   Play by session ID
    """
    session = _resolve_session(ref, _session_manager())

    dur_str = ""
    if session.duration_seconds is not None:
        m, s = divmod(int(session.duration_seconds), 60)
        dur_str = f" ({m}m {s:02d}s)"

    click.echo(f"Playing: {session.wav_path.name}{dur_str}")

    _play_audio(session.wav_path, session.duration_seconds)


def _resolve_transcript_path(ref, fmt):
    """Resolve a session ref + optional format to a transcript file path."""
    from tscribe.constants import VALID_OUTPUT_FORMATS

    session = _resolve_session(ref, _session_manager())

    if fmt:
        path = session.wav_path.with_suffix(f".{fmt}")
        if not path.exists():
            raise click.ClickException(f"File not found: {path.name}")
        return path

    for ext in VALID_OUTPUT_FORMATS:
        candidate = session.wav_path.with_suffix(f".{ext}")
        if candidate.exists():
            return candidate

    raise click.ClickException(
        f"No transcript found for {session.stem}. "
        f"Run: tscribe transcribe {session.wav_path}"
    )


@main.command(name="open")
@click.argument("ref", default="HEAD")
@click.option("--format", "-f", "fmt", default=None,
              type=click.Choice(["txt", "json", "srt", "vtt", "wav"]),
              help="File format to open (default: first available transcript).")
def open_file(ref, fmt):
    """Open a transcription file with the default program.

    REF can be HEAD (most recent), HEAD~N (Nth previous), or a session stem.

    \b
    Examples:
      tscribe open                 Open most recent transcript
      tscribe open -f json         Open JSON transcript
      tscribe open HEAD~1          Open previous transcript
      tscribe open -f wav          Open the audio file
    """
    path = _resolve_transcript_path(ref, fmt)
    click.echo(f"Opening: {path.name}")
    _open_file(path)


@main.command()
@click.argument("ref", default="HEAD")
@click.option("--format", "-f", "fmt", default=None,
              type=click.Choice(["txt", "json", "srt", "vtt"]),
              help="Output format (default: first available transcript).")
def dump(ref, fmt):
    """Print a transcription to stdout.

    REF can be HEAD (most recent), HEAD~N (Nth previous), or a session stem.

    \b
    Examples:
      tscribe dump                 Print most recent transcript
      tscribe dump -f json         Print JSON transcript
      tscribe dump HEAD~1          Print previous transcript
    """
    path = _resolve_transcript_path(ref, fmt)
    click.echo(path.read_text(), nl=False)


@main.command()
@click.argument("ref", default="HEAD")
@click.option("--format", "-f", "fmt", default=None,
              type=click.Choice(["wav", "txt", "json", "srt", "vtt", "meta"]),
              help="File type (default: txt).")
def path(ref, fmt):
    """Print the file path of a recording artifact.

    REF can be HEAD (most recent), HEAD~N (Nth previous), or a session stem.

    \b
    Examples:
      tscribe path                 Path to most recent transcript
      tscribe path -f wav          Path to audio file
      tscribe path HEAD~1 -f json  Path to previous JSON transcript
    """
    session = _resolve_session(ref, _session_manager())
    ext = fmt or "txt"
    file_path = session.wav_path.with_suffix(f".{ext}")
    if not file_path.exists():
        raise click.ClickException(f"File not found: {file_path.name}")
    click.echo(str(file_path))


@main.command()
@click.argument("ref", default="HEAD")
@click.option("--names", default=None, required=False, help="Comma-separated speaker names (e.g. 'Alice,Bob').")
def label(ref, names):
    """Re-label speaker names in an existing transcript."""
    import json

    from tscribe.diarization import extract_speaker_samples, parse_speaker_names, remap_transcript_speakers
    from tscribe.transcriber import TranscriptResult, TranscriptSegment

    json_path = None
    session = None
    session_mgr = None
    ref_path = Path(ref)
    if ref_path.is_file():
        if ref_path.suffix == ".json":
            json_path = ref_path
        else:
            json_path = ref_path.with_suffix(".json")
    elif ref.endswith(".json"):
        raise click.ClickException(f"File not found: {ref}")
    else:
        session_mgr = _session_manager()
        session = _resolve_session(ref, session_mgr)
        json_path = session.wav_path.with_suffix(".json")

    if not json_path or not json_path.exists():
        raise click.ClickException(f"Transcript JSON not found: {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    result = TranscriptResult(
        file=data.get("file", json_path.stem),
        model=data.get("model", "unknown"),
        language=data.get("language", "en"),
        segments=[TranscriptSegment(**s) for s in data.get("segments", [])],
    )

    mapping: dict[str, str] = {}
    if names is not None:
        name_map = parse_speaker_names(names)
        tokens = [t.strip() for t in names.split(",") if t.strip()]
        is_explicit = any("=" in token for token in tokens)

        distinct_speakers: list[str] = []
        for seg in result.segments:
            raw = seg.raw_speaker or seg.speaker
            if raw and raw not in distinct_speakers:
                distinct_speakers.append(raw)

        if is_explicit:
            mapping = name_map
        else:
            for idx, raw in enumerate(distinct_speakers):
                if idx < len(tokens):
                    mapping[raw] = tokens[idx]
    else:
        samples = extract_speaker_samples(result)
        if not samples:
            click.echo("No diarized speakers found in transcript.")
            return

        click.echo(f"Found {len(samples)} speaker{'s' if len(samples) != 1 else ''}:")
        for spk in samples:
            sample_preview = spk['sample_text'][:40]
            if len(spk['sample_text']) > 40:
                sample_preview += "..."
            val = click.prompt(
                f"  {spk['raw_speaker']} (\"{sample_preview}\")",
                default=spk["speaker"],
            )
            mapping[spk["raw_speaker"]] = val.strip()

    remapped = remap_transcript_speakers(result, mapping)
    json_path.write_text(json.dumps(remapped.to_json(), indent=2), encoding="utf-8")

    updated_files = [json_path.name]
    for ext, render in (("txt", remapped.to_txt), ("srt", remapped.to_srt), ("vtt", remapped.to_vtt)):
        out_path = json_path.with_suffix(f".{ext}")
        if out_path.exists():
            out_path.write_text(render(), encoding="utf-8")
            updated_files.append(out_path.name)

    if session and session_mgr:
        session_mgr.update_metadata(session.stem, speaker_map=mapping)

    click.echo(f"Updated speaker labels in {', '.join(updated_files)}.")


@main.command()
@click.option("--loopback", "-l", is_flag=True, help="Show only loopback/monitor sources.")
def devices(loopback):
    """List available audio input devices."""
    # Try PipeWire first on Linux
    if sys.platform == "linux":
        from tscribe.pipewire_devices import is_pipewire_available, list_pipewire_nodes

        if is_pipewire_available():
            nodes = list_pipewire_nodes(loopback_only=loopback)
            if not nodes:
                if loopback:
                    click.echo("No PipeWire monitor/loopback sources found.")
                else:
                    click.echo("No PipeWire audio nodes found.")
                return

            click.echo(f"{'Serial':<8} {'Name':<40} {'Type':<10} {'Description'}")
            click.echo("-" * 85)
            for n in nodes:
                type_label = "Monitor" if n.is_monitor else "Input"
                display_name = n.nick or n.name
                click.echo(
                    f"{n.serial:<8} {display_name:<40} {type_label:<10} {n.description}"
                )
            return

    # On Windows, use PyAudioWPatch for WASAPI loopback device listing
    if sys.platform == "win32":
        try:
            import pyaudiowpatch as pyaudio

            with pyaudio.PyAudio() as p:
                loopback_devs = list(p.get_loopback_device_info_generator())

            if loopback and loopback_devs:
                click.echo(f"{'Idx':<5} {'Name':<50} {'Ch':>3} {'Rate':>7}")
                click.echo("-" * 70)
                for dev in loopback_devs:
                    click.echo(
                        f"{dev['index']:<5} {dev['name']:<50} "
                        f"{dev['maxInputChannels']:>3} "
                        f"{dev['defaultSampleRate']:>7.0f}"
                    )
                return
            elif loopback:
                click.echo("No WASAPI loopback devices found.")
                return
            # For non-loopback, fall through to show all devices via sounddevice
        except ImportError:
            pass

    # Fall back to sounddevice enumeration
    from tscribe.devices import get_platform_loopback_guidance, list_devices

    devs = list_devices(loopback_only=loopback)
    if not devs:
        if loopback:
            guidance = get_platform_loopback_guidance()
            if guidance:
                click.echo(guidance)
                return
        click.echo("No audio input devices found.")
        return

    click.echo(f"{'Idx':<5} {'Name':<45} {'Ch':>3} {'Rate':>7} {'Loopback':>9}  {'Host API'}")
    click.echo("-" * 90)
    for dev in devs:
        lb = "Yes" if dev.is_loopback else ""
        click.echo(
            f"{dev.index:<5} {dev.name:<45} {dev.max_input_channels:>3} "
            f"{dev.default_samplerate:>7.0f} {lb:>9}  {dev.hostapi}"
        )


@main.command()
@click.argument("key", required=False)
@click.argument("value", required=False)
@click.option("--list", "list_all", is_flag=True, help="Show all configuration values.")
@click.option("--path", "show_path", is_flag=True, help="Show the active config file path.")
@click.option("--init", "initialize", is_flag=True, help="Create a config file with defaults if missing.")
@click.option("--edit", "edit", is_flag=True, help="Open the config file in your editor.")
def config(key, value, list_all, show_path, initialize, edit):
    """View or set configuration."""
    from tscribe.paths import get_config_path

    config_path = get_config_path()
    if show_path:
        click.echo(config_path)
        return
    cfg = _load_config()
    if initialize or edit:
        if not config_path.exists():
            cfg.save(config_path)
        if edit:
            click.edit(filename=str(config_path))
        else:
            click.echo(f"Config file: {config_path}")
        return

    if list_all or (key is None and value is None):
        for section_name, section_dict in cfg._to_dict().items():
            for k, v in section_dict.items():
                click.echo(f"{section_name}.{k} = {v!r}")
        return

    if value is None:
        try:
            click.echo(cfg.get(key))
        except KeyError as e:
            raise click.ClickException(str(e))
        return

    try:
        cfg.set(key, value)
    except (KeyError, ValueError) as e:
        raise click.ClickException(str(e))
    cfg.save(config_path)
    click.echo(f"Set {key} = {cfg.get(key)!r}")


@main.command()
@click.option("--days", type=int, default=None, help="Delete sessions older than N days.")
@click.option("--30", "days_30", is_flag=True, help="Shortcut for --days 30.")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@click.option("--dry-run", is_flag=True, help="Preview sessions to be deleted without removing them.")
@click.option("--dir", "custom_dir", type=click.Path(path_type=Path), default=None, hidden=True)
def clean(days, days_30, yes, dry_run, custom_dir):
    """Clean old recordings and artifacts."""
    from tscribe.paths import get_data_dir, get_recordings_dir
    from tscribe.session import SessionManager

    if custom_dir:
        recordings_dir = Path(custom_dir)
    else:
        cfg = _load_config()
        recordings_dir = get_recordings_dir(get_data_dir(cfg.storage.data_dir))

    mgr = SessionManager(recordings_dir)
    effective_days = 30 if days_30 else days

    results = mgr.clean_sessions(older_than_days=effective_days, dry_run=True)
    if not results:
        msg = f"No sessions older than {effective_days} days found." if effective_days else "No sessions found to clean."
        click.echo(msg)
        return

    total_bytes = sum(freed for _, _, freed in results)
    mb = total_bytes / (1024 * 1024)
    scope = f"older than {effective_days} days" if effective_days else "all"

    if dry_run:
        click.echo(f"Would delete {len(results)} session(s) ({scope}), freeing {mb:.1f} MB:")
        for stem, files, _ in results:
            click.echo(f"  {stem} ({len(files)} files)")
        return

    if not yes:
        try:
            click.confirm(f"Delete {len(results)} session(s) ({scope}), freeing {mb:.1f} MB?", abort=True)
        except click.Abort:
            click.echo("Aborted.")
            return

    actual_deleted = mgr.clean_sessions(older_than_days=effective_days, dry_run=False)
    actual_freed = sum(freed for _, _, freed in actual_deleted) / (1024 * 1024)
    click.echo(f"Deleted {len(actual_deleted)} session(s), freed {actual_freed:.1f} MB.")


@main.command()
@click.option("--diarize/--no-diarize", default=None, help="Enable speaker diarization by default.")
@click.option("--diarize-engine", type=click.Choice(["nemotron", "wespeaker"]), default=None, help="Diarization engine (default: config, else nemotron).")
@click.option("--install-desktop", is_flag=True, help="Install the built native app in ~/Applications.")
def app(diarize, diarize_engine, install_desktop):
    """Open the native macOS recording app and menu bar controls."""
    if sys.platform != "darwin":
        raise click.ClickException("The 'app' command is only supported on macOS.")

    import subprocess
    from tscribe.desktop import find_native_app, install_native_app

    bundle = find_native_app(prefer_build=install_desktop)
    if bundle is None:
        raise click.ClickException(
            "Native macOS app not found. Build it with 'uv run --group mac-app python "
            "packaging/macos/build_native.py', or set TSCRIBE_APP_PATH to a native .app bundle."
        )
    if install_desktop:
        bundle = install_native_app(bundle)
        click.echo(f"Installed native app: {bundle}")
        return
    arguments = ["open", str(bundle)]
    if diarize is not None:
        arguments.extend(["--args", "--diarize" if diarize else "--no-diarize"])
    if diarize_engine is not None:
        if diarize is None:
            arguments.append("--args")
        arguments.extend(["--diarize-engine", diarize_engine])
    try:
        subprocess.run(arguments, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise click.ClickException(f"Could not launch native app: {exc}") from exc
    click.echo("Opened native tscribe app and recording window.")


if __name__ == "__main__":
    main()
