# Spec Delta

## Purpose
Defines selectable speaker-diarization engines behind one contract, so users get NVIDIA Nemotron 3 Diarization by default and can choose the WeSpeaker pipeline instead.

## ADDED Requirements

### Requirement: REQ-DIAR-1 Engine selection
The system MUST provide a `diarize_engine` setting (config file and CLI option) accepting `nemotron` or `wespeaker`, defaulting to `nemotron`.

#### Scenario: Default engine
- **WHEN** diarization runs and `diarize_engine` is unset
- **THEN** the Nemotron engine produces the speaker turns

#### Scenario: WeSpeaker selected
- **WHEN** `diarize_engine = "wespeaker"` and diarization runs
- **THEN** the WeSpeaker engine is used and output is identical to the behaviour before this change

#### Scenario: Invalid value
- **WHEN** `diarize_engine` is any other value
- **THEN** the system reports an error naming the valid values and does not diarize

### Requirement: REQ-DIAR-2 Common engine contract
Every engine MUST implement `diarize(audio_path, num_speakers) -> list[SpeakerTurn]`, and speaker attribution SHALL consume that result without engine-specific handling.

#### Scenario: Attribution is engine-agnostic
- **WHEN** either engine returns turns for the same audio
- **THEN** `attribute_speakers` labels transcript segments from them with no code path depending on the engine

### Requirement: REQ-DIAR-3 Nemotron weights on first use
The Nemotron engine MUST download its model weights on first use into the diarization models directory, and MUST NOT require weights to be bundled in the app.

#### Scenario: First run
- **WHEN** Nemotron is selected and weights are absent
- **THEN** they are downloaded once and reused on later runs

#### Scenario: Download failure
- **WHEN** the download fails or the file is empty or invalid
- **THEN** a clear error is raised, no partial file remains at the final path, and no other engine is substituted

### Requirement: REQ-DIAR-4 Packaged macOS app support
The packaged macOS app MUST include the runtime needed to run the Nemotron engine.

#### Scenario: Packaged run
- **WHEN** the packaged app is used with `diarize_engine = "nemotron"` on a sample recording
- **THEN** speaker turns are produced without a separately installed runtime

### Requirement: REQ-DIAR-5 Unavailable engine fails loudly
If the selected engine's runtime or weights are unavailable, the system MUST fail with an actionable error and MUST NOT silently fall back to another engine.

#### Scenario: Missing runtime
- **WHEN** Nemotron is selected and its runtime cannot be imported
- **THEN** the error names the missing component and how to resolve it

### Requirement: REQ-DIAR-6 Speaker limit surfaced
If the selected engine supports fewer speakers than requested or detected, the system MUST report the limit rather than silently merging or dropping speakers.

#### Scenario: Request exceeds limit
- **WHEN** `num_speakers` exceeds the Nemotron engine's maximum
- **THEN** an error or explicit warning states the maximum

### Requirement: REQ-DIAR-7 Local audio
Both engines MUST process audio locally; audio SHALL NOT be sent to any remote service.

#### Scenario: Offline after download
- **WHEN** weights are already cached and the network is unavailable
- **THEN** diarization still completes

### Requirement: NFR-DIAR-1 WeSpeaker path isolated
Running the WeSpeaker engine MUST NOT import the Nemotron runtime.

#### Scenario: WeSpeaker import cost
- **WHEN** diarization runs with `diarize_engine = "wespeaker"`
- **THEN** the Nemotron runtime is not loaded

### Requirement: NFR-DIAR-2 Bundle size recorded
The app bundle size increase caused by the Nemotron runtime MUST be measured and recorded in the change before release. (ASM-GEN-4; no numeric budget is set until measured.)

#### Scenario: Size check
- **WHEN** the app is packaged with and without the Nemotron runtime
- **THEN** the difference is recorded in the design or release notes

## Review Gate
- [x] **Gate 2 Approval**: Specifications reviewed and approved by human before technical design.
