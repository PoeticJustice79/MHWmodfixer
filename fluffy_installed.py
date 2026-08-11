"""Optional enhancement to the native-loose-file occupancy check (see
`game_archive.find_loose_files`): resolves WHICH mod a conflicting loose
file actually belongs to, by reading Fluffy Mod Manager's own
`installed.ini` (its per-game "currently deployed" manifest) --
found 2026-08-10 at `<fluffy_root>/Games/MonsterHunterWilds/installed.ini`.

The native-file check alone (mod-manager-agnostic, works for anyone) can
only say "something is already here" -- it has no way to know WHICH mod
put it there. `installed.ini` is Fluffy-specific but adds exactly that:
one `[Section]` per installed/enabled mod page, each listing every
natives/-relative file path it deploys via repeated `file=` lines
(confirmed real, e.g. `file=natives/STM/Art/Model/Item/it00/00/0000/
it0000_0000_0.mdf2.45`). A page that ISN'T currently enabled never gets
its files copied into natives/ at all, so this only ever lists what's
ACTUALLY occupying a slot right now. This is purely a naming enhancement
-- if no Fluffy path is configured or `installed.ini` can't be read, the
caller falls back to showing the raw occupying file name instead (see
gui.py's retarget dialogs).

Custom line-based parser, not `configparser`: a section's `file=` key
repeats many times per section (once per deployed file), and
`configparser` only keeps the last value for a repeated key.
"""
from __future__ import annotations

import re
from pathlib import Path

INSTALLED_INI_REL = "Games/MonsterHunterWilds/installed.ini"

_SECTION_RE = re.compile(r"^\[(.+)\]$")
_VERSION_SUFFIX_RE = re.compile(r"\.\d+$")


def _normalize(path: str) -> str:
    """"natives/.../it0000_0000_0.mdf2.45" -> "natives/.../it0000_0000_0.mdf2"
    (also lowercased, forward-slashed) -- occupancy lookup doesn't depend
    on matching the exact version suffix Fluffy happens to have deployed,
    only the underlying path."""
    return _VERSION_SUFFIX_RE.sub("", path.replace("\\", "/").lower())


def installed_ini_path(fluffy_root: str | Path) -> Path:
    return Path(fluffy_root) / INSTALLED_INI_REL


def parse_installed_ini(path: str | Path) -> dict[str, list[str]]:
    """{"natives/.../foo.mdf2" (normalized): [mod section name, ...]} --
    a path CAN legitimately be claimed by more than one installed mod
    page (e.g. two pages both shipping the same file unchanged), so this
    is a list, not a single name. Returns {} (never raises) if the file
    doesn't exist or can't be read -- callers treat that the same as
    "name unknown," falling back to the raw file name instead."""
    index: dict[str, list[str]] = {}
    current_section = None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                m = _SECTION_RE.match(line)
                if m:
                    current_section = m.group(1)
                    continue
                if current_section is None:
                    continue
                if line.lower().startswith("file="):
                    raw_path = line[len("file="):].strip()
                    index.setdefault(_normalize(raw_path), []).append(current_section)
    except OSError:
        return {}
    return index


def find_occupant_names(index: dict[str, list[str]], natives_relative_path: str) -> list[str]:
    """The deduplicated, sorted list of mod section names occupying this
    single natives/-relative path (any version suffix) -- empty if
    `installed.ini` doesn't know about it (e.g. no Fluffy path configured,
    or the occupying file wasn't deployed by Fluffy)."""
    return sorted(set(index.get(_normalize(natives_relative_path), [])))
