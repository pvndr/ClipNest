# -*- mode: python ; coding: utf-8 -*-

"""PyInstaller build description for the ClipNest Windows release candidate.

A one-folder (``--onedir``) build is used on purpose. Qt loads its platform,
style and image-formats plugins from disk, so keeping them visible makes a
missing plugin diagnosable instead of turning it into a silent
"could not find or load the Qt platform plugin" failure inside a
self-extracting archive.

Build from the project root with the project virtual environment::

    .\\.venv\\Scripts\\python.exe -m PyInstaller --noconfirm --clean ClipNest.spec

Output: ``dist\\\\ClipNest\\\\ClipNest.exe`` beside its ``_internal`` folder. The
build never bundles a database, a preference file, or a user path: the packaged
application creates those under ``%LOCALAPPDATA%`` on first launch.
"""

from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).resolve()  # noqa: F821 - provided by PyInstaller
ASSETS = PROJECT_ROOT / "clipnest" / "assets"
VERSION_INFO = PROJECT_ROOT / "build_support" / "version_info.txt"

analysis = Analysis(  # noqa: F821 - provided by PyInstaller
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    # Only the artwork is data: everything else is Python the analysis follows.
    datas=[(str(ASSETS), "clipnest/assets")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="ClipNest",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ASSETS / "clipnest.ico"),
    version=str(VERSION_INFO),
)

COLLECT(  # noqa: F821
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ClipNest",
)
