"""Exercise native-recorder error paths without opening an audio device."""

import sys
import wave
from unittest.mock import MagicMock

import pytest

from tscribe.recorder.base import RecordingConfig
from tscribe.recorder.sounddevice_recorder import SounddeviceRecorder


def fake_sounddevice(monkeypatch):
    module = MagicMock()
    module.PortAudioError = RuntimeError
    module.default.device = (5, 6)
    module.query_devices.return_value = {'default_samplerate': 48000}
    monkeypatch.setitem(sys.modules, 'sounddevice', module)
    return module


def test_device_zero_is_preserved(tmp_path, monkeypatch):
    sd = fake_sounddevice(monkeypatch)
    recorder = SounddeviceRecorder()
    recorder.start(tmp_path / 'audio.wav', RecordingConfig(device=0))
    sd.query_devices.assert_called_once_with(0, kind='input')
    assert recorder.stop().device_name == '0'


def test_failed_stream_start_finalizes_wav(tmp_path, monkeypatch):
    sd = fake_sounddevice(monkeypatch)
    sd.InputStream.return_value.start.side_effect = RuntimeError('Microphone denied')
    recorder = SounddeviceRecorder()
    path = tmp_path / 'audio.wav'
    with pytest.raises(RuntimeError, match='Microphone denied'):
        recorder.start(path, RecordingConfig())
    sd.InputStream.return_value.close.assert_called_once()
    assert recorder.is_recording() is False
    with wave.open(str(path)) as wav:
        assert wav.getnframes() == 0
    assert recorder._wav_file is None


def test_configured_sample_rate_is_used_when_supported(tmp_path, monkeypatch):
    sd = fake_sounddevice(monkeypatch)
    recorder = SounddeviceRecorder()
    recorder.start(tmp_path / 'audio.wav', RecordingConfig(sample_rate=22050))
    assert sd.InputStream.call_args.kwargs['samplerate'] == 22050
    assert recorder.stop().sample_rate == 22050


def test_unsupported_rate_falls_back_to_native_rate(tmp_path, monkeypatch):
    sd = fake_sounddevice(monkeypatch)
    sd.check_input_settings.side_effect = RuntimeError('Unsupported sample rate')
    recorder = SounddeviceRecorder()
    recorder.start(tmp_path / 'audio.wav', RecordingConfig(sample_rate=16000))
    assert sd.InputStream.call_args.kwargs['samplerate'] == 48000
    assert recorder.stop().sample_rate == 48000
