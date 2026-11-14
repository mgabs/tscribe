# Proposal

## Intent
Add macOS `.dmg` disk image generation alongside the existing `.zip` release archives, and make `pyproject.toml` the single source of truth for the `tscribe` package version so bumping `pyproject.toml` and merging/pushing to `main` automatically drives the full release pipeline.

## Problem Statement
1. Releases to `main` currently publish only `.zip` archives for macOS (`tscribe-<version>-macos-<arch>.zip`), requiring manual extraction instead of a standard drag-to-Applications `.dmg` installer.
2. The version string is duplicated in `pyproject.toml` and `src/tscribe/__init__.py` (`__version__`), forcing two-file edits on every release and risking version-mismatch failures in CI/release checks.

## Capabilities

### New Capabilities
- `macos-dmg-packaging`: Build, verify, checksum, and publish `tscribe-<version>-macos-<arch>.dmg` alongside `.zip` during `make package` and GitHub Actions `Release` runs.
- `single-source-versioning`: Resolve `tscribe.__version__` from `pyproject.toml` / installed package metadata so `pyproject.toml` is the sole version definition, and trigger releases on `main` whenever `pyproject.toml` introduces an unpublished version.

### Modified Capabilities
- None.

## Scope

### In-Scope
- `Makefile`: update `package` to build and `hdiutil verify` `dist/tscribe-$(VERSION)-macos-$(ARCH).dmg` (and `dist/tscribe-macos-$(ARCH).dmg`) alongside `.zip`; update `checksums` to include `./*.dmg`.
- `.github/workflows/release.yml`: verify and upload `.dmg` artifacts from `macos` job, include `./*.dmg` in `SHA256SUMS` and `gh release upload`, and read `pyproject.toml` as the sole version source in the `version` job.
- `src/tscribe/__init__.py` (and `packaging/macos/worker.spec` if needed for PyInstaller metadata): resolve `__version__` dynamically from package metadata / `pyproject.toml` instead of hardcoding a literal string.
- Tests covering single-source `__version__` resolution.

### Out-of-Scope (YAGNI)
- Removing `.zip` archives or changing `Update Homebrew Tap` from `.zip` to `.dmg`.
- Apple Developer ID notarization, DMG background artwork, or custom Finder `.DS_Store` layout.
- Auto-bumping `pyproject.toml` via CI commits or changing `ci.yml` / `release.yml` non-release triggers.

## Assumptions
- **ASM-GEN-1**: macOS runners (`macos-15`, `macos-15-intel`) provide `hdiutil` in standard PATH.
- **ASM-GEN-2**: `tscribe` is installed in the active environment (or `pyproject.toml` is present at repo root) when `__version__` is imported, and PyInstaller bundles `tscribe` distribution metadata.

## Success Metrics
- `make package` on macOS produces both verified `.zip` and verified `.dmg` files in `dist/`.
- `Release` workflow on `main` publishes `.whl`, `.tar.gz`, `.zip`, `.dmg`, and `SHA256SUMS` for both `arm64` and `x86_64` when `pyproject.toml` `project.version` is bumped and has no published GitHub release.
- Only `pyproject.toml` needs to be edited to bump the version across CLI, native app bundle, tests, and release workflow.

## Review Gate
- [ ] **Gate 1 Approval**: Proposal reviewed and approved by human before drafting specs.
