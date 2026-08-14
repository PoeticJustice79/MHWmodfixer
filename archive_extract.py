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


class PasswordRequired(Exception):
    """Raised when an archive is password-protected. `wrong_password` is
    False the first time (no password was supplied at all) and True on a
    retry where a password WAS supplied but didn't work -- callers use this
    to distinguish "ask for a password" from "that password was wrong, ask
    again" without parsing the message text."""

    def __init__(self, message: str, wrong_password: bool = False):
        super().__init__(message)
        self.wrong_password = wrong_password


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


def _extract_zip(archive_path: Path, dest: Path, password: str | None) -> None:
    """Plain zipfile handles the overwhelming majority of real mod zips
    (including the classic ZipCrypto password scheme, given a password) and
    needs no extra dependency -- tried first. It can never read AES
    (WinZip AE-x, zipfile's own `compress_type` 99) at all, password or not:
    with no password it raises RuntimeError ("encrypted, password required");
    WITH the correct password it instead raises NotImplementedError
    ("compression type ... not supported") -- confirmed directly against a
    real AES-encrypted mod archive (2026-08-14, Mangie "Echo", the whole
    zip -- not just one file -- was AES-encrypted). Both cases fall through
    to `pyzipper` (MIT-licensed, real AES support, pulled in only for this
    fallback path so the common unencrypted case never pays for it)."""
    try:
        with zipfile.ZipFile(archive_path) as z:
            z.extractall(dest, pwd=password.encode("utf-8") if password else None)
        return
    except (RuntimeError, NotImplementedError):
        pass

    import pyzipper

    if password is None:
        raise PasswordRequired(f"{archive_path.name} is password-protected")
    try:
        with pyzipper.AESZipFile(archive_path) as z:
            z.extractall(dest, pwd=password.encode("utf-8"))
    except RuntimeError as e:
        raise PasswordRequired(f"Incorrect password for {archive_path.name}", wrong_password=True) from e


def _extract_7z(archive_path: Path, dest: Path, password: str | None) -> None:
    try:
        with py7zr.SevenZipFile(archive_path, mode="r", password=password) as z:
            z.extractall(path=dest)
    except py7zr.exceptions.PasswordRequired as e:
        raise PasswordRequired(f"{archive_path.name} is password-protected",
                                wrong_password=password is not None) from e
    except (py7zr.exceptions.CrcError, py7zr.exceptions.Bad7zFile) as e:
        # A wrong password on a 7z archive doesn't fail cleanly like zip's
        # "bad password" check -- it manifests as garbage bytes that fail
        # CRC/header validation downstream. Only reinterpreted as a password
        # problem when a password was actually supplied; a genuinely corrupt,
        # never-encrypted archive should still raise its real error.
        if password is not None:
            raise PasswordRequired(f"Incorrect password for {archive_path.name}", wrong_password=True) from e
        raise


def extract_archive(archive_path: str | Path, dest_dir: str | Path, password: str | None = None) -> Path:
    archive_path = Path(archive_path)
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    suffix = archive_path.suffix.lower()
    if suffix == ".zip":
        _extract_zip(archive_path, dest, password)
    elif suffix == ".7z":
        _extract_7z(archive_path, dest, password)
    elif suffix == ".rar":
        # tar.exe (bsdtar/libarchive) has no password support at all for
        # RAR -- a password-protected .rar just fails with its own generic
        # extraction error here. Not handled: would need re-bundling a real
        # RAR-decryption binary, which is exactly what UnRAR.exe's removal
        # (see this module's own docstring) was meant to avoid.
        _extract_rar(archive_path, dest)
    else:
        raise ValueError(f"Unsupported archive format: {suffix} ({archive_path})")

    return dest
