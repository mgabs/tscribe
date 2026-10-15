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
