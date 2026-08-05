"""
Extract a mod archive (zip/7z/rar) with no external tool required on the
end user's machine:
  - .zip -> stdlib zipfile
  - .7z  -> py7zr (pure Python, pip dependency, no native binary)
  - .rar -> rarfile + the official freeware UnRAR.exe console tool bundled
            in tools/UnRAR.exe (RARLAB's freeware license explicitly
            permits redistributing UnRAR inside other software packages)

This replaces the earlier Bandizip-based approach, which worked but only
on machines that happen to have Bandizip installed -- not something a
shared, double-click tool can assume.
"""
from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

import py7zr
import rarfile

_HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
_BUNDLED_UNRAR = _HERE / "tools" / "UnRAR.exe"

if _BUNDLED_UNRAR.exists():
    rarfile.UNRAR_TOOL = str(_BUNDLED_UNRAR)


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
        if not _BUNDLED_UNRAR.exists() and not shutil.which("unrar"):
            raise FileNotFoundError(
                f"No UnRAR tool available (expected bundled at {_BUNDLED_UNRAR}). "
                "Can't extract .rar archives without it."
            )
        with rarfile.RarFile(archive_path) as z:
            z.extractall(dest)
    else:
        raise ValueError(f"Unsupported archive format: {suffix} ({archive_path})")

    return dest
