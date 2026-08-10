"""
Extract a mod archive (zip/7z/rar) with no external tool required on the
end user's machine:
  - .zip -> stdlib zipfile
  - .7z  -> py7zr (pure Python, pip dependency, no native binary)
  - .rar -> Windows's own built-in `tar.exe` (%windir%\\System32\\tar.exe,
            libarchive/bsdtar under the hood, BSD-licensed, ships on every
            Windows 10 (since the 1803 update)/11 install) -- confirmed
            directly (2026-08-10) to genuinely decompress real RAR5
            archives correctly (tested against 2 real Nexus mod .rar
            files, ~63x expansion ratio on one, not just passing through
            already-stored entries), not just list them.

Previously bundled RARLAB's freeware `UnRAR.exe` (tools/UnRAR.exe) via the
`rarfile` package for this. Switched away deliberately: RARLAB's freeware
license permits redistribution but the binary itself isn't open source,
which is a real blocker for this project's SignPath Foundation code-signing
application (their policy prohibits bundling non-OSS components). Shelling
out to the OS's own already-present tar.exe needs no bundling at all --
not even an open-source replacement binary (a Windows build of the LGPL
`unar` tool was considered too, but no current prebuilt Windows binary is
readily available for it; tar.exe sidesteps needing one entirely).

This replaces the earlier Bandizip-based approach, which worked but only
on machines that happen to have Bandizip installed -- not something a
shared, double-click tool can assume.
"""
from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import py7zr

_TAR_EXE = Path(r"C:\Windows\System32\tar.exe")


def _extract_rar(archive_path: Path, dest: Path) -> None:
    if not _TAR_EXE.exists():
        raise FileNotFoundError(
            f"{_TAR_EXE} not found -- .rar extraction needs Windows's own built-in "
            "tar.exe (present by default on Windows 10 1803+/11). Can't extract "
            "this archive without it."
        )
    result = subprocess.run(
        [str(_TAR_EXE), "-xf", str(archive_path), "-C", str(dest)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"tar.exe failed to extract {archive_path.name}: {result.stderr.strip()}")


def extract_archive(archive_path: str | Path, dest_dir: str | Path) -> Path:
    archive_path = Path(archive_path)
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    suffix = archive_path.suffix.lower()
    if suffix == ".zip":
        with zipfile.ZipFile(archive_path) as z:
            z.extractall(dest)
    elif suffix == ".7z":
        with py7zr.SevenZipFile(archive_path, mode="r") as z:
            z.extractall(path=dest)
    elif suffix == ".rar":
        _extract_rar(archive_path, dest)
    else:
        raise ValueError(f"Unsupported archive format: {suffix} ({archive_path})")

    return dest
