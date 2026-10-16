"""Native echo DSP checks: convergence, double talk, bypass, and safe fallback."""
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from tscribe.echo import EchoCanceller, EchoUnavailable
from tscribe.live import mix_recording, read_window

def wav(path, samples):
    import wave
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(np.asarray(samples, dtype='<i2').tobytes())


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def native_library(tmp_path_factory):
    if os.name != 'posix' or not shutil.which('cc'):
        pytest.skip('Native echo DSP needs a Unix C compiler')
    extension = 'dylib' if sys.platform == 'darwin' else 'so'
    library = tmp_path_factory.mktemp('echo-dsp') / f'libtscribe_echo.{extension}'
    subprocess.run([sys.executable, str(ROOT / 'packaging/macos/build_audio_dsp.py'), '--output', str(library)], check=True)
    return library


@pytest.fixture
def echo_library(native_library, monkeypatch):
    monkeypatch.setenv('TSCRIBE_ECHO_LIBRARY', str(native_library))


def echo_fixture(seconds=8, delay_ms=50):
    rate = 16000
    remote = np.random.default_rng(42).normal(0, .1, rate * seconds).astype(np.float32)
    echo = np.zeros_like(remote)
    for delay, gain in [(rate * delay_ms // 1000, .5), (rate * (delay_ms + 50) // 1000, .15)]:
        echo[delay:] += remote[:-delay] * gain
    return remote, echo


@pytest.mark.parametrize('delay_ms', [20, 50, 150])
def test_adaptive_filter_reduces_delayed_multipath_echo(echo_library, delay_ms):
    remote, echo = echo_fixture(delay_ms=delay_ms)
    with EchoCanceller() as canceller:
        cleaned = canceller.process(echo, remote)
    late = slice(16000 * 3, None)
    reduction = 10 * np.log10(np.mean(echo[late] ** 2) / max(np.mean(cleaned[late] ** 2), 1e-12))
    assert reduction > 12, f'Expected >12 dB echo reduction, got {reduction:.1f}'
    assert np.isfinite(cleaned).all()


def test_simultaneous_local_speech_is_not_muted(echo_library):
    remote, echo = echo_fixture(seconds=9)
    time = np.arange(len(remote)) / 16000
    near = (.09 * np.sin(2 * np.pi * 213 * time) + .045 * np.sin(2 * np.pi * 426 * time)).astype(np.float32)
    near[:16000 * 3] = 0  # Establish the acoustic path before double talk.
    with EchoCanceller() as canceller:
        cleaned = canceller.process(echo + near, remote)
    late = slice(16000 * 5, None)
    gain = np.dot(cleaned[late], near[late]) / np.dot(near[late], near[late])
    assert .7 < gain < 1.3
    assert np.mean((cleaned[late] - near[late]) ** 2) < np.mean(near[late] ** 2) * .5


def test_silent_reference_preserves_microphone_exactly_and_final_partial_frame(echo_library):
    mic = np.random.default_rng(7).normal(0, .1, 16317).astype(np.float32)
    with EchoCanceller() as canceller:
        result = canceller.process(mic, np.zeros_like(mic))
    np.testing.assert_array_equal(result, mic)
    assert len(result) == len(mic)
    with pytest.raises(RuntimeError, match='closed'):
        canceller.process(mic, mic)
    canceller.close()  # Safe to close twice.


def test_rejects_invalid_arrays_before_native_processing(echo_library):
    with EchoCanceller() as canceller:
        for mic, reference in [(np.zeros(5), np.zeros(6)), (np.zeros((2, 3)), np.zeros((2, 3))), (np.array([np.nan]), np.zeros(1))]:
            with pytest.raises(ValueError):
                canceller.process(mic, reference)
    with pytest.raises(EchoUnavailable, match='Hz'):
        EchoCanceller(44100)


def test_missing_library_reports_actionable_error(tmp_path, monkeypatch):
    monkeypatch.setenv('TSCRIBE_ECHO_LIBRARY', str(tmp_path / 'missing.dylib'))
    with pytest.raises(EchoUnavailable, match='make audio-dsp'):
        EchoCanceller()


def test_live_window_cleans_mic_and_preserves_remote_reference(echo_library, tmp_path):
    remote, echo = echo_fixture()
    mic_path, system_path = tmp_path / 'microphone.wav', tmp_path / 'system.wav'
    wav(mic_path, echo * 32768)
    wav(system_path, remote * 32768)
    cleaned, start, end = read_window([(mic_path, 0), (system_path, 0)], echo_cancellation=True)
    assert (start, end) == (0, 8)
    late = slice(16000 * 3, None)
    # The remote speaker remains in the mix; only its copy in the mic is removed.
    error = cleaned[late] - remote[late] / 2
    assert np.mean(error ** 2) < np.mean((echo[late] / 2) ** 2) / 10


def test_final_mix_applies_echo_reduction_and_preserves_both_originals(echo_library, tmp_path):
    remote, echo = echo_fixture()
    path = tmp_path / 'meeting.wav'
    system = tmp_path / '.tracks/meeting/system.wav'
    wav(path, echo * 32768)
    wav(system, remote * 32768)
    original_mic, original_system = path.read_bytes(), system.read_bytes()
    assert mix_recording(path, {}, echo_cancellation=True) is None
    assert (tmp_path / '.tracks/meeting/microphone.wav').read_bytes() == original_mic
    assert system.read_bytes() == original_system
    import wave
    with wave.open(str(path)) as audio:
        result = np.frombuffer(audio.readframes(audio.getnframes()), dtype='<i2').astype(np.float32) / 32768
    late = slice(16000 * 3, None)
    assert np.mean((result[late] - remote[late] / 2) ** 2) < np.mean((echo[late] / 2) ** 2) / 10


def test_missing_dsp_still_saves_mix_and_returns_warning(tmp_path, monkeypatch):
    monkeypatch.setenv('TSCRIBE_ECHO_LIBRARY', str(tmp_path / 'missing.dylib'))
    path = tmp_path / 'meeting.wav'
    wav(path, [1000] * 16000)
    wav(tmp_path / '.tracks/meeting/system.wav', [2000] * 16000)
    warning = mix_recording(path, {}, echo_cancellation=True)
    assert 'unavailable' in warning
    assert path.exists()


def test_disabled_echo_never_loads_library(tmp_path):
    path = tmp_path / 'meeting.wav'
    wav(path, [1000] * 16000)
    wav(tmp_path / '.tracks/meeting/system.wav', [2000] * 16000)
    with patch('tscribe.echo._library', side_effect=AssertionError('Must bypass DSP')):
        assert mix_recording(path, {}, echo_cancellation=False) is None


@pytest.mark.skipif(os.name != 'posix', reason='Native DSP builds require Unix')
def test_build_failure_preserves_last_complete_library(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('audio_dsp_build', ROOT / 'packaging/macos/build_audio_dsp.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = tmp_path / 'echo.dylib'
    output.write_bytes(b'previous')
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **k: (_ for _ in ()).throw(subprocess.CalledProcessError(1, 'cc')))
    with pytest.raises(subprocess.CalledProcessError):
        module.build(output)
    assert output.read_bytes() == b'previous'


@pytest.mark.parametrize(('mode', 'enabled', 'active'), [('headphones', True, False), ('speakers', False, False), ('speakers', True, True)])
def test_worker_orders_reference_tracks_and_applies_mode(mode, enabled, active):
    from tscribe.worker import Worker
    worker = Worker(lambda _: None)
    worker.handle({'id': 'settings', 'command': 'save-config', 'changes': {'captions.output_mode': mode, 'captions.echo_cancellation': enabled}})
    with patch('tscribe.live.read_window', return_value=(np.zeros(160), 0, .01)) as read, patch('tscribe.transcriber.Transcriber') as transcriber:
        transcriber.return_value.transcribe_words.return_value = []
        result = worker.handle({'id': 'live', 'command': 'live-caption', 'stem': 'meeting', 'sequence': 0, 'tracks': {'system': 0, 'microphone': 0}})
    assert read.call_args.kwargs['echo_cancellation'] is active
    assert read.call_args.args[0][0][0].name.endswith('-microphone.wav')
    assert read.call_args.args[0][1][0].name.endswith('-system.wav')
    assert result['echo_active'] is active


def test_live_worker_missing_dsp_warns_and_still_transcribes():
    from tscribe.worker import Worker
    worker = Worker(lambda _: None)
    worker.handle({'id': 'settings', 'command': 'save-config', 'changes': {'captions.output_mode': 'speakers'}})
    with patch('tscribe.live.read_window', side_effect=[EchoUnavailable('missing echo library'), (np.zeros(160), 0, .01)]) as read, patch('tscribe.transcriber.Transcriber') as transcriber:
        transcriber.return_value.transcribe_words.return_value = []
        result = worker.handle({'id': 'live', 'command': 'live-caption', 'stem': 'meeting', 'sequence': 0, 'tracks': {'microphone': 0, 'system': 0}})
    assert read.call_count == 2
    assert result['echo_active'] is False
    assert result['warning'] == 'missing echo library'


def test_worker_finishes_recording_even_if_echo_library_is_missing(tmp_path, monkeypatch):
    from tscribe.worker import Worker
    monkeypatch.setenv('TSCRIBE_ECHO_LIBRARY', str(tmp_path / 'missing.dylib'))
    worker = Worker(lambda _: None)
    worker.handle({'id': 'settings', 'command': 'save-config', 'changes': {'captions.output_mode': 'speakers', 'recording.auto_transcribe': False}})
    prepared = worker.handle({'id': 'prepare', 'command': 'prepare-recording'})
    path = Path(prepared['wav_path'])
    wav(path, [1000] * 16000)
    wav(path.parent / '.tracks' / path.stem / 'system.wav', [2000] * 16000)
    result = worker.handle({'id': 'finish', 'command': 'finish-recording', 'stem': prepared['stem'], 'source': 'meeting'})
    assert result['message'] == 'Recording saved'
    assert result['sessions'][0]['duration'] == 1
    assert 'unavailable' in result['warning']
