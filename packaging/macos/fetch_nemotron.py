"""Fetch the pinned NeMo-Speech.cpp runtime and Nemotron 3 Diarization weights for the app bundle."""
from __future__ import annotations

import argparse
import hashlib
import platform
import shutil
import ssl
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

RUNTIME_VERSION = '0.3.0'
RUNTIME_URL = 'https://github.com/NVIDIA/NeMo-Speech.cpp/releases/download/v{v}/nemo-speech-{v}-macos-{arch}.tar.gz'
RUNTIME_ARCHIVES = {
    'arm64': ('aarch64-metal', '2b972ed8b5dba07492212acf8cb75cbf34ecb141198ffa1997febe84b7c4d9ed'),
    'x86_64': ('x86_64-cpu', '97e98aa5eb82dffa4f513f26336b5301d792c9fb43f720ac8f9520a0e92ffe3f'),
}
WEIGHTS_NAME = 'Nemotron-3-Diarization.q8_0.gguf'
WEIGHTS_URL = f'https://huggingface.co/nvidia/Nemotron-3-Diarization/resolve/main/{WEIGHTS_NAME}'
WEIGHTS_SHA256 = '08456d9e22cd9a323c0364d98375f3746d6e68507ebb705cd46438c534c7a3a1'


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, destination: Path, expected: str):
    try:
        import truststore
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        context = ssl.create_default_context()
    with urllib.request.urlopen(url, context=context) as response, destination.open('wb') as stream:
        shutil.copyfileobj(response, stream)
    actual = sha256(destination)
    if actual != expected:
        raise SystemExit(f'Checksum mismatch for {url}: expected {expected}, got {actual}')


def fetch(output: Path, machine: str | None = None):
    machine = machine or platform.machine()
    if machine not in RUNTIME_ARCHIVES:
        raise SystemExit(f'No Nemotron runtime is pinned for {machine}.')
    arch, runtime_sha = RUNTIME_ARCHIVES[machine]
    if (output / 'bin/nemo-speech').is_file() and (output / WEIGHTS_NAME).is_file() and (output / 'VERSION').read_text() == f'{RUNTIME_VERSION} {arch}\n' and sha256(output / WEIGHTS_NAME) == WEIGHTS_SHA256:
        print(f'Nemotron runtime and weights already present: {output}')
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='nemotron-fetch-', dir=output.parent) as staging:
        staging = Path(staging)
        archive = staging / 'runtime.tar.gz'
        download(RUNTIME_URL.format(v=RUNTIME_VERSION, arch=arch), archive, runtime_sha)
        with tarfile.open(archive) as bundle:
            bundle.extractall(staging / 'extract', filter='data')
        (root,) = (staging / 'extract').iterdir()
        staged = staging / 'bundle'
        staged.mkdir()
        for name in ('bin', 'lib', 'share'):
            if (root / name).exists():
                shutil.copytree(root / name, staged / name, symlinks=True)
        shutil.rmtree(staged / 'lib/cmake', ignore_errors=True)
        download(WEIGHTS_URL, staged / WEIGHTS_NAME, WEIGHTS_SHA256)
        (staged / 'VERSION').write_text(f'{RUNTIME_VERSION} {arch}\n')
        shutil.rmtree(output, ignore_errors=True)
        staged.rename(output)
    print(f'Fetched Nemotron runtime and weights: {output}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/nemotron')
    fetch(parser.parse_args().output)
