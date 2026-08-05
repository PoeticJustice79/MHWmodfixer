"""
Whole-game mmtr (shader) index: when a mod material's shader doesn't exist
anywhere in its own file or its sibling pieces (slot_merge.py's first two
match tiers), this searches across the WHOLE game for any material using
that exact shader, as a last-resort structural donor template. Confirmed
useful in practice: a 10-material weapon VFX mdf2 had one material
("lambert33") using a shader ("Base_ATOS_Emit_FX_Detail_RT_VFX.mmtr") that
didn't appear anywhere else in that mod's own file -- but 87 other
materials across the game use that exact shader, any of which is an
equally valid structural template (only textures ever get copied from the
mod; everything else comes from whichever donor is picked).

Built from a bundled filelist of known mdf2 paths
(tools/mdf2_filelist.txt, extracted from the community-maintained
MHWs_STM_Release.list -- see donor.py/slot_merge.py for why *this* mod's
own scope isn't enough on its own). Fetches the CURRENT version of each
candidate straight out of the live game paks and indexes every material
by its mmtr; takes roughly 30 seconds the first time (reading ~10k small
entries), so it's built LAZILY -- only when something actually needs it,
not on every run -- and cached to disk afterward like game_archive.py's
own pak index (same game-folder fingerprint invalidation).

This is deliberately a last resort, tried only after both narrower tiers
fail: it can't disambiguate between many candidates as precisely as
"same file" or "same equipment set" can (see slot_merge._pick_best),
so it's more likely to pick a structurally-compatible-but-not-identical
donor. Since only texture paths are ever copied from the mod, this is
still safe -- the picked donor's OWN shader parameters/gpbf/etc. are used
as-is -- but the specific default values a texture slot inherits if the
mod doesn't override it may differ visually from what the original
(pre-break) mod looked like.
"""
from __future__ import annotations

import pickle
import re
import sys
from pathlib import Path

from game_archive import GameArchive, _CACHE_DIR, _discover_paks, _fingerprint
from mdf2 import Mdf2File, detect_numVersion
from mdf2_slice import extract_material

_MDF2_RE = re.compile(r"\.mdf2\.\d+$")


def _filelist_path() -> Path:
    here = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return here / "tools" / "mdf2_filelist.txt"


def _load_candidate_bases() -> list[str]:
    p = _filelist_path()
    if not p.exists():
        return []
    with open(p, "r", encoding="utf-8", errors="ignore") as f:
        lines = [l.strip() for l in f if l.strip()]
    return sorted(set(_MDF2_RE.sub("", l) for l in lines))


class WholeGameIndex:
    def __init__(self, game: GameArchive, log=lambda s: None, use_cache: bool = True):
        self._by_mmtr: dict[str, list[tuple[str, dict]]] = {}

        pak_paths = _discover_paks(game.game_dir)
        fp = _fingerprint(pak_paths)
        cache_file = _CACHE_DIR / f"mmtr_index_{fp}.pkl"

        if use_cache and cache_file.exists():
            log("loading cached whole-game shader index...")
            try:
                with open(cache_file, "rb") as f:
                    self._by_mmtr = pickle.load(f)
                log(f"  {sum(len(v) for v in self._by_mmtr.values())} materials across "
                    f"{len(self._by_mmtr)} shaders (from cache)")
                return
            except Exception as e:
                log(f"  [warn] shader index cache load failed ({e}), rebuilding")

        bases = _load_candidate_bases()
        log(f"building whole-game shader index from {len(bases)} known mdf2 paths "
            f"(one-time, roughly 30s)...")
        skipped = 0
        for base in bases:
            try:
                found = game.find_versioned(base, "mdf2")
                if found is None:
                    continue
                path, raw = found
                nv = detect_numVersion(raw)
                if nv is None:
                    continue
                mdf = Mdf2File(raw, nv)
                for i, mat in enumerate(mdf.materials):
                    blob = extract_material(mdf, i)
                    self._by_mmtr.setdefault(mat.mmtr_path, []).append((path, blob))
            except Exception:
                # detect_numVersion can occasionally land on a bucket that
                # round-trips the file's own bytes but still doesn't parse
                # this ONE material's fields sanely (e.g. a stray numVersion
                # this format never actually uses in practice) -- one bad
                # file shouldn't abort indexing the other ~9900.
                skipped += 1
                continue
        if skipped:
            log(f"  [warn] skipped {skipped} candidate file(s) that failed to parse cleanly")

        log(f"  indexed {sum(len(v) for v in self._by_mmtr.values())} materials across "
            f"{len(self._by_mmtr)} shaders")

        if use_cache:
            try:
                _CACHE_DIR.mkdir(parents=True, exist_ok=True)
                with open(cache_file, "wb") as f:
                    pickle.dump(self._by_mmtr, f)
            except Exception as e:
                log(f"  [warn] failed to write shader index cache: {e}")

    def find_by_mmtr(self, mmtr_path: str) -> list[tuple[str, dict]]:
        return self._by_mmtr.get(mmtr_path, [])


class LazyWholeGameIndex:
    """Defers building WholeGameIndex until the first actual lookup, so
    mods that never need this tier never pay its ~30s one-time cost."""

    def __init__(self, game: GameArchive, log=lambda s: None):
        self._game = game
        self._log = log
        self._index: WholeGameIndex | None = None

    def find_by_mmtr(self, mmtr_path: str) -> list[tuple[str, dict]]:
        if self._index is None:
            self._index = WholeGameIndex(self._game, log=self._log)
        return self._index.find_by_mmtr(mmtr_path)
