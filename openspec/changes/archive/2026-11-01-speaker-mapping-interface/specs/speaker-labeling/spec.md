# Spec Delta

## Purpose
Provides an interactive CLI wizard and native macOS application interface for mapping diarized speakers to human names, preserving raw speaker identifiers for reversible, idempotent remapping across all output formats.

## ADDED Requirements

### Requirement: REQ-SPK-1 Raw speaker preservation
The system MUST preserve the original diarization speaker identifier (`raw_speaker`) for every transcript segment in memory and serialized transcript JSON files alongside the human-readable `speaker` field.

#### Scenario: Legacy transcript backward compatibility
- **WHEN** a transcript JSON without `raw_speaker` fields is loaded
- **THEN** the system MUST treat the existing `speaker` field as the `raw_speaker`.

#### Scenario: Serialization preserves both fields
- **WHEN** a transcript segment with `raw_speaker="Speaker 1"` and `speaker="Alice"` is saved to JSON
- **THEN** both `raw_speaker` and `speaker` SHALL be present in the segment dictionary.

### Requirement: REQ-SPK-2 Idempotent speaker remapping
The remapping engine MUST evaluate new mappings against the immutable `raw_speaker` value rather than the current `speaker` value, ensuring repeated remappings or edits never corrupt cluster assignments.

#### Scenario: Successive renames
- **WHEN** a user renames `Speaker 1` to `Alice`, and subsequently renames `Speaker 1` to `Alicia`
- **THEN** all segments whose `raw_speaker` is `Speaker 1` SHALL have their `speaker` updated to `Alicia`.

### Requirement: REQ-SPK-3 Worker speaker inspection RPC
The worker process MUST provide a `get-speakers` command that accepts a session stem and returns the distinct speakers found in the transcript, including their `raw_speaker`, current `speaker`, and a preview text sample from their earliest spoken segment.

#### Scenario: Inspect speakers for active transcript
- **WHEN** a client sends a `get-speakers` request with a valid `stem`
- **THEN** the worker returns a list of speaker records containing `raw_speaker`, `speaker`, `start`, and `sample_text`.

### Requirement: REQ-SPK-4 Worker speaker update RPC
The worker process MUST provide a `set-speakers` command accepting a session stem and a dictionary mapping `raw_speaker` to human names, which updates the transcript JSON, rewrites existing TXT, SRT, and VTT files, stores the mapping in `metadata.json`, and returns the newly formatted transcript text.

#### Scenario: Update speaker mappings via RPC
- **WHEN** a client sends `set-speakers` with `stem="session-1"` and `mapping={"Speaker 1": "Alice"}`
- **THEN** the worker writes the updated files and returns `{"status": "ok", "text": "<updated_transcript_text>"}`.

### Requirement: REQ-SPK-5 Interactive CLI mapping
When the user runs `tscribe label <ref>` without the `--names` option in an interactive terminal, the command MUST prompt the user for each distinct speaker, displaying an excerpt of what they said.

#### Scenario: CLI interactive wizard
- **WHEN** the user executes `tscribe label HEAD` without `--names`
- **THEN** the CLI prompts for each speaker sequentially with speech samples and writes the updated labels upon confirmation.

#### Scenario: Non-interactive flag compatibility
- **WHEN** the user executes `tscribe label HEAD --names "Alice,Bob"`
- **THEN** the command SHALL apply the positional or key-value names non-interactively and update all transcript files.

### Requirement: REQ-SPK-6 Post-transcribe prompt configuration
The system MUST support a `prompt_speaker_labels` boolean configuration setting under `[transcription]`, defaulting to `false`. When enabled and interactive, transcription commands that produce two or more distinct speakers SHALL prompt to label speakers upon completion.

#### Scenario: Automatic prompt when enabled
- **WHEN** `prompt_speaker_labels = true` and a recording is transcribed with multiple speakers in an interactive terminal
- **THEN** the CLI launches the speaker labeling wizard immediately following transcription.

#### Scenario: Default non-interactive behavior
- **WHEN** `prompt_speaker_labels = false`
- **THEN** the CLI completes transcription without pausing for speaker input.

### Requirement: REQ-SPK-7 macOS speaker mapping interface
The macOS desktop application detail view MUST provide a "Map Speakers" action button whenever a transcribed session with speaker turns is selected, presenting a sheet modal with distinct speakers, sample spoken text, and editable name fields.

#### Scenario: Apply mapping from macOS app
- **WHEN** a user enters names in the "Map Speakers" sheet and clicks "Save"
- **THEN** the application sends `set-speakers` to the worker and refreshes the displayed transcript with the new speaker names.

### Requirement: NFR-SPK-1 Remap latency
The worker `set-speakers` command and CLI label remapping MUST complete remapping and file rewrites within 100 milliseconds for transcripts up to 5,000 segments.

#### Scenario: Fast remapping on large transcripts
- **WHEN** remapping a transcript with 5,000 segments
- **THEN** the file updates and RPC response SHALL complete in under 100ms.

## Review Gate
- [x] **Gate 2 Approval**: Specifications reviewed and approved by human before technical design.
