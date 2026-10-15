# Build on macOS: uv run --group mac-app pyinstaller --noconfirm packaging/macos/tscribe.spec
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata

root = Path(SPECPATH).parents[1]
sys.path.insert(0, str(root / 'src'))
from tscribe.desktop import RESOURCE_DIR, bundle_info

# Native extension hooks collect numpy/scipy/sklearn, PyAV, sounddevice and PyObjC.
# Explicitly collect Whisper's VAD model and CTranslate2's bundled libraries.
datas = collect_data_files('faster_whisper') + collect_data_files('tscribe')
for package in ('faster-whisper', 'ctranslate2', 'huggingface-hub', 'tokenizers', 'tqdm'):
    datas += copy_metadata(package)
binaries = collect_dynamic_libs('ctranslate2')
identity = os.environ.get('TSCRIBE_CODESIGN_IDENTITY')

a = Analysis(
    [str(root / 'packaging' / 'macos' / 'entrypoint.py')],
    pathex=[str(root / 'src')],
    datas=datas,
    binaries=binaries,
    hiddenimports=['rumps', 'AppKit', 'Foundation', 'sklearn', 'faster_whisper'],
    excludes=['pytest', 'mutmut', 'PyInstaller', 'tkinter'],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name='tscribe',
    console=False, argv_emulation=False, codesign_identity=identity,
)
coll = COLLECT(exe, a.binaries, a.datas, name='tscribe')
app = BUNDLE(
    coll, name='tscribe.app', icon=str(RESOURCE_DIR / 'AppIcon.icns'),
    bundle_identifier='com.tscribe.app', info_plist=bundle_info(),
)
