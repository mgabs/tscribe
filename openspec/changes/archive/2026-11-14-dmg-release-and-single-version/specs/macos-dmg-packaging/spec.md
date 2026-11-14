# Spec Delta: macOS DMG Packaging

## Purpose
Build, verify, checksum, and publish macOS `.dmg` disk images alongside existing `.zip` archives for every `tscribe` release.

## ADDED Requirements

### Requirement: REQ-DMG-1 Build and Verify DMG Alongside ZIP
`make package` MUST produce both `dist/tscribe-$(VERSION)-macos-$(ARCH).zip` (and `dist/tscribe-macos-$(ARCH).zip`) and `dist/tscribe-$(VERSION)-macos-$(ARCH).dmg` (and `dist/tscribe-macos-$(ARCH).dmg`) on macOS, where the `.dmg` contains `tscribe.app` and an `Applications` symlink and passes `hdiutil verify`.

#### Scenario: Local or CI macOS packaging produces verified ZIP and DMG
- **GIVEN** `dist/tscribe.app` has been built for `<ARCH>` and `pyproject.toml` defines `<VERSION>`
- **WHEN** `make package` runs on macOS
- **THEN** `dist/tscribe-<VERSION>-macos-<ARCH>.zip`, `dist/tscribe-macos-<ARCH>.zip`, `dist/tscribe-<VERSION>-macos-<ARCH>.dmg`, and `dist/tscribe-macos-<ARCH>.dmg` exist
- **AND** `unzip -tq` succeeds on the `.zip` and `hdiutil verify` succeeds on the `.dmg`

#### Scenario: Clean staging directory on failure
- **GIVEN** `make package` creates a temporary staging directory under `build/`
- **WHEN** `hdiutil create` or `hdiutil verify` fails
- **THEN** the staging directory is removed and the command exits non-zero without leaving a partial `.dmg` in `dist/`

### Requirement: REQ-DMG-2 Checksums and Release Asset Publishing
`make checksums` and the `Release` workflow (`publish` job) MUST include `./*.dmg` in `SHA256SUMS` and upload both `.zip` and `.dmg` macOS assets for `arm64` and `x86_64`, while `Update Homebrew Tap` continues to use the `.zip` SHA256s and URLs.

#### Scenario: Release workflow publishes DMG and ZIP assets
- **GIVEN** `Release` runs on `main` for an unpublished version `<VERSION>`
- **WHEN** `macos` (`arm64` and `x86_64`) and `publish` complete
- **THEN** the GitHub release for `v<VERSION>` contains `.whl`, `.tar.gz`, `tscribe-<VERSION>-macos-arm64.zip`, `tscribe-<VERSION>-macos-x86_64.zip`, `tscribe-<VERSION>-macos-arm64.dmg`, `tscribe-<VERSION>-macos-x86_64.dmg`, and `SHA256SUMS` covering all uploaded archives
- **AND** `Update Homebrew Tap` updates `Casks/tscribe.rb` using the `.zip` SHA256s

### Requirement: NFR-DMG-1 Zero External Packaging Dependencies
DMG creation MUST use macOS built-in `hdiutil` without requiring Homebrew or third-party DMG tools on CI runners or developer machines.

#### Scenario: DMG builds with stock macOS tools
- **GIVEN** a stock `macos-15` or `macos-15-intel` runner without `create-dmg` installed
- **WHEN** `make package` runs
- **THEN** the `.dmg` is created and verified using only `hdiutil` and POSIX shell utilities

