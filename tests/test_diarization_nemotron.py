import json
import subprocess
import sys

import pytest

from tscribe import diarization_nemotron as nem
from tscribe.diarization import EngineUnavailableError, SpeakerTurn


def no_download(*args):
    raise AssertionError("unexpected weight download")


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("TSCRIBE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(nem, "download_weights", no_download)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    binary = tmp_path / "nemo-speech"
    binary.write_text("")
    weights = tmp_path / "w.gguf"
    weights.write_bytes(b"x")
    monkeypatch.setenv("TSCRIBE_NEMO_SPEECH", str(binary))
    monkeypatch.setenv("TSCRIBE_NEMOTRON_WEIGHTS", str(weights))
    monkeypatch.setattr(nem, "_to_wav16k", lambda src, dst: dst.write_bytes(b"RIFF"))
    return binary, weights


def fake_run(monkeypatch, segments=None, code=0, stderr=""):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        out = json.dumps({"file": "a", "segments": segments or []})
        return subprocess.CompletedProcess(cmd, code, out, stderr)

    monkeypatch.setattr(nem.subprocess, "run", run)
    return calls


def test_maps_segments_to_one_based_speaker_turns(runtime, monkeypatch, tmp_path):
    segs = [{"start": 0.0, "end": 1.5, "speaker": 1}, {"start": 1.5, "end": 3, "speaker": 2}]
    calls = fake_run(monkeypatch, segs)
    turns = nem.NemotronEngine().diarize(tmp_path / "a.mp3")
    assert turns == [SpeakerTurn(0.0, 1.5, "Speaker 1"), SpeakerTurn(1.5, 3.0, "Speaker 2")]
    cmd = calls[0]
    assert cmd[1] == "diarize" and cmd[cmd.index("--format") + 1] == "json"
    assert cmd[cmd.index("--model") + 1] == str(runtime[1])


def test_speaker_cap_rejected_before_running(runtime, monkeypatch):
    calls = fake_run(monkeypatch)
    with pytest.raises(ValueError, match="maximum of 8"):
        nem.NemotronEngine().diarize("a.wav", num_speakers=9)
    assert not calls


def test_more_than_eight_distinct_speakers_reported(runtime, monkeypatch):
    fake_run(monkeypatch, [{"start": i, "end": i + 1, "speaker": i + 1} for i in range(9)])
    with pytest.raises(RuntimeError, match="maximum of 8"):
        nem.NemotronEngine().diarize("a.wav")


def test_nonzero_exit_includes_stderr_tail(runtime, monkeypatch):
    fake_run(monkeypatch, code=2, stderr="boom")
    with pytest.raises(RuntimeError, match="boom"):
        nem.NemotronEngine().diarize("a.wav")


def test_missing_binary_explains_install(monkeypatch, tmp_path):
    monkeypatch.setattr(nem, "download_weights", no_download)
    monkeypatch.setenv("TSCRIBE_NEMOTRON_WEIGHTS", str(tmp_path / "w.gguf"))
    monkeypatch.delenv("TSCRIBE_NEMO_SPEECH", raising=False)
    monkeypatch.setattr(nem.shutil, "which", lambda name: None)
    with pytest.raises(EngineUnavailableError, match="NeMo-Speech.cpp"):
        nem.NemotronEngine().diarize("a.wav")


def test_frozen_uses_bundle_and_never_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(nem, "download_weights", no_download)
    with pytest.raises(EngineUnavailableError, match="nemo-speech"):
        nem.NemotronEngine().diarize("a.wav")
    (tmp_path / "nemotron" / "bin").mkdir(parents=True)
    (tmp_path / "nemotron" / "bin" / "nemo-speech").write_text("")
    with pytest.raises(EngineUnavailableError, match="Nemotron-3-Diarization"):
        nem.NemotronEngine().diarize("a.wav")


def test_dev_downloads_weights_to_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TSCRIBE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("TSCRIBE_NEMOTRON_WEIGHTS", raising=False)
    binary = tmp_path / "nemo-speech"
    binary.write_text("")
    monkeypatch.setenv("TSCRIBE_NEMO_SPEECH", str(binary))
    seen = []

    def download(models_dir, filename, url):
        seen.append((models_dir, filename, url))
        return models_dir / filename

    monkeypatch.setattr(nem, "download_weights", download)
    monkeypatch.setattr(nem, "_to_wav16k", lambda s, d: d.write_bytes(b"R"))
    fake_run(monkeypatch)
    nem.NemotronEngine().diarize("a.wav")
    assert seen[0][0] == tmp_path / "models" / "diarization" / "nemotron"
    assert seen[0][2].startswith("https://huggingface.co/nvidia/Nemotron-3-Diarization/")


def test_temp_wav_removed(runtime, monkeypatch):
    paths = []
    monkeypatch.setattr(nem, "_to_wav16k", lambda s, d: (paths.append(d), d.write_bytes(b"R")))
    fake_run(monkeypatch)
    nem.NemotronEngine().diarize("a.mp3")
    assert not paths[0].exists()


def test_frozen_missing_weights_named(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    (tmp_path / "nemotron" / "bin").mkdir(parents=True)
    (tmp_path / "nemotron" / "bin" / "nemo-speech").write_text("")
    with pytest.raises(EngineUnavailableError, match="weights"):
        nem.NemotronEngine().diarize("a.wav")


def test_frozen_bundle_runs_with_bundled_weights(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    bundle = tmp_path / "nemotron"
    (bundle / "bin").mkdir(parents=True)
    (bundle / "bin" / "nemo-speech").write_text("")
    (bundle / nem.WEIGHTS_NAME).write_bytes(b"x")
    monkeypatch.setattr(nem, "_to_wav16k", lambda s, d: d.write_bytes(b"R"))
    calls = fake_run(monkeypatch)
    nem.NemotronEngine().diarize("a.wav")
    assert calls[0][0] == str(bundle / "bin" / "nemo-speech")
    assert calls[0][calls[0].index("--model") + 1] == str(bundle / nem.WEIGHTS_NAME)


@pytest.mark.parametrize("bad", [0, -1, True, 2.5])
def test_invalid_speaker_count_rejected(runtime, monkeypatch, bad):
    fake_run(monkeypatch)
    with pytest.raises(ValueError, match="positive integer"):
        nem.NemotronEngine().diarize("a.wav", num_speakers=bad)


def test_eight_speakers_allowed(runtime, monkeypatch):
    fake_run(monkeypatch, [{"start": i, "end": i + 1, "speaker": i + 1} for i in range(8)])
    assert len(nem.NemotronEngine().diarize("a.wav", num_speakers=8)) == 8


def test_invalid_cli_output_reported(runtime, monkeypatch):
    monkeypatch.setattr(
        nem.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "not json", "")
    )
    with pytest.raises(RuntimeError, match="invalid diarization output"):
        nem.NemotronEngine().diarize("a.wav")


def test_to_wav16k_writes_mono_16k(tmp_path, monkeypatch):
    import wave

    import numpy as np
    import faster_whisper.audio as fw

    seen = []

    def decode(path, sampling_rate):
        seen.append((path, sampling_rate))
        return np.array([0.0, 1.0, -2.0, 2.0], dtype="float32")

    monkeypatch.setattr(fw, "decode_audio", decode)
    monkeypatch.setattr("tscribe.transcriber.ensure_av_compatibility", lambda: None)
    out = tmp_path / "o.wav"
    nem._to_wav16k("x.mp3", out)
    assert seen == [("x.mp3", 16000)]
    with wave.open(str(out)) as w:
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth(), w.getnframes()) == (1, 16000, 2, 4)
        assert np.frombuffer(w.readframes(4), dtype="<i2").tolist() == [0, 32767, -32767, 32767]


def test_diarize_decodes_given_audio_path(runtime, monkeypatch):
    seen = []
    monkeypatch.setattr(nem, "_to_wav16k", lambda s, d: (seen.append(s), d.write_bytes(b"R")))
    fake_run(monkeypatch)
    nem.NemotronEngine().diarize("clip.mp3")
    assert seen == ["clip.mp3"]



def test_cli_invocation_exact(runtime, monkeypatch):
    seen = {}

    def run(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        seen["wav_exists"] = __import__("pathlib").Path(cmd[2]).is_file()
        seen["wav_name"] = __import__("pathlib").Path(cmd[2]).name
        seen["wav_dir"] = __import__("pathlib").Path(cmd[2]).parent.name
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"segments": []}), "")

    monkeypatch.setattr(nem.subprocess, "run", run)
    nem.NemotronEngine().diarize("a.wav", num_speakers=1)
    assert seen["cmd"][0] == str(runtime[0])
    assert seen["cmd"][1] == "diarize" and seen["cmd"][3] == "--model" and seen["cmd"][5] == "--format"
    assert seen["cmd"][4] == str(runtime[1]) and seen["cmd"][6] == "json" and len(seen["cmd"]) == 7
    assert seen["kw"] == {"capture_output": True, "text": True}
    assert seen["wav_exists"] and seen["wav_name"] == "audio.wav" and seen["wav_dir"].startswith("tscribe-nemotron-")


def test_stderr_tail_limited_and_messages_exact(runtime, monkeypatch):
    fake_run(monkeypatch, code=3, stderr="A" * 600 + "B" * 500)
    with pytest.raises(RuntimeError) as info:
        nem.NemotronEngine().diarize("a.wav")
    assert str(info.value) == "nemo-speech failed (exit 3): " + "B" * 500
    fake_run(monkeypatch, code=4, stderr="")
    with pytest.raises(RuntimeError) as info:
        nem.NemotronEngine().diarize("a.wav")
    assert str(info.value) == "nemo-speech failed (exit 4): "


def test_error_messages_exact(runtime, monkeypatch):
    fake_run(monkeypatch)
    with pytest.raises(ValueError) as info:
        nem.NemotronEngine().diarize("a.wav", num_speakers=0)
    assert str(info.value) == "Number of speakers must be a positive integer"
    with pytest.raises(ValueError) as info:
        nem.NemotronEngine().diarize("a.wav", num_speakers=9)
    assert str(info.value) == "Nemotron diarization supports a maximum of 8 speakers (requested 9)"
    fake_run(monkeypatch, [{"start": i, "end": i + 1, "speaker": i + 1} for i in range(9)])
    with pytest.raises(RuntimeError) as info:
        nem.NemotronEngine().diarize("a.wav")
    assert str(info.value) == "Nemotron found more than the maximum of 8 speakers"


def test_binary_lookup_and_messages(monkeypatch):
    monkeypatch.setattr(nem, "download_weights", no_download)
    monkeypatch.delenv("TSCRIBE_NEMO_SPEECH", raising=False)
    names = []
    monkeypatch.setattr(nem.shutil, "which", lambda n: names.append(n))
    with pytest.raises(EngineUnavailableError) as info:
        nem.NemotronEngine()._binary()
    assert names == ["nemo-speech"]
    assert str(info.value) == (
        "The nemo-speech runtime was not found. Install it from https://github.com/NVIDIA/NeMo-Speech.cpp"
        " and put it on PATH or set TSCRIBE_NEMO_SPEECH."
    )


def test_frozen_messages_exact(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    with pytest.raises(EngineUnavailableError) as info:
        nem.NemotronEngine()._binary()
    assert str(info.value) == f"Bundled Nemotron runtime (nemo-speech) is missing at {tmp_path / 'nemotron' / 'bin' / 'nemo-speech'}"
    with pytest.raises(EngineUnavailableError) as info:
        nem.NemotronEngine()._weights()
    assert str(info.value) == f"Bundled Nemotron weights ({nem.WEIGHTS_NAME}) are missing at {tmp_path / 'nemotron' / nem.WEIGHTS_NAME}"


def test_invalid_output_message_and_weights_override_wins(runtime, monkeypatch):
    monkeypatch.setattr(nem, "download_weights", no_download)
    assert nem.NemotronEngine()._weights() == runtime[1]
    monkeypatch.setattr(nem.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "{}", ""))
    with pytest.raises(RuntimeError, match="^nemo-speech returned invalid diarization output: 'segments'$"):
        nem.NemotronEngine().diarize("a.wav")
