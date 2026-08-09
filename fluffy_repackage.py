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

Two real shapes handled, both confirmed against real mod authors' own
raw releases:

1. Exactly ONE modinfo.ini folder plus loose extras (Mangie Banshee/
   MooMoo's original releases) -- the ORIGINAL case this module was built
   for. The single folder gets renamed into a "0. <name> - Main File"
   page too, and every loose extra becomes its own new page.
2. TWO OR MORE modinfo.ini folders that are ALREADY a working page set,
   but with additional loose extras still sitting outside any page --
   confirmed real case: Mangie "Mask Bikini"'s own release has a proper
   "01. Mask Bikini - Main File" + "02. Mask Bikini - Open Mask (Option)"
   pair, but 3 more pieces (Alma.pak, Gemma.pak, Textures.pak -- one of
   them, per the mod's own README, actually REQUIRED alongside the main
   file) are loose .pak files at the archive root with no modinfo.ini at
   all, so Fluffy's page-selector never offers them and a user has no way
   to install them through the normal install flow. The existing 2 pages
   are left COMPLETELY untouched here (renaming/rewriting an
   already-working page risks breaking something that already works, for
   zero benefit) -- only the still-loose extras get wrapped into new
   pages, continuing whichever numeric prefix style ("01."/"02." vs
   "0."/"1.") the existing pages already use.

Deliberately still conservative in one respect: a mod with ZERO
modinfo.ini folders at all is left alone -- there's no existing page to
derive NameAsBundle/author/category from, and guessing those would risk
producing a page set Fluffy displays under the wrong bundle name.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

MODINFO_NAME = "modinfo.ini"
_IGNORED_EXTRA_SUFFIXES = {".txt", ".md"}
_IGNORED_EXTRA_NAMES = {"thumbs.db", "desktop.ini", ".ds_store", "__macosx"}


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
    bracket_stripped = re.sub(r"^\[.*?\]\s*", "", Path(entry_name).stem)
    stem = bracket_stripped
    if base_name and stem.lower().startswith(base_name.lower()):
        stem = stem[len(base_name):]
    stem = stem.strip(" -_")
    # fall back to the bracket-stripped (but not base-name-stripped) stem
    # first, so e.g. "[MM] Banshee.pak" with base_name="Banshee" still
    # yields "Banshee" instead of the raw un-stripped "[MM] Banshee"
    return stem or bracket_stripped or Path(entry_name).stem


def _is_junk_extra(entry: Path) -> bool:
    if entry.suffix.lower() in _IGNORED_EXTRA_SUFFIXES:
        return True
    return entry.name.lower() in _IGNORED_EXTRA_NAMES


def _modinfo_folders(top_entries: list[Path]) -> list[Path]:
    return [e for e in top_entries if e.is_dir() and (e / MODINFO_NAME).is_file()]


_LEADING_NUM_RE = re.compile(r"^(\d+)\.")


def _next_page_number(existing_names: list[str]) -> tuple[int, int]:
    """Continues whatever numeric page-prefix style existing pages already
    use (e.g. "01."/"02." -> next is 3 with width 2, so it renders "03."),
    so newly-wrapped pages don't look visually inconsistent next to
    already-correct ones. Falls back to (1, 1) -- plain "1." -- when no
    existing page name has a recognizable numeric prefix at all."""
    nums, width = [], 1
    for name in existing_names:
        m = _LEADING_NUM_RE.match(name.strip())
        if m:
            nums.append(int(m.group(1)))
            width = max(width, len(m.group(1)))
    return (max(nums) + 1, width) if nums else (1, 1)


def needs_repackaging(mod_root: Path) -> bool:
    top_entries = list(mod_root.iterdir())
    folders = _modinfo_folders(top_entries)
    if not folders:
        return False  # no modinfo.ini anywhere -- nothing to safely derive a bundle name from
    extras = [e for e in top_entries if e not in folders and not _is_junk_extra(e)]
    return len(extras) > 0


def repackage_for_fluffy(mod_root: Path, log=lambda s: None) -> bool:
    """Restructures mod_root in place. Returns True if anything changed.

    Two shapes (see module docstring): exactly one modinfo.ini folder
    (the original case -- renames it into a "0. ... - Main File" page
    too) vs. two or more ALREADY-working page folders that still have
    loose, un-paged extras left over (confirmed real case: Mangie "Mask
    Bikini") -- the existing folders are left completely untouched in
    that case, and only the loose extras get wrapped into new trailing
    pages."""
    if not needs_repackaging(mod_root):
        return False

    top_entries = list(mod_root.iterdir())
    folders = _modinfo_folders(top_entries)
    extras = [e for e in top_entries if e not in folders and not _is_junk_extra(e)]

    if len(folders) > 1:
        return _wrap_loose_extras_only(mod_root, folders, extras, log)

    main_folder = folders[0]
    main_info = _read_modinfo(main_folder / MODINFO_NAME)
    # NameAsBundle is the mod's own short title (e.g. "MooMoo"); the "name"
    # field is often already a full per-page label the author chose for
    # their single original page (e.g. "01. MooMoo - Main File"). Using
    # "name" as the base for newly-derived page names doubled it up into
    # garbage like "0. 01. MooMoo - Main File - Main File" -- confirmed via
    # a real mod (Mangie MooMoo's raw release) whose own modinfo.ini "name"
    # already carried a page-style prefix/suffix.
    base_name = main_info.get("NameAsBundle", main_info.get("name", main_folder.name)).strip()
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


def _is_mangie_mod(info: dict) -> bool:
    """Whether a page's modinfo.ini identifies it as one of MangieW's own
    mods (author='MangieW', category="Mangie's Modding" in every real
    example seen). Mangie appears to build/test with MO2, which has no
    concept of Fluffy's page-selector at all -- explaining why this exact
    "extra pieces shipped as loose top-level files, no page" gap recurs
    consistently across Mangie's own raw releases (confirmed: Mask
    Bikini) while community-repackaged copies of the same mods always fix
    it the same specific way (see the Mask Bikini reference this function
    was written against, "0. .. - Model" / "1. .. - Textures" /
    "2. .. - Open Mask" / "3." / "4." -- Textures placed right after the
    main page, ahead of cosmetic option pages). Recognizing the author
    lets this module reproduce that exact convention with confidence
    instead of guessing at a generic mod's intended page order."""
    author = info.get("author", "").strip().lower()
    category = info.get("category", "").strip().lower()
    return "mangie" in author or "mangie" in category


def _wrap_loose_extras_only(mod_root: Path, folders: list[Path], extras: list[Path], log) -> bool:
    """The already-multi-page case (2+ folders already have modinfo.ini)
    with leftover un-paged extras -- e.g. Mangie "Mask Bikini"'s own
    release, whose 2 existing pages work fine in Fluffy but 3 more
    pieces (including one the mod's own README marks REQUIRED) are loose
    .pak files with no page at all.

    For a recognized Mangie mod (see _is_mangie_mod()), reproduces the
    exact convention observed in a real community repackaging of this
    same mod: renumber EVERYTHING from 0, with any "Textures" page moved
    to right after the main page (ahead of cosmetic option pages) since
    the mod's own README always marks it required alongside the main
    file. For any other/unrecognized author, stays conservative: the
    existing folders are never touched at all, and new pages are simply
    appended after them, continuing whichever numeric page-prefix style
    they already use -- safe for a mod author whose actual intended page
    order this project has no real evidence about."""
    anchor_info = _read_modinfo(folders[0] / MODINFO_NAME)
    base_name = anchor_info.get("NameAsBundle", anchor_info.get("name", folders[0].name)).strip()
    bundle_name = anchor_info.get("NameAsBundle", base_name)
    screenshot_name = anchor_info.get("screenshot", "preview.png")
    screenshot_src = folders[0] / screenshot_name
    # read into memory now -- folders[0] itself may get renamed below
    # (the Mangie branch), which would make a path-based re-read fail
    screenshot_bytes = screenshot_src.read_bytes() if screenshot_src.is_file() else None

    if _is_mangie_mod(anchor_info):
        log(f"[fluffy 재포장] '{mod_root.name}'은(는) Mangie 모드로 인식됩니다 -- 옵션 화면에 뜨지 않는 "
            f"개별 파일 {len(extras)}개를 포함해 전체 페이지를 0번부터 다시 정리합니다 "
            f"(번들명={bundle_name!r})")
        textures = [e for e in extras if _derive_suffix(e.name, base_name).lower() == "textures"]
        other_extras = [e for e in extras if e not in textures]
        ordered_folders = [(folders[0], _read_modinfo(folders[0] / MODINFO_NAME))] + \
                           [(f, _read_modinfo(f / MODINFO_NAME)) for f in folders[1:]]
        ordered_items = [("folder", ordered_folders[0])] + \
                         [("extra", e) for e in textures] + \
                         [("folder", f) for f in ordered_folders[1:]] + \
                         [("extra", e) for e in other_extras]
        width = 1
        for i, (kind, item) in enumerate(ordered_items):
            if kind == "folder":
                folder, info = item
                suffix = re.sub(r"^\d+\.\s*", "", info.get("name", folder.name)).strip()
                suffix = re.sub(rf"^{re.escape(base_name)}\s*-\s*", "", suffix, flags=re.IGNORECASE).strip()
                page_name = f"{i}. {base_name} - {suffix}"
                new_path = mod_root / page_name
                folder.rename(new_path)
                info["name"] = page_name
                info["NameAsBundle"] = bundle_name
                _write_modinfo(new_path / MODINFO_NAME, info)
                log(f"    '{folder.name}' -> '{page_name}' (기존 페이지, 이름만 재정렬)")
            else:
                extra = item
                suffix = _derive_suffix(extra.name, base_name)
                page_name = f"{i}. {base_name} - {suffix}"
                page_path = mod_root / page_name
                page_path.mkdir(parents=True, exist_ok=True)
                shutil.move(str(extra), str(page_path / extra.name))
                page_info = {
                    "name": page_name, "version": anchor_info.get("version", "1.0"),
                    "description": f"{suffix} option", "author": anchor_info.get("author", ""),
                    "category": anchor_info.get("category", ""), "NameAsBundle": bundle_name,
                }
                if screenshot_bytes is not None:
                    (page_path / screenshot_name).write_bytes(screenshot_bytes)
                    page_info["screenshot"] = screenshot_name
                _write_modinfo(page_path / MODINFO_NAME, page_info)
                log(f"    '{extra.name}' -> '{page_name}/{extra.name}' (신규 modinfo.ini 생성)")
        return True

    existing_names = [_read_modinfo(f / MODINFO_NAME).get("name", f.name) for f in folders]
    start_num, width = _next_page_number(existing_names)

    log(f"[fluffy 재포장] '{mod_root.name}'에 옵션 화면에 뜨지 않는 개별 파일 {len(extras)}개가 있어 "
        f"새 페이지로 감쌉니다 (기존 페이지 {len(folders)}개는 그대로 유지, 번들명={bundle_name!r})")

    for i, extra in enumerate(extras, start=start_num):
        suffix = _derive_suffix(extra.name, base_name)
        page_name = f"{i:0{width}d}. {base_name} - {suffix}"
        page_path = mod_root / page_name
        page_path.mkdir(parents=True, exist_ok=True)
        shutil.move(str(extra), str(page_path / extra.name))

        page_info = {
            "name": page_name,
            "version": anchor_info.get("version", "1.0"),
            "description": f"{suffix} option",
            "author": anchor_info.get("author", ""),
            "category": anchor_info.get("category", ""),
            "NameAsBundle": bundle_name,
        }
        if screenshot_src.is_file():
            shutil.copy2(screenshot_src, page_path / screenshot_name)
            page_info["screenshot"] = screenshot_name
        _write_modinfo(page_path / MODINFO_NAME, page_info)
        log(f"    '{extra.name}' -> '{page_name}/{extra.name}' (신규 modinfo.ini 생성)")

    return True
