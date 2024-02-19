# -*- mode: python ; coding: utf-8 -*-
#excludeFiles = ['/home/ubuntu/Documents/MultiTwitchRenderer/config.py']
excludeFiles = []

a = Analysis(
    ['__main__.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludeFiles,
    noarchive=False,
)
print("scripts", a.scripts, sep="\n", end="\n\n")
#a.scripts = TOC([entry for entry in a.scripts if not any((exclude == entry[1] for exclude in excludeFiles))])
#a.binaries = TOC([entry for entry in a.binaries if not any((exclude in entry[0] for exclude in excludeFiles))])
#a.datas = TOC([entry for entry in a.datas if not any((exclude in entry[0] for exclude in excludeFiles))])
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MultiTwitchRenderer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
