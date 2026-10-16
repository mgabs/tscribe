"""Reference-based speaker echo cancellation using the bundled SpeexDSP core.

Processing happens on completed snapshots/final tracks, never a capture callback.
Original microphone and system tracks remain untouched.
"""
from __future__ import annotations

import ctypes
import os
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np


class EchoUnavailable(RuntimeError):
    pass


def library_path() -> Path:
    if override := os.environ.get('TSCRIBE_ECHO_LIBRARY'):
        return Path(override)
    filename = 'libtscribe_echo.dylib' if sys.platform == 'darwin' else 'libtscribe_echo.so'
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / filename
    return Path(__file__).resolve().parents[2] / 'build/audio-dsp' / filename


@lru_cache(maxsize=4)
def _library(path: str):
    try:
        lib = ctypes.CDLL(path)
    except OSError as error:
        raise EchoUnavailable('Echo cancellation library is unavailable. Rebuild the app or run make audio-dsp for development.') from error
    pointer = ctypes.POINTER(ctypes.c_int16)
    lib.speex_echo_state_init.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.speex_echo_state_init.restype = ctypes.c_void_p
    lib.speex_echo_state_destroy.argtypes = [ctypes.c_void_p]
    lib.speex_echo_state_destroy.restype = None
    lib.speex_echo_cancellation.argtypes = [ctypes.c_void_p, pointer, pointer, pointer]
    lib.speex_echo_cancellation.restype = None
    lib.speex_echo_ctl.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    lib.speex_echo_ctl.restype = ctypes.c_int
    return lib


class EchoCanceller:
    """A continuous mono echo path with a 300 ms adaptive filter tail."""
    def __init__(self, rate: int = 16000):
        if rate not in (8000, 16000, 32000, 48000):
            raise EchoUnavailable('Echo cancellation requires 8000, 16000, 32000, or 48000 Hz recording.')
        self.rate = rate
        self.frame_size = rate // 100  # 10 ms, reference and capture use the same clock.
        self.tail = rate * 3 // 10
        self.lib = _library(str(library_path()))
        self.state = self.lib.speex_echo_state_init(self.frame_size, self.tail)
        if not self.state:
            raise EchoUnavailable('Could not allocate the echo canceller.')
        value = ctypes.c_int(rate)
        if self.lib.speex_echo_ctl(self.state, 24, ctypes.byref(value)) != 0:
            self.close()
            raise EchoUnavailable('Could not configure the echo canceller sample rate.')
        self.silent_reference = self.tail

    @staticmethod
    def _pcm(samples):
        return np.ascontiguousarray(np.rint(np.clip(samples, -1, 32767 / 32768) * 32768), dtype=np.int16)

    def process(self, microphone, reference):
        if self.state is None:
            raise RuntimeError('Echo canceller is closed')
        microphone = np.asarray(microphone, dtype=np.float32)
        reference = np.asarray(reference, dtype=np.float32)
        if microphone.ndim != 1 or reference.shape != microphone.shape:
            raise ValueError('Echo input and reference must be aligned mono arrays of equal length')
        if not np.isfinite(microphone).all() or not np.isfinite(reference).all():
            raise ValueError('Echo samples must be finite')
        output = np.empty_like(microphone)
        pointer = ctypes.POINTER(ctypes.c_int16)
        for first in range(0, len(microphone), self.frame_size):
            count = min(self.frame_size, len(microphone) - first)
            mic = self._pcm(np.pad(microphone[first:first + count], (0, self.frame_size - count)))
            render = self._pcm(np.pad(reference[first:first + count], (0, self.frame_size - count)))
            if np.any(render):
                self.silent_reference = 0
            else:
                self.silent_reference += self.frame_size
            cleaned = np.empty(self.frame_size, dtype=np.int16)
            self.lib.speex_echo_cancellation(
                self.state, mic.ctypes.data_as(pointer), render.ctypes.data_as(pointer), cleaned.ctypes.data_as(pointer),
            )
            if self.silent_reference >= self.tail:
                # With no playback reference/tail, preserve microphone-only speech.
                output[first:first + count] = microphone[first:first + count]
            else:
                output[first:first + count] = cleaned[:count].astype(np.float32) / 32768
        return output

    def close(self):
        if self.state is not None:
            self.lib.speex_echo_state_destroy(self.state)
            self.state = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
