# Proposal

## Intent
Provide an interactive CLI prompt and native macOS SwiftUI sheet to easily map diarized speakers (`Speaker 1`, `Speaker 2`) to custom names (`Alice`, `Bob`), while preserving raw speaker identities in transcripts and session metadata for reversible, idempotent remapping.

## Problem Statement
Currently, assigning names to diarized speakers requires running `tscribe label <ref> --names "Alice,Bob"` with upfront knowledge of speaker order and zero preview context. The macOS application has no interface for speaker re-labeling. Renaming permanently replaces the speaker label in transcript files, making it impossible to audit or re-map without re-transcribing.

## Capabilities

### New Capabilities
- `speaker-labeling`: Interactive CLI wizard and macOS UI for mapping diarized speaker turns to custom names, preserving underlying raw speaker IDs and updating all output formats (JSON, TXT, SRT, VTT).

### Modified Capabilities
None.

## Scope

### In-Scope
- **Raw Speaker Tracking**: Extend `TranscriptSegment` and transcript JSON to preserve `raw_speaker` alongside the mapped `speaker` name.
- **Session Metadata**: Record active `speaker_map` in session metadata (`metadata.json`).
- **Worker RPC Commands**: Add `get-speakers` (returns distinct speakers with speech snippets) and `set-speakers` (applies mapping, updates files, returns new transcript text) to `tscribe.worker`.
- **Interactive CLI Wizard**: Enhance `tscribe label <ref>` to prompt interactively with speech previews when `--names` is omitted.
- **Post-Transcribe Config Gate**: Add `transcription.prompt_speaker_labels = false` config option to optionally launch the wizard right after transcription.
- **macOS App UI**: Add "Map Speakers" button and a sheet modal in `TscribeApp.swift` to view snippets and assign names.

### Out-of-Scope (YAGNI)
- Audio clip playback of speaker turns within the UI.
- Real-time live speaker identification during active recording.
- Cross-recording global voiceprints or biometric profile databases.
- Automatic LLM-based speaker name guessing from transcript text.

## Assumptions
- **ASM-GEN-1**: Existing transcript files without `raw_speaker` fall back to using their current `speaker` field as `raw_speaker`.
- **ASM-GEN-2**: Transcripts retain speaker turns only when diarization was enabled during transcription.

## Success Metrics
- Users can run `tscribe label HEAD` without arguments and interactively map speakers with sample text context.
- Users can map speakers directly in the macOS app via the "Map Speakers" sheet and immediately see the updated transcript and files.
- Re-labeling multiple times remains idempotent and accurate against the original diarization clusters.

## Review Gate
- [x] **Gate 1 Approval**: Proposal reviewed and approved by human before drafting specs.
