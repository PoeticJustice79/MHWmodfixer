"""
Heuristics for finding the real vanilla file a mod's file was built from,
when the mod's own in-pak-style path doesn't exist in the vanilla game at
all -- which happens for "custom slot" mods (installed via a mod manager
under a fake character code, e.g. mh03, that stands in for a real vanilla
one, e.g. ch03, so multiple mods can't collide over the same equipment
slot). Confirmed against the live game + the community MHWs_STM_Release.list
filelist: "mh03" never appears in vanilla, but the identical slot/variant
numbers exist under "ch03".
"""
from __future__ import annotations

import re

_MH_SLOT_RE = re.compile(r"(?<![a-z0-9])mh(\d\d)", re.IGNORECASE)


def candidate_donor_paths(rel_path_no_version: str) -> list[str]:
    """Returns candidate in-pak paths to try, in priority order: the exact
    path first (covers plain texture-replacer mods that keep the original
    vanilla identity), then heuristic substitutions for known custom-slot
    conventions."""
    candidates = [rel_path_no_version]
    swapped = _MH_SLOT_RE.sub(r"ch\1", rel_path_no_version)
    if swapped != rel_path_no_version:
        candidates.append(swapped)
    return candidates
