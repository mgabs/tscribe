"""Caption stability, bounded audio, retained tracks, and worker integration."""
import json
import wave
from unittest.mock import patch

import numpy as np
import pytest

from tscribe.live import CaptionDraft, mix_recording, read_window
from tscribe.worker import Worker


def wav(path, samples, rate=16000, channels=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(np.array(samples, dtype='<i2').tobytes())


def word(text, start, end):
    return {'text': text, 'start': start, 'end': end}


def test_confirms_shared_prefix_and_revises_only_provisional_tail(tmp_path):
    draft = CaptionDraft()
    first = [word(' Welcome', 0, 1), word(' everyone', 1, 2), word(' today', 3, 4)]
    result = draft.update(first, 0, 4, 0)
    assert result['text'] == ''
    assert result['provisional_text'] == 'Welcome everyone today'
    corrected = first[:2] + [word(' tomorrow', 3, 4)]
    result = draft.update(corrected, 0, 7, 1)
    assert result['text'] == 'Welcome everyone'
    assert result['provisional_text'] == 'tomorrow'
    result = draft.update(corrected, 0, 10, 2)
    assert result['text'] == 'Welcome everyone tomorrow'
    assert result['provisional_text'] == ''
    draft.save(tmp_path / 'meeting.wav')
    assert json.loads((tmp_path / 'meeting.captions.json').read_text())['text'] == result['text']
    assert (tmp_path / 'meeting.captions.txt').read_text() == result['text']
    assert not (tmp_path / 'meeting.txt').exists()


def test_repeated_words_and_silence_do_not_duplicate_committed_text():
    draft = CaptionDraft()
    words = [word(' very', 0, 0.5), word(' very', 0.6, 1), word(' good', 1.2, 2)]
    draft.update(words, 0, 4, 0)
    draft.update(words, 0, 7, 1)
    assert draft.update(words, 0, 10, 2)['text'] == 'very very good'
    assert draft.update([], 0, 13, 3)['text'] == 'very very good'
    with pytest.raises(ValueError, match='in order'):
        draft.update(words, 0, 16, 2)


def test_slow_inference_marks_gap_and_preserves_last_hypothesis():
    draft = CaptionDraft()
    draft.update([word(' Earlier', 1, 2)], 0, 4, 0)
    result = draft.update([word(' Later', 40, 41)], 39, 45, 1)
    assert result['text'] == ''
    assert result['unconfirmed_before_gaps'][0]['text'] == ' Earlier'
    assert result['provisional_text'] == 'Later'
    assert result['gaps'] == [{'start': 4, 'end': 39}]


def test_snapshot_alignment_mixes_both_sources_and_retains_silence(tmp_path):
    mic, system = tmp_path / 'mic.wav', tmp_path / 'system.wav'
    wav(mic, [1000] * 16000)
    wav(system, [3000] * 16000)
    samples, start, end = read_window([(mic, 0), (system, 0.5)])
    assert (start, end) == (0, 1.5)
    np.testing.assert_allclose(samples[:8000], 500 / 32768)
    np.testing.assert_allclose(samples[8000:16000], 2000 / 32768)
    np.testing.assert_allclose(samples[16000:], 1500 / 32768)


def test_snapshot_rejects_unbounded_audio_and_invalid_timestamps(tmp_path):
    path = tmp_path / 'audio.wav'
    wav(path, [0] * (16000 * 32))
    with pytest.raises(ValueError, match='at most 30'):
        read_window([(path, 0)])
    wav(path, [0] * 16000)
    for offset in [-1, float('nan'), float('inf')]:
        with pytest.raises(ValueError, match='timestamps'):
            read_window([(path, offset)])


def test_final_mix_is_aligned_retryable_and_preserves_originals(tmp_path):
    path = tmp_path / 'meeting.wav'
    system = tmp_path / '.tracks/meeting/system.wav'
    wav(path, [1000] * 16000)
    wav(system, [3000] * 16000)
    for _ in range(2):
        mix_recording(path, {'microphone': 0, 'system': 0.5})
        with wave.open(str(path)) as audio:
            assert audio.getnframes() == 24000
            samples = np.frombuffer(audio.readframes(24000), dtype='<i2')
        assert np.all(samples[:8000] == 500)
        assert np.all(samples[8000:16000] == 2000)
        assert np.all(samples[16000:] == 1500)
        with wave.open(str(tmp_path / '.tracks/meeting/microphone.wav')) as original:
            assert np.all(np.frombuffer(original.readframes(16000), dtype='<i2') == 1000)


def test_live_worker_uses_caption_model_and_never_exports_final_transcript():
    from pathlib import Path
    worker = Worker(lambda _: None)
    worker.handle({'id': 'config', 'command': 'save-config', 'changes': {'captions.model': 'tiny', 'transcription.model': 'small', 'transcription.diarize': True}})
    prepared = worker.handle({'id': 'prepare', 'command': 'prepare-recording'})
    path, stem = Path(prepared['wav_path']), prepared['stem']
    words = [word(' Hello', 0, 1), word(' meeting', 1, 2)]
    with patch('tscribe.transcriber.Transcriber') as transcriber:
        transcriber.return_value.transcribe_words.side_effect = lambda *args, **kwargs: [dict(item) for item in words]
        for sequence in range(2):
            wav(path.parent / '.live' / stem / f'{sequence}-microphone.wav', [0] * 64000)
            result = worker.handle({'id': str(sequence), 'command': 'live-caption', 'stem': stem, 'sequence': sequence, 'tracks': {'microphone': 0}})
        transcriber.assert_called_once_with(model_name='tiny', device='cpu')
        transcriber.return_value.transcribe.assert_not_called()
    assert result['text'] == 'Hello meeting'
    assert path.with_suffix('.captions.txt').read_text() == 'Hello meeting'
    assert not path.with_suffix('.txt').exists()
    assert worker.handle({'id': 'list', 'command': 'bootstrap'})['sessions'] == []


@pytest.mark.parametrize('values', [
    {'stem': '../outside', 'sequence': 0, 'tracks': {'microphone': 0}},
    {'stem': 'safe', 'sequence': -1, 'tracks': {'microphone': 0}},
    {'stem': 'safe', 'sequence': True, 'tracks': {'microphone': 0}},
    {'stem': 'safe', 'sequence': 0, 'tracks': {}},
    {'stem': 'safe', 'sequence': 0, 'tracks': {'../outside': 0}},
    {'stem': 'safe', 'sequence': 0, 'tracks': {'microphone': 'bad'}},
])
def test_live_worker_rejects_malformed_requests(values):
    with pytest.raises(ValueError):
        Worker(lambda _: None).handle({'id': 'test', 'command': 'live-caption', **values})


def test_committed_word_timestamp_jitter_does_not_repeat_text():
    draft = CaptionDraft()
    first = [word(' Hello', 0, 1), word(' everyone', 1, 2)]
    draft.update(first, 0, 4, 0)
    draft.update(first, 0, 7, 1)
    shifted = [word(' Hello', 0, 1), word(' everyone', 1, 2.2), word(' again', 2.3, 3)]
    draft.update(shifted, 0, 10, 2)
    result = draft.update(shifted, 0, 13, 3)
    assert result['text'] == 'Hello everyone again'


def test_meeting_finalization_and_clean_include_drafts_and_retained_tracks():
    from pathlib import Path
    from tscribe.session import SessionManager

    worker = Worker(lambda _: None)
    worker.handle({'id': 'settings', 'command': 'save-config', 'changes': {'recording.auto_transcribe': False}})
    prepared = worker.handle({'id': 'prepare', 'command': 'prepare-recording'})
    path, stem = Path(prepared['wav_path']), prepared['stem']
    wav(path, [1000] * 16000)
    wav(path.parent / '.tracks' / stem / 'system.wav', [2000] * 16000)
    CaptionDraft().save(path)
    result = worker.handle({'id': 'finish', 'command': 'finish-recording', 'stem': stem, 'source': 'meeting', 'track_offsets': {}})
    assert len(result['sessions']) == 1
    assert result['sessions'][0]['source'] == 'meeting'
    assert result['sessions'][0]['duration'] == 1
    manager = SessionManager(path.parent)
    dry = manager.clean_sessions(dry_run=True)
    assert len(dry) == 1
    assert len(dry[0][1]) == 6  # WAV, metadata, two tracks, two draft files
    total = sum(item.stat().st_size for item in dry[0][1])
    deleted, freed = manager.delete_session(stem)
    assert freed == total
    assert set(deleted) == set(dry[0][1])
    assert not list(path.parent.rglob('*.wav'))


def test_rolling_window_eviction_recovers_without_claiming_old_hypothesis_is_confirmed():
    draft = CaptionDraft()
    draft.update([word(' Old', 0, 1), word(' current', 5, 6)], 0, 10, 0)
    result = draft.update([word(' current', 5, 6), word(' phrase', 7, 8)], 4, 12, 1)
    assert result['text'] == 'current'
    assert result['unconfirmed_before_gaps'] == [word(' Old', 0, 1)]
    assert result['gaps'] == [{'start': 0, 'end': 4}]


def test_empty_remote_track_still_produces_microphone_meeting(tmp_path):
    path = tmp_path / 'quiet.wav'
    wav(path, [1000] * 16000)
    wav(tmp_path / '.tracks/quiet/system.wav', [])
    mix_recording(path, {})
    with wave.open(str(path)) as audio:
        assert audio.getnframes() == 16000
        assert np.all(np.frombuffer(audio.readframes(16000), dtype='<i2') == 500)


@pytest.mark.slow
def test_real_speech_caption_windows_and_final_export(tmp_path, monkeypatch):
    """Opt-in, cached-model check: no microphone access and no downloads."""
    import os
    from pathlib import Path
    from tscribe.transcriber import ensure_av_compatibility
    from faster_whisper.audio import decode_audio

    fixture = os.environ.get('TSCRIBE_LIVE_TEST_AUDIO')
    if not fixture:
        pytest.skip('Set TSCRIBE_LIVE_TEST_AUDIO to a speech audio file')
    monkeypatch.setenv('HF_HUB_OFFLINE', '1')
    ensure_av_compatibility()
    samples = decode_audio(fixture, sampling_rate=16000)
    samples = np.concatenate([samples, np.zeros(16000 * 4, dtype=np.float32)])
    worker = Worker(lambda _: None)
    model = os.environ.get('TSCRIBE_LIVE_TEST_MODEL', 'small')
    worker.handle({'id': 'config', 'command': 'save-config', 'changes': {'captions.model': model, 'transcription.model': model, 'transcription.language': 'en'}})
    prepared = worker.handle({'id': 'prepare', 'command': 'prepare-recording'})
    path, stem = Path(prepared['wav_path']), prepared['stem']
    wav(path, samples * 32767)
    for sequence, end in enumerate(range(4, int(len(samples) / 16000) + 1, 3)):
        start = max(0, end - 30)
        wav(path.parent / '.live' / stem / f'{sequence}-microphone.wav', samples[start * 16000:end * 16000] * 32767)
        result = worker.handle({'id': str(sequence), 'command': 'live-caption', 'stem': stem, 'sequence': sequence, 'tracks': {'microphone': start}})
    assert result['text'], 'Expected stable words across consecutive speech windows'
    assert path.with_suffix('.captions.json').exists()
    final = worker.handle({'id': 'finish', 'command': 'finish-recording', 'stem': stem})
    assert final['text']
    assert path.with_suffix('.json').exists()


def test_failed_mix_keeps_primary_recording_available(tmp_path):
    path = tmp_path / 'meeting.wav'
    wav(path, [1000] * 16000)
    original = path.read_bytes()
    # Missing system track must not move the primary WAV out of the session list.
    with pytest.raises(FileNotFoundError):
        mix_recording(path, {})
    assert path.read_bytes() == original


def test_caption_word_decoder_uses_vad_without_writing_exports():
    from types import SimpleNamespace
    from tscribe.transcriber import Transcriber

    model = Transcriber('tiny')
    samples = np.zeros(16000, dtype=np.float32)
    decoded = [SimpleNamespace(words=[SimpleNamespace(start=0, end=1, word=' Hello')])]
    with patch.object(model, '_get_model') as load, patch.object(model, '_write_outputs') as export:
        load.return_value.transcribe.return_value = (iter(decoded), None)
        assert model.transcribe_words(samples, 'de') == [word(' Hello', 0, 1)]
        options = load.return_value.transcribe.call_args.kwargs
        assert options['language'] == 'de'
        assert options['vad_filter'] is True
        assert options['word_timestamps'] is True
        assert options['condition_on_previous_text'] is False
        export.assert_not_called()



def test_caption_history_can_resume_for_final_window(tmp_path):
    path = tmp_path / 'meeting.wav'
    draft = CaptionDraft()
    words = [word(' Earlier', 1, 2)]
    draft.update(words, 0, 4, 0)
    draft.update(words, 0, 7, 1)
    draft.save(path)
    resumed = CaptionDraft.load(path)
    result = resumed.update([word(' Last', 39, 40), word(' words', 40, 41)], 35, 42, 2, final=True)
    resumed.save(path)
    assert result['text'] == 'Earlier'
    assert result['provisional_text'] == 'Last words'
    assert result['finished'] is True
    saved = json.loads(path.with_suffix('.captions.json').read_text())
    assert saved['audio_end'] == 42
    assert saved['sequence'] == 2
    assert path.with_suffix('.captions.txt').read_text() == 'Earlier Last words'


def test_final_window_creates_draft_before_first_caption_tick_and_without_final_transcription():
    from pathlib import Path
    worker = Worker(lambda _: None)
    worker.handle({'id': 'settings', 'command': 'save-config', 'changes': {'recording.auto_transcribe': False}})
    prepared = worker.handle({'id': 'prepare', 'command': 'prepare-recording'})
    path, stem = Path(prepared['wav_path']), prepared['stem']
    wav(path, [0] * 32000)
    wav(path.parent / '.live' / stem / '0-microphone.wav', [0] * 32000)
    with patch('tscribe.transcriber.Transcriber') as model:
        model.return_value.transcribe_words.return_value = [word(' Last', 0, 1), word(' words', 1, 2)]
        captions = worker.handle({'id': 'caption', 'command': 'live-caption', 'stem': stem, 'sequence': 0, 'tracks': {'microphone': 0}, 'final': True})
        result = worker.handle({'id': 'finish', 'command': 'finish-recording', 'stem': stem})
        model.return_value.transcribe.assert_not_called()
    assert captions['finished'] is True
    assert captions['audio_end'] == 2
    assert 'Last words' in result['text']
    assert result['sessions'][0]['transcribed'] is False
    assert not path.with_suffix('.json').exists()


def test_restarted_worker_final_window_retains_earlier_confirmed_text():
    from pathlib import Path
    worker = Worker(lambda _: None)
    prepared = worker.handle({'id': 'prepare', 'command': 'prepare-recording'})
    path, stem = Path(prepared['wav_path']), prepared['stem']
    draft = CaptionDraft()
    for sequence in range(2):
        draft.update([word(' Earlier', 0, 1)], 0, 3, sequence)
    draft.save(path)
    wav(path.parent / '.live' / stem / '2-microphone.wav', [0] * 32000)
    with patch('tscribe.transcriber.Transcriber') as model:
        model.return_value.transcribe_words.return_value = [word(' Goodbye', 1, 2)]
        result = worker.handle({'id': 'final', 'command': 'live-caption', 'stem': stem, 'sequence': 2, 'tracks': {'microphone': 40}, 'final': True})
    assert result['text'] == 'Earlier'
    assert result['provisional_text'] == 'Goodbye'
    assert result['finished'] is True
    assert path.with_suffix('.captions.txt').read_text() == 'Earlier Goodbye'


def test_corrupt_caption_history_is_not_overwritten_by_final_pass(tmp_path):
    path = tmp_path / 'meeting.wav'
    saved = path.with_suffix('.captions.json')
    saved.write_text('{"confirmed": "invalid"}')
    with pytest.raises(ValueError, match='saved caption'):
        CaptionDraft.load(path)
    assert saved.read_text() == '{"confirmed": "invalid"}'


@pytest.mark.slow
def test_real_speech_final_window_without_periodic_ticks_or_full_transcription(monkeypatch):
    import os
    from pathlib import Path
    from tscribe.transcriber import ensure_av_compatibility
    from faster_whisper.audio import decode_audio

    fixture = os.environ.get('TSCRIBE_LIVE_TEST_AUDIO')
    if not fixture:
        pytest.skip('Set TSCRIBE_LIVE_TEST_AUDIO to a speech audio file')
    monkeypatch.setenv('HF_HUB_OFFLINE', '1')
    ensure_av_compatibility()
    samples = decode_audio(fixture, sampling_rate=16000)
    assert len(samples) < 16000 * 30, 'Use a fixture under 30 seconds for this stop-before-first-tick check'
    worker = Worker(lambda _: None)
    model = os.environ.get('TSCRIBE_LIVE_TEST_MODEL', 'small')
    worker.handle({'id': 'config', 'command': 'save-config', 'changes': {'captions.model': model, 'recording.auto_transcribe': False, 'transcription.language': 'en'}})
    prepared = worker.handle({'id': 'prepare', 'command': 'prepare-recording'})
    path, stem = Path(prepared['wav_path']), prepared['stem']
    wav(path, samples * 32767)
    wav(path.parent / '.live' / stem / '0-microphone.wav', samples * 32767)
    result = worker.handle({'id': 'final', 'command': 'live-caption', 'stem': stem, 'sequence': 0, 'tracks': {'microphone': 0}, 'final': True})
    assert result['finished'] is True
    assert result['provisional_text']
    assert result['audio_end'] == pytest.approx(len(samples) / 16000)
    saved = worker.handle({'id': 'finish', 'command': 'finish-recording', 'stem': stem})
    assert result['provisional_text'] in saved['text']
    assert not path.with_suffix('.json').exists()
