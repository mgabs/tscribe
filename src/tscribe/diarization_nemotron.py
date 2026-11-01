from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

from tscribe.diarization import EngineUnavailableError, SpeakerTurn, download_weights

MAX_SPEAKERS = 8
WEIGHTS_NAME = "Nemotron-3-Diarization.q8_0.gguf"
WEIGHTS_URL = f"https://huggingface.co/nvidia/Nemotron-3-Diarization/resolve/main/{WEIGHTS_NAME}"
INSTALL_HINT = "Install it from https://github.com/NVIDIA/NeMo-Speech.cpp"


def _to_wav16k(source: Path | str, destination: Path) -> None:
    from faster_whisper.audio import decode_audio
    from tscribe.transcriber import ensure_av_compatibility

    ensure_av_compatibility()
    samples = decode_audio(str(source), sampling_rate=16000)
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(destination), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(pcm.tobytes())


class NemotronEngine:
    """Local diarization through the NeMo-Speech.cpp CLI; audio never leaves this machine."""

    def _bundle(self) -> Path | None:
        if getattr(sys, "frozen", False):  # pragma: no mutate
            return Path(sys._MEIPASS) / "nemotron"
        return None

    def _binary(self) -> Path:
        bundle = self._bundle()
        if bundle is not None:
            binary = bundle / "bin" / "nemo-speech"
            if not binary.is_file():
                raise EngineUnavailableError(
                    f"Bundled Nemotron runtime (nemo-speech) is missing at {binary}"
                )
            return binary
        found = os.environ.get("TSCRIBE_NEMO_SPEECH") or shutil.which("nemo-speech")
        if not found:
            raise EngineUnavailableError(
                f"The nemo-speech runtime was not found. {INSTALL_HINT} and put it on PATH "
                "or set TSCRIBE_NEMO_SPEECH."
            )
        return Path(found)

    def _weights(self) -> Path:
        bundle = self._bundle()
        if bundle is not None:
            weights = bundle / WEIGHTS_NAME
            if not weights.is_file():
                raise EngineUnavailableError(
                    f"Bundled Nemotron weights ({WEIGHTS_NAME}) are missing at {weights}"
                )
            return weights
        override = os.environ.get("TSCRIBE_NEMOTRON_WEIGHTS")
        if override:
            return Path(override)
        from tscribe.paths import get_data_dir

        models_dir = get_data_dir() / "models" / "diarization" / "nemotron"
        return download_weights(models_dir, WEIGHTS_NAME, WEIGHTS_URL)

    def diarize(self, audio_path: Path | str, num_speakers: int | None = None) -> list[SpeakerTurn]:
        if num_speakers is not None and (type(num_speakers) is not int or num_speakers < 1):
            raise ValueError("Number of speakers must be a positive integer")
        if num_speakers is not None and num_speakers > MAX_SPEAKERS:
            raise ValueError(
                f"Nemotron diarization supports a maximum of {MAX_SPEAKERS} speakers "
                f"(requested {num_speakers})"
            )
        binary = self._binary()
        weights = self._weights()
        with tempfile.TemporaryDirectory(prefix="tscribe-nemotron-") as work:
            wav = Path(work) / "audio.wav"
            _to_wav16k(audio_path, wav)
            result = subprocess.run(
                [str(binary), "diarize", str(wav), "--model", str(weights), "--format", "json"],
                capture_output=True, text=True,
            )
        if result.returncode != 0:
            tail = (result.stderr or "").strip()[-500:]
            raise RuntimeError(f"nemo-speech failed (exit {result.returncode}): {tail}")
        try:
            segments = json.loads(result.stdout)["segments"]
        except (ValueError, KeyError, TypeError) as error:
            raise RuntimeError(f"nemo-speech returned invalid diarization output: {error}") from error
        if len({s["speaker"] for s in segments}) > MAX_SPEAKERS:
            raise RuntimeError(
                f"Nemotron found more than the maximum of {MAX_SPEAKERS} speakers"
            )
        return [
            SpeakerTurn(float(s["start"]), float(s["end"]), f"Speaker {int(s['speaker'])}")
            for s in segments
        ]
