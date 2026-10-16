import io
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from tscribe.diarization import Diarizer


def test_voice_embeddings_keep_three_speakers_and_returning_speaker(tmp_path):
    diarizer = Diarizer(tmp_path)
    extractor = MagicMock()
    extractor.compute.side_effect = [[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 0, 0]]
    chunks = [(i, i+1, np.ones(16000, dtype=np.float32)) for i in range(4)]
    with patch.object(diarizer, '_extract_speech_chunks', return_value=chunks), patch.object(
        diarizer, '_get_extractor', return_value=extractor,
    ):
        turns = diarizer.diarize('meeting.wav', num_speakers=3)
    assert [turn.speaker_id for turn in turns] == [
        'Speaker 1', 'Speaker 2', 'Speaker 3', 'Speaker 1',
    ]
    assert [(turn.start, turn.end) for turn in turns] == [(0, 1), (1, 2), (2, 3), (3, 4)]
    assert extractor.create_stream.return_value.accept_waveform.call_args.args[0] == 16000


@pytest.mark.parametrize('samples', [np.array([], dtype=np.float32), np.zeros(16000)])
def test_empty_or_silent_audio_does_not_download_models(tmp_path, samples):
    diarizer = Diarizer(tmp_path)
    with patch('faster_whisper.audio.decode_audio', return_value=samples), patch.object(
        diarizer, '_get_extractor',
    ) as create:
        assert diarizer.diarize('empty.wav') == []
    create.assert_not_called()


def test_continuous_speech_is_split_without_waiting_for_silence():
    samples = np.ones(9*16000, dtype=np.float32)
    with patch('faster_whisper.audio.decode_audio', return_value=samples), patch(
        'faster_whisper.vad.get_speech_timestamps', return_value=[{'start': 0, 'end': len(samples)}],
    ):
        chunks = Diarizer()._extract_speech_chunks('continuous.wav')
    assert [(start, end) for start, end, _ in chunks] == [
        (0, 1.5), (1.5, 3), (3, 4.5), (4.5, 6), (6, 7.5), (7.5, 9),
    ]
    assert all(0.5*16000 <= len(data) <= 3*16000 for _, _, data in chunks)


@pytest.mark.parametrize('count', [0, -1, True, 2.5])
def test_invalid_speaker_count(count):
    with pytest.raises(ValueError, match='positive integer'):
        Diarizer().diarize('unused.wav', num_speakers=count)


def test_empty_and_single_embedding():
    diarizer = Diarizer()
    assert diarizer._cluster_embeddings(np.empty((0, 3)), []) == []
    turns = diarizer._cluster_embeddings(np.array([[1, 0, 0]]), [(0, 2)])
    assert len(turns) == 1
    assert (turns[0].start, turns[0].end, turns[0].speaker_id) == (0, 2, 'Speaker 1')


@pytest.mark.filterwarnings('ignore:Graph is not fully connected')
def test_auto_spectral_clustering_finds_three_voice_groups():
    rng = np.random.default_rng(1)
    features = np.repeat(np.eye(3), 20, axis=0) + rng.normal(0, 0.01, (60, 3))
    timestamps = [(float(i), float(i+1)) for i in range(60)]
    turns = Diarizer()._cluster_embeddings(features, timestamps)
    assert [(turn.start, turn.end, turn.speaker_id) for turn in turns] == [
        (0, 20, 'Speaker 1'), (20, 40, 'Speaker 2'), (40, 60, 'Speaker 3'),
    ]


def test_invalid_voice_embedding_is_an_error(tmp_path):
    diarizer = Diarizer(tmp_path)
    extractor = MagicMock()
    extractor.compute.return_value = [float('nan'), 1]
    with patch.object(diarizer, '_extract_speech_chunks', return_value=[(0, 1, np.ones(16000))]), patch.object(
        diarizer, '_get_extractor', return_value=extractor,
    ), pytest.raises(RuntimeError, match='invalid voice embedding'):
        diarizer.diarize('speech.wav')


def test_cached_model_needs_no_network(tmp_path):
    model = tmp_path / 'model.onnx'
    model.write_bytes(b'cached-model')
    with patch('urllib.request.urlopen') as download:
        assert Diarizer(tmp_path)._get_model('model.onnx', 'https://example.test/model') == model
    download.assert_not_called()


def test_failed_download_never_leaves_partial_model(tmp_path):
    with patch('urllib.request.urlopen', side_effect=OSError('offline')):
        with pytest.raises(RuntimeError, match='place.*model.onnx'):
            Diarizer(tmp_path)._get_model('model.onnx', 'https://example.test/model')
    assert list(tmp_path.iterdir()) == []


def test_engine_uses_voice_model(tmp_path):
    import sherpa_onnx

    diarizer = Diarizer(tmp_path)
    model = tmp_path / 'embedding.onnx'
    model.touch()
    with patch.object(diarizer, '_get_model', return_value=model), patch(
        'sherpa_onnx.SpeakerEmbeddingExtractorConfig.validate', return_value=True,
    ), patch('sherpa_onnx.SpeakerEmbeddingExtractor') as extractor:
        diarizer._get_extractor()
    config = extractor.call_args.args[0]
    assert isinstance(config, sherpa_onnx.SpeakerEmbeddingExtractorConfig)
    assert config.model == str(model)


def test_expired_asset_redirect_gets_one_fresh_retry(tmp_path):
    from urllib.error import HTTPError

    url = 'https://example.test/model'
    with patch('urllib.request.urlopen', side_effect=[
        HTTPError(url, 403, 'Expired signature', {}, None), io.BytesIO(b'model'),
    ]) as download:
        model = Diarizer(tmp_path)._get_model('model.onnx', url)
    assert model.read_bytes() == b'model'
    assert download.call_count == 2
    assert download.call_args.args[0].startswith(url + '?tscribe=')


def test_known_count_is_capped_at_available_voice_windows():
    features = np.eye(12)
    timestamps = [(float(i), float(i + 1)) for i in range(12)]
    turns = Diarizer()._cluster_embeddings(features, timestamps, num_speakers=20)
    assert len({turn.speaker_id for turn in turns}) == 12
