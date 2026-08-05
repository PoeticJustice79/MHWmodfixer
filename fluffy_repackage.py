"""
Some mod authors distribute a single top-level folder (with its own
modinfo.ini) plus one or more loose top-level extras -- most commonly an
extra standalone .pak (e.g. a separate texture pack) that has to be
installed alongside the main folder. Fluffy Mod Manager only shows its
page-selector install screen (letting the user pick which pieces to
install) when each installable "page" is its OWN top-level folder with
its OWN modinfo.ini, and all of those modinfo.ini's share the same
NameAsBundle value -- confirmed by comparing a mod author's original
"[MM] Banshee" + loose "Banshee - Textures.pak" layout (no page-selector
in Fluffy) against a community re-packaging of the same mod into
"0. Banshee - Model/" + "1. Banshee - Textures/" folders, each with its
own modinfo.ini declaring NameAsBundle=Mangie Banshee (page-selector
appears). This module reproduces that re-packaging automatically so a
mod author's original archive gets the same friendlier install UX
without a human having to do it by hand.

Deliberately conservative: only triggers when there's exactly ONE
top-level folder containing a modinfo.ini and at least one OTHER
top-level entry that isn't just a stray readme/doc file. A mod that's
already split into multiple modinfo.ini-bearing folders (already has the
Fluffy-friendly layout) is left completely untouched.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

MODINFO_NAME = "modinfo.ini"
_IGNORED_EXTRA_SUFFIXES = {".txt", ".md"}


def _read_modinfo(path: Path) -> dict:
    kv = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        kv[k.strip()] = v.strip()
    return kv


def _write_modinfo(path: Path, kv: dict):
    path.write_text("\n".join(f"{k}={v}" for k, v in kv.items()) + "\n", encoding="utf-8")


def _derive_suffix(entry_name: str, base_name: str) -> str:
    """'[MM] Banshee - Textures.pak' + base_name='Banshee' -> 'Textures'."""
    stem = Path(entry_name).stem
    stem = re.sub(r"^\[.*?\]\s*", "", stem)
    if base_name and stem.lower().startswith(base_name.lower()):
        stem = stem[len(base_name):]
    stem = stem.strip(" -_")
    return stem or Path(entry_name).stem


def _modinfo_folders(top_entries: list[Path]) -> list[Path]:
    return [e for e in top_entries if e.is_dir() and (e / MODINFO_NAME).is_file()]


def needs_repackaging(mod_root: Path) -> bool:
    top_entries = list(mod_root.iterdir())
    folders = _modinfo_folders(top_entries)
    if len(folders) != 1:
        return False  # already multi-page, or no modinfo.ini at all -- leave alone
    main_folder = folders[0]
    extras = [e for e in top_entries if e != main_folder and e.suffix.lower() not in _IGNORED_EXTRA_SUFFIXES]
    return len(extras) > 0


def repackage_for_fluffy(mod_root: Path, log=lambda s: None) -> bool:
    """Restructures mod_root in place. Returns True if anything changed."""
    if not needs_repackaging(mod_root):
        return False

    top_entries = list(mod_root.iterdir())
    main_folder = _modinfo_folders(top_entries)[0]
    extras = [e for e in top_entries if e != main_folder and e.suffix.lower() not in _IGNORED_EXTRA_SUFFIXES]

    main_info = _read_modinfo(main_folder / MODINFO_NAME)
    base_name = main_info.get("name", main_folder.name).strip()
    bundle_name = main_info.get("NameAsBundle", base_name)

    log(f"[fluffy 재포장] '{mod_root.name}'을(를) 여러 옵션 선택 구조로 재포장합니다 "
        f"(번들명={bundle_name!r}, 부가 구성요소 {len(extras)}개 발견)")

    new_main_name = f"0. {base_name} - Main File"
    new_main_path = mod_root / new_main_name
    main_folder.rename(new_main_path)
    main_info["name"] = new_main_name
    main_info["NameAsBundle"] = bundle_name
    _write_modinfo(new_main_path / MODINFO_NAME, main_info)
    log(f"    '{main_folder.name}' -> '{new_main_name}'")

    screenshot_name = main_info.get("screenshot", "preview.png")
    screenshot_src = new_main_path / screenshot_name

    for i, extra in enumerate(extras, start=1):
        suffix = _derive_suffix(extra.name, base_name)
        page_name = f"{i}. {base_name} - {suffix}"
        page_path = mod_root / page_name
        page_path.mkdir(parents=True, exist_ok=True)
        shutil.move(str(extra), str(page_path / extra.name))

        page_info = {
            "name": page_name,
            "version": main_info.get("version", "1.0"),
            "description": main_info.get("description", ""),
            "author": main_info.get("author", ""),
            "category": main_info.get("category", ""),
            "NameAsBundle": bundle_name,
        }
        if screenshot_src.is_file():
            shutil.copy2(screenshot_src, page_path / screenshot_name)
            page_info["screenshot"] = screenshot_name
        _write_modinfo(page_path / MODINFO_NAME, page_info)
        log(f"    '{extra.name}' -> '{page_name}/{extra.name}' (신규 modinfo.ini 생성)")

    return True
