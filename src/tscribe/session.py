"""Session management — file naming, metadata, listing, and search."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tscribe.recorder.base import RecordingResult


@dataclass
class SessionInfo:
    """Represents a recording session with all its associated files."""
    stem: str
    wav_path: Path
    txt_path: Optional[Path]
    json_path: Optional[Path]
    meta_path: Optional[Path]
    metadata: Optional[dict]
    duration_seconds: Optional[float]
    transcribed: bool


class SessionManager:
    def __init__(self, recordings_dir: Path):
        self.recordings_dir = recordings_dir
        self.recordings_dir.mkdir(parents=True, exist_ok=True)

    def generate_session_stem(self) -> str:
        """Include microseconds so rapid CLI/app recordings do not share a name."""
        return datetime.now().strftime("%Y-%m-%d-%H%M%S-%f")

    def create_metadata(self, result: RecordingResult, **extra) -> dict:
        """Build metadata dict from a recording result."""
        meta = {
            "created": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": result.duration_seconds,
            "sample_rate": result.sample_rate,
            "channels": result.channels,
            "device": result.device_name,
            "source_type": result.source_type,
            "transcribed": False,
            "model": None,
            "original_path": None,
        }
        meta.update(extra)
        return meta

    def write_metadata(self, stem: str, metadata: dict) -> Path:
        """Write .meta JSON file."""
        meta_path = self.recordings_dir / f"{stem}.meta"
        meta_path.write_text(json.dumps(metadata, indent=2))
        return meta_path

    def read_metadata(self, stem: str) -> Optional[dict]:
        """Read .meta JSON file, return None if missing."""
        meta_path = self.recordings_dir / f"{stem}.meta"
        if not meta_path.exists():
            return None
        return json.loads(meta_path.read_text())

    def update_metadata(self, stem: str, **updates) -> None:
        """Update fields in an existing metadata file."""
        meta = self.read_metadata(stem) or {}
        meta.update(updates)
        self.write_metadata(stem, meta)

    def list_sessions(
        self,
        limit: Optional[int] = 20,
        sort_by: str = "date",
        search: Optional[str] = None,
    ) -> list[SessionInfo]:
        """List recording sessions, optionally filtered by transcript text search."""
        sessions = []

        for wav_path in self.recordings_dir.glob("*.wav"):
            stem = wav_path.stem
            info = self._build_session_info(stem, wav_path)

            if search:
                if not self._matches_search(info, search):
                    continue

            sessions.append(info)

        sessions.sort(key=lambda s: self._sort_key(s, sort_by), reverse=(sort_by == "date"))
        return sessions[:limit] if limit else sessions

    def get_session(self, stem: str) -> Optional[SessionInfo]:
        """Load a single session by its stem name."""
        wav_path = self.recordings_dir / f"{stem}.wav"
        if not wav_path.exists():
            return None
        return self._build_session_info(stem, wav_path)

    def import_external(self, source_path: Path) -> tuple[str, Path]:
        """Copy an external audio file into the recordings directory.

        Returns (stem, destination_path).
        """
        stem = self.generate_session_stem()
        dest = self.recordings_dir / f"{stem}.wav"
        shutil.copy2(source_path, dest)
        return stem, dest

    def _build_session_info(self, stem: str, wav_path: Path) -> SessionInfo:
        txt_path = self.recordings_dir / f"{stem}.txt"
        json_path = self.recordings_dir / f"{stem}.json"
        meta_path = self.recordings_dir / f"{stem}.meta"

        metadata = None
        if meta_path.exists():
            try:
                metadata = json.loads(meta_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass

        duration = metadata.get("duration_seconds") if metadata else None
        transcribed = txt_path.exists() or (metadata.get("transcribed", False) if metadata else False)

        return SessionInfo(
            stem=stem,
            wav_path=wav_path,
            txt_path=txt_path if txt_path.exists() else None,
            json_path=json_path if json_path.exists() else None,
            meta_path=meta_path if meta_path.exists() else None,
            metadata=metadata,
            duration_seconds=duration,
            transcribed=transcribed,
        )

    def _matches_search(self, info: SessionInfo, query: str) -> bool:
        """Check if a session's transcript contains the search query."""
        query_lower = query.lower()
        if info.txt_path and info.txt_path.exists():
            try:
                text = info.txt_path.read_text()
                if query_lower in text.lower():
                    return True
            except OSError:
                pass
        return False

    def search_transcripts(
        self,
        query: str,
        limit: int = 20,
        sort_by: str = "date",
    ) -> list[tuple[SessionInfo, list[str]]]:
        """Search transcript text and return matching sessions with context lines."""
        query_lower = query.lower()
        results = []

        for wav_path in self.recordings_dir.glob("*.wav"):
            stem = wav_path.stem
            info = self._build_session_info(stem, wav_path)
            if not info.txt_path or not info.txt_path.exists():
                continue
            try:
                text = info.txt_path.read_text()
            except OSError:
                continue
            matching_lines = [
                line.strip()
                for line in text.splitlines()
                if query_lower in line.lower()
            ]
            if matching_lines:
                results.append((info, matching_lines))

        results.sort(
            key=lambda r: self._sort_key(r[0], sort_by),
            reverse=(sort_by == "date"),
        )
        return results[:limit]

    def _sort_key(self, session: SessionInfo, sort_by: str):
        if sort_by == "date":
            return session.stem
        if sort_by == "duration":
            return session.duration_seconds or 0.0
        if sort_by == "name":
            return session.stem
        return session.stem

    def delete_session(self, stem: str) -> tuple[list[Path], int]:
        """Delete all files associated with a session stem.

        Returns (list_of_deleted_files, total_bytes_freed).
        """
        deleted: list[Path] = []
        bytes_freed = 0
        for f in self.recordings_dir.glob(f"{stem}.*"):
            if f.is_file():
                try:
                    size = f.stat().st_size
                    f.unlink()
                    deleted.append(f)
                    bytes_freed += size
                except OSError:
                    pass
        return deleted, bytes_freed

    def clean_sessions(
        self,
        older_than_days: Optional[int] = None,
        dry_run: bool = False,
    ) -> list[tuple[str, list[Path], int]]:
        """Clean recording sessions.

        If older_than_days is provided, only deletes sessions older than that many days.
        Returns list of (stem, deleted_files, bytes_freed).
        """
        from datetime import timedelta

        cutoff_date = None
        if older_than_days is not None:
            cutoff_date = datetime.now() - timedelta(days=older_than_days)

        results: list[tuple[str, list[Path], int]] = []

        for wav_path in sorted(self.recordings_dir.glob("*.wav")):
            stem = wav_path.stem
            session_date = None

            try:
                session_date = datetime.strptime(stem[:10], "%Y-%m-%d")
            except (ValueError, IndexError):
                pass

            if session_date is None:
                try:
                    mtime = wav_path.stat().st_mtime
                    session_date = datetime.fromtimestamp(mtime)
                except OSError:
                    continue

            if cutoff_date is not None and session_date > cutoff_date:
                continue

            session_files = [f for f in self.recordings_dir.glob(f"{stem}.*") if f.is_file()]
            total_size = sum(f.stat().st_size for f in session_files if f.exists())

            if dry_run:
                results.append((stem, session_files, total_size))
            else:
                deleted, freed = self.delete_session(stem)
                results.append((stem, deleted, freed))

        return results
