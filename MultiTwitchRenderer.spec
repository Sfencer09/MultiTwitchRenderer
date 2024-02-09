# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []
tmp_ret = collect_all('MultiTwitchRenderer')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
excludeFiles = ['knownFiles.pickle', 'config.py']

a = Analysis(
    ['MultiTwitchRenderer/__main__.py'],
    pathex=['/home/ubuntu/Documents/MultiTwitchRenderer/MultiTwitchRenderer'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludeFiles,
    noarchive=False,
)
a.scripts = TOC([entry for entry in a.scripts if not any((exclude in entry[0] for exclude in excludeFiles))])
a.binaries = TOC([entry for entry in a.binaries if not any((exclude in entry[0] for exclude in excludeFiles))])
a.datas = TOC([entry for entry in a.datas if not any((exclude in entry[0] for exclude in excludeFiles))])
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
