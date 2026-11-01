# tscribe
![macOS](https://img.shields.io/badge/-macOS-000000?style=flat-square&logo=apple&logoColor=white)
![Linux](https://img.shields.io/badge/-Linux-FCC624?style=flat-square&logo=linux&logoColor=black)
![Windows](https://img.shields.io/badge/-Windows-0078D6?style=flat-square&logo=windows&logoColor=white)
![Python](https://img.shields.io/badge/-Python-3776AB?style=flat-square&logo=python&logoColor=white)
![CLI](https://img.shields.io/badge/-CLI-000000?style=flat-square&logo=gnu-bash&logoColor=white)

Cross-platform CLI and native macOS menu bar app for recording audio and transcribing it to text using [faster-whisper](https://github.com/SYSTRAN/faster-whisper). Runs on modest hardware — no GPU required, but GPU acceleration is supported.

> **Note:** This project is a fork of [johnrobinsn/tscribe](https://github.com/johnrobinsn/tscribe.git).

https://private-user-images.githubusercontent.com/1709257/546508788-dcd6ee47-d2bd-429c-be38-3ab8e5f5b243.mp4?jwt=eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJnaXRodWIuY29tIiwiYXVkIjoicmF3LmdpdGh1YnVzZXJjb250ZW50LmNvbSIsImtleSI6ImtleTUiLCJleHAiOjE3NzA0NDYwMDAsIm5iZiI6MTc3MDQ0NTcwMCwicGF0aCI6Ii8xNzA5MjU3LzU0NjUwODc4OC1kY2Q2ZWU0Ny1kMmJkLTQyOWMtYmUzOC0zYWI4ZTVmNWIyNDMubXA0P1gtQW16LUFsZ29yaXRobT1BV1M0LUhNQUMtU0hBMjU2JlgtQW16LUNyZWRlbnRpYWw9QUtJQVZDT0RZTFNBNTNQUUs0WkElMkYyMDI2MDIwNyUyRnVzLWVhc3QtMSUyRnMzJTJGYXdzNF9yZXF1ZXN0JlgtQW16LURhdGU9MjAyNjAyMDdUMDYyODIwWiZYLUFtei1FeHBpcmVzPTMwMCZYLUFtei1TaWduYXR1cmU9ZWM0OTAzMjdhMDkyNzNmNDA4Y2Y0NDJjOTczNDFhMDFmMjk1ZDNkNmZjNDkyMjEzYzUyZDMxYjQ5OTM1Y2QyNCZYLUFtei1TaWduZWRIZWFkZXJzPWhvc3QifQ.jjZsx6_5HnEaFd-0CMg7e9vtRPOqNA8OaGR3SToiLns

## Use Cases

- Capture both sides of video calls (Teams, Zoom, Meet) for searchable transcripts
- Voice memos and audio note-taking
- Transcribe podcasts, lectures, or downloaded audio
- Generate subtitles (SRT/VTT) from any audio or video source

## Features

- **Record** system audio (loopback) or microphone with live level meter
- **Transcribe** recordings, WAV files, or URLs (YouTube, etc.) via faster-whisper
- **Auto-transcribe** after recording stops (configurable)
- **Play** recordings with progress bar
- **Open** transcripts in your default editor/viewer
- **Dump** transcripts to stdout for piping
- **Search** past transcripts by keyword
- **Live meeting captions** in the Mac app, with microphone + system audio capture
- **Speaker identification** using local voice embeddings and word-level attribution
- **Cross-platform**: Linux (PipeWire), macOS, Windows
- Output formats: plain text, JSON (timestamped), SRT, WebVTT

## Requirements

The self-contained [native Mac app](docs/macos-app.md) requires macOS 14 or later.
The following requirements apply to the Python CLI:

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Linux: PipeWire (for system audio capture)
- macOS: [BlackHole](https://github.com/ExistentialAudio/BlackHole) (for system audio capture). Optional: [switchaudio-osx](https://github.com/deweller/switchaudio-osx) for auto-switching.
- Windows: WASAPI (built-in)

## Installation

```bash
git clone https://github.com/johnrobinsn/tscribe.git && cd tscribe
uv sync

# Run from the project directory
uv run tscribe record

# Or install globally (available from any directory)
uv tool install .
tscribe record
```

Models are downloaded automatically on first transcription (~244MB for the default `small` model).

## Quick Start

```bash
# Record system audio (Ctrl+C to stop, auto-transcribes by default)
tscribe record

# Record from microphone instead
tscribe record --mic

# Transcribe a YouTube video
tscribe transcribe "https://youtu.be/dQw4w9W"

# Play back the last recording
tscribe play

# Open the transcript in your default editor
tscribe open

# Print transcript to stdout
tscribe dump
```

## Commands

| Command | Description |
|---------|-------------|
| `tscribe record` | Record system audio or microphone |
| `tscribe app` | Open the native macOS recording app and menu bar controls |
| `tscribe play [REF]` | Play a recording |
| `tscribe open [REF]` | Open transcript in default program |
| `tscribe dump [REF]` | Print transcript to stdout |
| `tscribe path [REF]` | Print file path of a recording artifact |
| `tscribe transcribe [SOURCE]` | Transcribe a file, URL, or recording ref |
| `tscribe label [REF]` | Re-label speaker names in an existing transcript |
| `tscribe clean` | Delete old recordings and artifacts |
| `tscribe list` | List past recordings |
| `tscribe search <query>` | Search transcript text |
| `tscribe devices` | List audio input devices |
| `tscribe config` | View or set configuration |

REF can be `HEAD` (most recent, default), `HEAD~N` (Nth previous), or a session stem (e.g. `2025-01-15-143022`).

### Record

```bash
tscribe record                        # System audio (default on Linux/Windows)
tscribe record --mic                  # Record from microphone
tscribe record --diarize              # Auto-diarize speakers
tscribe record --diarize --names "Alice,Bob" # Assign custom speaker names
tscribe record --device 56            # Specific device (see tscribe devices)
tscribe record --no-transcribe        # Skip auto-transcription
tscribe record -o meeting.wav         # Custom output path
```

While recording, a live level meter shows audio activity:

```
● REC 00:05  ▁▂▃▅▇█▆▃▁▁▂▅▇█▇▅▃▂▁▁
```

### Play

```bash
tscribe play                          # Play most recent recording
tscribe play HEAD~1                   # Play previous recording
tscribe play 2025-01-15-143022        # Play by session ID
```

### Open & Dump

```bash
tscribe open                          # Open transcript in default editor
tscribe open -f json                  # Open JSON transcript
tscribe open -f wav                   # Open the audio file itself
tscribe dump                          # Print transcript to stdout
tscribe dump -f json                  # Print JSON to stdout
tscribe dump HEAD~1                   # Print previous transcript
tscribe dump | grep "action items"    # Pipe to other tools
```

### Path

```bash
tscribe path                          # Path to most recent transcript
tscribe path -f wav                   # Path to audio file
tscribe path HEAD~1 -f json           # Previous session's JSON
tscribe path -f meta                  # Metadata file
cat $(tscribe path)                   # Use in scripts
```

### Transcribe

```bash
tscribe transcribe                              # Re-transcribe most recent recording
tscribe transcribe --diarize                     # Transcribe with speaker diarization
tscribe transcribe --diarize --names "Alice,Bob" # Assign custom names to speakers
tscribe transcribe --model small                # Re-transcribe with a better model
tscribe transcribe HEAD~2                       # Re-transcribe a previous recording
tscribe transcribe audio.wav                    # Local file (base model, txt+json)
tscribe transcribe "https://youtu.be/dQw4w9W"  # YouTube or other URL
tscribe transcribe audio.wav --format all       # Output txt, json, srt, vtt
tscribe transcribe audio.wav --language en      # Force language
tscribe transcribe audio.wav --gpu              # Request NVIDIA CUDA acceleration
```

SOURCE defaults to HEAD (most recent recording). Accepts file paths, URLs, or recording refs (HEAD, HEAD~N, session stems).

URL transcription uses [yt-dlp](https://github.com/yt-dlp/yt-dlp) (installed with tscribe) to download audio, imports it into the recordings directory, and transcribes it. The result appears in `tscribe list` like any other recording.

Use `--format srt` or `--format vtt` to generate subtitle files for adding captions to videos.

A progress bar with ETA is shown during transcription:

```
  ⟳ 02:30/10:00  |████████░░░░░░░░░░░░░░░░░░░░░░|  ETA 01:30
```

### Speaker Diarization

Speakers are identified by the `diarize_engine` setting (`[transcription]`):

- `nemotron` (default): NVIDIA Nemotron 3 Diarization, run locally through the
  [NeMo-Speech.cpp](https://github.com/NVIDIA/NeMo-Speech.cpp) runtime. Maximum 8 speakers.
  The packaged macOS app bundles the runtime and weights (~121 MB) and works offline.
  A source/dev install downloads the weights on first use and needs the `nemo-speech`
  CLI on `PATH`.
- `wespeaker`: opt out to the previous behaviour, short speech windows and neural voice
  embeddings from [sherpa-onnx](https://k2-fsa.github.io/sherpa/onnx/speaker-identification/)
  with spectral clustering.

Choose per run with `--diarize-engine nemotron|wespeaker` on `record`, `transcribe` and
`app`, or persist it with `tscribe config transcription.diarize_engine wespeaker`.
There is no silent fallback between engines: a missing runtime or weights is an error.

Word timestamps preserve speaker changes inside a transcription segment. Models
are downloaded on first use to `~/.tscribe/models/diarization/` (or under
`TSCRIBE_DATA_DIR`) and reused offline; audio stays on your computer. For offline
setup of WeSpeaker, place `wespeaker_en_voxceleb_resnet34_LM.onnx` in that directory. A download
failure reports the source URL and expected path; it does not fall back to
volume-based grouping.
Speaker detection can still make mistakes, especially during overlapping speech.
Use `--speakers 3` when the recording has three speakers:

```bash
# Auto-diarize during recording
tscribe record --diarize

# Auto-diarize with known speaker count & names
tscribe record --diarize --speakers 3 --names "Alice,Bob,Charlie"

# Transcribe an existing recording or file with diarization
tscribe transcribe HEAD --diarize
tscribe transcribe meeting.wav --diarize --names "Alice,Bob"

# Enable diarization by default
tscribe config transcription.diarize true
```

Output formats automatically include speaker attribution:
- **Plain text (`.txt`)**: Dialogues grouped under `[Speaker 1]:` or `[Alice]:` headings.
- **JSON (`.json`)**: Segment entries contain a `"speaker"` key.
- **WebVTT (`.vtt`)**: Uses native `<v Alice>...</v>` voice tags.
- **SRT (`.srt`)**: Lines prefixed with `[Alice] ...`.

### Label (Rename Speakers)

Re-label speaker names in an existing transcript without re-running audio transcription or ML clustering:

```bash
# Re-label most recent transcript
tscribe label HEAD --names "Alice,Bob"

# Positional mapping: Speaker 1 -> Alice, Speaker 2 -> Bob
tscribe label 2026-10-15-135309 --names "Alice,Bob"

# Explicit index mapping: Speaker 1 -> Alice, Speaker 3 -> Charlie
tscribe label HEAD --names "1=Alice,3=Charlie"
```

Updates `.json`, `.txt`, `.srt`, and `.vtt` artifacts in-place.

### Clean

Manage and remove old recording sessions and their associated artifacts (`.wav`, `.txt`, `.json`, `.meta`, `.vtt`, `.srt`):

```bash
# Clean sessions older than 30 days (prompts for confirmation)
tscribe clean --30

# Clean sessions older than N days
tscribe clean --days 60

# Clean all sessions
tscribe clean

# Preview what would be deleted without removing files
tscribe clean --30 --dry-run

# Skip confirmation prompt
tscribe clean --30 -y
```

Reports number of deleted sessions and total disk space freed.

### Native App (macOS)

The macOS app uses SwiftUI, opens a recording/transcript window on launch, and
provides menu bar controls. It records microphone audio with AVFoundation and
system audio with ScreenCaptureKit, without BlackHole. Python and the local
transcription engine are bundled inside the app.

```bash
make setup
make app
open dist/tscribe.app

# Install the native build, then open it from the CLI or Finder
make install
make run
```

Requires macOS 14+. The window provides recording controls, recent sessions,
transcript viewing/copying, visible errors, and shared settings. Closing the
window hides the app to the menu bar; choose **Open tscribe** from its microphone icon.

See [native app build, permissions, verification and distribution](docs/macos-app.md).

### List

```bash
tscribe list                          # Show recent recordings
tscribe list --search "meeting"       # Filter by transcript text
tscribe list --sort duration          # Sort by duration
tscribe list -n 50                    # Show 50 entries
```

Output includes REF, date with day-of-week, duration, transcription status, and source:

```
REF     Date                      Dur Tx  Source
------------------------------------------------------
HEAD    2025-01-15-143022 We  00:05:30  Y  loopback
HEAD~1  2025-01-14-091500 Tu  00:03:15  Y  https://youtu.be/dQw4w9W
HEAD~2  2025-01-13-100000 Mo  00:10:00  N  microphone
```

URLs are clickable hyperlinks in supported terminals.

### Search

```bash
tscribe search "action items"         # Search all transcripts
tscribe search meeting -n 50          # Limit results
tscribe search budget --sort date     # Sort by date (default)
```

Shows matching lines with session context:

```
── 2025-01-15-143022 We (HEAD) ──
discussed the action items for next week

── 2025-01-14-091500 Tu (HEAD~1) ──
review action items from Monday's standup

2 matches found.
```

### Devices

```bash
tscribe devices                       # List all audio devices
tscribe devices --loopback            # Show only loopback/monitor sources
```

### Configuration

```bash
tscribe config --path                           # Show the active config.toml path
tscribe config --init                           # Create defaults (preserves an existing file)
tscribe config --edit                           # Open config.toml in $VISUAL / $EDITOR
tscribe config                                  # Show all settings
tscribe config recording.sample_rate            # Get a value
tscribe config recording.auto_transcribe false  # Set a value
tscribe config transcription.model small        # Change default model
```

The CLI and macOS menu bar app share one TOML configuration file. New setups use
`~/.config/tscribe/config.toml` (or `$XDG_CONFIG_HOME/tscribe/config.toml`).
An existing `~/.tscribe/config.toml` continues to work without migration.

The active file is selected in this order; files are not merged:

1. `TSCRIBE_CONFIG_FILE`, if set (supports `~`).
2. `$TSCRIBE_DATA_DIR/config.toml`, if that environment variable is set (legacy compatibility).
3. `~/.tscribe/config.toml`, if it exists.
4. `$XDG_CONFIG_HOME/tscribe/config.toml`, falling back to `~/.config/tscribe/config.toml`.

Missing settings use defaults. Command-line flags override settings for that run.
Changing `storage.data_dir` only moves where future recordings are stored; it does
not move the config file or existing recordings. Restart the menu bar app after
editing settings. `--init` creates the active file without overwriting it.
See [config.example.toml](config.example.toml) for a complete example.

Available keys and defaults:

| Key | Default | Description |
|-----|---------|-------------|
| `recording.sample_rate` | `16000` | Sample rate in Hz |
| `recording.channels` | `1` | Number of channels (mono) |
| `recording.default_device` | `""` | Audio device name or index as a string (empty = system default) |
| `recording.auto_transcribe` | `true` | Auto-transcribe after recording |
| `transcription.model` | `"small"` | Whisper model size (tiny/base/small/medium/large) |
| `transcription.language` | `"auto"` | Language code or auto-detect |
| `transcription.output_formats` | `["txt","json"]` | Output formats (txt, json, srt, vtt) |
| `transcription.gpu` | `false` | Request NVIDIA CUDA acceleration; fall back to CPU when unavailable |
| `transcription.diarize` | `true` | Identify speakers by default |
| `transcription.diarize_engine` | `"nemotron"` | Diarization engine: `nemotron` (max 8 speakers) or `wespeaker` |
| `app.notifications` | `true` | Show macOS menu bar app notifications |
| `app.recent_limit` | `5` | Number of recent recordings in the menu (positive integer) |
| `app.show_elapsed_time` | `true` | Show elapsed recording time in the menu bar |
| `storage.data_dir` | `""` | Override data directory (empty = `~/.tscribe`) |

Experimental live meeting captions are available in the native app. Open
**Settings…** from the menu bar or press **⌘,**, enable **Live captions while
recording**, then choose **Record Meeting**. Microphone and system-audio recording
buttons also support live captions when enabled.

| Key | Default | Accepted values |
|-----|---------|-----------------|
| `captions.enabled` | `true` | Enable live captions in the native app |
| `captions.model` | `"base"` | Same model choices as `transcription.model` |
| `captions.audio_source` | `"both"` | `both`, `microphone`, `system`; used by Record Meeting |
| `captions.output_mode` | `"headphones"` | `headphones`, `speakers` |
| `captions.echo_cancellation` | `true` | Experimental echo reduction with speakers and both sources |
| `captions.font_size` | `24` | 12–72 points |
| `captions.always_on_top` | `true` | `true`, `false` |

The floating window shows stable text and a provisional latest phrase. Caption
language uses `transcription.language`. Drafts are saved separately; final
transcription still follows `recording.auto_transcribe` and the normal model
settings. Speaker mode has experimental reference-based echo reduction using
SpeexDSP, applied to live captions and the final mix while retaining original
tracks. Real-room quality still needs validation; headphones bypass the filter.
See the
[Mac app guide](docs/macos-app.md#live-meeting-captions) for details and limitations.

## Whisper Models

| Model | Size | Speed (CPU) | Quality |
|-------|------|-------------|---------|
| tiny | ~39MB | ~30x realtime | Low |
| base | ~74MB | ~10x realtime | Good |
| small | ~244MB | ~3-4x realtime | Better |
| medium | ~769MB | ~1x realtime | High |
| large | ~1.5GB | Slower than realtime | Best |

Default: `small` — a good balance of speed and accuracy. If transcriptions have too many errors, try `medium` for better quality at the cost of slower processing. For faster but lower-quality results, try `base` or `tiny`. You can also override per-transcription without changing the default:

```bash
tscribe transcribe --model small
```

Models are downloaded automatically from Hugging Face on first use.

## System Audio (Loopback)

By default, `tscribe record` captures system audio (what you hear through your speakers/headphones). Use `--mic` to record from the microphone instead.

| Platform | How It Works |
|----------|--------------|
| Linux | PipeWire native via `pw-record` with monitor capture |
| Windows | WASAPI loopback via [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch) (auto-installed) |
| macOS | Requires [BlackHole](https://github.com/ExistentialAudio/BlackHole) + Multi-Output Device. See [macOS setup guide](docs/macos-system-audio.md). |

On macOS, the CLI will detect your setup and guide you: if BlackHole is missing it warns and falls back to the microphone, and if [switchaudio-osx](https://github.com/deweller/switchaudio-osx) is installed (`brew install switchaudio-osx`) it can automatically switch to your Multi-Output Device when recording and restore your previous output when done. The native Mac app uses ScreenCaptureKit and does not require BlackHole.

Run `tscribe devices --loopback` to see available loopback sources. Use `--device <id>` to record from a specific microphone or input device.

## Storage

Recordings are stored in `~/.tscribe/recordings/` on all platforms. Override with the `TSCRIBE_DATA_DIR` environment variable or `storage.data_dir` config key.

Each recording produces:
- `.wav` — audio file
- `.txt` — plain text transcript
- `.json` — timestamped transcript with segments
- `.meta` — recording metadata (device, duration, etc.)
- `.srt` / `.vtt` — subtitles (when generated)

To manage and delete old recordings, run `tscribe clean` (e.g. `tscribe clean --30` to remove sessions older than 30 days) or manually remove files from `~/.tscribe/recordings/`.

## Development

```bash
make setup       # Install development and build dependencies from uv.lock
make check       # Lint + Python + Swift + desktop menu bar tests (macOS)
make lint test   # Checks for the Python CLI on Linux/macOS
make dist        # Remove old distributions and build the current release
make help        # All targets, including cleanup, installation, and launch

# Tests with coverage
uv run --locked --group dev pytest --cov=tscribe --cov-report=term-missing
```

`dist/` contains only the current wheel, source archive, macOS app, its ZIP, and
`SHA256SUMS`.
Worker intermediates live under `build/`. `make clean-dist` removes distribution
files; `make clean` also removes build outputs and test caches. Build and cleanup
commands share a lock, so overlapping invocations fail clearly instead of
removing an app while it is being archived. Apps and ZIPs are staged and
verified before replacing their previous outputs. Neither removes
recordings, configuration, or the installed app.

### CI and releases

GitHub Actions runs lint and Python tests on Linux/Windows, plus native Swift and
Python checks on Apple Silicon and Intel Macs. Dependency resolution is locked
with `uv.lock`. Tests use synthetic audio and do not need capture permissions or
Whisper model downloads.

After committing/pushing the release changes, publish version 2.3.1 by pushing
its matching tag:

```bash
git tag -a v2.3.1 -m "tscribe 2.3.1"
git push origin v2.3.1
```

The release workflow rejects mismatched versions, waits for checks, builds the
CLI packages and both Mac architectures, verifies packaged workers/signatures,
and publishes a GitHub release with SHA256 checksums. Only the publishing job
has write permission. It uses the repository's automatic `GITHUB_TOKEN`; no
publishing token is needed. macOS packages are ad-hoc signed; Apple notarization
still requires the developer credentials described in [the Mac app guide](docs/macos-app.md).

Mutation testing uses [mutmut](https://mutmut.readthedocs.io/en/latest/) to
deliberately alter code and check whether tests detect the changed behavior.
The initial scope covers `config.py` and `paths.py`, using their focused unit
tests without recording audio or downloading models.

```bash
# Run new mutations, resuming cached results
uv run mutmut run --max-children 4

# Recheck all configured mutations after changing tests
uv run mutmut run --max-children 4 'tscribe.*'

# Inspect surviving mutations
uv run mutmut results
uv run mutmut browse
```

Generated files and results stay in the ignored `mutants/` directory; normal
source files are preserved. A surviving mutation needs review: it can reveal
a missing assertion or a change that does not matter to the behavior being
tested. The command's successful exit alone is not a passing mutation score.
Expand `only_mutate` and `pytest_add_cli_args_test_selection` in `pyproject.toml`
to cover more modules. Mutation testing requires macOS or Linux (Windows users
can use WSL).

Initial baseline: **246 of 248 mutations detected (99.2%)**. The two remaining
mutations only change the separator between valid choices in error messages;
the tests check rejection of invalid values without requiring that punctuation.

## Architecture

`macos/` contains the native SwiftUI app and audio capture. `packaging/macos/build_native.py` builds it with the Python worker.

```
src/tscribe/
├── worker.py             # JSON bridge for native macOS app
├── desktop.py            # Native app discovery/installation
├── cli.py                # Click CLI with subcommands
├── config.py             # TOML configuration management
├── diarization.py        # Speaker diarization (voice embeddings + clustering)
├── paths.py              # Cross-platform path resolution
├── devices.py            # Audio device enumeration (sounddevice)
├── pipewire_devices.py   # PipeWire device enumeration (Linux)
├── session.py            # Recording session & file management
├── transcriber.py        # faster-whisper transcription
└── recorder/
    ├── base.py                  # Abstract Recorder interface
    ├── sounddevice_recorder.py  # sounddevice capture (macOS/Windows mic)
    ├── wasapi_recorder.py       # WASAPI loopback capture (Windows)
    ├── pipewire_recorder.py     # PipeWire capture (Linux)
    └── mock_recorder.py         # Test mock
```
