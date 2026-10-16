.DEFAULT_GOAL := help

UV ?= uv
UV := $(shell command -v "$(UV)")
SWIFT ?= swift
VERSION := $(shell sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
ARCH := $(shell uname -m)
APP := dist/tscribe.app
ARCHIVE := dist/tscribe-$(VERSION)-macos-$(ARCH).zip

.PHONY: help setup lint test test-swift test-menu-bar check cli app package checksums dist install run clean-dist clean

help:
	@printf '%s\n' \
	  'make setup       Install development and app build dependencies' \
	  'make check       Run lint, Python, Swift, and desktop menu bar tests' \
	  'make test-menu-bar  Verify the real icon, menu, and hide/restore behavior' \
	  'make cli         Build the Python wheel and source distribution' \
	  'make app         Build the self-contained macOS app' \
	  'make package     Build and zip the macOS app' \
	  'make dist        Replace dist with the current release and checksums' \
	  'make install     Build and install the app in ~/Applications' \
	  'make run         Open the installed app or local build' \
	  'make clean-dist  Remove generated distribution files' \
	  'make clean       Remove generated distributions, builds, and test caches'

setup:
	$(UV) sync --group dev --group mac-app

lint:
	$(UV) run --locked --group dev ruff check src tests packaging/macos

test:
	$(UV) run --locked --group dev pytest

test-swift:
	TSCRIBE_PYTHON_EXECUTABLE="$(CURDIR)/.venv/bin/python" \
	TSCRIBE_CONFIG_FILE="$(CURDIR)/build/test-state/config.toml" \
	TSCRIBE_DATA_DIR="$(CURDIR)/build/test-state/data" \
	TSCRIBE_LOG_DIR="$(CURDIR)/build/test-state/logs" \
	$(UV) run --locked --group dev $(SWIFT) test --disable-sandbox --package-path macos --scratch-path build/swift

check: lint test test-swift
	$(MAKE) test-menu-bar

test-menu-bar:
	$(UV) run --locked --group dev python packaging/macos/test_menu_bar.py

# Hold one lock for the entire requested operation, including recursive Make.
ifndef TSCRIBE_BUILD_LOCK_HELD
cli app package checksums dist install clean-dist clean:
	$(UV) run --locked python packaging/macos/build_lock.py $(MAKE) UV="$(UV)" $@
else
cli:
	$(UV) build

app:
	$(UV) run --locked --group mac-app python packaging/macos/build_native.py

package: app
	@set -eu; \
	archive_stage=$$(mktemp -d build/tscribe-package.XXXXXX); \
	trap 'rm -rf "$$archive_stage"' EXIT; \
	ditto -c -k --sequesterRsrc --keepParent "$(APP)" "$$archive_stage/release.zip"; \
	unzip -tq "$$archive_stage/release.zip"; \
	mv "$$archive_stage/release.zip" "$(ARCHIVE)"

checksums:
	cd dist && shasum -a 256 ./*.whl ./*.tar.gz ./*.zip > SHA256SUMS

# Keep cleanup and builds sequential, including when invoked with make -j.
dist:
	$(MAKE) clean-dist
	$(MAKE) cli
	$(MAKE) package
	$(MAKE) checksums

install: app
	$(UV) run --locked tscribe app --install-desktop

clean-dist:
	rm -rf -- dist

clean:
	rm -rf -- dist build macos/.build macos/.swiftpm .pytest_cache .ruff_cache
endif

run:
	$(UV) run --locked tscribe app
