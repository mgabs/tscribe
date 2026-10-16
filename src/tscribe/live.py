"""Bounded local caption windows and a draft separate from the final transcript."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import wave
from pathlib import Path

import numpy as np

RATE = 16000
MAX_WINDOW = 30


def read_window(tracks, echo_cancellation=False):
    """Align completed rolling WAV snapshots; inference never reads an open WAV."""
    from faster_whisper.audio import decode_audio
    from tscribe.transcriber import ensure_av_compatibility

    ensure_av_compatibility()

    decoded = []
    for path, start in tracks:
        with wave.open(str(path)) as audio:
            if audio.getnframes() / audio.getframerate() > MAX_WINDOW + 1:
                raise ValueError('Caption snapshots must be at most 30 seconds')
        samples = decode_audio(str(path), sampling_rate=RATE)
        decoded.append((samples, float(start)))
    start = min(offset for _, offset in decoded)
    end = max(offset + len(samples) / RATE for samples, offset in decoded)
    if not np.isfinite(start) or not np.isfinite(end) or start < 0 or end - start > MAX_WINDOW + 2:
        raise ValueError('Invalid caption window timestamps')
    aligned = []
    for samples, offset in decoded:
        track = np.zeros(round((end - start) * RATE), dtype=np.float32)
        first = round((offset - start) * RATE)
        count = min(len(samples), len(track) - first)
        track[first:first + count] = samples[:count]
        aligned.append(track)
    if echo_cancellation and len(aligned) == 2:
        from tscribe.echo import EchoCanceller
        # The caller orders microphone first, system playback reference second.
        with EchoCanceller(RATE) as canceller:
            aligned[0] = canceller.process(aligned[0], aligned[1])
    mixed = sum(aligned) / len(aligned)
    return mixed, start, end


def mix_recording(path: Path, offsets: dict, echo_cancellation=False):
    """Mix retained mic/system tracks in bounded blocks after capture closes."""
    tracks = path.parent / '.tracks' / path.stem
    tracks.mkdir(parents=True, exist_ok=True)
    microphone = tracks / 'microphone.wav'
    system = tracks / 'system.wav'
    # Preserve the untouched microphone track, including if finalization is retried.
    if not microphone.exists():
        original = microphone.with_suffix('.wav.tmp')
        try:
            shutil.copyfile(path, original)
            original.replace(microphone)
        finally:
            original.unlink(missing_ok=True)
    with wave.open(str(microphone)) as mic, wave.open(str(system)) as remote:
        if mic.getparams()[:3] != remote.getparams()[:3] or mic.getsampwidth() != 2:
            raise ValueError('Meeting tracks must use matching 16-bit PCM formats')
        rate, channels = mic.getframerate(), mic.getnchannels()
        starts = [round(float(offsets.get(key, 0)) * rate) for key in ('microphone', 'system')]
        if any(value < 0 or value > rate * 60 for value in starts):
            raise ValueError('Invalid meeting track start offsets')
        length = max(start + source.getnframes() for start, source in zip(starts, (mic, remote)))
        canceller, warning = None, None
        if echo_cancellation:
            from tscribe.echo import EchoCanceller, EchoUnavailable
            try:
                canceller = EchoCanceller(rate)
            except EchoUnavailable as error:
                warning = str(error)
        descriptor, temporary = tempfile.mkstemp(prefix='.tscribe-mix-', suffix='.wav', dir=path.parent)
        os.close(descriptor)
        try:
            with wave.open(temporary, 'wb') as output:
                output.setnchannels(channels)
                output.setsampwidth(2)
                output.setframerate(rate)
                for position in range(0, length, rate):
                    count = min(rate, length - position)
                    blocks = []
                    for source, start in zip((mic, remote), starts):
                        block = np.zeros((count, channels), dtype=np.int32)
                        blocks.append(block)
                        first = max(position, start)
                        last = min(position + count, start + source.getnframes())
                        if first >= last:
                            continue
                        source.setpos(first - start)
                        samples = np.frombuffer(source.readframes(last - first), dtype='<i2').reshape(-1, channels)
                        block[first - position:last - position] = samples.astype(np.int32)
                    if canceller is not None:
                        try:
                            clean = canceller.process(blocks[0].mean(axis=1) / 32768, blocks[1].mean(axis=1) / 32768)
                            blocks[0] = np.rint(clean[:, None] * 32768).astype(np.int32)
                        except (RuntimeError, ValueError) as error:
                            warning = f'Echo cancellation stopped: {error}. Original audio is preserved.'
                            canceller.close()
                            canceller = None
                    mixed = blocks[0] + blocks[1]
                    output.writeframes((mixed // 2).astype('<i2').tobytes())
            os.replace(temporary, path)
        finally:
            if canceller is not None:
                canceller.close()
            Path(temporary).unlink(missing_ok=True)
        return warning


class CaptionDraft:
    """Confirm only the word prefix shared by two overlapping decodes."""
    def __init__(self):
        self.confirmed = []
        self.pending = []
        self.unconfirmed = []
        self.sequence = -1
        self.last_end = 0.0
        self.gaps = []

    @staticmethod
    def token(word):
        return word['text'].strip().casefold().strip('.,!?;:')

    def update(self, words, start, end, sequence):
        if sequence <= self.sequence:
            raise ValueError('Caption windows must arrive in order')
        self.sequence = sequence
        if start > self.last_end + 0.5:
            # Retain the last hypothesis before its audio leaves the rolling window.
            self.unconfirmed.extend(self.pending)
            self.pending = []
            self.gaps.append({'start': self.last_end, 'end': start})
        lost = [word for word in self.pending if word['end'] <= start]
        if lost:
            self.unconfirmed.extend(lost)
            self.gaps.append({'start': lost[0]['start'], 'end': start})
            self.pending = [word for word in self.pending if word['end'] > start]
        watermark = self.confirmed[-1]['end'] if self.confirmed else 0.0
        # Find the last confirmed word again in the overlap. Its end timestamp
        # can move slightly between decodes; matching the anchor avoids repeats.
        if self.confirmed:
            anchor = self.confirmed[-1]
            matches = [
                (abs(word['start'] - anchor['start']) + abs(word['end'] - anchor['end']), index)
                for index, word in enumerate(words)
                if self.token(word) == self.token(anchor)
                and abs(word['start'] - anchor['start']) < 0.5
                and abs(word['end'] - anchor['end']) < 0.5
            ]
            if matches:
                words = words[min(matches)[1] + 1:]
        current = [word for word in words if word['end'] > watermark + 0.05]
        previous = [word for word in self.pending if word['end'] > watermark + 0.05]
        count = 0
        for old, new in zip(previous, current):
            if self.token(old) != self.token(new) or abs(old['start'] - new['start']) > 1:
                break
            if new['end'] > end - 1:
                break
            count += 1
        self.confirmed.extend(current[:count])
        self.pending = current[count:]
        self.last_end = end
        return self.snapshot()

    def snapshot(self):
        return {
            'confirmed': self.confirmed, 'provisional': self.pending,
            'unconfirmed_before_gaps': self.unconfirmed,
            'text': ''.join(word['text'] for word in self.confirmed).strip(),
            'provisional_text': ''.join(word['text'] for word in self.pending).strip(),
            'audio_end': self.last_end, 'gaps': self.gaps,
        }

    def save(self, path):
        snapshot = self.snapshot()
        # Keep draft artifacts distinct from TXT/JSON produced by final transcription.
        temporary = path.with_suffix('.captions.json.tmp')
        temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path.with_suffix('.captions.json'))
        words = sorted(self.confirmed + self.unconfirmed + self.pending, key=lambda word: word['start'])
        text = ''.join(word['text'] for word in words).strip()
        temporary_text = path.with_suffix('.captions.txt.tmp')
        temporary_text.write_text(text, encoding='utf-8')
        temporary_text.replace(path.with_suffix('.captions.txt'))
