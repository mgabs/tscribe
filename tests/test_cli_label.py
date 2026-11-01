import json
from pathlib import Path
from click.testing import CliRunner
from tscribe.cli import main
from tscribe.transcriber import TranscriptResult, TranscriptSegment


def test_cli_label_interactive(tmp_path):
    runner = CliRunner()
    json_path = tmp_path / "test.json"
    txt_path = tmp_path / "test.txt"

    segments = [
        TranscriptSegment(0.0, 2.0, "Hello Alice", speaker="Speaker 1", raw_speaker="Speaker 1"),
        TranscriptSegment(2.5, 4.0, "Hi there", speaker="Speaker 2", raw_speaker="Speaker 2"),
    ]
    res = TranscriptResult("test.wav", "small", "en", segments)
    json_path.write_text(json.dumps(res.to_json()), encoding="utf-8")
    txt_path.write_text(res.to_txt(), encoding="utf-8")

    # Run label without --names and provide input
    result = runner.invoke(main, ["label", str(json_path)], input="Alice\nBob\n")
    assert result.exit_code == 0
    assert "Speaker 1" in result.output
    assert "Speaker 2" in result.output

    updated = json.loads(json_path.read_text(encoding="utf-8"))
    assert updated["segments"][0]["speaker"] == "Alice"
    assert updated["segments"][0]["raw_speaker"] == "Speaker 1"
    assert updated["segments"][1]["speaker"] == "Bob"
    assert updated["segments"][1]["raw_speaker"] == "Speaker 2"


def test_cli_label_non_interactive(tmp_path):
    runner = CliRunner()
    json_path = tmp_path / "test.json"
    txt_path = tmp_path / "test.txt"

    segments = [
        TranscriptSegment(0.0, 2.0, "Hello", speaker="Speaker 1", raw_speaker="Speaker 1"),
        TranscriptSegment(2.5, 4.0, "Hi", speaker="Speaker 2", raw_speaker="Speaker 2"),
    ]
    res = TranscriptResult("test.wav", "small", "en", segments)
    json_path.write_text(json.dumps(res.to_json()), encoding="utf-8")
    txt_path.write_text(res.to_txt(), encoding="utf-8")

    result = runner.invoke(main, ["label", str(json_path), "--names", "Carol,Dan"])
    assert result.exit_code == 0
    updated = json.loads(json_path.read_text(encoding="utf-8"))
    assert updated["segments"][0]["speaker"] == "Carol"
    assert updated["segments"][1]["speaker"] == "Dan"


def test_config_prompt_speaker_labels_default():
    from tscribe.config import TranscriptionDefaults
    td = TranscriptionDefaults()
    assert hasattr(td, "prompt_speaker_labels")
    assert td.prompt_speaker_labels is False
