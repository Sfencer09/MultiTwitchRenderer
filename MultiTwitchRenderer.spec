# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

#excludeFiles = ['/home/ubuntu/Documents/MultiTwitchRenderer/config.py']
excludeFiles = []

datas = []
binaries = []
hiddenimports = []
tmp_ret = collect_all('urwid.display')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['__main__.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludeFiles,
    noarchive=False,
)
print("scripts", [entry for entry in a.scripts if any(('MultiTwitchRenderer' in item and 'MultiTwitchRenderer/venv' not in item for item in entry))], sep="\n", end="\n\n")
#a.scripts = TOC([entry for entry in a.scripts if not any((exclude == entry[1] for exclude in excludeFiles))])
print("binaries", [entry for entry in a.binaries if any(('MultiTwitchRenderer' in item and 'MultiTwitchRenderer/venv' not in item for item in entry))], sep="\n", end="\n\n")
#a.binaries = TOC([entry for entry in a.binaries if not any((exclude == entry[1] for exclude in excludeFiles))])
print("datas", [entry for entry in a.datas if any(('MultiTwitchRenderer' in item and 'MultiTwitchRenderer/venv' not in item for item in entry))], sep="\n", end="\n\n")
#a.datas = TOC([entry for entry in a.datas if not any((exclude == entry[1] for exclude in excludeFiles))])
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
