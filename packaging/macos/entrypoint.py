"""Finder entry point for the frozen menu bar app."""

import sys
from pathlib import Path


def run():
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
