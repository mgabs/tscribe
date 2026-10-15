from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import pytest
from tscribe.diarization import Diarizer, SpeakerTurn


def test_clustering_with_known_speakers():
    diarizer = Diarizer()
    # 4 embeddings: two close to [1, 0], two close to [0, 1]
    embeddings = np.array([
        [1.0, 0.05],
        [0.95, 0.0],
        [0.05, 1.0],
        [0.0, 0.98],
    ])
    timestamps = [(0.0, 1.0), (1.5, 2.5), (3.0, 4.0), (4.5, 5.5)]
    turns = diarizer._cluster_embeddings(embeddings, timestamps, num_speakers=2)
    assert len(turns) == 4
    assert turns[0].speaker_id == turns[1].speaker_id
    assert turns[2].speaker_id == turns[3].speaker_id
    assert turns[0].speaker_id != turns[2].speaker_id


def test_clustering_empty():
    diarizer = Diarizer()
    turns = diarizer._cluster_embeddings(np.empty((0, 64)), [])
    assert turns == []


def test_clustering_single_speaker():
    diarizer = Diarizer()
    embeddings = np.array([[1.0, 0.5]])
    timestamps = [(0.0, 2.0)]
    turns = diarizer._cluster_embeddings(embeddings, timestamps)
    assert len(turns) == 1
    assert turns[0].start == 0.0
    assert turns[0].end == 2.0
    assert turns[0].speaker_id == "Speaker 1"


def test_empty_audio_returns_empty_turns(tmp_path):
    diarizer = Diarizer()
    empty_file = tmp_path / "empty.wav"
    empty_file.write_bytes(b"RIFF....WAVEfmt ....data....")
    with patch.object(diarizer, "_extract_speech_chunks", return_value=[]):
        turns = diarizer.diarize(empty_file)
        assert turns == []


def test_diarize_extracts_and_clusters(tmp_path):
    diarizer = Diarizer()
    fake_audio = tmp_path / "speech.wav"
    fake_audio.write_bytes(b"dummy")

    fake_chunks = [
        (0.0, 1.5, np.ones(3200, dtype=np.float32) * 0.5),
        (2.0, 3.5, np.ones(3200, dtype=np.float32) * -0.5),
    ]
    with patch.object(diarizer, "_extract_speech_chunks", return_value=fake_chunks):
        turns = diarizer.diarize(fake_audio, num_speakers=2)
        assert len(turns) == 2
        assert turns[0].start == 0.0
        assert turns[0].end == 1.5
        assert turns[1].start == 2.0
        assert turns[1].end == 3.5
