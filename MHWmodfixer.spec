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
hiddenimports = ['pak_mod_fix', 'whole_game_index', 'slot_retarget', 'weapon_retarget', 'fluffy_installed']
tmp_ret = collect_all('tkinterdnd2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('backports.zstd')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# pyzipper (AES-encrypted .zip support, archive_extract.py's password-
# protected-archive fallback) is only ever `import`ed lazily inside a
# function body -- PyInstaller's static analysis doesn't see it at all in
# that form (confirmed: a first build with just `hiddenimports += ['pyzipper']`
# missing produced zero mention of pyzipper anywhere in the build log, and
# no pyzipper files anywhere under dist/. Same class of gap this project's
# own README already warns about for every other lazily-imported module).
# collect_all, not a bare hiddenimports entry, since it's a real package
# with its own submodules pyinstaller's static analysis won't chase through
# a lazy import. Its pycryptodomex dependency is already handled by
# PyInstaller's own bundled `hook-Cryptodome.py` (confirmed: no separate
# collect_all needed for it -- adding one pulls in Cryptodome's entire
# SelfTest suite as a side effect, pure bloat, no functional benefit).
tmp_ret = collect_all('pyzipper')
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
