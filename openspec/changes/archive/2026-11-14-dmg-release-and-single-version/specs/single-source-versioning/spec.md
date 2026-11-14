# Spec Delta: Single-Source Versioning

## Purpose
Establish `pyproject.toml` (`project.version`) as the single source of truth for `tscribe` version resolution and automatic release triggering on `main`.

## ADDED Requirements

### Requirement: REQ-VER-1 Single Version Source in pyproject.toml
`tscribe.__version__` MUST NOT hardcode a version literal; it MUST resolve dynamically from installed package metadata (`importlib.metadata.version("tscribe")`) with a fallback to reading `project.version` from `pyproject.toml` when running from an uninstalled source tree.

#### Scenario: Installed package resolves version from metadata
- **GIVEN** `tscribe` is installed in the Python environment with version `<VERSION>` from `pyproject.toml`
- **WHEN** `from tscribe import __version__` is executed
- **THEN** `__version__` equals `<VERSION>`

#### Scenario: Uninstalled source tree falls back to pyproject.toml
- **GIVEN** `importlib.metadata.version("tscribe")` raises `PackageNotFoundError` and `pyproject.toml` is present at the repository root
- **WHEN** `from tscribe import __version__` is executed
- **THEN** `__version__` equals `project.version` from `pyproject.toml`

#### Scenario: Packaged PyInstaller worker reports matching version
- **GIVEN** `make package` builds `dist/tscribe.app` with `tscribe` distribution metadata included
- **WHEN** `tscribe-worker --cli --version` is executed
- **THEN** it outputs `tscribe, version <VERSION>` matching `pyproject.toml`

### Requirement: REQ-VER-2 Release Workflow Uses pyproject.toml Exclusively
The `Release` workflow `version` job MUST read `project.version` from `pyproject.toml`, validate `X.Y.Z` format, and set `should_release=true` whenever `v<version>` is not already a published GitHub release on `main`, without comparing against a hardcoded string in `src/tscribe/__init__.py`.

#### Scenario: Version bump in pyproject.toml triggers release on push to main
- **GIVEN** `pyproject.toml` `project.version` is updated to an unpublished `X.Y.Z` version and pushed/merged to `main`
- **WHEN** the `Release` workflow runs its `version` job
- **THEN** `should_release` is `true` and downstream `checks`, `cli`, `macos`, `publish`, and `homebrew-tap` jobs execute

#### Scenario: Non-version push to main skips release
- **GIVEN** `pyproject.toml` `project.version` already has a published GitHub release `v<version>`
- **WHEN** a commit is pushed to `main` without changing `project.version`
- **THEN** `should_release` is `false` and downstream release jobs are skipped

### Requirement: NFR-VER-1 Zero Startup Latency Regression
Resolving `tscribe.__version__` MUST NOT spawn subprocesses or perform network calls.

#### Scenario: In-process version resolution
- **GIVEN** `tscribe` is imported in Python
- **WHEN** `__version__` is evaluated
- **THEN** it completes purely in-process using `importlib.metadata` or local file read of `pyproject.toml`
