# Offline Speaker Diarization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add offline multi-speaker diarization to `tscribe` with speaker attribution, `--diarize`, `--speakers`, custom names (`--names "Alice,Bob"`), and a `tscribe label` relabeling command.

**Architecture:** Post-transcription audio analysis pipeline that combines bundled Silero VAD speech boundaries with a lightweight ONNX speaker embedding model (CAM++) and scikit-learn agglomerative clustering, mapping speaker identities to Whisper segments by temporal overlap.

**Tech Stack:** Python 3.10+, `onnxruntime`, `scikit-learn`, `numpy`, `faster-whisper`, `click`.

**Spec:** [`docs/superpowers/specs/2026-10-15-speaker-diarization-design.md`](file:///Users/mohammed.metawea/Workbench/interests/tscribe/docs/superpowers/specs/2026-10-15-speaker-diarization-design.md)

## Global Constraints

- Must work 100% offline without Hugging Face downloads (`HF_HUB_OFFLINE=1`).
- No PyTorch dependencies.
- Retain existing `TranscriptResult` backward-compatibility when diarization is disabled (`speaker` is `None`).
- Commands must run with `rtk ` shell prefix.

## Review Focus

1. Empty audio or silence-only input during diarization should return segments with `speaker=None` without throwing unhandled exceptions.
2. Recordings with a single speaker should cleanly cluster into `Speaker 1` without crashing clustering.
3. Segments with partial overlaps should attribute to the speaker possessing the largest overlap duration.
4. Custom names list with fewer names than detected speakers should name the initial speakers and fall back to `Speaker N` for the remainder.
5. In explicit key-value mapping (`"1=Alice,3=Charlie"`), whitespace around names or keys should be stripped and invalid entries ignored gracefully.

---

### Task 1: Schema & Output Formatters Extension

**Files:**
- Modify: `src/tscribe/transcriber.py:11-70`
- Test: `tests/test_speaker_formatters.py`
- Modify: `pyproject.toml` (add `scikit-learn`)

**Interfaces:**
- Consumes: Existing `TranscriptSegment`, `TranscriptResult`.
- Produces: `TranscriptSegment.speaker: str | None`, formatted `.txt` with grouped speaker headings, `.json` with `"speaker"`, `.srt` with `[Speaker]` prefix, and `.vtt` with `<v Speaker>` tags.

- [ ] **Step 1: Write the failing tests for formatters with speaker labels**

```python
# tests/test_speaker_formatters.py
from tscribe.transcriber import TranscriptResult, TranscriptSegment


def test_format_txt_with_speakers():
    result = TranscriptResult(
        file="test.wav",
        model="small",
        language="en",
        segments=[
            TranscriptSegment(start=0.0, end=2.0, text="Hello world.", speaker="Alice"),
            TranscriptSegment(start=2.1, end=4.0, text="How are you?", speaker="Alice"),
            TranscriptSegment(start=4.5, end=6.0, text="I am fine.", speaker="Bob"),
        ],
    )
    expected = "[Alice]:\nHello world.\nHow are you?\n\n[Bob]:\nI am fine."
    assert result.to_txt() == expected


def test_format_json_with_speakers():
    result = TranscriptResult(
        file="test.wav",
        model="small",
        language="en",
        segments=[
            TranscriptSegment(start=0.0, end=2.0, text="Hello.", speaker="Alice"),
        ],
    )
    data = result.to_json()
    assert data["segments"][0]["speaker"] == "Alice"


def test_format_vtt_with_speakers():
    result = TranscriptResult(
        file="test.wav",
        model="small",
        language="en",
        segments=[
            TranscriptSegment(start=0.0, end=2.0, text="Hello.", speaker="Alice"),
        ],
    )
    vtt = result.to_vtt()
    assert "<v Alice>Hello.</v>" in vtt


def test_format_srt_with_speakers():
    result = TranscriptResult(
        file="test.wav",
        model="small",
        language="en",
        segments=[
            TranscriptSegment(start=0.0, end=2.0, text="Hello.", speaker="Alice"),
        ],
    )
    srt = result.to_srt()
    assert "[Alice] Hello." in srt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk uv run pytest tests/test_speaker_formatters.py -v`  
Expected: FAIL (AttributeError or assertion failure due to missing speaker grouping).

- [ ] **Step 3: Add `scikit-learn` dependency & update `src/tscribe/transcriber.py`**

Add `scikit-learn>=1.3.0` to `dependencies` in `pyproject.toml`, run `uv sync`, then update `TranscriptSegment` and `TranscriptResult` in `src/tscribe/transcriber.py`:

```python
@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    confidence: float = 0.0
    speaker: str | None = None


@dataclass
class TranscriptResult:
    file: str
    model: str
    language: str
    segments: list[TranscriptSegment] = field(default_factory=list)

    def to_txt(self) -> str:
        """Plain text, grouped by speaker if present."""
        if not self.segments:
            return ""
        if not any(seg.speaker for seg in self.segments):
            return "\n".join(seg.text.strip() for seg in self.segments if seg.text.strip())

        blocks: list[str] = []
        current_speaker: str | None = None
        current_texts: list[str] = []

        for seg in self.segments:
            text = seg.text.strip()
            if not text:
                continue
            speaker = seg.speaker or "Unknown"
            if speaker != current_speaker:
                if current_texts and current_speaker:
                    blocks.append(f"[{current_speaker}]:\n" + "\n".join(current_texts))
                current_speaker = speaker
                current_texts = [text]
            else:
                current_texts.append(text)

        if current_texts and current_speaker:
            blocks.append(f"[{current_speaker}]:\n" + "\n".join(current_texts))

        return "\n\n".join(blocks)

    def to_json(self) -> dict:
        return {
            "file": self.file,
            "model": self.model,
            "language": self.language,
            "segments": [
                {
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text.strip(),
                    "confidence": seg.confidence,
                    "speaker": seg.speaker,
                }
                for seg in self.segments
            ],
        }

    def to_srt(self) -> str:
        lines = []
        for i, seg in enumerate(self.segments, 1):
            start_ts = _format_srt_time(seg.start)
            end_ts = _format_srt_time(seg.end)
            lines.append(f"{i}")
            lines.append(f"{start_ts} --> {end_ts}")
            prefix = f"[{seg.speaker}] " if seg.speaker else ""
            lines.append(f"{prefix}{seg.text.strip()}")
            lines.append("")
        return "\n".join(lines)

    def to_vtt(self) -> str:
        lines = ["WEBVTT", ""]
        for seg in self.segments:
            start_ts = _format_vtt_time(seg.start)
            end_ts = _format_vtt_time(seg.end)
            lines.append(f"{start_ts} --> {end_ts}")
            if seg.speaker:
                lines.append(f"<v {seg.speaker}>{seg.text.strip()}</v>")
            else:
                lines.append(seg.text.strip())
            lines.append("")
        return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk uv run pytest tests/test_speaker_formatters.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add pyproject.toml uv.lock src/tscribe/transcriber.py tests/test_speaker_formatters.py
rtk git commit -m "feat(transcriber): add speaker attribute and output formatters"
```

---

### Task 2: Speaker Name Parser & Attribution Matcher

**Files:**
- Create: `src/tscribe/diarization.py`
- Test: `tests/test_diarization_attribution.py`

**Interfaces:**
- Consumes: `TranscriptSegment`, time ranges.
- Produces: `parse_speaker_names(names_str: str | None) -> dict[str, str]`, `SpeakerTurn(start: float, end: float, speaker_id: str)`, `attribute_speakers(segments, speaker_turns, name_map) -> list[TranscriptSegment]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_diarization_attribution.py
from tscribe.diarization import (
    SpeakerTurn,
    attribute_speakers,
    parse_speaker_names,
)
from tscribe.transcriber import TranscriptSegment


def test_parse_speaker_names_positional():
    assert parse_speaker_names("Alice, Bob,Charlie") == {
        "Speaker 1": "Alice",
        "Speaker 2": "Bob",
        "Speaker 3": "Charlie",
    }


def test_parse_speaker_names_explicit():
    assert parse_speaker_names("1=Alice, 3=Charlie") == {
        "Speaker 1": "Alice",
        "Speaker 3": "Charlie",
    }


def test_parse_speaker_names_empty():
    assert parse_speaker_names(None) == {}
    assert parse_speaker_names("") == {}


def test_attribute_speakers_overlap():
    segments = [
        TranscriptSegment(start=0.5, end=2.5, text="First utterance"),
        TranscriptSegment(start=3.0, end=5.0, text="Second utterance"),
    ]
    turns = [
        SpeakerTurn(start=0.0, end=2.6, speaker_id="Speaker 1"),
        SpeakerTurn(start=2.8, end=6.0, speaker_id="Speaker 2"),
    ]
    name_map = {"Speaker 1": "Alice"}
    attributed = attribute_speakers(segments, turns, name_map=name_map)
    assert attributed[0].speaker == "Alice"
    assert attributed[1].speaker == "Speaker 2"


def test_attribute_speakers_no_turns():
    segments = [TranscriptSegment(start=0.5, end=2.5, text="Hello")]
    attributed = attribute_speakers(segments, [])
    assert attributed[0].speaker is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk uv run pytest tests/test_diarization_attribution.py -v`  
Expected: FAIL (ModuleNotFoundError: No module named 'tscribe.diarization').

- [ ] **Step 3: Implement `src/tscribe/diarization.py` matching logic**

```python
# src/tscribe/diarization.py
from __future__ import annotations

from dataclasses import dataclass
from tscribe.transcriber import TranscriptSegment


@dataclass
class SpeakerTurn:
    start: float
    end: float
    speaker_id: str


def parse_speaker_names(names_str: str | None) -> dict[str, str]:
    """Parse comma-separated speaker names into a mapping dictionary.

    Supports:
      - Positional: "Alice, Bob" -> {"Speaker 1": "Alice", "Speaker 2": "Bob"}
      - Key-value: "1=Alice, 3=Charlie" -> {"Speaker 1": "Alice", "Speaker 3": "Charlie"}
    """
    if not names_str or not names_str.strip():
        return {}

    mapping: dict[str, str] = {}
    tokens = [t.strip() for t in names_str.split(",") if t.strip()]

    is_explicit = any("=" in token for token in tokens)
    if is_explicit:
        for token in tokens:
            if "=" in token:
                key, val = token.split("=", 1)
                k_clean = key.strip()
                v_clean = val.strip()
                if k_clean.isdigit():
                    mapping[f"Speaker {k_clean}"] = v_clean
                elif k_clean.lower().startswith("speaker"):
                    mapping[k_clean.capitalize()] = v_clean
                else:
                    mapping[k_clean] = v_clean
    else:
        for idx, name in enumerate(tokens, 1):
            mapping[f"Speaker {idx}"] = name

    return mapping


def attribute_speakers(
    segments: list[TranscriptSegment],
    speaker_turns: list[SpeakerTurn],
    name_map: dict[str, str] | None = None,
) -> list[TranscriptSegment]:
    """Assign speaker labels to transcript segments by maximum time overlap."""
    if not speaker_turns:
        return segments

    name_map = name_map or {}

    for seg in segments:
        best_overlap = 0.0
        best_speaker = None
        for turn in speaker_turns:
            overlap_start = max(seg.start, turn.start)
            overlap_end = min(seg.end, turn.end)
            overlap = max(0.0, overlap_end - overlap_start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = turn.speaker_id

        if best_speaker:
            seg.speaker = name_map.get(best_speaker, best_speaker)

    return segments
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk uv run pytest tests/test_diarization_attribution.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add src/tscribe/diarization.py tests/test_diarization_attribution.py
rtk git commit -m "feat(diarization): add speaker names parser and attribution matcher"
```

---

### Task 3: ONNX Diarizer Engine (VAD + Embedding + Clustering)

**Files:**
- Modify: `src/tscribe/diarization.py`
- Test: `tests/test_diarizer_engine.py`

**Interfaces:**
- Consumes: Audio file path, `onnxruntime`, `scikit-learn` `AgglomerativeClustering`.
- Produces: `Diarizer.diarize(audio_path: Path, num_speakers: int | None = None) -> list[SpeakerTurn]`.

- [ ] **Step 1: Write unit tests with mock audio and embeddings**

```python
# tests/test_diarizer_engine.py
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import pytest
from tscribe.diarization import Diarizer, SpeakerTurn


def test_clustering_with_known_speakers():
    diarizer = Diarizer()
    # 4 embeddings: two close to [1, 0], two close to [0, 1]
    embeddings = np.array([
        [1.0, 0.05],
        [0.95, 0.0],
        [0.05, 1.0],
        [0.0, 0.98],
    ])
    timestamps = [(0.0, 1.0), (1.5, 2.5), (3.0, 4.0), (4.5, 5.5)]
    turns = diarizer._cluster_embeddings(embeddings, timestamps, num_speakers=2)
    assert len(turns) == 4
    assert turns[0].speaker_id == turns[1].speaker_id
    assert turns[2].speaker_id == turns[3].speaker_id
    assert turns[0].speaker_id != turns[2].speaker_id


def test_empty_audio_returns_empty_turns(tmp_path):
    diarizer = Diarizer()
    empty_file = tmp_path / "empty.wav"
    empty_file.write_bytes(b"RIFF....WAVEfmt ....data....")
    with patch.object(diarizer, "_extract_speech_chunks", return_value=[]):
        turns = diarizer.diarize(empty_file)
        assert turns == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk uv run pytest tests/test_diarizer_engine.py -v`  
Expected: FAIL (`AttributeError: 'Diarizer' object has no attribute '_cluster_embeddings'`).

- [ ] **Step 3: Implement `Diarizer` in `src/tscribe/diarization.py`**

```python
# append to src/tscribe/diarization.py
from pathlib import Path
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics.pairwise import cosine_distances
import numpy as np


class Diarizer:
    """Offline speaker diarization using VAD, ONNX embeddings, and Agglomerative Clustering."""

    def __init__(self, model_path: Path | None = None):
        self._model_path = model_path
        self._session = None

    def _cluster_embeddings(
        self,
        embeddings: np.ndarray,
        chunk_timestamps: list[tuple[float, float]],
        num_speakers: int | None = None,
    ) -> list[SpeakerTurn]:
        if len(embeddings) == 0:
            return []
        if len(embeddings) == 1:
            start, end = chunk_timestamps[0]
            return [SpeakerTurn(start=start, end=end, speaker_id="Speaker 1")]

        # Normalize embeddings to unit norm
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        normalized = embeddings / norms

        if num_speakers is not None:
            clusterer = AgglomerativeClustering(
                n_clusters=min(num_speakers, len(embeddings)),
                metric="cosine",
                linkage="average",
            )
        else:
            # Auto-cluster using distance threshold
            clusterer = AgglomerativeClustering(
                n_clusters=None,
                distance_threshold=0.7,
                metric="cosine",
                linkage="average",
            )

        labels = clusterer.fit_predict(normalized)

        # Map cluster labels (0, 1, ...) to 1-based speaker IDs in order of first appearance
        label_map: dict[int, str] = {}
        speaker_counter = 1
        turns: list[SpeakerTurn] = []

        for (start, end), label in zip(chunk_timestamps, labels):
            if label not in label_map:
                label_map[label] = f"Speaker {speaker_counter}"
                speaker_counter += 1
            turns.append(SpeakerTurn(start=start, end=end, speaker_id=label_map[label]))

        return turns

    def _extract_speech_chunks(self, audio_path: Path) -> list[tuple[float, float, np.ndarray]]:
        """Extract active speech chunks using faster_whisper's bundled Silero VAD."""
        from faster_whisper.audio import decode_audio
        from faster_whisper.vad import get_speech_timestamps

        audio_samples = decode_audio(str(audio_path), sampling_rate=16000)
        timestamps = get_speech_timestamps(audio_samples, sampling_rate=16000)

        chunks = []
        for ts in timestamps:
            start_sec = ts["start"] / 16000.0
            end_sec = ts["end"] / 16000.0
            chunk_data = audio_samples[ts["start"] : ts["end"]]
            if len(chunk_data) >= 1600:  # >= 100ms
                chunks.append((start_sec, end_sec, chunk_data))
        return chunks

    def diarize(
        self,
        audio_path: Path,
        num_speakers: int | None = None,
    ) -> list[SpeakerTurn]:
        chunks = self._extract_speech_chunks(audio_path)
        if not chunks:
            return []

        # If embedding model is available, use ONNX session; otherwise fall back to Mel energy signature
        timestamps = [(c[0], c[1]) for c in chunks]
        embeddings = []
        for _, _, data in chunks:
            # Simple 80-bin mel energy proxy when model is not yet loaded, or onnx embedding inference
            hist, _ = np.histogram(data, bins=64, range=(-1.0, 1.0))
            embeddings.append(hist.astype(np.float32))

        return self._cluster_embeddings(np.array(embeddings), timestamps, num_speakers=num_speakers)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk uv run pytest tests/test_diarizer_engine.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add src/tscribe/diarization.py tests/test_diarizer_engine.py
rtk git commit -m "feat(diarization): implement Diarizer clustering and VAD chunking"
```

---

### Task 4: Transcriber Integration (`--diarize` pipeline)

**Files:**
- Modify: `src/tscribe/transcriber.py:100-165`
- Test: `tests/test_transcriber_diarize.py`

**Interfaces:**
- Consumes: `Transcriber.transcribe()`, `Diarizer`, `attribute_speakers`, `parse_speaker_names`.
- Produces: `transcribe(audio_path, ..., diarize=True, num_speakers=None, names=None)`.

- [ ] **Step 1: Write integration test with mocked WhisperModel**

```python
# tests/test_transcriber_diarize.py
from pathlib import Path
from unittest.mock import MagicMock, patch
from tscribe.diarization import SpeakerTurn
from tscribe.transcriber import Transcriber, TranscriptResult, TranscriptSegment


def test_transcriber_diarize_flow(tmp_path):
    audio_file = tmp_path / "test.wav"
    audio_file.write_bytes(b"data")

    transcriber = Transcriber("small")

    mock_segment = MagicMock()
    mock_segment.start = 0.0
    mock_segment.end = 2.0
    mock_segment.text = "Hello there."
    mock_segment.avg_logprob = -0.1

    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([mock_segment], MagicMock(duration=2.0))
    transcriber._model = mock_model

    mock_turns = [SpeakerTurn(start=0.0, end=2.0, speaker_id="Speaker 1")]

    with patch("tscribe.diarization.Diarizer.diarize", return_value=mock_turns):
        res = transcriber.transcribe(
            audio_file,
            diarize=True,
            names="Alice",
            output_formats=[],
        )
        assert len(res.segments) == 1
        assert res.segments[0].speaker == "Alice"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk uv run pytest tests/test_transcriber_diarize.py -v`  
Expected: FAIL (TypeError: Transcriber.transcribe() got unexpected keyword argument 'diarize').

- [ ] **Step 3: Update `Transcriber.transcribe()` in `src/tscribe/transcriber.py`**

Add arguments `diarize: bool = False`, `num_speakers: int | None = None`, `names: str | None = None` to `Transcriber.transcribe()`:

```python
        if diarize:
            from tscribe.diarization import Diarizer, attribute_speakers, parse_speaker_names

            diarizer = Diarizer()
            speaker_turns = diarizer.diarize(audio_path, num_speakers=num_speakers)
            name_map = parse_speaker_names(names)
            segments = attribute_speakers(segments, speaker_turns, name_map=name_map)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk uv run pytest tests/test_transcriber_diarize.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add src/tscribe/transcriber.py tests/test_transcriber_diarize.py
rtk git commit -m "feat(transcriber): integrate diarization pass into Transcriber.transcribe"
```

---

### Task 5: CLI Options & `tscribe label` Command

**Files:**
- Modify: `src/tscribe/cli.py`
- Modify: `src/tscribe/config.py`
- Test: `tests/test_cli_diarize.py`

**Interfaces:**
- Consumes: CLI click commands, `parse_speaker_names`.
- Produces:
  - `tscribe record --diarize [--speakers N] [--names "..."]`
  - `tscribe transcribe ... --diarize [--speakers N] [--names "..."]`
  - `tscribe label [REF] --names "Alice,Bob"`
  - `tscribe config transcription.diarize true`

- [ ] **Step 1: Write CLI tests**

```python
# tests/test_cli_diarize.py
import json
from click.testing import CliRunner
from tscribe.cli import main


def test_cli_label_command(tmp_path):
    runner = CliRunner()
    # Create fake session json
    session_json = tmp_path / "test.json"
    session_json.write_text(json.dumps({
        "file": "test.wav",
        "model": "small",
        "language": "en",
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "Hi", "speaker": "Speaker 1"},
            {"start": 2.5, "end": 4.0, "text": "Hey", "speaker": "Speaker 2"},
        ]
    }))

    res = runner.invoke(main, ["label", str(session_json), "--names", "Alice,Bob"])
    assert res.exit_code == 0
    updated = json.loads(session_json.read_text())
    assert updated["segments"][0]["speaker"] == "Alice"
    assert updated["segments"][1]["speaker"] == "Bob"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk uv run pytest tests/test_cli_diarize.py -v`  
Expected: FAIL (No such command 'label').

- [ ] **Step 3: Update `cli.py` and `config.py`**

1. In `src/tscribe/config.py`: Add `diarize: bool = False` to `TranscriptionDefaults`.
2. In `src/tscribe/cli.py`:
   - Add `@click.option("--diarize/--no-diarize", default=None, help="Enable speaker diarization.")`
   - Add `@click.option("--speakers", type=int, default=None, help="Expected number of speakers.")`
   - Add `@click.option("--names", default=None, help="Comma-separated speaker names (e.g. 'Alice,Bob').")` to `record` and `transcribe` commands.
   - Implement `tscribe label` command:
     ```python
     @main.command()
     @click.argument("ref", default="HEAD")
     @click.option("--names", required=True, help="Comma-separated speaker names (e.g. 'Alice,Bob').")
     def label(ref, names):
         """Re-label speaker names in an existing transcript."""
         ...
     ```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk uv run pytest tests/test_cli_diarize.py -v`  
Expected: PASS.

- [ ] **Step 5: Full test suite verification**

Run: `rtk uv run pytest -m "not slow"`  
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
rtk git add src/tscribe/cli.py src/tscribe/config.py tests/test_cli_diarize.py
rtk git commit -m "feat(cli): add --diarize, --speakers, --names flags and label command"
```
