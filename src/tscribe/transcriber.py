"""Transcription via faster-whisper."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    confidence: float = 0.0
    speaker: str | None = None


@dataclass
class TranscriptResult:
    file: str
    model: str
    language: str
    segments: list[TranscriptSegment] = field(default_factory=list)

    def to_txt(self) -> str:
        """Plain text, grouped by speaker if present."""
        if not self.segments:
            return ""
        if not any(seg.speaker for seg in self.segments):
            return "\n".join(seg.text.strip() for seg in self.segments if seg.text.strip())

        blocks: list[str] = []
        current_speaker: str | None = None
        current_texts: list[str] = []

        for seg in self.segments:
            text = seg.text.strip()
            if not text:
                continue
            speaker = seg.speaker or "Unknown"
            if speaker != current_speaker:
                if current_texts and current_speaker:
                    blocks.append(f"[{current_speaker}]:\n" + "\n".join(current_texts))
                current_speaker = speaker
                current_texts = [text]
            else:
                current_texts.append(text)

        if current_texts and current_speaker:
            blocks.append(f"[{current_speaker}]:\n" + "\n".join(current_texts))

        return "\n\n".join(blocks)

    def to_json(self) -> dict:
        return {
            "file": self.file,
            "model": self.model,
            "language": self.language,
            "segments": [
                {
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text.strip(),
                    "confidence": seg.confidence,
                    "speaker": seg.speaker,
                }
                for seg in self.segments
            ],
        }

    def to_srt(self) -> str:
        lines = []
        for i, seg in enumerate(self.segments, 1):
            start_ts = _format_srt_time(seg.start)
            end_ts = _format_srt_time(seg.end)
            lines.append(f"{i}")
            lines.append(f"{start_ts} --> {end_ts}")
            prefix = f"[{seg.speaker}] " if seg.speaker else ""
            lines.append(f"{prefix}{seg.text.strip()}")
            lines.append("")
        return "\n".join(lines)

    def to_vtt(self) -> str:
        lines = ["WEBVTT", ""]
        for seg in self.segments:
            start_ts = _format_vtt_time(seg.start)
            end_ts = _format_vtt_time(seg.end)
            lines.append(f"{start_ts} --> {end_ts}")
            if seg.speaker:
                lines.append(f"<v {seg.speaker}>{seg.text.strip()}</v>")
            else:
                lines.append(seg.text.strip())
            lines.append("")
        return "\n".join(lines)


class Transcriber:
    """Transcribe audio files using faster-whisper (CTranslate2 backend)."""

    def __init__(
        self,
        model_name: str = "base",
        device: str = "cpu",
        compute_type: str | None = None,
    ):
        self._model_name = model_name
        self._device = device
        self._compute_type = compute_type or ("float16" if device == "cuda" else "int8")
        self._model = None

    def _get_model(self):
        """Lazy-load the WhisperModel (downloads on first use)."""
        if self._model is None:
            import os

            os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

            try:
                import av

                _orig_open = av.open

                def _compat_open(*args, **kwargs):
                    kwargs.pop("metadata_errors", None)
                    return _orig_open(*args, **kwargs)

                av.open = _compat_open
            except ImportError:
                pass

            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self._model_name,
                device=self._device,
                compute_type=self._compute_type,
            )
        return self._model

    def transcribe(
        self,
        audio_path: Path,
        language: str = "auto",
        output_formats: list[str] | None = None,
        progress_callback: Callable[[float, float], None] | None = None,
        diarize: bool = False,
        num_speakers: int | None = None,
        names: str | None = None,
    ) -> TranscriptResult:
        """Transcribe an audio file and write output files.

        If *progress_callback* is provided it is called after each segment
        with ``(segment_end_seconds, audio_duration_seconds)``.
        """
        if output_formats is None:
            output_formats = ["txt", "json"]

        model = self._get_model()
        lang = None if language == "auto" else language
        segments_iter, info = model.transcribe(str(audio_path), language=lang)

        duration = getattr(info, "duration", 0.0) or 0.0

        segments = []
        for seg in segments_iter:
            segments.append(
                TranscriptSegment(
                    start=seg.start,
                    end=seg.end,
                    text=seg.text,
                    confidence=seg.avg_logprob,
                )
            )
            if progress_callback and duration > 0:
                progress_callback(seg.end, duration)

        if progress_callback and duration > 0:
            progress_callback(duration, duration)

        if diarize:
            from tscribe.diarization import (
                Diarizer,
                attribute_speakers,
                parse_speaker_names,
            )

            diarizer = Diarizer()
            speaker_turns = diarizer.diarize(audio_path, num_speakers=num_speakers)
            name_map = parse_speaker_names(names)
            segments = attribute_speakers(segments, speaker_turns, name_map=name_map)

        result = TranscriptResult(
            file=audio_path.name,
            model=self._model_name,
            language=info.language,
            segments=segments,
        )

        base_path = audio_path.with_suffix("")
        self._write_outputs(result, base_path, output_formats)

        return result

    def _write_outputs(
        self, result: TranscriptResult, base_path: Path, formats: list[str]
    ) -> None:
        """Write output files in the requested formats."""
        for fmt in formats:
            if fmt == "txt":
                base_path.with_suffix(".txt").write_text(result.to_txt())
            elif fmt == "json":
                base_path.with_suffix(".json").write_text(
                    json.dumps(result.to_json(), indent=2)
                )
            elif fmt == "srt":
                base_path.with_suffix(".srt").write_text(result.to_srt())
            elif fmt == "vtt":
                base_path.with_suffix(".vtt").write_text(result.to_vtt())


def _format_srt_time(seconds: float) -> str:
    """Format seconds as SRT timestamp: HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def _format_vtt_time(seconds: float) -> str:
    """Format seconds as VTT timestamp: HH:MM:SS.mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"
