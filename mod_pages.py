"""Detects and extracts individual FOMOD-style "pages" (each its own
top-level folder with its own modinfo.ini) out of a multi-option mod
archive, so a user can pull out just ONE appearance/option as its own
standalone mod instead of the whole bundle.

Real motivating case (2026-08-15): "Summer Fleet Weapons" bundles several
unrelated weapon-type reskins as separate pages (Hammer, Hunting Horn,
Insect Glaive x2) in one archive. A user who only wants the Hammer page
had to be extracted and repaired by hand -- this module automates that
extraction step; the caller is still responsible for running the result
through the normal repair pipeline (auto_fix.process_mod()) since a
lone page pulled out of an old bundle is just as likely to be stale as
any other mod.

Reuses fluffy_repackage.py's own modinfo.ini reading/writing and page-
folder detection helpers rather than duplicating that logic -- both
modules are about the same underlying "FOMOD page" concept, just from
opposite ends (fluffy_repackage.py WRAPS loose extras into new pages;
this module PULLS ONE EXISTING page back out on its own)."""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

import fluffy_repackage as _fr


@dataclass
class ModPage:
    folder: Path       # the page's own top-level folder inside the mod archive
    info: dict          # parsed modinfo.ini key/value pairs
    files: list = field(default_factory=list)  # absolute paths of every file under `folder`

    @property
    def display_name(self) -> str:
        return self.info.get("name") or self.info.get("NameAsBundle") or self.folder.name


def detect_mod_pages(mod_root: Path) -> list[ModPage]:
    """One ModPage per top-level folder that carries its own modinfo.ini.
    A mod with no such folders (the common flat single-mod layout) returns
    an empty list -- the caller should treat that as "nothing to choose
    between", not as an error."""
    top_entries = list(mod_root.iterdir())
    pages = []
    for folder in _fr._modinfo_folders(top_entries):
        info = _fr._read_modinfo(folder / _fr.MODINFO_NAME)
        files = [p for p in folder.rglob("*") if p.is_file()]
        pages.append(ModPage(folder=folder, info=info, files=files))
    return pages


def extract_page_standalone(page: ModPage, out_root: Path) -> None:
    """Copies `page`'s own files into out_root, FLATTENED to out_root's own
    top level (out_root/modinfo.ini, out_root/natives/..., not nested
    under the page's original folder name) so the result is a normal,
    directly-installable single-page Fluffy mod. modinfo.ini is rewritten:
    `AddOnFor` is dropped (it names a base bundle that won't be present in
    this standalone extract, and an orphaned AddOnFor page is what
    confused Fluffy's installer the first time this was done by hand,
    2026-08-15) and `NameAsBundle` is set if the page never had one of its
    own (falls back to the page's own `name` field, then its folder name)."""
    out_root.mkdir(parents=True, exist_ok=True)
    for p in page.files:
        rel = p.relative_to(page.folder)
        dst = out_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dst)

    info = {k: v for k, v in page.info.items() if k.lower() != "addonfor"}
    if not any(k.lower() == "nameasbundle" for k in info):
        info["NameAsBundle"] = info.get("name", page.folder.name)
    _fr._write_modinfo(out_root / _fr.MODINFO_NAME, info)
