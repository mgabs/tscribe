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


def test_parse_speaker_names_explicit_edge_cases():
    # Whitespace stripping, "speaker 2", and malformed entries
    names = " 1 = Alice , speaker 2 = Bob , invalid_token, =no_key, no_val= "
    assert parse_speaker_names(names) == {
        "Speaker 1": "Alice",
        "Speaker 2": "Bob",
    }


def test_attribute_speakers_largest_overlap():
    # Segment spans 1.0 to 4.0 (duration 3.0s)
    # Turn 1 overlaps from 1.0 to 2.0 (1.0s overlap)
    # Turn 2 overlaps from 2.0 to 4.0 (2.0s overlap) -> largest
    segments = [TranscriptSegment(start=1.0, end=4.0, text="Interrupted talk")]
    turns = [
        SpeakerTurn(start=0.0, end=2.0, speaker_id="Speaker 1"),
        SpeakerTurn(start=2.0, end=5.0, speaker_id="Speaker 2"),
    ]
    attributed = attribute_speakers(segments, turns)
    assert attributed[0].speaker == "Speaker 2"


def test_attribute_speakers_no_overlap():
    segments = [TranscriptSegment(start=10.0, end=12.0, text="Late utterance")]
    turns = [SpeakerTurn(start=0.0, end=2.0, speaker_id="Speaker 1")]
    attributed = attribute_speakers(segments, turns)
    assert attributed[0].speaker is None

