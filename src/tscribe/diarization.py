from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import numpy as np
from tscribe.transcriber import TranscriptSegment


@dataclass
class SpeakerTurn:
    start: float
    end: float
    speaker_id: str


def parse_speaker_names(names_str: str | None) -> dict[str, str]:
    """Parse comma-separated speaker names into a mapping dictionary.

    Supports:
      - Positional: "Alice, Bob" -> {"Speaker 1": "Alice", "Speaker 2": "Bob"}
      - Key-value: "1=Alice, 3=Charlie" -> {"Speaker 1": "Alice", "Speaker 3": "Charlie"}
    """
    if not names_str or not names_str.strip():
        return {}

    mapping: dict[str, str] = {}
    tokens = [t.strip() for t in names_str.split(",") if t.strip()]

    is_explicit = any("=" in token for token in tokens)
    if is_explicit:
        for token in tokens:
            if "=" in token:
                key, val = token.split("=", 1)
                k_clean = key.strip()
                v_clean = val.strip()
                if not k_clean or not v_clean:
                    continue
                if k_clean.isdigit():
                    mapping[f"Speaker {k_clean}"] = v_clean
                elif k_clean.lower().startswith("speaker"):
                    rest = k_clean[7:].strip()
                    if rest.isdigit():
                        mapping[f"Speaker {rest}"] = v_clean
                    else:
                        mapping[k_clean.capitalize()] = v_clean
                else:
                    mapping[k_clean] = v_clean
    else:
        for idx, name in enumerate(tokens, 1):
            mapping[f"Speaker {idx}"] = name

    return mapping


def attribute_speakers(
    segments: list[TranscriptSegment],
    speaker_turns: list[SpeakerTurn],
    name_map: dict[str, str] | None = None,
    word_segments: list[list[TranscriptSegment]] | None = None,
) -> list[TranscriptSegment]:
    """Assign by overlap, splitting at word boundaries when timing is available."""
    if not speaker_turns:
        return segments

    name_map = name_map or {}

    if word_segments is not None:
        if len(word_segments) != len(segments):
            raise ValueError("Word timings must match transcript segments")
        attributed = []
        for segment, words in zip(segments, word_segments):
            if not words:
                attributed.extend(attribute_speakers([segment], speaker_turns, name_map))
                continue
            attributed_words = attribute_speakers(words, speaker_turns, name_map)
            groups: list[TranscriptSegment] = []
            for word in attributed_words:
                if groups and groups[-1].speaker == word.speaker:
                    groups[-1].text += word.text
                    groups[-1].end = word.end
                else:
                    groups.append(TranscriptSegment(
                        start=word.start, end=word.end, text=word.text,
                        confidence=segment.confidence, speaker=word.speaker,
                    ))
            attributed.extend(groups)
        return attributed

    for seg in segments:
        best_overlap = 0.0
        best_speaker = None
        for turn in speaker_turns:
            overlap_start = max(seg.start, turn.start)
            overlap_end = min(seg.end, turn.end)
            overlap = max(0.0, overlap_end - overlap_start)
            # Whisper sometimes emits zero-duration words. Match their point
            # timestamp rather than losing their speaker through zero overlap.
            if seg.start == seg.end and turn.start <= seg.start < turn.end:
                overlap = 1.0
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = turn.speaker_id

        if best_speaker:
            seg.speaker = name_map.get(best_speaker, best_speaker)

    return segments


class Diarizer:
    """Local speaker diarization using neural voice embeddings and spectral clustering.

    Models are cached on first use; audio never leaves this machine.
    """

    def __init__(self, models_dir: Path | None = None):
        from tscribe.paths import get_data_dir

        self.models_dir = models_dir or get_data_dir() / "models" / "diarization"

    def _get_model(self, filename: str, url: str) -> Path:
        import logging
        import shutil
        import ssl
        import tempfile
        from urllib.error import HTTPError
        from urllib.request import urlopen
        from uuid import uuid4

        import truststore

        destination = self.models_dir / filename
        if destination.is_file() and destination.stat().st_size:
            return destination
        self.models_dir.mkdir(parents=True, exist_ok=True)
        logging.getLogger(__name__).info("Downloading speaker model %s", filename)
        try:
            # Stage each download separately so interruption or concurrent workers
            # cannot leave a partially downloaded model at the final path.
            with tempfile.TemporaryDirectory(dir=self.models_dir) as temporary:
                download_path = Path(temporary) / "download"
                context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                try:
                    response = urlopen(url, timeout=60, context=context)
                except HTTPError as error:
                    if error.code != 403:
                        raise
                    error.close()
                    # A cached GitHub redirect may carry an expired asset signature.
                    # Request a fresh redirect once, keeping certificate checks on.
                    separator = "&" if "?" in url else "?"
                    response = urlopen(
                        f"{url}{separator}tscribe={uuid4().hex}", timeout=60, context=context,
                    )
                with response, download_path.open("wb") as output:
                    shutil.copyfileobj(response, output)
                if not download_path.stat().st_size:
                    raise ValueError("Downloaded speaker model is empty")
                download_path.replace(destination)
        except (OSError, ValueError) as error:
            raise RuntimeError(
                f"Could not download speaker model {filename}: {error}. "
                f"Download it from {url} and place "
                f"{filename} at {destination} to use it offline."
            ) from error
        return destination

    def _get_extractor(self):
        import sherpa_onnx

        filename = "wespeaker_en_voxceleb_resnet34_LM.onnx"
        model = self._get_model(
            filename,
            "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
            f"speaker-recongition-models/{filename}",
        )
        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(model))
        if not config.validate():
            raise RuntimeError(f"Invalid speaker model in {self.models_dir}")
        return sherpa_onnx.SpeakerEmbeddingExtractor(config)

    def _extract_speech_chunks(self, audio_path: Path | str):
        """Return 1.5s speech intervals with up to 3s of context for each voice vector.

        Silence detection alone cannot find a speaker handover in continuous
        speech, so even long VAD regions must be subdivided.
        """
        from faster_whisper.audio import decode_audio
        from faster_whisper.vad import get_speech_timestamps
        from tscribe.transcriber import ensure_av_compatibility

        ensure_av_compatibility()
        samples = decode_audio(str(audio_path), sampling_rate=16000)
        if not len(samples) or not np.any(samples):
            return []
        chunks = []
        for region in get_speech_timestamps(samples, sampling_rate=16000):
            start, end = region["start"], region["end"]
            for position in range(start, end, 24000):
                boundary = min(position + 24000, end)
                context_start = max(start, position - 12000)
                context_end = min(end, boundary + 12000)
                # Include short tails using the surrounding speech as context.
                if context_end - context_start < 8000:
                    context_start = max(start, context_end - 24000)
                if context_end - context_start >= 8000:
                    chunks.append((position / 16000, boundary / 16000,
                                   samples[context_start:context_end]))
        return chunks

    def _cluster_embeddings(self, embeddings, timestamps, num_speakers=None):
        from sklearn.cluster import AgglomerativeClustering, SpectralClustering
        from sklearn.neighbors import kneighbors_graph
        from scipy.sparse.csgraph import laplacian
        from scipy.sparse.linalg import eigsh

        if not len(embeddings):
            return []
        normalized = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)
        count = min(num_speakers, len(embeddings)) if num_speakers is not None else None
        if len(embeddings) == 1 or count == 1:
            labels = np.zeros(len(embeddings), dtype=int)
        elif count == len(embeddings):
            labels = np.arange(len(embeddings))
        elif len(embeddings) <= 10:
            labels = AgglomerativeClustering(
                n_clusters=count, distance_threshold=0.25 if count is None else None,
                metric="cosine", linkage="average",
            ).fit_predict(normalized)
        else:
            # A graph of nearby voice vectors is less sensitive to a noisy short
            # utterance than cutting the most distant pairs in a hierarchy.
            graph = kneighbors_graph(
                normalized, n_neighbors=10, include_self=True, n_jobs=1,
            )
            graph = (graph + graph.T) * 0.5
            if count is None:
                eigenvalues = np.sort(eigsh(
                    laplacian(graph, normed=True), k=min(11, len(embeddings) - 1),
                    which="SM", return_eigenvectors=False,
                    v0=np.linspace(0.1, 1.0, len(embeddings)),
                ))
                count = int(np.argmax(np.diff(eigenvalues))) + 1
            labels = (np.zeros(len(embeddings), dtype=int) if count == 1 else
                      SpectralClustering(
                          n_clusters=count, affinity="precomputed",
                          assign_labels="cluster_qr", random_state=0,
                      ).fit_predict(graph))
        names = {}
        turns = []
        for (start, end), label in zip(timestamps, labels):
            if label not in names:
                names[label] = f"Speaker {len(names) + 1}"
            speaker = names[label]
            if turns and turns[-1].speaker_id == speaker and turns[-1].end == start:
                turns[-1].end = end
            else:
                turns.append(SpeakerTurn(start, end, speaker))
        return turns

    def diarize(self, audio_path: Path | str, num_speakers: int | None = None) -> list[SpeakerTurn]:
        if num_speakers is not None and (type(num_speakers) is not int or num_speakers < 1):
            raise ValueError("Number of speakers must be a positive integer")
        chunks = self._extract_speech_chunks(audio_path)
        if not chunks:
            return []
        extractor = self._get_extractor()
        embeddings, timestamps = [], []
        for start, end, audio in chunks:
            stream = extractor.create_stream()
            stream.accept_waveform(16000, audio)
            stream.input_finished()
            if not extractor.is_ready(stream):
                continue
            embedding = np.asarray(extractor.compute(stream), dtype=np.float32)
            if not np.all(np.isfinite(embedding)) or not np.linalg.norm(embedding):
                raise RuntimeError("Speaker model returned an invalid voice embedding")
            embeddings.append(embedding)
            timestamps.append((start, end))
        return self._cluster_embeddings(np.asarray(embeddings), timestamps, num_speakers)
