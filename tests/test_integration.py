"""Integration tests — require faster-whisper model download.

Run with: uv run pytest tests/test_integration.py -v -m slow
"""

import json
import wave

import numpy as np
import pytest

from tscribe.transcriber import Transcriber


@pytest.fixture
def speech_wav(tmp_path):
    """Create a WAV with silence (for basic smoke testing)."""
    path = tmp_path / "test_speech.wav"
    samples = np.zeros(16000 * 3, dtype=np.int16)  # 3 seconds silence
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(samples.tobytes())
    return path


@pytest.mark.slow
def test_transcribe_silence(speech_wav):
    """Smoke test: transcribing silence should succeed without crashing."""
    t = Transcriber(model_name="tiny")
    try:
        result = t.transcribe(speech_wav, output_formats=["txt", "json"])
    except Exception as e:
        if "huggingface" in type(e).__module__ or "Offline" in type(e).__name__ or "LocalEntryNotFound" in type(e).__name__:
            pytest.skip(f"Model not cached locally in offline mode: {e}")
        raise

    assert result.file == speech_wav.name
    assert result.language is not None

    # Output files should exist
    assert speech_wav.with_suffix(".txt").exists()
    assert speech_wav.with_suffix(".json").exists()


@pytest.mark.slow
def test_transcribe_output_json_structure(speech_wav):
    """Verify the JSON output has the expected structure."""
    t = Transcriber(model_name="tiny")
    try:
        result = t.transcribe(speech_wav, output_formats=["json"])
    except Exception as e:
        if "huggingface" in type(e).__module__ or "Offline" in type(e).__name__ or "LocalEntryNotFound" in type(e).__name__:
            pytest.skip(f"Model not cached locally in offline mode: {e}")
        raise

    json_path = speech_wav.with_suffix(".json")
    data = json.loads(json_path.read_text())

    assert "file" in data
    assert "model" in data
    assert "language" in data
    assert "segments" in data
    assert isinstance(data["segments"], list)
