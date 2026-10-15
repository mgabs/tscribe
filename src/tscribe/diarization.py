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
