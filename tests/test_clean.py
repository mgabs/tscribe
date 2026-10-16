from datetime import datetime, timedelta
from click.testing import CliRunner
from tscribe.cli import main
from tscribe.session import SessionManager


def test_session_manager_delete_session(tmp_path):
    mgr = SessionManager(tmp_path)
    stem = "2026-10-15-120000"
    wav = tmp_path / f"{stem}.wav"
    txt = tmp_path / f"{stem}.txt"
    json_f = tmp_path / f"{stem}.json"
    meta = tmp_path / f"{stem}.meta"

    for f in (wav, txt, json_f, meta):
        f.write_text("test")

    deleted_files, bytes_freed = mgr.delete_session(stem)
    assert len(deleted_files) == 4
    assert bytes_freed > 0
    assert not wav.exists()
    assert not txt.exists()
    assert not json_f.exists()
    assert not meta.exists()


def test_session_manager_clean_sessions_by_age(tmp_path):
    mgr = SessionManager(tmp_path)

    # Old session: 40 days ago
    old_date = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d-%H%M%S")
    (tmp_path / f"{old_date}.wav").write_bytes(b"old" * 100)

    # Recent session: 5 days ago
    recent_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d-%H%M%S")
    (tmp_path / f"{recent_date}.wav").write_bytes(b"new" * 100)

    # Clean older than 30 days
    cleaned = mgr.clean_sessions(older_than_days=30, dry_run=False)
    assert len(cleaned) == 1
    assert cleaned[0][0] == old_date
    assert not (tmp_path / f"{old_date}.wav").exists()
    assert (tmp_path / f"{recent_date}.wav").exists()


def test_session_manager_clean_all(tmp_path):
    mgr = SessionManager(tmp_path)
    s1 = "2026-10-01-100000"
    s2 = "2026-10-10-100000"
    (tmp_path / f"{s1}.wav").write_bytes(b"data1")
    (tmp_path / f"{s2}.wav").write_bytes(b"data2")

    cleaned = mgr.clean_sessions(older_than_days=None, dry_run=False)
    assert len(cleaned) == 2
    assert not (tmp_path / f"{s1}.wav").exists()
    assert not (tmp_path / f"{s2}.wav").exists()


def test_cli_clean_all_prompt_aborted(tmp_path):
    runner = CliRunner()
    s = "2026-10-01-100000"
    (tmp_path / f"{s}.wav").write_bytes(b"data")

    res = runner.invoke(main, ["clean", "--dir", str(tmp_path)], input="n\n")
    assert res.exit_code == 0
    assert "Aborted" in res.output or "aborted" in res.output.lower()
    assert (tmp_path / f"{s}.wav").exists()


def test_cli_clean_all_with_yes(tmp_path):
    runner = CliRunner()
    s = "2026-10-01-100000"
    (tmp_path / f"{s}.wav").write_bytes(b"data")

    res = runner.invoke(main, ["clean", "--dir", str(tmp_path), "-y"])
    assert res.exit_code == 0
    assert "Deleted 1 session" in res.output
    assert not (tmp_path / f"{s}.wav").exists()


def test_cli_clean_with_days_flag(tmp_path):
    runner = CliRunner()
    old_stem = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d-%H%M%S")
    recent_stem = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d-%H%M%S")
    (tmp_path / f"{old_stem}.wav").write_bytes(b"old")
    (tmp_path / f"{recent_stem}.wav").write_bytes(b"new")

    res = runner.invoke(main, ["clean", "--dir", str(tmp_path), "--days", "30", "-y"])
    assert res.exit_code == 0
    assert "Deleted 1 session" in res.output
    assert not (tmp_path / f"{old_stem}.wav").exists()
    assert (tmp_path / f"{recent_stem}.wav").exists()


def test_cli_clean_with_30_shortcut_flag(tmp_path):
    runner = CliRunner()
    old_stem = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d-%H%M%S")
    recent_stem = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d-%H%M%S")
    (tmp_path / f"{old_stem}.wav").write_bytes(b"old")
    (tmp_path / f"{recent_stem}.wav").write_bytes(b"new")

    res = runner.invoke(main, ["clean", "--dir", str(tmp_path), "--30", "-y"])
    assert res.exit_code == 0
    assert "Deleted 1 session" in res.output
    assert not (tmp_path / f"{old_stem}.wav").exists()
    assert (tmp_path / f"{recent_stem}.wav").exists()


def test_clean_respects_time_of_day_at_cutoff(tmp_path):
    from unittest.mock import patch
    mgr = SessionManager(tmp_path)
    old = tmp_path / '2026-09-15-110000.wav'
    recent = tmp_path / '2026-09-15-130000.wav'
    old.write_bytes(b'old')
    recent.write_bytes(b'recent')
    with patch('tscribe.session.datetime', wraps=datetime) as clock:
        clock.now.return_value = datetime(2026, 10, 15, 12, 0, 0)
        cleaned = mgr.clean_sessions(older_than_days=30)
    assert [item[0] for item in cleaned] == [old.stem]
    assert recent.exists()


def test_delete_session_treats_filename_as_literal(tmp_path):
    mgr = SessionManager(tmp_path)
    wav = tmp_path / 'meeting[1].wav'
    txt = tmp_path / 'meeting[1].txt'
    other = tmp_path / 'meeting1.wav'
    for path in (wav, txt, other):
        path.write_bytes(b'data')
    deleted, _ = mgr.delete_session('meeting[1]')
    assert set(deleted) == {wav, txt}
    assert other.exists()


def test_delete_session_preserves_other_dotted_sessions(tmp_path):
    mgr = SessionManager(tmp_path)
    first = tmp_path / 'meeting.wav'
    second = tmp_path / 'meeting.v2.wav'
    first.write_bytes(b'one')
    second.write_bytes(b'two')
    mgr.delete_session(first.stem)
    assert not first.exists()
    assert second.exists()
