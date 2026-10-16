"""Tests for the transcriber module."""

import json
from unittest.mock import MagicMock, patch

import pytest

from tscribe.transcriber import (
    TranscriptResult,
    TranscriptSegment,
    Transcriber,
    _format_srt_time,
    _format_vtt_time,
)


class TestFormatTimestamps:
    def test_srt_format(self):
        assert _format_srt_time(83.456) == "00:01:23,456"

    def test_vtt_format(self):
        assert _format_vtt_time(83.456) == "00:01:23.456"

    def test_zero(self):
        assert _format_srt_time(0.0) == "00:00:00,000"
        assert _format_vtt_time(0.0) == "00:00:00.000"


class TestTranscriptResult:
    @pytest.fixture
    def result(self):
        return TranscriptResult(
            file="test.wav",
            model="base",
            language="en",
            segments=[
                TranscriptSegment(start=0.0, end=2.5, text=" Hello world. "),
                TranscriptSegment(start=2.5, end=5.0, text=" This is a test. "),
            ],
        )

    def test_to_txt(self, result):
        txt = result.to_txt()
        assert "Hello world." in txt
        assert "This is a test." in txt
        # Should be stripped
        assert txt == "Hello world.\nThis is a test."

    def test_to_json(self, result):
        data = result.to_json()
        assert data["file"] == "test.wav"
        assert data["model"] == "base"
        assert len(data["segments"]) == 2
        assert data["segments"][0]["text"] == "Hello world."
        assert data["segments"][0]["start"] == 0.0

    def test_to_srt(self, result):
        srt = result.to_srt()
        assert "1\n00:00:00,000 --> 00:00:02,500\nHello world." in srt
        assert "2\n00:00:02,500 --> 00:00:05,000\nThis is a test." in srt

    def test_to_vtt(self, result):
        vtt = result.to_vtt()
        assert vtt.startswith("WEBVTT")
        assert "00:00:00.000 --> 00:00:02.500" in vtt


class TestTranscriberInit:
    def test_default_cpu(self):
        t = Transcriber(model_name="base")
        assert t._model_name == "base"
        assert t._device == "cpu"
        assert t._compute_type == "int8"

    def test_gpu_defaults_to_float16(self):
        t = Transcriber(model_name="base", device="cuda")
        assert t._compute_type == "float16"

    def test_custom_compute_type(self):
        t = Transcriber(model_name="small", compute_type="float32")
        assert t._compute_type == "float32"


def _mock_whisper_model():
    """Create a mock WhisperModel with a transcribe method."""
    mock_seg = MagicMock()
    mock_seg.start = 0.0
    mock_seg.end = 2.5
    mock_seg.text = " Hello world."
    mock_seg.avg_logprob = -0.1

    mock_info = MagicMock()
    mock_info.language = "en"
    mock_info.duration = 10.0

    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([mock_seg], mock_info)
    return mock_model


class TestTranscriberTranscribe:
    def test_transcribe_success(self, tmp_path):
        mock_model = _mock_whisper_model()

        t = Transcriber(model_name="base")
        t._model = mock_model  # inject mock directly

        audio_path = tmp_path / "audio.wav"
        audio_path.write_bytes(b"fake wav")

        result = t.transcribe(audio_path, output_formats=["txt"])

        assert len(result.segments) == 1
        assert result.segments[0].text == " Hello world."
        assert result.model == "base"
        assert result.language == "en"
        assert (tmp_path / "audio.txt").exists()
        mock_model.transcribe.assert_called_once()

    def test_transcribe_with_language(self, tmp_path):
        mock_model = _mock_whisper_model()

        t = Transcriber(model_name="base")
        t._model = mock_model

        audio_path = tmp_path / "audio.wav"
        audio_path.write_bytes(b"fake wav")

        t.transcribe(audio_path, language="en")
        mock_model.transcribe.assert_called_once_with(str(audio_path), language="en")

    def test_transcribe_auto_language(self, tmp_path):
        mock_model = _mock_whisper_model()

        t = Transcriber(model_name="base")
        t._model = mock_model

        audio_path = tmp_path / "audio.wav"
        audio_path.write_bytes(b"fake wav")

        t.transcribe(audio_path, language="auto")
        mock_model.transcribe.assert_called_once_with(str(audio_path), language=None)

    def test_lazy_model_loading(self):
        with patch("faster_whisper.WhisperModel") as mock_cls:
            mock_cls.return_value = _mock_whisper_model()
            t = Transcriber(model_name="tiny")
            assert t._model is None
            model = t._get_model()
            assert model is not None
            mock_cls.assert_called_once_with("tiny", device="cpu", compute_type="int8")


class TestTranscriberWriteOutputs:
    def test_write_txt_and_json(self, tmp_path):
        t = Transcriber(model_name="base")
        result = TranscriptResult(
            file="test.wav",
            model="base",
            language="en",
            segments=[TranscriptSegment(start=0.0, end=2.0, text="Hello")],
        )
        base = tmp_path / "test"
        t._write_outputs(result, base, ["txt", "json"])

        assert (tmp_path / "test.txt").exists()
        assert (tmp_path / "test.json").exists()

        txt = (tmp_path / "test.txt").read_text()
        assert "Hello" in txt

        data = json.loads((tmp_path / "test.json").read_text())
        assert data["segments"][0]["text"] == "Hello"

    def test_write_srt_and_vtt(self, tmp_path):
        t = Transcriber(model_name="base")
        result = TranscriptResult(
            file="test.wav",
            model="base",
            language="en",
            segments=[TranscriptSegment(start=0.0, end=2.0, text="Hello")],
        )
        base = tmp_path / "test"
        t._write_outputs(result, base, ["srt", "vtt"])

        assert (tmp_path / "test.srt").exists()
        assert (tmp_path / "test.vtt").exists()


class TestProgressCallback:
    def test_callback_invoked(self, tmp_path):
        mock_model = _mock_whisper_model()
        t = Transcriber(model_name="base")
        t._model = mock_model

        audio_path = tmp_path / "audio.wav"
        audio_path.write_bytes(b"fake wav")

        calls = []
        t.transcribe(audio_path, output_formats=["txt"], progress_callback=lambda c, d: calls.append((c, d)))

        assert len(calls) == 2
        assert calls[0] == (2.5, 10.0)
        assert calls[1] == (10.0, 10.0)  # final 100% call

    def test_no_callback(self, tmp_path):
        """transcribe works fine without a callback."""
        mock_model = _mock_whisper_model()
        t = Transcriber(model_name="base")
        t._model = mock_model

        audio_path = tmp_path / "audio.wav"
        audio_path.write_bytes(b"fake wav")

        result = t.transcribe(audio_path, output_formats=["txt"])
        assert len(result.segments) == 1


@pytest.mark.parametrize(('seconds', 'expected'), [
    (59.9996, '00:01:00.000'),
    (3599.9996, '01:00:00.000'),
    (60, '00:01:00.000'),
])
def test_subtitle_timestamps_carry_rounded_milliseconds(seconds, expected):
    assert _format_vtt_time(seconds) == expected
    assert _format_srt_time(seconds) == expected.replace('.', ',')


def test_transcribe_custom_output_preserves_dotted_names(tmp_path):
    audio = tmp_path / 'meeting.v2.wav'
    audio.write_bytes(b'fake')
    transcriber = Transcriber()
    transcriber._model = _mock_whisper_model()
    output = tmp_path / 'exports' / 'notes.v2'
    transcriber.transcribe(audio, output_formats=['txt', 'json'], output_base=output)
    assert (tmp_path / 'exports' / 'notes.v2.txt').exists()
    assert (tmp_path / 'exports' / 'notes.v2.json').exists()
    assert not audio.with_suffix('.txt').exists()


def test_default_output_preserves_dotted_names(tmp_path):
    audio = tmp_path / 'meeting.v2.wav'
    audio.write_bytes(b'fake')
    transcriber = Transcriber()
    transcriber._model = _mock_whisper_model()
    transcriber.transcribe(audio, output_formats=['txt'])
    assert (tmp_path / 'meeting.v2.txt').exists()
    assert not (tmp_path / 'meeting.txt').exists()


@pytest.mark.parametrize(('compute_type', 'expected'), [(None, 'int8'), ('float32', 'float32')])
def test_unavailable_cuda_falls_back_to_cpu(compute_type, expected, caplog):
    def supported(device):
        if device == 'cuda':
            raise RuntimeError('This CTranslate2 package was not compiled with CUDA support')
        return {'int8', 'float32'}

    with patch('ctranslate2.get_supported_compute_types', side_effect=supported), patch('faster_whisper.WhisperModel') as model:
        transcriber = Transcriber(model_name='tiny', device='cuda', compute_type=compute_type)
        assert transcriber._get_model() is transcriber._get_model()
        model.assert_called_once_with('tiny', device='cpu', compute_type=expected)
    assert 'using CPU transcription instead' in caplog.text


def test_available_cuda_keeps_gpu_acceleration():
    with patch('ctranslate2.get_supported_compute_types', return_value={'float16', 'float32'}) as supported, patch('faster_whisper.WhisperModel') as model:
        Transcriber(model_name='tiny', device='cuda')._get_model()
        supported.assert_called_once_with('cuda')
        model.assert_called_once_with('tiny', device='cuda', compute_type='float16')


def test_cpu_transcription_does_not_probe_cuda():
    with patch('ctranslate2.get_supported_compute_types') as supported, patch('faster_whisper.WhisperModel'):
        Transcriber()._get_model()
        supported.assert_not_called()


def test_model_loading_errors_are_not_hidden_by_cpu_fallback():
    with patch('ctranslate2.get_supported_compute_types', return_value={'float16'}), patch('faster_whisper.WhisperModel', side_effect=RuntimeError('Model download failed')):
        with pytest.raises(RuntimeError, match='Model download failed'):
            Transcriber(device='cuda')._get_model()
