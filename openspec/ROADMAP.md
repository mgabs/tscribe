# OpenSpec Roadmap: tscribe

High-level roadmap organizing pending backlog items from `TODO.md` into spec-rails capabilities.

---

## 1. Roadmap Overview & Status

| Track | Capability Path | Description | Status | Priority |
| :--- | :--- | :--- | :--- | :--- |
| **Audio Capture** | `audio/bounds` | Automatic `--start` / `--end` bounds for record & play | Planned | Medium |
| **Audio Capture** | `audio/vad` | Voice Activity Detection (`record --vad`) | Planned | High |
| **Audio Capture** | `audio/device-resilience` | Handle output-device switching during live meetings | Planned | High |
| **Storage & Metadata** | `session/tagging` | Tag and comment annotations on clips for search | Planned | Medium |
| **Storage & Metadata** | `audio/compression` | Evaluate compressed audio formats (MP3/Opus) vs WAV | Evaluation | Low |
| **Live Captions** | `captions/stabilization` | Echo cancellation & combined capture call validation | In Progress | Critical |
| **Live Captions** | `captions/benchmarks` | Benchmarking latency, accuracy, memory, and CPU/energy | Planned | Medium |
| **Live Captions** | `captions/cli-streaming` | CLI live recording and streaming caption pipeline | Planned | High |
| **Transcription** | `transcription/whisperkit-eval` | WhisperKit vs faster-whisper Apple Silicon spike | Evaluation | High |
| **Surfaces** | `surfaces/cli-polish` | Command aliases (`list` -> `ls`) and CLI ergonomic tweaks | Planned | Low |
| **Surfaces** | `surfaces/webui` | Local browser UI (`tscribe serve`) for session review | Backlog | Low |

---

## 2. Capability Tracks & Phasing

### Phase 1: Live Captions & Real-Time Parity (Current Focus)

Focus on stabilizing the live captions engine and bringing streaming capabilities to the CLI.

#### `captions/stabilization`
- **Scope**:
  - Echo cancellation validation on real call topologies (open speakers, headphones, overlapping speech, latency drifts).
  - Dynamic audio output-device re-routing during active capture.
  - End-to-end verification of dual-stream (mic + loopback) capture.
- **YAGNI Boundary**: Do not introduce cloud-based cleanup or multi-room spatial DSP.

#### `captions/cli-streaming`
- **Scope**:
  - Bring streaming live captions (`transcribe --live` or `record --live`) to terminal stdout/curses interface.
  - Share core windowing and provisional phrase streaming buffer between macOS app and CLI shell.
- **YAGNI Boundary**: No web sockets or network streaming protocol yet.

#### `captions/benchmarks`
- **Scope**:
  - Automated measurement harness for caption latency, CPU utilization, peak RAM, and power consumption on Apple Silicon.
- **YAGNI Boundary**: No synthetic benchmark bots; test on recorded standard reference clips.

---

### Phase 2: Core Capture Upgrades & VAD

Improve capture ergonomics and efficiency at recording time.

#### `audio/vad`
- **Scope**:
  - Implement `--vad` flag on `tscribe record`.
  - Frame-level silence gating using a lightweight offline model (e.g., Silero VAD).
  - Retain timestamp alignment when writing speech segments.
- **YAGNI Boundary**: No real-time speaker identification during VAD; purely speech/non-speech decision.

#### `audio/bounds`
- **Scope**:
  - Add `--start` and `--end` parameters to `tscribe record` (duration/time bounded) and `tscribe play` (range playback).
- **YAGNI Boundary**: No complex scheduling cron engine inside the CLI.

#### `audio/device-resilience`
- **Scope**:
  - Audio stream recovery when headphones are unplugged or output devices switch during recording.
- **YAGNI Boundary**: No custom virtual audio driver packaging.

---

### Phase 3: Transcription Engine Evolution

#### `transcription/whisperkit-eval`
- **Scope**:
  - Benchmark WhisperKit against bundled `faster-whisper` on Apple Silicon.
  - Validate accuracy across multilingual datasets, accents, and noisy tracks.
  - Compare cold start, memory footprint, export parity (SRT, VTT, JSON, TXT), and offline air-gapped readiness.
  - Deliver Go / No-Go decision on migrating the macOS transcription worker.
- **YAGNI Boundary**: Do not refactor core engine abstractions before the benchmark report is approved.

---

### Phase 4: Metadata, Storage & Search

#### `session/tagging`
- **Scope**:
  - Add `--tag` and `--comment` options to `record`, `transcribe`, and `label`.
  - Expose tag/comment search filtering in `tscribe search` and `tscribe list`.
  - Persist tags cleanly in session metadata JSON.
- **YAGNI Boundary**: No semantic vector search or external database dependencies; use local JSON session metadata.

#### `audio/compression`
- **Scope**:
  - Spike storage size vs CPU overhead and transcribe accuracy for MP3/Opus encoding.
- **YAGNI Boundary**: Keep WAV as default lossless capture format.

---

### Phase 5: Surfaces & Ergonomics

#### `surfaces/cli-polish`
- **Scope**:
  - Add `ls` alias for `list`.
  - Terminal UX polish and documentation examples (e.g. Claude Code integration recipes).

#### `surfaces/webui`
- **Scope**:
  - Optional local web server (`tscribe serve`) displaying recordings, audio player, and synchronized transcripts.
- **YAGNI Boundary**: Strictly local read-only viewer; no multi-user auth or remote management.

---

## 3. Completed Capabilities (Archived)

- `diarization-engine` (Archived: `2026-10-31-add-nemotron-diarization-engine`):
  - NVIDIA Nemotron 3 Diarization engine integrated alongside WeSpeaker fallback.
- `speaker-labeling` (Archived: `2026-11-01-speaker-mapping-interface`):
  - Interactive and CLI speaker mapping interface (`tscribe label`).
- `recordings-cleanup` (`tscribe clean [--30]`):
  - Automated deletion and pruning of old session recordings.
- `macos-menubar-app` (`tscribe app [--install-desktop]`):
  - Native macOS menu bar status item, floating caption window, and system audio loopback capture.
