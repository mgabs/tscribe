import pytest
from tscribe.transcriber import TranscriptResult, TranscriptSegment
from tscribe.diarization import remap_transcript_speakers, extract_speaker_samples


def test_segment_raw_speaker_preservation():
    seg = TranscriptSegment(
        start=0.0,
        end=2.0,
        text="Hello world",
        speaker="Alice",
        raw_speaker="Speaker 1",
    )
    d = seg.to_dict()
    assert d["speaker"] == "Alice"
    assert d["raw_speaker"] == "Speaker 1"


def test_segment_legacy_fallback():
    # If raw_speaker is None, from dict without raw_speaker it defaults to speaker
    seg = TranscriptSegment(
        start=0.0,
        end=2.0,
        text="Hello world",
        speaker="Speaker 1",
    )
    assert seg.raw_speaker == "Speaker 1"


def test_remap_transcript_speakers_idempotence():
    segments = [
        TranscriptSegment(0.0, 1.0, "Hello", speaker="Speaker 1", raw_speaker="Speaker 1"),
        TranscriptSegment(1.0, 2.0, "Hi", speaker="Speaker 2", raw_speaker="Speaker 2"),
        TranscriptSegment(2.0, 3.0, "How are you", speaker="Speaker 1", raw_speaker="Speaker 1"),
    ]
    result = TranscriptResult("test.wav", "model", "en", segments)

    # First remap
    mapped1 = remap_transcript_speakers(result, {"Speaker 1": "Alice"})
    assert mapped1.segments[0].speaker == "Alice"
    assert mapped1.segments[0].raw_speaker == "Speaker 1"
    assert mapped1.segments[1].speaker == "Speaker 2"
    assert mapped1.segments[2].speaker == "Alice"

    # Second remap from same or new map - should not lose Speaker 1 linkage
    mapped2 = remap_transcript_speakers(mapped1, {"Speaker 1": "Alicia", "Speaker 2": "Bob"})
    assert mapped2.segments[0].speaker == "Alicia"
    assert mapped2.segments[0].raw_speaker == "Speaker 1"
    assert mapped2.segments[1].speaker == "Bob"
    assert mapped2.segments[2].speaker == "Alicia"


def test_remap_transcript_speakers_reset():
    segments = [
        TranscriptSegment(0.0, 1.0, "Hello", speaker="Alice", raw_speaker="Speaker 1"),
    ]
    result = TranscriptResult("test.wav", "model", "en", segments)
    # Empty mapping resets back to raw_speaker
    mapped = remap_transcript_speakers(result, {})
    assert mapped.segments[0].speaker == "Speaker 1"


def test_extract_speaker_samples():
    segments = [
        TranscriptSegment(1.5, 3.0, "First quote", speaker="Alice", raw_speaker="Speaker 1"),
        TranscriptSegment(3.5, 5.0, "Second quote", speaker="Bob", raw_speaker="Speaker 2"),
        TranscriptSegment(5.5, 7.0, "Third quote", speaker="Alice", raw_speaker="Speaker 1"),
    ]
    result = TranscriptResult("test.wav", "model", "en", segments)
    samples = extract_speaker_samples(result)
    assert len(samples) == 2
    assert samples[0]["raw_speaker"] == "Speaker 1"
    assert samples[0]["speaker"] == "Alice"
    assert samples[0]["start"] == 1.5
    assert samples[0]["sample_text"] == "First quote"
    assert samples[1]["raw_speaker"] == "Speaker 2"
    assert samples[1]["speaker"] == "Bob"
    assert samples[1]["start"] == 3.5
    assert samples[1]["sample_text"] == "Second quote"
