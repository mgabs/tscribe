# CLI and self-contained macOS app

The project provides a cross-platform CLI and a macOS menu bar app backed by
the same configuration, recordings, and transcription code.

## CLI

```bash
uv tool install .
tscribe --help
tscribe record --mic
tscribe transcribe meeting.wav --output exports/meeting --format txt,json
```

## Build the self-contained app

Build on macOS for the architecture you want to distribute. An Apple Silicon
build targets Apple Silicon; build separately on Intel for Intel Macs. The
bundle includes Python, the audio libraries, Whisper runtime, Silero VAD model,
and icons. No separate Python installation is needed on the recipient's Mac.

```bash
uv sync --group mac-app
uv run --group mac-app pyinstaller --noconfirm packaging/macos/tscribe.spec
```

The result is `dist/tscribe.app`. Copy it to `/Applications` or
`~/Applications` and open it from Finder. A microphone icon appears in the menu
bar; the app runs without a Dock window. Its menu supports microphone and
system audio recording, stopping, speaker labeling, recent recordings,
opening configuration, and opening the recordings folder.

Quitting while recording finishes saving and any automatic transcription before
exiting. Whisper models download on the first transcription; allow time for
that initial download. Audio and transcription remain local. Speaker diarization
is experimental: the current algorithm clusters amplitude histograms rather than
voice embeddings and can confuse different people or recording conditions.

Microphone access must be allowed in macOS Privacy & Security settings. System
audio requires the [BlackHole and Multi-Output setup](macos-system-audio.md).
The app uses `recording.default_device` for microphone recordings and detects
a loopback device separately for system-audio recordings. Supported sample rates
use the configured value; unsupported rates fall back to the device's native
rate, which is saved in the recording metadata.
Select that Multi-Output Device before using Record System Audio in the app;
automatic output switching currently belongs to the CLI recording command.

The app and CLI share the file shown by `tscribe config --path`. Restart the app
after changing configuration. Finder launch errors are shown in a dialog;
logs are written to `~/Library/Logs/tscribe/tscribe.log`.

## Verify the bundle

These commands run the bundled runtime, independent of your virtual environment:

```bash
dist/tscribe.app/Contents/MacOS/tscribe --self-test
dist/tscribe.app/Contents/MacOS/tscribe --cli --version
dist/tscribe.app/Contents/MacOS/tscribe --cli --help
codesign --verify --deep --strict dist/tscribe.app
```

`--self-test` loads bundled native audio, VAD, transcription and clustering
libraries without recording audio or downloading a Whisper model. It does not
replace a manual microphone/system-audio recording check on the destination Mac.
Use `--cli` to access the CLI from the bundle when Python is not installed.
URL imports via yt-dlp additionally require an `ffmpeg` executable on your PATH;
local audio transcription uses the bundled PyAV libraries.

## Distribution

A default build is ad-hoc signed for local testing. Public distribution needs a
Developer ID Application certificate and Apple notarization. Build with your
existing signing identity:

```bash
TSCRIBE_CODESIGN_IDENTITY='Developer ID Application: Your Name (TEAMID)' \
  uv run --group mac-app pyinstaller --noconfirm packaging/macos/tscribe.spec

ditto -c -k --sequesterRsrc --keepParent dist/tscribe.app dist/tscribe-macos.zip
xcrun notarytool submit dist/tscribe-macos.zip --keychain-profile YOUR_PROFILE --wait
xcrun stapler staple dist/tscribe.app
# Recreate the archive after stapling before sending it to recipients.
ditto -c -k --sequesterRsrc --keepParent dist/tscribe.app dist/tscribe-macos-notarized.zip
```

Use a keychain profile you have already configured for your Apple developer
account. Building and local signature verification do not confirm notarization.
See the [PyInstaller macOS signing documentation](https://pyinstaller.org/en/stable/feature-notes.html#macos-binary-code-signing).

## Lightweight launcher

For development, `tscribe app` runs from the installed Python environment.
`tscribe app --install-desktop` creates a Finder launcher in
`~/Applications/tscribe.app`; this small launcher depends on that Python
installation. Use the self-contained build above for sharing with others.
