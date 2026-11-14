"""tscribe — Cross-platform audio recorder and transcriber."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import tomllib


def _resolve_version() -> str:
    """Return the package version from installed metadata or pyproject.toml."""
    try:
        return version("tscribe")
    except PackageNotFoundError:
        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        return tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]


__version__ = _resolve_version()
