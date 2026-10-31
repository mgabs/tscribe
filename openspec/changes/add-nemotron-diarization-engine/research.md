# Research & Technical Tradeoffs

## 1. Intent & Ground Truth

**Intent:** Make the speaker-diarization engine selectable, adding NVIDIA Nemotron 3 Diarization
(`nvidia/Nemotron-3-Diarization`) alongside the current engine. It must work in the packaged macOS app.

**Verified in the codebase:**
- `src/tscribe/diarization.py` `Diarizer` pipeline: faster-whisper VAD -> WeSpeaker ONNX embeddings
  (sherpa-onnx) -> spectral/agglomerative clustering (sklearn/scipy) -> `list[SpeakerTurn]`.
- Models download on first use into `get_data_dir()/models/diarization`; audio stays local.
- `attribute_speakers()` maps `SpeakerTurn`s onto transcript segments; it is engine-agnostic.
- Config has only `diarize: bool` (`config.py`, `config.example.toml`); no engine selection.
- `openspec/specs/` is empty, so there are no `REQ-*`/`NFR-*` to modify.

**NOT verified (blocked, HF returns 403 from this network):** the model card and discussion #2.
Unknown: runtime/format (NeMo/PyTorch vs ONNX/CoreML), max speakers, licence/gating, weight size,
offline vs streaming, macOS/Apple Silicon support. If it is Sortformer-family, expect a ~4 speaker cap
and a NeMo/PyTorch runtime. These must be confirmed before Go.

**Constraints from the user:** engine is selectable (Nemotron default, per later developer decision; WeSpeaker remains selectable); must be packaged into the app.

## 2. Options Explored

**A. Pluggable engine, Nemotron in-process (Python).** `diarize_engine = "wespeaker" | "nemotron"`
behind a shared `diarize(path, num_speakers) -> list[SpeakerTurn]` interface. Nemotron runs via its native runtime.
- Pros: smallest code change; reuses `attribute_speakers`, config and CLI.
- Cons: PyTorch/NeMo (if required) greatly inflates the self-contained app.

**B. Pluggable engine, Nemotron exported to ONNX/CoreML.** Same interface; model converted or consumed
from an existing export, run via onnxruntime/sherpa-onnx or CoreML.
- Pros: keeps the app small and the runtime consistent with today's stack.
- Cons: depends on an export existing (or us producing one); streaming/stateful models export poorly.

**C. Optional extra, not bundled.** Nemotron available only when the user installs an extra; app falls back to WeSpeaker.
- Pros: zero app-size impact. Cons: violates "packaged into the app".

## 3. Tradeoff Matrix

| Criteria | Option A | Option B | Option C |
| :--- | :--- | :--- | :--- |
| **Complexity** | Low code, high packaging | Medium (export/convert) | Low |
| **New Dependencies** | torch + nemo (likely) | onnxruntime/CoreML (mostly present) | torch + nemo, optional |
| **Performance & Latency** | Unknown; MPS/CPU on Mac | Likely good, unknown | Same as A |
| **Maintenance Burden** | High (heavy runtime upgrades) | Medium | Low-Medium |
| **Blast Radius** | App size/build, signing | Model conversion pipeline | Docs/fallback only |

## 4. Recommendation

Go with the selectable-engine interface now (the shared part of A/B), and choose A vs B only once the
model card confirms its runtime and an ONNX/CoreML path. Keep WeSpeaker selectable (Nemotron is the default); download Nemotron weights
on first use rather than bundling them.

## 5. Breaking Changes & Deprecations

No specs exist in `openspec/specs/`. Behavioural break: the default engine changes from WeSpeaker to Nemotron (developer decision), so existing users get a first-use download and different output unless they set `diarize_engine = "wespeaker"`.

## Review Gate
- [x] **Gate 0 Decision**: Human decides Go (name the option) or No-Go before the proposal is drafted.
  Decision: **Go, Option A** (native runtime, in-process), recorded from the developer's explicit choice.
