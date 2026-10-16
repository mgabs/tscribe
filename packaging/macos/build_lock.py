"""Serialize generated-output changes across Make and direct native builds."""

from __future__ import annotations

import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK_ENV = 'TSCRIBE_BUILD_LOCK_HELD'


@contextmanager
def build_lock(root: Path = ROOT):
    if os.environ.get(LOCK_ENV) == str(root.resolve()):
        yield
        return

    import fcntl

    # Keep the lock outside build/ and dist/: cleaning must not unlink its inode.
    with (root / '.tscribe-build.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Another tscribe build or cleanup is running. Wait for it to finish, then retry.') from None
        previous = os.environ.get(LOCK_ENV)
        os.environ[LOCK_ENV] = str(root.resolve())
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop(LOCK_ENV, None)
            else:
                os.environ[LOCK_ENV] = previous


def main():
    if not sys.argv[1:]:
        raise SystemExit('Usage: build_lock.py COMMAND [ARGUMENTS...]')
    with build_lock():
        raise SystemExit(subprocess.run(sys.argv[1:]).returncode)


if __name__ == '__main__':
    main()
