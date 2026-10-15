"""Finder entry point for the frozen menu bar app."""

import sys
from pathlib import Path


def self_test():
    """Check frozen native dependencies without recording or downloading models."""
    import json
    import av
    import ctranslate2
    import numpy as np
    import rumps
    import sounddevice
    from sklearn.cluster import AgglomerativeClustering
    from faster_whisper.vad import get_vad_model
    from tscribe import __version__
    from tscribe.desktop import RESOURCE_DIR

    for name in ('menu_icon.png', 'menu_icon@2x.png', 'AppIcon.icns'):
        if not (RESOURCE_DIR / name).is_file():
            raise RuntimeError(f'Missing resource: {name}')
    get_vad_model()
    labels = AgglomerativeClustering(n_clusters=2).fit_predict(np.array([[0, 0], [1, 1], [9, 9]]))
    assert len(labels) == 3
    print(json.dumps({
        'version': __version__,
        'frozen': bool(getattr(sys, 'frozen', False)),
        'native_dependencies': 'ok',
        'portaudio': sounddevice.get_portaudio_version()[1],
        'cpu_compute_types': sorted(ctranslate2.get_supported_compute_types('cpu')),
        'pyav': av.__version__,
        'menu_framework': rumps.__version__,
    }))


def run():
    if sys.argv[1:2] == ['--cli']:
        from tscribe.cli import main
        main(sys.argv[2:])
        return
    if sys.argv[1:] == ['--self-test']:
        self_test()
        return
    log_dir = Path.home() / 'Library' / 'Logs' / 'tscribe'
    log_dir.mkdir(parents=True, exist_ok=True)
    log = (log_dir / 'tscribe.log').open('a', buffering=1, encoding='utf-8')
    sys.stdout = sys.stderr = log

    from tscribe.cli import main

    try:
        main(['app'], standalone_mode=False)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        from AppKit import NSAlert
        alert = NSAlert.alloc().init()
        alert.setMessageText_('tscribe could not start')
        alert.setInformativeText_(f'{exc}\n\nDetails: {log_dir / "tscribe.log"}')
        alert.runModal()
        raise SystemExit(1) from exc


if __name__ == '__main__':
    run()
