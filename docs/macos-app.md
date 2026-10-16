# Native macOS app and Python CLI

The macOS app uses **SwiftUI** for its window, menu bar controls and settings,
**AVFoundation** for microphone capture, and **ScreenCaptureKit** for system
audio. Its Python transcription worker is bundled inside the app. Recipients do
not need to install Python. The cross-platform Python CLI remains available.

The app requires macOS 14 or later. Build separately on Apple Silicon and Intel
for the architecture you intend to distribute.

## Build and run

Build with Xcode or its Swift toolchain installed:

```bash
make setup
make app
open dist/tscribe.app
```

The app opens a recording/transcript window and also adds menu bar controls.
Closing or minimizing the window hides it to the menu bar and removes its Dock
icon. **Hide to Menu Bar** does the same. Click the microphone icon and choose
**Open tscribe**, or launch the app again from Finder, to restore the window and
Dock icon. Recording and transcription continue while the window is hidden. Starting a second native instance
activates the existing app.

If the icon only appears when you expand **Hidden Bar**, hold **⌘** and drag
tscribe to the always-visible side of Hidden Bar’s divider. The app keeps its
window and Dock icon available when its menu bar icon is offscreen. This also
applies when the menu bar is too crowded or the icon sits behind the camera
housing.

To install the build in `~/Applications` (quit the previous app first):

```bash
make install
make run
```

Installation preserves an existing app in a hidden `.tscribe-backup-*` directory
beside it. `TSCRIBE_APP_PATH` can select a native app at another location.

## Recording and permissions

- **Record Microphone** requests microphone access when first used.
- **Record System Audio** requests macOS screen/system-audio capture permission.
  The native app does not require BlackHole or output-device switching. It saves
  only audio; it does not save screen video. macOS may require you to quit and
  reopen the app after changing capture permission.
- **Stop** finalizes the WAV, saves session metadata, and transcribes if enabled.
- Quitting during recording/transcription finishes the active job before exiting.

The app uses `recording.default_device` for the microphone: leave it empty for
the system default, or specify a native device name/unique ID. PortAudio numeric
device indexes from the Python CLI are not native device IDs. Audio is converted
to the configured sample rate and channel count before being written as PCM WAV.

Whisper models download on first transcription. Audio is processed locally.
The bundled CTranslate2 engine uses the CPU on macOS. `transcription.gpu` requests
NVIDIA CUDA, not Apple GPU acceleration; leave it `false` on a Mac. If CUDA is
unavailable, transcription falls back to CPU automatically.
Experimental speaker grouping still uses the Python algorithm; replacing it with
WhisperKit/SpeakerKit requires the quality, performance and parity evaluation in
[TODO.md](../TODO.md).

## Shared configuration and recordings

The app reads and writes the same TOML settings and session files as the CLI.
Use `tscribe config --path` to find the active configuration file. The window's
Settings form covers model, language, automatic transcription, speaker grouping,
notifications and recent recordings. **Open config.toml** exposes the remaining
settings. Reopen the app after editing the file externally.

Open **Settings…** from the microphone menu or press **⌘,**. Caption settings
are also shared with the CLI through `[captions]` in `config.toml`.

## Live meeting captions

Enable **Live captions while recording** in Settings, select a caption model,
audio source, and Headphones/Speakers, then choose **Record Meeting** from the
window or menu bar. **Record Microphone** and **Record System Audio** also provide
captions when enabled. A separate floating captions window opens during capture;
use **Show Captions Window** to reopen it. Text size and always-on-top behavior
follow your saved preferences.

The caption model defaults to `base`, separate from the normal final-transcript
model. First use downloads that model; later use can run offline. Language uses
`transcription.language`. Example configuration:

```bash
tscribe config captions.enabled true
tscribe config captions.model base
tscribe config captions.output_mode headphones
tscribe config captions.audio_source both
tscribe config captions.font_size 32
tscribe config captions.always_on_top true
```

Each caption pass uses a closed WAV snapshot of at most the latest 30 seconds.
A separate worker processes one window at a time on an approximately three-second
cadence; it never queues an unbounded backlog. Actual delay depends on the model
and hardware. Words shared by consecutive decodes become stable; the latest
phrase stays provisional. VAD filters silence. If processing loses coverage, the
window reports missed captions while full audio capture continues independently.
Caption failures do not stop recording.

**Stop** preserves the latest draft as `STEM.captions.txt` and
`STEM.captions.json`, including provisional words and gap information. The draft
can miss the last few seconds or audio lost while inference was behind. With
`recording.auto_transcribe = true`, normal full-recording transcription follows
and replaces the preview with the final transcript. With it disabled, the draft
remains available in the app; select **Transcribe** later for a final version.
Live drafts do not perform speaker diarization. Final transcription uses the
existing `transcription.diarize` setting.

Combined meeting capture preserves separate original microphone/system WAVs under
`recordings/.tracks/STEM/` and produces a time-aligned mixed `STEM.wav` after
stopping. Caption snapshots use `recordings/.live/STEM/` and are removed when the
caption session ends. Normal session deletion/cleanup includes the drafts and
retained tracks. A crash can leave temporary snapshots in `.live`.

**Speaker mode is experimental.** This version has no acoustic echo cancellation;
remote voices leaking into the microphone may repeat or reduce accuracy. The
Headphones/Speakers choice records your setup and shows guidance; it does not
apply an echo filter. Real-call quality, echo handling, output-device changes,
and sustained CPU/power use still need validation. Live capture is currently a
native-app feature; the Python CLI retains recording and final transcription.

Completion notifications request permission when first needed. Worker diagnostics
are appended to `~/Library/Logs/tscribe/worker.log`. Errors also appear in the main
window, including missing permissions, model download failures and worker exits.

## Verification

```bash
make check

# Isolated temporary app: real icon, menu actions, and window hide/restore
make test-menu-bar

# Native audio conversion and Python worker integration, using isolated files
TSCRIBE_PYTHON_EXECUTABLE="$PWD/.venv/bin/python" \
TSCRIBE_CONFIG_FILE=/tmp/tscribe-tests/config.toml \
TSCRIBE_DATA_DIR=/tmp/tscribe-tests/data \
TSCRIBE_LOG_DIR=/tmp/tscribe-tests/logs \
  swift test --package-path macos --scratch-path build/swift

# Real launch check: requires a visible main window and a responding worker
# Quit any running native tscribe instance before this check.
open -n -W --env TSCRIBE_CONFIG_FILE=/tmp/tscribe-ui-check/config.toml \
  --env TSCRIBE_DATA_DIR=/tmp/tscribe-ui-check/data \
  dist/tscribe.app --args --smoke-report /tmp/tscribe-ui-check.json --smoke-menu-bar
cat /tmp/tscribe-ui-check.json

codesign --verify --deep --strict dist/tscribe.app
```

The desktop menu bar check requires a logged-in, visible macOS desktop. It uses
a temporary app with a separate bundle identifier and isolated settings, so the
regular app can keep recording. It fails if a menu bar manager hides the test
icon; expand the hidden-icons section before running it. Visibility checks use
the actual onscreen position, including the camera housing, rather than only
AppKit’s visibility flag.

For an opt-in real-speech regression, use a speech file and an already cached
model (the test disables downloads):

```bash
TSCRIBE_LIVE_TEST_AUDIO=/path/to/speech.wav TSCRIBE_LIVE_TEST_MODEL=small \
  uv run --locked --group dev pytest tests/test_live.py -m slow

# Build a separate preview while preserving dist/tscribe.app
uv run --locked --group mac-app python packaging/macos/build_native.py \
  --output build/live-preview/tscribe.app
uv run --locked python packaging/macos/test_worker.py \
  build/live-preview/tscribe.app/Contents/Resources/Worker/tscribe-worker
```

The bundled-worker check also verifies that multiprocessing helpers cannot open
a second protocol server and steal caption requests. Release builds run it before
uploading packages.

The launch check never records audio or grants capture permission. Audio tests
exercise WAV conversion using synthetic samples, not microphone input. A real
microphone/system-audio recording check still requires user permission.

## Python CLI

```bash
uv tool install .
tscribe record --mic
tscribe transcribe meeting.wav --output exports/meeting --format txt,json
tscribe app
```

The bundled worker also exposes the CLI without an external Python installation:

```bash
dist/tscribe.app/Contents/Resources/Worker/tscribe-worker --cli --help
```

The Python recording command retains its cross-platform audio backends. Its macOS
system-audio capture still uses [BlackHole](macos-system-audio.md).

## Distribution

`make dist` clears old distribution outputs and creates the current wheel,
source archive, `tscribe.app`, `tscribe-VERSION-macos-ARCH.zip`, and `SHA256SUMS`. The worker's
intermediate directory stays in `build/worker-dist`, outside `dist/`. Build and
cleanup commands share a lock: wait for an active operation to finish before
starting another. A failed app build preserves the last complete app; a ZIP
replaces its previous version only after archive verification succeeds.

Pushing a matching version tag (for example `v2.2.0`) triggers the GitHub release
workflow. It runs CI, builds both Apple Silicon (`arm64`) and Intel (`x86_64`)
archives, checks each bundled worker, and publishes the packages plus SHA256
checksums. No PyPI upload or Apple notarization occurs automatically.

A default build is ad-hoc signed for local testing. Public distribution still
needs a Developer ID Application certificate and Apple notarization:

```bash
TSCRIBE_CODESIGN_IDENTITY='Developer ID Application: Your Name (TEAMID)' \
  uv run --group mac-app python packaging/macos/build_native.py

ditto -c -k --sequesterRsrc --keepParent dist/tscribe.app dist/tscribe-macos.zip
xcrun notarytool submit dist/tscribe-macos.zip --keychain-profile YOUR_PROFILE --wait
xcrun stapler staple dist/tscribe.app
ditto -c -k --sequesterRsrc --keepParent dist/tscribe.app dist/tscribe-macos-notarized.zip
```

Use a keychain profile already configured for your Apple developer account.
A local build or signature verification does not confirm notarization.
