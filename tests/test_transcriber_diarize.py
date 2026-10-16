from unittest.mock import MagicMock, patch
from tscribe.diarization import SpeakerTurn
from tscribe.transcriber import Transcriber


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

    with patch("tscribe.diarization.Diarizer.diarize", return_value=mock_turns) as mock_diarize:
        res = transcriber.transcribe(
            audio_file,
            diarize=True,
            num_speakers=2,
            names="Alice",
            output_formats=[],
        )
        assert len(res.segments) == 1
        assert res.segments[0].speaker == "Alice"
        mock_diarize.assert_called_once_with(audio_file, num_speakers=2)


def test_transcriber_diarize_false_by_default(tmp_path):
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

    with patch("tscribe.diarization.Diarizer.diarize") as mock_diarize:
        res = transcriber.transcribe(audio_file, output_formats=[])
        assert len(res.segments) == 1
        assert res.segments[0].speaker is None
        mock_diarize.assert_not_called()


def test_transcriber_splits_speaker_handover_and_exports_it(tmp_path):
    import json
    from types import SimpleNamespace

    audio_file = tmp_path / 'meeting.wav'
    transcriber = Transcriber('small')
    transcriber._model = MagicMock()
    segment = SimpleNamespace(
        start=0, end=3, text=' First. Second. Third.', avg_logprob=-0.1,
        words=[SimpleNamespace(start=i, end=i+1, word=text) for i, text in enumerate(
            [' First.', ' Second.', ' Third.'],
        )],
    )
    transcriber._model.transcribe.return_value = ([segment], SimpleNamespace(duration=3, language='en'))
    turns = [SpeakerTurn(i, i+1, f'Speaker {i+1}') for i in range(3)]
    with patch('tscribe.diarization.Diarizer.diarize', return_value=turns):
        result = transcriber.transcribe(audio_file, diarize=True, num_speakers=3)
    transcriber._model.transcribe.assert_called_once_with(str(audio_file), language=None, word_timestamps=True)
    assert [part.speaker for part in result.segments] == ['Speaker 1', 'Speaker 2', 'Speaker 3']
    assert '[Speaker 2]:\nSecond.' in audio_file.with_suffix('.txt').read_text()
    assert len(json.loads(audio_file.with_suffix('.json').read_text())['segments']) == 3
