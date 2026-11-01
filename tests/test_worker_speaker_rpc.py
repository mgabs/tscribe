import json
import time
from pathlib import Path
from tscribe.worker import Worker
from tscribe.transcriber import TranscriptResult, TranscriptSegment


def call(worker, command, **values):
    return worker.handle({"id": "request", "command": command, **values})


def test_worker_get_speakers_and_set_speakers(tmp_path):
    worker = Worker(lambda _: None)
    call(worker, "save-config", changes={"storage.data_dir": str(tmp_path / "audio")})
    prepared = call(worker, "prepare-recording")
    stem = prepared["stem"]
    path = Path(prepared["wav_path"])
    path.write_bytes(b"dummy")

    # Write initial transcript JSON with 2 speakers
    segments = [
        TranscriptSegment(0.0, 2.0, "Hello Alice", speaker="Speaker 1", raw_speaker="Speaker 1"),
        TranscriptSegment(2.5, 4.0, "Hi there", speaker="Speaker 2", raw_speaker="Speaker 2"),
        TranscriptSegment(4.5, 6.0, "How are you", speaker="Speaker 1", raw_speaker="Speaker 1"),
    ]
    initial_result = TranscriptResult(path.name, "small", "en", segments)
    path.with_suffix(".json").write_text(json.dumps(initial_result.to_json()), encoding="utf-8")
    path.with_suffix(".txt").write_text(initial_result.to_txt(), encoding="utf-8")
    path.with_suffix(".srt").write_text(initial_result.to_srt(), encoding="utf-8")

    # 1. Test get-speakers (REQ-SPK-3, REQ-SPK-7)
    res = call(worker, "get-speakers", stem=stem)
    assert "speakers" in res
    assert len(res["speakers"]) == 2
    assert res["speakers"][0]["raw_speaker"] == "Speaker 1"
    assert res["speakers"][0]["sample_text"] == "Hello Alice"
    assert res["speakers"][1]["raw_speaker"] == "Speaker 2"
    assert res["speakers"][1]["sample_text"] == "Hi there"

    # 2. Test set-speakers and latency (REQ-SPK-4, REQ-SPK-7)
    t0 = time.perf_counter()
    res_set = call(
        worker,
        "set-speakers",
        stem=stem,
        mapping={"Speaker 1": "Alice", "Speaker 2": "Bob"},
    )
    duration = time.perf_counter() - t0
    assert duration < 0.100  # NFR-SPK-1: < 100ms
    assert res_set["status"] == "ok"
    assert "[Alice]:\nHello Alice" in res_set["text"]
    assert "[Bob]:\nHi there" in res_set["text"]

    # Verify JSON file on disk
    updated_data = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert updated_data["segments"][0]["speaker"] == "Alice"
    assert updated_data["segments"][0]["raw_speaker"] == "Speaker 1"
    assert updated_data["segments"][1]["speaker"] == "Bob"
    assert updated_data["segments"][1]["raw_speaker"] == "Speaker 2"

    # Verify TXT and SRT files
    txt_content = path.with_suffix(".txt").read_text(encoding="utf-8")
    assert "[Alice]:" in txt_content
    srt_content = path.with_suffix(".srt").read_text(encoding="utf-8")
    assert "[Alice]" in srt_content

    # Verify metadata.json contains speaker_map
    _, manager = worker.configuration()
    meta = manager.read_metadata(stem)
    assert meta is not None
    assert meta.get("speaker_map") == {"Speaker 1": "Alice", "Speaker 2": "Bob"}
