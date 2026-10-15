from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import numpy as np
from sklearn.cluster import AgglomerativeClustering
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
                if not k_clean or not v_clean:
                    continue
                if k_clean.isdigit():
                    mapping[f"Speaker {k_clean}"] = v_clean
                elif k_clean.lower().startswith("speaker"):
                    rest = k_clean[7:].strip()
                    if rest.isdigit():
                        mapping[f"Speaker {rest}"] = v_clean
                    else:
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


class Diarizer:
    """Offline speaker diarization using VAD, amplitude histograms, and clustering."""

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

    def _extract_speech_chunks(self, audio_path: Path | str) -> list[tuple[float, float, np.ndarray]]:
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
        audio_path: Path | str,
        num_speakers: int | None = None,
    ) -> list[SpeakerTurn]:
        chunks = self._extract_speech_chunks(audio_path)
        if not chunks:
            return []

        # Represent each speech chunk by its amplitude distribution.
        timestamps = [(c[0], c[1]) for c in chunks]
        embeddings = []
        for _, _, data in chunks:
            hist, _ = np.histogram(data, bins=64, range=(-1.0, 1.0))
            embeddings.append(hist.astype(np.float32))

        return self._cluster_embeddings(np.array(embeddings), timestamps, num_speakers=num_speakers)
