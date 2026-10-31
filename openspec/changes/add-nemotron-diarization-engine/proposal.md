# Proposal

## Intent
Add NVIDIA Nemotron 3 Diarization as a selectable speaker-diarization engine, running natively in-process
(research Option A), as the default engine, with the existing WeSpeaker pipeline remaining selectable, and package its runtime into the macOS app.

## Problem Statement
Diarization has a single fixed engine (VAD + WeSpeaker embeddings + clustering). Users cannot choose an
end-to-end model that may be more accurate, and config has no engine selection.

## Capabilities

### New Capabilities
- `diarization-engine`: selectable diarization engine (`nemotron` default, `wespeaker`), shared
  `diarize(path, num_speakers) -> list[SpeakerTurn]` contract, first-use model download, local-only audio.

### Modified Capabilities
- None (`openspec/specs/` is empty).

## Scope

### In-Scope
- `diarize_engine` config key and CLI option; default `nemotron`; `wespeaker` keeps today's behaviour when selected.
- Engine interface extracted from `Diarizer`; `attribute_speakers` untouched.
- Nemotron engine using its native runtime, weights downloaded on first use.
- Packaging the Nemotron runtime into the self-contained macOS app build.
- Clear error when the engine, runtime or weights are unavailable (no silent fallback).

### Out-of-Scope (YAGNI)
- ONNX/CoreML conversion of the model (Option B).
- Bundling model weights inside the app.
- Streaming/live-caption diarization.
- Fine-tuning, new speaker-labelling UI, or changes to `attribute_speakers`.
- Engines beyond `wespeaker` and `nemotron`.

## Assumptions
- **ASM-GEN-1**: Nemotron 3 Diarization is usable via a Python runtime on macOS (unverified; model card unreadable).
- **ASM-GEN-2**: Its licence permits downloading and use in this app (unverified).
- **ASM-GEN-3**: Its speaker limit may be below the WeSpeaker path; the engine must surface it, not hide it.
- **ASM-GEN-4**: The extra runtime size is acceptable for the app bundle.
- **ASM-GEN-5**: Making Nemotron the default is accepted despite the first-use weight download and heavier runtime; first diarization needs network access.

## Success Metrics
- `diarize_engine = "wespeaker"` is output-identical to today.
- Default (`nemotron`) produces `SpeakerTurn`s that pass the existing attribution tests.
- Packaged app runs the Nemotron engine end to end on a sample file.
- App bundle size increase is measured and recorded.

## Review Gate
- [x] **Gate 1 Approval**: Proposal reviewed and approved by human before drafting specs.
