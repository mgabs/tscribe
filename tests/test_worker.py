"""Protocol and persistence tests for the GUI-free native-app worker."""
import io
import json
import wave
from pathlib import Path
from unittest.mock import patch

import pytest

from tscribe.worker import Worker, serve


def call(worker, command, **values):
    return worker.handle({'id': 'request', 'command': command, **values})


def test_bootstrap_shares_config_and_storage(tmp_path):
    worker = Worker(lambda _: None)
    original = call(worker, 'bootstrap')
    assert original['config']['transcription']['model'] == 'small'
    snapshot = call(worker, 'save-config', changes={'storage.data_dir': str(tmp_path / 'audio'), 'transcription.model': 'tiny'})
    assert snapshot['recordings_dir'] == str(tmp_path / 'audio/recordings')
    assert snapshot['config_path'] == original['config_path']
    assert call(worker, 'bootstrap')['config']['transcription']['model'] == 'tiny'


def test_worker_finishes_native_wav_without_transcribing(tmp_path):
    worker = Worker(lambda _: None)
    call(worker, 'save-config', changes={'recording.auto_transcribe': False})
    prepared = call(worker, 'prepare-recording')
    with wave.open(prepared['wav_path'], 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b'\0\0' * 16000)
    with patch('tscribe.transcriber.Transcriber') as transcriber:
        result = call(worker, 'finish-recording', stem=prepared['stem'], source='loopback', device='ScreenCaptureKit')
        transcriber.assert_not_called()
    assert result['sessions'][0]['duration'] == 1
    assert result['sessions'][0]['source'] == 'loopback'
    assert result['sessions'][0]['transcribed'] is False


def test_worker_protocol_recovers_after_bad_input():
    incoming = io.StringIO('bad json\n[]\n' + json.dumps({'id': 'ok', 'command': 'bootstrap'}) + '\n')
    outgoing = io.StringIO()
    serve(incoming, outgoing)
    messages = [json.loads(line) for line in outgoing.getvalue().splitlines()]
    assert [message['event'] for message in messages] == ['error', 'error', 'result']
    assert messages[-1]['id'] == 'ok'


@pytest.mark.parametrize('stem', ['../outside', '', '/tmp/audio'])
def test_worker_rejects_recording_path_traversal(stem):
    with pytest.raises(ValueError, match='Invalid recording name'):
        call(Worker(lambda _: None), 'read-transcript', stem=stem)


def test_save_config_is_transactional():
    worker = Worker(lambda _: None)
    call(worker, 'save-config', changes={'transcription.model': 'tiny'})
    with pytest.raises(ValueError):
        call(worker, 'save-config', changes={'transcription.model': 'base', 'recording.channels': 0})
    assert call(worker, 'bootstrap')['config']['transcription']['model'] == 'tiny'


def test_native_recording_transcribes_with_shared_settings_and_progress():
    from tscribe.transcriber import TranscriptResult, TranscriptSegment

    events = []
    worker = Worker(events.append)
    call(worker, 'save-config', changes={
        'transcription.model': 'tiny', 'transcription.language': 'fr',
        'transcription.diarize': True, 'transcription.output_formats': ['json', 'srt'],
    })
    prepared = call(worker, 'prepare-recording')
    path = Path(prepared['wav_path'])
    with wave.open(str(path), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b'\0\0' * 1600)
    transcript = TranscriptResult(path.name, 'tiny', 'fr', [TranscriptSegment(0, 0.1, 'Bonjour')])

    def transcribe(audio_path, **options):
        assert audio_path == path
        assert options['language'] == 'fr'
        assert options['diarize'] is True
        assert options['output_formats'] == ['json', 'srt']
        options['progress_callback'](0.1, 0.1)
        path.with_suffix('.json').write_text(json.dumps(transcript.to_json()))
        return transcript

    with patch('tscribe.transcriber.Transcriber') as transcriber:
        transcriber.return_value.transcribe.side_effect = transcribe
        result = call(worker, 'finish-recording', stem=prepared['stem'])
        transcriber.assert_called_once_with(model_name='tiny', device='cpu')
    assert result['text'] == 'Bonjour'
    assert result['sessions'][0]['transcribed'] is True
    assert result['sessions'][0]['duration'] == 0.1
    assert [event['event'] for event in events] == ['phase', 'progress']
    assert call(worker, 'read-transcript', stem=prepared['stem'])['text'] == 'Bonjour'
