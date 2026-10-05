"""Reproducible Windows x64 one-file GUI build; run from the repository root."""

from pathlib import Path
import sys

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo,
    VarStruct, VSVersionInfo,
)

root = Path(SPECPATH)
sys.path.insert(0, str(root))
from app_metadata import APP_NAME, VERSION

parts = tuple(int(part) for part in VERSION.split('.'))
file_version = parts + (0,) * (4 - len(parts))
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=file_version, prodvers=file_version, mask=0x3f,
                      flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
    kids=[StringFileInfo([StringTable('040904B0', [
        StringStruct('FileDescription', APP_NAME),
        StringStruct('FileVersion', VERSION),
        StringStruct('ProductName', APP_NAME),
        StringStruct('ProductVersion', VERSION),
        StringStruct('OriginalFilename', f'CelestialEvolutionSimulation-{VERSION}-windows-x64.exe'),
    ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])],
)
analysis = Analysis(
    [str(root / 'main.py')], pathex=[str(root)],
    datas=[(str(root / 'scenes' / '*.json'), 'scenes')],
    hiddenimports=['OpenGL.platform.win32', 'OpenGL.arrays.numpymodule'],
    excludes=['cupy', 'tkinter', 'matplotlib', 'scipy', 'pytest'],
    binaries=[], hookspath=[], runtime_hooks=[], noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, analysis.binaries, analysis.datas, [],
    name=f'CelestialEvolutionSimulation-{VERSION}-windows-x64',
    console=False, debug=False, strip=False, upx=False,
    version=version_info,
)
