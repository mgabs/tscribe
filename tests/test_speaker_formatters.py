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
