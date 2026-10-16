"""Check a bundled worker without recording audio or downloading models."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main(executable: Path):
    with tempfile.TemporaryDirectory(prefix='tscribe-worker-check-') as directory:
        env = dict(os.environ, TSCRIBE_CONFIG_FILE=f'{directory}/config.toml', TSCRIBE_DATA_DIR=f'{directory}/data')
        request = json.dumps({'id': 'check', 'command': 'bootstrap'}) + '\n'
        result = subprocess.run([str(executable)], input=request, text=True, capture_output=True, check=True, env=env, timeout=30)
        response = json.loads(result.stdout)
        assert response['id'] == 'check' and response['event'] == 'result', result.stdout
        # Emulate the helper arguments used by multiprocessing on macOS. The
        # tracker reads this dedicated, already-closed pipe, not protocol stdin.
        reader, writer = os.pipe()
        os.close(writer)
        try:
            tracker = subprocess.run(
                [str(executable), '-B', '-S', '-I', '-c', f'from multiprocessing.resource_tracker import main;main({reader})'],
                input=request, text=True, capture_output=True, check=True, env=env,
                pass_fds=(reader,), timeout=30,
            )
        finally:
            os.close(reader)
        assert tracker.stdout == '', 'Resource tracker incorrectly started another protocol server: ' + tracker.stdout
    print('Bundled worker bootstrap and multiprocessing isolation checks passed.')


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve())
