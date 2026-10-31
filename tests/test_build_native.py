"""Packaging failures preserve the complete app; concurrent builds cannot race."""

import importlib.util
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BUILD_SCRIPTS = Path(__file__).resolve().parents[1] / 'packaging/macos'


@pytest.fixture
def native_build(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(BUILD_SCRIPTS))
    spec = importlib.util.spec_from_file_location('native_build_test', BUILD_SCRIPTS / 'build_native.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.setattr(module.sys, 'platform', 'darwin')
    executable = tmp_path / 'build/swift/release/tscribe-native'
    executable.parent.mkdir(parents=True)
    executable.write_text('new executable')
    worker = tmp_path / 'build/worker-dist/tscribe-worker'
    worker.mkdir(parents=True)
    (worker / 'tscribe-worker').write_text('new worker')
    nemotron = worker / '_internal/nemotron'
    (nemotron / 'bin').mkdir(parents=True)
    (nemotron / 'bin/nemo-speech').write_text('runtime')
    (nemotron / 'lib').mkdir()
    (nemotron / 'lib/libggml.0.dylib').write_text('library')
    resources = tmp_path / 'resources'
    resources.mkdir()
    (resources / 'AppIcon.icns').write_bytes(b'icon')
    monkeypatch.setattr('tscribe.desktop.RESOURCE_DIR', resources)
    destination = tmp_path / 'dist/tscribe.app'
    destination.mkdir(parents=True)
    (destination / 'previous').write_text('last complete build')
    return module, destination


def fake_run(*arguments):
    if arguments[0] == 'ditto':
        shutil.copytree(arguments[1], arguments[2], symlinks=True)


def test_failed_signature_check_preserves_previous_app(native_build, monkeypatch):
    module, destination = native_build

    def fail_verify(*arguments):
        if arguments[:2] == ('codesign', '--verify'):
            raise subprocess.CalledProcessError(1, arguments)
        fake_run(*arguments)

    monkeypatch.setattr(module, 'run', fail_verify)
    with pytest.raises(subprocess.CalledProcessError):
        module.main()
    assert (destination / 'previous').read_text() == 'last complete build'
    assert not list((module.ROOT / 'build').glob('tscribe-stage-*'))


def test_successful_build_publishes_complete_bundle(native_build, monkeypatch):
    module, destination = native_build
    monkeypatch.setattr(module, 'run', fake_run)
    module.main()
    assert not (destination / 'previous').exists()
    assert (destination / 'Contents/MacOS/tscribe-native').read_text() == 'new executable'
    assert (destination / 'Contents/Resources/Worker/tscribe-worker').read_text() == 'new worker'
    info = plistlib.loads((destination / 'Contents/Info.plist').read_bytes())
    assert info['CFBundleExecutable'] == 'tscribe-native'
    assert not list((module.ROOT / 'build').glob('tscribe-stage-*'))


@pytest.mark.skipif(os.name != 'posix', reason='Make/native packaging runs on Unix')
def test_independent_build_is_rejected_until_lock_is_released(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(BUILD_SCRIPTS))
    from build_lock import LOCK_ENV, build_lock

    script = (
        'import sys; from pathlib import Path; '
        f'sys.path.insert(0, {str(BUILD_SCRIPTS)!r}); '
        'from build_lock import build_lock; '
        'context=build_lock(Path(sys.argv[1])); context.__enter__(); print("acquired")'
    )
    env = {key: value for key, value in os.environ.items() if key != LOCK_ENV}
    with build_lock(tmp_path):
        # Nested Make/build operations inherit ownership instead of deadlocking.
        with build_lock(tmp_path):
            blocked = subprocess.run([sys.executable, '-c', script, str(tmp_path)], env=env, capture_output=True, text=True, timeout=10)
        assert blocked.returncode != 0
        assert 'Another tscribe build or cleanup is running' in blocked.stderr
    released = subprocess.run([sys.executable, '-c', script, str(tmp_path)], env=env, capture_output=True, text=True, timeout=10)
    assert released.returncode == 0
    assert released.stdout.strip() == 'acquired'


def test_preview_build_preserves_current_dist_app(native_build, monkeypatch):
    module, destination = native_build
    monkeypatch.setattr(module, 'run', fake_run)
    preview = module.ROOT / 'build/preview/tscribe.app'
    module.main(preview)
    assert (destination / 'previous').read_text() == 'last complete build'
    assert (preview / 'Contents/MacOS/tscribe-native').read_text() == 'new executable'


def test_packaged_entrypoint_initializes_multiprocessing_before_worker(monkeypatch):
    import builtins
    import runpy

    events = []
    original_import = builtins.__import__

    def observe_import(name, *args, **kwargs):
        if name == 'tscribe.worker':
            events.append('worker-import')
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr('multiprocessing.freeze_support', lambda: events.append('freeze-support'))
    monkeypatch.setattr('tscribe.worker.main', lambda: events.append('worker-main'))
    monkeypatch.setattr(builtins, '__import__', observe_import)
    runpy.run_path(str(BUILD_SCRIPTS / 'worker_entrypoint.py'), run_name='__main__')
    assert events == ['freeze-support', 'worker-import', 'worker-main']
