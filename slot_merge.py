"""
Donor-material resolution for mods that restructure a mesh's material list
(so index/name-based matching against a single same-path vanilla donor
isn't reliable -- see the module docstring in mdf2_slice.py for why).

Match priority for a given mod material:
  1. Exact name match within its OWN same-path vanilla donor file.
  2. Unique mmtr (shader) match within that same donor file.
  3. (only if cross-piece search is enabled) mmtr match anywhere in the
     pool of ALL vanilla donor files resolved during this run -- i.e. the
     other pieces of the same equipment set.
  4. (only if a whole_game_lookup is supplied) mmtr match anywhere in the
     ENTIRE game -- see whole_game_index.py. Confirmed necessary in
     practice: a 10-material weapon VFX file had one material whose shader
     didn't exist anywhere else in that mod's own file (no siblings to
     borrow from either, since it's a standalone weapon, not part of a
     multi-piece equipment set) -- but the shader is used by 87 other
     materials elsewhere in the game.
If none of these produce a match, the material is left unresolved and the
caller should skip rebuilding that mod file rather than guess.
"""
from __future__ import annotations


def _is_usesc(name: str) -> bool:
    return name.lower().endswith("_usesc")


def _category(path: str) -> str | None:
    """.../art/model/item/... -> 'item', .../art/model/character/... ->
    'character', etc. Used to prefer same-category donors (a weapon's
    material should borrow from another weapon/item, not a character)
    when a whole-game search turns up many otherwise-equal candidates --
    confirmed to matter in practice: an unrelated character asset was
    picked over 59 available item-category ones sharing the same shader,
    for a weapon mod, and the mod then didn't visually apply at all in
    game (no crash, no error -- the engine silently fell back to vanilla
    for the whole material array rather than accept the mismatched one)."""
    parts = path.lower().split("/")
    try:
        i = parts.index("model")
        return parts[i + 1]
    except (ValueError, IndexError):
        return None


def _pick_best(candidates: list[tuple[str, dict]], mod_mat: dict, log,
               category_hint: str | None = None) -> tuple[str, dict] | None:
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    pool = candidates
    if category_hint is not None:
        same_cat = [c for c in pool if _category(c[0]) == category_hint]
        if same_cat:
            pool = same_cat

    want = _is_usesc(mod_mat["name"])
    filtered = [c for c in pool if _is_usesc(c[1]["name"]) == want]
    pool = filtered if len(filtered) == 1 else (filtered or pool)

    if len(pool) > 1:
        log(f"    [warn] ambiguous donor match for material {mod_mat['name']!r} "
            f"({len(pool)} candidates share mmtr {mod_mat['mmtr_path']!r}) -- picking {pool[0][0]!r}")
    return pool[0]


def find_donor_for_material(
    mod_mat: dict,
    own_pool: list[tuple[str, dict]],
    global_pool: list[tuple[str, dict]],
    allow_cross_piece: bool,
    log=lambda s: None,
    whole_game_lookup=None,
) -> tuple[dict, str, str] | None:
    """own_pool / global_pool: [(source_path, material_blob), ...].
    whole_game_lookup: optional callable(mmtr_path) -> [(source_path, blob), ...]
    (see whole_game_index.LazyWholeGameIndex.find_by_mmtr), consulted only
    as a last resort. Returns (donor_blob, source_path, match_kind) or None."""
    # own_pool's own source path (a real, known-good in-game path, whether
    # from a loose-file donor or a pak-hash-matched one) tells us what
    # asset category this mod file itself belongs to, for preferring
    # same-category donors if the whole-game tier ends up needed.
    category_hint = _category(own_pool[0][0]) if own_pool else None

    for src, blob in own_pool:
        if blob["name"] == mod_mat["name"]:
            return blob, src, "own-file exact name"

    same_mmtr = [(src, b) for src, b in own_pool if b["mmtr_path"] == mod_mat["mmtr_path"]]
    picked = _pick_best(same_mmtr, mod_mat, log)
    if picked:
        return picked[1], picked[0], "own-file mmtr match"

    if allow_cross_piece:
        same_mmtr_global = [(src, b) for src, b in global_pool if b["mmtr_path"] == mod_mat["mmtr_path"]]
        picked = _pick_best(same_mmtr_global, mod_mat, log)
        if picked:
            return picked[1], picked[0], "cross-piece mmtr match"

    if whole_game_lookup is not None:
        candidates = whole_game_lookup(mod_mat["mmtr_path"])
        picked = _pick_best(candidates, mod_mat, log, category_hint=category_hint)
        if picked:
            log(f"    [info] material {mod_mat['name']!r}: no donor in this mod or its equipment set -- "
                f"borrowed from elsewhere in the game ({picked[0]!r})")
            return picked[1], picked[0], "whole-game mmtr match"

    return None
