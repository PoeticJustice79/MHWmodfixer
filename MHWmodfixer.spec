# -*- mode: python ; coding: utf-8 -*-
import glob
from PyInstaller.utils.hooks import collect_all

datas = [('tools/UnRAR.exe', 'tools'), ('tools/mdf2_filelist.txt', 'tools'),
         ('tools/rsz_fields_mhwilds.json.gz', 'tools')]
datas += [(p, 'tools/rsz_archive') for p in glob.glob('tools/rsz_archive/*.json.gz')]
binaries = []
hiddenimports = ['pak_mod_fix', 'whole_game_index']
tmp_ret = collect_all('tkinterdnd2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MHWmodfixer',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='MHWmodfixer',
)
