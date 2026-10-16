"""Build the pinned, vendored SpeexDSP echo-only library without network access."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def build(output: Path):
    if os.name != 'posix':
        raise SystemExit('The native echo library build requires macOS or Linux.')
    source = ROOT / 'vendor/speexdsp'
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = tempfile.TemporaryDirectory(prefix='echo-build-', dir=output.parent)
    staged = Path(staging.name) / output.name
    command = [os.environ.get('CC', 'cc'), '-O3', '-fPIC']
    command += ['-dynamiclib', '-mmacosx-version-min=14.0', '-Wl,-install_name,@rpath/libtscribe_echo.dylib'] if sys.platform == 'darwin' else ['-shared']
    command += ['-DFLOATING_POINT', '-DUSE_KISS_FFT', '-DEXPORT=', f'-I{source / "include"}', f'-I{source / "libspeexdsp"}']
    command += [str(source / 'libspeexdsp' / name) for name in ('mdf.c', 'fftwrap.c', 'kiss_fft.c', 'kiss_fftr.c')]
    command += ['-lm', '-o', str(staged)]
    try:
        subprocess.run(command, check=True)
        staged.replace(output)
    finally:
        staging.cleanup()
    print(f'Built echo cancellation library: {output}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    suffix = 'dylib' if sys.platform == 'darwin' else 'so'
    parser.add_argument('--output', type=Path, default=ROOT / f'build/audio-dsp/libtscribe_echo.{suffix}')
    build(parser.parse_args().output)
