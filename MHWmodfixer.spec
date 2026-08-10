# -*- mode: python ; coding: utf-8 -*-
import glob
import os
from PyInstaller.utils.hooks import collect_all

datas = [('tools/mdf2_filelist.txt', 'tools'),
         ('tools/rsz_fields_mhwilds.json.gz', 'tools'),
         ('tools/armor_slots_ch03.json.gz', 'tools'),
         ('tools/weapon_slots.json.gz', 'tools')]
datas += [(p, 'tools/rsz_archive') for p in glob.glob('tools/rsz_archive/*.json.gz')]
binaries = []
hiddenimports = ['pak_mod_fix', 'whole_game_index', 'slot_retarget', 'weapon_retarget']
tmp_ret = collect_all('tkinterdnd2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('backports.zstd')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
import backports.zstd as _bz
_bz_dir = os.path.dirname(_bz.__file__)
binaries += [(p, 'backports/zstd') for p in glob.glob(os.path.join(_bz_dir, '*.pyd'))]


a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['backports.zstd._zstd', 'backports.zstd._cffi'],
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
