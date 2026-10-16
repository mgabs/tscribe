import json
from unittest.mock import MagicMock, patch
from click.testing import CliRunner
from tscribe.cli import main
from tscribe.transcriber import TranscriptResult, TranscriptSegment


def test_cli_label_command(tmp_path):
    runner = CliRunner()
    # Create fake session json
    session_json = tmp_path / "test.json"
    session_json.write_text(
        json.dumps({
            "file": "test.wav",
            "model": "small",
            "language": "en",
            "segments": [
                {"start": 0.0, "end": 2.0, "text": "Hi", "speaker": "Speaker 1"},
                {"start": 2.5, "end": 4.0, "text": "Hey", "speaker": "Speaker 2"},
            ],
        })
    )

    res = runner.invoke(main, ["label", str(session_json), "--names", "Alice,Bob"])
    assert res.exit_code == 0
    updated = json.loads(session_json.read_text())
    assert updated["segments"][0]["speaker"] == "Alice"
    assert updated["segments"][1]["speaker"] == "Bob"


def test_cli_label_with_associated_files(tmp_path):
    runner = CliRunner()
    session_json = tmp_path / "test.json"
    session_txt = tmp_path / "test.txt"
    session_srt = tmp_path / "test.srt"
    session_vtt = tmp_path / "test.vtt"

    session_json.write_text(
        json.dumps({
            "file": "test.wav",
            "model": "small",
            "language": "en",
            "segments": [
                {"start": 0.0, "end": 2.0, "text": "Hi", "speaker": "Speaker 1"},
                {"start": 2.5, "end": 4.0, "text": "Hey", "speaker": "Speaker 2"},
            ],
        })
    )
    session_txt.write_text("[Speaker 1]:\nHi\n\n[Speaker 2]:\nHey")
    session_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n[Speaker 1] Hi\n")
    session_vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n<v Speaker 1>Hi</v>\n")

    res = runner.invoke(main, ["label", str(session_json), "--names", "Alice,Bob"])
    assert res.exit_code == 0
    assert "test.json" in res.output
    assert "test.txt" in res.output

    txt_content = session_txt.read_text()
    assert "[Alice]:" in txt_content
    assert "[Bob]:" in txt_content

    srt_content = session_srt.read_text()
    assert "[Alice] Hi" in srt_content

    vtt_content = session_vtt.read_text()
    assert "<v Alice>Hi</v>" in vtt_content


def test_cli_label_with_session_ref(monkeypatch, tmp_path):
    monkeypatch.setenv("TSCRIBE_DATA_DIR", str(tmp_path))
    rec_dir = tmp_path / "recordings"
    rec_dir.mkdir(parents=True)

    stem = "2026-10-15-120000"
    (rec_dir / f"{stem}.wav").touch()
    (rec_dir / f"{stem}.meta").write_text(
        json.dumps({
            "created": "2026-10-15T12:00:00Z",
            "duration_seconds": 5.0,
            "sample_rate": 16000,
            "channels": 1,
            "device": "mic",
            "source_type": "mic",
            "transcribed": True,
        })
    )
    (rec_dir / f"{stem}.json").write_text(
        json.dumps({
            "file": f"{stem}.wav",
            "model": "small",
            "language": "en",
            "segments": [
                {"start": 0.0, "end": 2.0, "text": "Hi", "speaker": "Speaker 1"},
            ],
        })
    )

    runner = CliRunner()
    res = runner.invoke(main, ["label", "HEAD", "--names", "Alice"])
    assert res.exit_code == 0
    updated = json.loads((rec_dir / f"{stem}.json").read_text())
    assert updated["segments"][0]["speaker"] == "Alice"


def test_cli_transcribe_diarize_flags(monkeypatch, tmp_path):
    monkeypatch.setenv("TSCRIBE_DATA_DIR", str(tmp_path))
    audio_file = tmp_path / "test.wav"
    audio_file.touch()

    runner = CliRunner()
    mock_transcriber = MagicMock()
    mock_transcriber.transcribe.return_value = TranscriptResult(
        file="test.wav",
        model="base",
        language="en",
        segments=[
            TranscriptSegment(start=0.0, end=1.0, text="Hello", speaker="Alice")
        ],
    )

    with patch("tscribe.transcriber.Transcriber", return_value=mock_transcriber):
        res = runner.invoke(
            main,
            [
                "transcribe",
                str(audio_file),
                "--diarize",
                "--speakers",
                "2",
                "--names",
                "Alice,Bob",
            ],
        )
        assert res.exit_code == 0
        mock_transcriber.transcribe.assert_called_once()
        _, kwargs = mock_transcriber.transcribe.call_args
        assert kwargs["diarize"] is True
        assert kwargs["num_speakers"] == 2
        assert kwargs["names"] == "Alice,Bob"


def test_cli_record_diarize_flags(monkeypatch, tmp_path):
    monkeypatch.setenv("TSCRIBE_DATA_DIR", str(tmp_path))
    runner = CliRunner()

    from tscribe.recorder.base import RecordingResult

    mock_recorder = MagicMock()
    mock_recorder.elapsed_seconds = 1.0
    mock_recorder.level = 0.5
    mock_recorder.stop.return_value = RecordingResult(
        path=tmp_path / "rec.wav",
        duration_seconds=1.0,
        sample_rate=16000,
        channels=1,
        device_name="mic",
        source_type="microphone",
    )

    import threading
    import time
    import signal

    def fake_create(cfg):
        def trigger_stop():
            time.sleep(0.1)
            signal.raise_signal(signal.SIGINT)

        threading.Thread(target=trigger_stop, daemon=True).start()
        return mock_recorder

    monkeypatch.setattr("tscribe.cli._create_recorder", fake_create)

    with patch("tscribe.cli._auto_transcribe") as mock_auto:
        res = runner.invoke(
            main,
            [
                "record",
                "--mic",
                "--diarize",
                "--speakers",
                "2",
                "--names",
                "Alice,Bob",
            ],
        )
        assert res.exit_code == 0
        mock_auto.assert_called_once()
        _, kwargs = mock_auto.call_args
        assert kwargs["diarize"] is True
        assert kwargs["num_speakers"] == 2
        assert kwargs["names"] == "Alice,Bob"


def test_cli_config_diarize(monkeypatch, tmp_path):
    monkeypatch.setenv("TSCRIBE_DATA_DIR", str(tmp_path))
    runner = CliRunner()

    # Get default diarize config
    res = runner.invoke(main, ["config", "transcription.diarize"])
    assert res.exit_code == 0
    assert "False" in res.output

    # Set diarize config to true
    res = runner.invoke(main, ["config", "transcription.diarize", "true"])
    assert res.exit_code == 0
    assert "True" in res.output

    # Verify get returns True
    res = runner.invoke(main, ["config", "transcription.diarize"])
    assert res.exit_code == 0
    assert "True" in res.output
