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



def test_word_timings_preserve_three_speakers_inside_one_segment():
    segment = TranscriptSegment(0, 6, ' Yes. My explanation. I have a question.', confidence=-0.2)
    words = [[
        TranscriptSegment(0, 1, ' Yes.'),
        TranscriptSegment(1, 2, ' My'),
        TranscriptSegment(2, 3, ' explanation.'),
        TranscriptSegment(3, 4, ' I'),
        TranscriptSegment(4, 5, ' have a'),
        TranscriptSegment(5, 6, ' question.'),
    ]]
    turns = [SpeakerTurn(0, 1, 'Speaker 1'), SpeakerTurn(1, 3, 'Speaker 2'), SpeakerTurn(3, 6, 'Speaker 3')]
    result = attribute_speakers([segment], turns, {'Speaker 2': 'Mohammed'}, word_segments=words)
    assert [part.speaker for part in result] == ['Speaker 1', 'Mohammed', 'Speaker 3']
    assert ''.join(part.text for part in result) == segment.text
    assert [(part.start, part.end) for part in result] == [(0, 1), (1, 3), (3, 6)]
    assert all(part.confidence == -0.2 for part in result)


def test_missing_word_timings_keep_original_text():
    segment = TranscriptSegment(0, 2, 'Complete text')
    turns = [SpeakerTurn(0, 2, 'Speaker 1')]
    assert attribute_speakers([segment], turns, word_segments=[[]]) == [segment]
    assert segment.speaker == 'Speaker 1'


def test_zero_duration_word_keeps_its_speaker():
    word = TranscriptSegment(1, 1, ' the')
    turns = [SpeakerTurn(0, 1, 'Speaker 1'), SpeakerTurn(1, 2, 'Speaker 2')]
    assert attribute_speakers([word], turns)[0].speaker == 'Speaker 2'
