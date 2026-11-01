# Research & Technical Tradeoffs

## 1. Intent & Ground Truth
- **Problem**: Transcripts output generic labels (`Speaker 1`, `Speaker 2`). Currently, re-labeling is only possible via `tscribe label <ref> --names "Alice,Bob"`, which is non-interactive and requires knowing speaker ordering in advance. There is no UI in the macOS app to map speakers, and transcripts permanently overwrite speaker labels so original diarization cluster IDs are lost.
- **Codebase Constraints**:
  - `tscribe.diarization.parse_speaker_names` handles comma-separated and `1=Name` key-value strings.
  - `TranscriptSegment` in `tscribe.transcriber` has `speaker: Optional[str]`, but no `raw_speaker` preservation.
  - `tscribe.worker.Worker` communicates with macOS app via JSON-RPC socket commands (`bootstrap`, `transcribe`, `read-transcript`).
  - macOS app is built in SwiftUI (`TscribeApp.swift`, `AppModel.swift`, `WorkerClient.swift`).
  - Configuration lives in `tscribe.config.TranscriptionDefaults`.

## 2. Options Explored

### Option A: In-place string replacement in CLI and App
- **Description**: Add an interactive CLI wizard to `tscribe label` and a basic prompt dialog in SwiftUI. Directly overwrite `speaker` field in JSON/TXT/SRT files.
- **Pros**: Minimal code changes, zero changes to data models.
- **Cons**: Irreversible; once renamed, original speaker cluster (`Speaker 1`) is erased; re-mapping or correcting mistakes is ambiguous.

### Option B: Bidirectional mapping with raw speaker preservation (Recommended)
- **Description**: Add `raw_speaker` to `TranscriptSegment`. Save `speaker_map` in session metadata. Expose `get-speakers` and `set-speakers` worker RPC commands. Provide both interactive CLI prompt (gated by config `prompt_speaker_labels`) and a SwiftUI sheet in the macOS app with speech preview snippets.
- **Pros**: Non-destructive, idempotent remapping, consistent across CLI and desktop app, reversible.
- **Cons**: Small schema extension in transcript segment JSON (`raw_speaker`).

### Option C: Standalone Web/TUI speaker management dashboard
- **Description**: Spin up a local web UI or Textual TUI with audio waveform snippet playback for each speaker.
- **Pros**: Rich audio playback and timeline visualization.
- **Cons**: Heavy dependencies, high complexity, violates YAGNI.

## 3. Tradeoff Matrix

| Criteria | Option A (In-place) | Option B (Dual Surface + Raw Preservation) | Option C (Web/TUI Dashboard) |
| :--- | :--- | :--- | :--- |
| **Complexity** | Low | Medium | High |
| **New Dependencies** | None | None | High (Textual or web framework) |
| **Performance & Latency** | Instant | Instant (<5ms file update) | Heavy startup |
| **Maintenance Burden** | Low (fragile data) | Low (clean separation) | High |
| **Blast Radius** | `cli.py` only | `transcriber.py`, `worker.py`, `cli.py`, `TscribeApp.swift` | Entire application |

## 4. Recommendation
Adopt Option B. It satisfies both CLI and macOS app needs with zero external dependencies, maintains clean idempotency by keeping raw speaker identities, and strictly respects YAGNI.

## 5. Breaking Changes & Deprecations
None. Backward compatible with existing transcript JSON files (missing `raw_speaker` defaults to `speaker`).

## Review Gate
- [x] **Gate 0 Decision**: Go (Option B)
