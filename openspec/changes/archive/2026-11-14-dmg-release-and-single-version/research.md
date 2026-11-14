# Research & Technical Tradeoffs

## 1. Intent & Ground Truth
- **Problem:**
  1. `make package` and `.github/workflows/release.yml` only produce `.zip` macOS archives (`dist/tscribe-$(VERSION)-macos-$(ARCH).zip`), not `.dmg` disk images for direct macOS drag-to-Applications installation.
  2. Package version is currently duplicated in `pyproject.toml` (`project.version`) and `src/tscribe/__init__.py` (`__version__ = "2.4.1"`), enforced by `tests/test_desktop.py::test_project_and_cli_versions_match` and `.github/workflows/release.yml` (`version` job).
- **Verified Codebase Facts:**
  - `Makefile` (`package` target, lines 76-83) uses `ditto -c -k` to produce `dist/tscribe-$(VERSION)-macos-$(ARCH).zip` and `dist/tscribe-macos-$(ARCH).zip`. `checksums` (line 86) hashes `.whl`, `.tar.gz`, and `.zip`.
  - `.github/workflows/release.yml` already triggers on `push` to `main` and automatically runs the release pipeline when `gh release view v<version>` has no published release (`should_release=true`).
  - `release.yml` `homebrew-tap` job (`Update Homebrew Tap`) consumes `tscribe-${VERSION}-macos-arm64.zip` and `tscribe-${VERSION}-macos-x86_64.zip` and their SHA256s; `.zip` must be retained alongside `.dmg`.
  - `src/tscribe/__init__.py` exports `__version__`, consumed by `src/tscribe/cli.py`, `src/tscribe/desktop.py`, `tests/test_cli.py`, `tests/test_desktop.py`, and `.github/workflows/release.yml`.
  - PyInstaller (`packaging/macos/worker.spec`) bundles `tscribe` metadata or source; `tscribe.desktop` and `tscribe.cli` import `__version__` at runtime.

## 2. Options Explored
- **Option A (Native `hdiutil` DMG + `importlib.metadata` with `pyproject.toml` fallback):**
  - Build `.dmg` in `Makefile` (`make package`) using macOS built-in `hdiutil create` over a staging dir containing `tscribe.app` and an `/Applications` symlink, verified with `hdiutil verify`.
  - Derive `tscribe.__version__` from `importlib.metadata.version("tscribe")` with `tomllib` fallback to `pyproject.toml` when running from an uninstalled source tree.
  - *Pros:* Zero new build dependencies, works offline and in PyInstaller worker if package metadata is copied or `importlib.metadata` resolves, keeps `.zip` intact for Homebrew.
  - *Cons:* Plain Finder layout without custom background art.
- **Option B (Third-party `create-dmg` CLI + `hatch-vcs` / `setuptools-scm`):**
  - Install `create-dmg` via Homebrew in CI and use git-tag-derived versions.
  - *Pros:* Custom DMG window styling; git-tag-driven versioning.
  - *Cons:* Extra CI/Homebrew dependency, breaks `pyproject.toml`-as-source-of-truth requirement, unnecessary complexity.
- **Option C (`python -m build` / `importlib.metadata` only, no `pyproject.toml` fallback):**
  - *Pros:* Minimal code in `__init__.py`.
  - *Cons:* Breaks direct source-tree execution (`PYTHONPATH=src python ...`) if wheel metadata is stale or missing.

## 3. Tradeoff Matrix

| Criteria | Option A (`hdiutil` + `metadata`/fallback) | Option B (`create-dmg` + VCS) | Option C (`metadata` only) |
| :--- | :--- | :--- | :--- |
| **Complexity** | Low | Medium | Low |
| **New Dependencies** | None | `create-dmg`, VCS plugin | None |
| **Performance & Latency** | Fast (~2-5s `hdiutil`) | Slower (Homebrew install) | Fast |
| **Maintenance Burden** | Very low | Medium | Low |
| **Blast Radius** | `Makefile`, `release.yml`, `__init__.py` | CI, build tooling, git workflow | Runtime source-tree imports |

## 4. Recommendation
Adopt **Option A**: use built-in `hdiutil create` in `Makefile` (`make package`) to emit and verify `.dmg` alongside `.zip`, upload `.dmg` in `release.yml`, and derive `tscribe.__version__` from `pyproject.toml` (`importlib.metadata` with `pyproject.toml` fallback) so `pyproject.toml` is the sole version source of truth.

## 5. Breaking Changes & Deprecations
None (no existing `openspec/specs/` entries cover release packaging or versioning).

## Review Gate
- [ ] **Gate 0 Decision**: Human decides Go (name the option) or No-Go before the proposal is drafted.
