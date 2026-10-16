import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata

root = Path(SPECPATH).parents[1]
datas = collect_data_files('faster_whisper')
datas += [(str(root / 'vendor/speexdsp' / name), 'licenses/SpeexDSP') for name in ('COPYING', 'THIRD_PARTY_NOTICES.txt')]
for package in ('faster-whisper', 'ctranslate2', 'huggingface-hub', 'tokenizers', 'tqdm'):
    datas += copy_metadata(package)
a = Analysis(
    [str(root / 'packaging/macos/worker_entrypoint.py')],
    pathex=[str(root / 'src')], datas=datas,
    binaries=[(str(root / 'build/audio-dsp/libtscribe_echo.dylib'), '.')] + collect_dynamic_libs('ctranslate2') + collect_dynamic_libs('sherpa_onnx'),
    hiddenimports=['faster_whisper', 'sherpa_onnx', 'sklearn'],
    excludes=['AppKit', 'Foundation', 'objc', 'pytest', 'mutmut', 'tkinter', 'PyInstaller'],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='tscribe-worker', console=True,
          codesign_identity=os.environ.get('TSCRIBE_CODESIGN_IDENTITY'))
coll = COLLECT(exe, a.binaries, a.datas, name='tscribe-worker')
