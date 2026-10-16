"""Transcription via faster-whisper."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


def ensure_av_compatibility():
    """Handle PyAV versions that removed faster-whisper's metadata_errors option."""
    import av

    if getattr(av.open, '_tscribe_compatible', False):
        return
    original = av.open

    def compatible_open(*args, **kwargs):
        kwargs.pop('metadata_errors', None)
        return original(*args, **kwargs)

    compatible_open._tscribe_compatible = True
    av.open = compatible_open


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

            if self._device == "cuda":
                import ctranslate2

                try:
                    ctranslate2.get_supported_compute_types("cuda")
                except (RuntimeError, ValueError) as error:
                    logging.getLogger(__name__).warning(
                        "CUDA is unavailable (%s); using CPU transcription instead.", error
                    )
                    self._device = "cpu"
                    supported = ctranslate2.get_supported_compute_types("cpu")
                    if self._compute_type not in supported:
                        self._compute_type = "int8" if "int8" in supported else "float32"

            ensure_av_compatibility()

            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self._model_name,
                device=self._device,
                compute_type=self._compute_type,
            )
        return self._model

    def transcribe_words(self, audio, language: str = "auto") -> list[dict]:
        """Decode one bounded caption window without export or diarization."""
        segments, _ = self._get_model().transcribe(
            audio, language=None if language == "auto" else language,
            beam_size=1, word_timestamps=True, vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 400},
            condition_on_previous_text=False,
        )
        return [
            {"start": word.start, "end": word.end, "text": word.word}
            for segment in segments for word in (segment.words or [])
        ]

    def transcribe(
        self,
        audio_path: Path,
        language: str = "auto",
        output_formats: list[str] | None = None,
        progress_callback: Callable[[float, float], None] | None = None,
        diarize: bool = False,
        num_speakers: int | None = None,
        names: str | None = None,
        output_base: Path | None = None,
    ) -> TranscriptResult:
        """Transcribe an audio file and write output files.

        If *progress_callback* is provided it is called after each segment
        with ``(segment_end_seconds, audio_duration_seconds)``.
        """
        if output_formats is None:
            output_formats = ["txt", "json"]

        model = self._get_model()
        lang = None if language == "auto" else language
        options = {"word_timestamps": True} if diarize else {}
        segments_iter, info = model.transcribe(str(audio_path), language=lang, **options)

        duration = getattr(info, "duration", 0.0) or 0.0

        segments = []
        word_segments = []
        for seg in segments_iter:
            segments.append(
                TranscriptSegment(
                    start=seg.start,
                    end=seg.end,
                    text=seg.text,
                    confidence=seg.avg_logprob,
                )
            )
            if diarize:
                word_segments.append([
                    TranscriptSegment(start=word.start, end=word.end, text=word.word)
                    for word in (seg.words or [])
                ])
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
            segments = attribute_speakers(
                segments, speaker_turns, name_map=name_map, word_segments=word_segments,
            )

        result = TranscriptResult(
            file=audio_path.name,
            model=self._model_name,
            language=info.language,
            segments=segments,
        )

        base_path = output_base if output_base is not None else audio_path.with_suffix("")
        self._write_outputs(result, base_path, output_formats)

        return result

    def _write_outputs(
        self, result: TranscriptResult, base_path: Path, formats: list[str]
    ) -> None:
        """Write output files in the requested formats."""
        from tscribe.constants import VALID_OUTPUT_FORMATS

        invalid = set(formats) - set(VALID_OUTPUT_FORMATS)
        if invalid:
            raise ValueError(f"Unknown output formats: {', '.join(sorted(invalid))}")
        base_path.parent.mkdir(parents=True, exist_ok=True)
        for fmt in formats:
            output_path = Path(f"{base_path}.{fmt}")
            if fmt == "txt":
                output_path.write_text(result.to_txt(), encoding="utf-8")
            elif fmt == "json":
                output_path.write_text(
                    json.dumps(result.to_json(), indent=2), encoding="utf-8"
                )
            elif fmt == "srt":
                output_path.write_text(result.to_srt(), encoding="utf-8")
            elif fmt == "vtt":
                output_path.write_text(result.to_vtt(), encoding="utf-8")


def _format_srt_time(seconds: float) -> str:
    """Format seconds as SRT timestamp: HH:MM:SS,mmm"""
    return _format_vtt_time(seconds).replace(".", ",")


def _format_vtt_time(seconds: float) -> str:
    """Format seconds as VTT timestamp: HH:MM:SS.mmm."""
    milliseconds = max(0, round(seconds * 1000))
    total_seconds, ms = divmod(milliseconds, 1000)
    total_minutes, sec = divmod(total_seconds, 60)
    hours, minute = divmod(total_minutes, 60)
    return f"{hours:02d}:{minute:02d}:{sec:02d}.{ms:03d}"
