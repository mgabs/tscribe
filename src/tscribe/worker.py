"""Line-delimited JSON bridge between the native Mac app and Python services.

Stdout is reserved for protocol messages; library output goes to stderr.
The worker does not record audio or import a GUI framework.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path
from typing import Callable

from tscribe.config import TscribeConfig
from tscribe.paths import get_config_path, get_data_dir, get_recordings_dir
from tscribe.recorder.base import RecordingResult
from tscribe.session import SessionManager


class Worker:
    def __init__(self, emit: Callable[[dict], None]):
        self.emit = emit
        self._transcriber = None
        self._model_key = None
        self._caption_stem = None
        self._caption_draft = None

    def configuration(self):
        config = TscribeConfig.load(get_config_path())
        manager = SessionManager(get_recordings_dir(get_data_dir(config.storage.data_dir)))
        return config, manager

    def snapshot(self, config, manager):
        return {
            'config': config._to_dict(),
            'config_path': str(get_config_path()),
            'recordings_dir': str(manager.recordings_dir),
            'sessions': [self.session_data(s) for s in manager.list_sessions(limit=config.app.recent_limit)],
        }

    @staticmethod
    def session_data(session):
        return {
            'stem': session.stem,
            'duration': session.duration_seconds or 0, 'transcribed': session.transcribed,
            'source': (session.metadata or {}).get('source_type', 'audio'),
        }

    @staticmethod
    def recording_path(manager, stem):
        if not isinstance(stem, str) or not stem or Path(stem).name != stem or stem in ('.', '..'):
            raise ValueError('Invalid recording name')
        return manager.recordings_dir / f'{stem}.wav'

    def handle(self, request):
        command = request.get('command')
        config, manager = self.configuration()
        if command == 'bootstrap':
            return self.snapshot(config, manager)
        if command == 'save-config':
            changes = request.get('changes', {})
            if not isinstance(changes, dict):
                raise ValueError('Configuration changes must be an object')
            for key, value in changes.items():
                config.set(key, value)
            config.save(get_config_path())
            config, manager = self.configuration()
            return self.snapshot(config, manager)
        if command == 'prepare-recording':
            stem = manager.generate_session_stem()
            return {'stem': stem, 'wav_path': str(self.recording_path(manager, stem)), 'config': config._to_dict()}
        if command == 'check-echo':
            import numpy as np
            from tscribe.echo import EchoCanceller
            with EchoCanceller() as canceller:
                canceller.process(np.zeros(160, dtype=np.float32), np.zeros(160, dtype=np.float32))
            return {'available': True, 'engine': 'SpeexDSP 1.2.1'}
        if command == 'live-caption':
            return self.live_caption(request, config, manager)
        if command in ('finish-recording', 'transcribe'):
            stem = request.get('stem')
            path = self.recording_path(manager, stem)
            if not path.is_file():
                raise FileNotFoundError(f'Recording not found: {path}')
            warning = None
            if command == 'finish-recording':
                # Read the completed WAV rather than trusting caller-supplied duration.
                import wave
                if request.get('source') == 'meeting':
                    from tscribe.live import mix_recording
                    warning = mix_recording(path, request.get('track_offsets', {}), echo_cancellation=self.use_echo(config))
                with wave.open(str(path)) as audio:
                    rate, channels = audio.getframerate(), audio.getnchannels()
                    duration = audio.getnframes() / rate
                if duration <= 0:
                    raise ValueError('The recording contains no audio. Check capture permissions and try again.')
                result = RecordingResult(path, duration, rate, channels, request.get('device', 'native'), request.get('source', 'microphone'))
                manager.write_metadata(stem, manager.create_metadata(result))
                if not config.recording.auto_transcribe:
                    return {**self.snapshot(config, manager), 'message': 'Recording saved', 'text': self.caption_text(path), 'warning': warning or ''}
            return {**self.transcribe(request, config, manager, stem, path), 'warning': warning or ''}
        if command == 'read-transcript':
            path = self.recording_path(manager, request.get('stem'))
            if path.with_suffix('.txt').is_file():
                return {'text': path.with_suffix('.txt').read_text(encoding='utf-8')}
            if path.with_suffix('.json').is_file():
                from tscribe.transcriber import TranscriptResult, TranscriptSegment
                data = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
                result = TranscriptResult(data.get('file', path.name), data.get('model', ''), data.get('language', ''), [TranscriptSegment(**segment) for segment in data['segments']])
                return {'text': result.to_txt()}
            return {'text': self.caption_text(path) or 'No text transcript is available. Select Transcribe to create one.'}
        raise ValueError(f'Unknown worker command: {command!r}')

    @staticmethod
    def use_echo(config):
        return config.captions.output_mode == 'speakers' and config.captions.echo_cancellation

    @staticmethod
    def caption_text(path):
        draft = path.with_suffix('.captions.txt')
        if draft.is_file():
            return 'Live caption draft (may be incomplete; not a final transcript)\n\n' + draft.read_text(encoding='utf-8')
        return ''

    def live_caption(self, request, config, manager):
        from tscribe.live import CaptionDraft, read_window
        from tscribe.transcriber import Transcriber

        stem = request.get('stem')
        path = self.recording_path(manager, stem)
        sequence = request.get('sequence')
        if type(sequence) is not int or sequence < 0:
            raise ValueError('Caption sequence must be a nonnegative integer')
        final = request.get('final', False)
        if type(final) is not bool:
            raise ValueError('Caption final flag must be a boolean')
        offsets = request.get('tracks')
        if not isinstance(offsets, dict) or not offsets or set(offsets) - {'microphone', 'system'}:
            raise ValueError('Caption tracks must be microphone and/or system')
        tracks = []
        for source in ('microphone', 'system'):
            if source not in offsets:
                continue
            offset = offsets[source]
            if type(offset) not in (int, float):
                raise ValueError('Caption track offsets must be numbers')
            tracks.append((path.parent / '.live' / stem / f'{sequence}-{source}.wav', offset))
        from tscribe.echo import EchoUnavailable
        use_echo = self.use_echo(config) and len(tracks) == 2
        warning = ''
        try:
            samples, start, end = read_window(tracks, echo_cancellation=use_echo)
        except EchoUnavailable as error:
            warning = str(error)
            samples, start, end = read_window(tracks)
            use_echo = False
        key = (config.captions.model, config.transcription.gpu)
        if key != self._model_key:
            self._transcriber = Transcriber(model_name=key[0], device='cuda' if key[1] else 'cpu')
            self._model_key = key
        words = self._transcriber.transcribe_words(samples, language=config.transcription.language)
        for word in words:
            word['start'] += start
            word['end'] += start
        if self._caption_stem != stem:
            self._caption_stem = stem
            self._caption_draft = CaptionDraft.load(path) if final else CaptionDraft()
        result = self._caption_draft.update(words, start, end, sequence, final=final)
        self._caption_draft.save(path)
        return {**result, 'echo_active': use_echo, 'warning': warning}

    def transcribe(self, request, config, manager, stem, path):
        from tscribe.transcriber import Transcriber
        self.emit({'id': request['id'], 'event': 'phase', 'data': {'phase': 'transcribing', 'model': config.transcription.model}})
        key = (config.transcription.model, config.transcription.gpu)
        if key != self._model_key:
            self._transcriber = Transcriber(model_name=key[0], device='cuda' if key[1] else 'cpu')
            self._model_key = key
        result = self._transcriber.transcribe(
            path, language=config.transcription.language,
            output_formats=config.transcription.output_formats,
            diarize=request.get('diarize', config.transcription.diarize),
            diarize_engine=request.get('diarize_engine', config.transcription.diarize_engine),
            progress_callback=lambda current, total: self.emit({
                'id': request['id'], 'event': 'progress', 'data': {'current': current, 'total': total},
            }),
        )
        manager.update_metadata(stem, transcribed=True, model=config.transcription.model)
        return {**self.snapshot(config, manager), 'text': result.to_txt(), 'message': 'Transcription complete', 'stem': stem}


def serve(input_stream, output_stream):
    def emit(message):
        output_stream.write(json.dumps(message, ensure_ascii=False) + '\n')
        output_stream.flush()

    worker = Worker(emit)
    for line in input_stream:
        request = {}
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError('Worker requests must be objects')
            if not isinstance(request.get('id'), str):
                raise ValueError('Worker requests need a string id')
            with contextlib.redirect_stdout(sys.stderr):
                data = worker.handle(request)
            emit({'id': request['id'], 'event': 'result', 'data': data})
        except Exception as exc:
            emit({'id': request.get('id') if isinstance(request, dict) else None, 'event': 'error', 'error': str(exc)})


def main():
    if sys.argv[1:2] == ['--cli']:
        from tscribe.cli import main as cli
        cli(sys.argv[2:])
        return
    serve(sys.stdin, sys.stdout)


if __name__ == '__main__':
    main()
