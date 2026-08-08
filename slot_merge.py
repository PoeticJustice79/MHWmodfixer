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

_MMTR_VARIANT_SUFFIX = "_NoMultiBlend"


def _mmtr_variants(mmtr_path: str) -> list[str]:
    """Capcom periodically splits a '_NoMultiBlend' variant out of an
    existing shader while the material's actual ROLE is unchanged --
    confirmed to recur across unrelated shader families (an equipment
    shader "Base_Equip" and a monster shader "Dynamic_ch90_156_0000" both
    got a "_NoMultiBlend" sibling added between when different mods were
    built and the current game version). Strict mmtr equality then makes
    an otherwise-perfect exact-name donor invisible to every match tier
    (it's simply not in the same-mmtr candidate pool at all), so donor
    search must also try the other spelling, not just the mod's own
    literal mmtr string."""
    suffix = _MMTR_VARIANT_SUFFIX + ".mmtr"
    if mmtr_path.endswith(suffix):
        return [mmtr_path, mmtr_path[: -len(suffix)] + ".mmtr"]
    if mmtr_path.endswith(".mmtr"):
        return [mmtr_path, mmtr_path[: -len(".mmtr")] + _MMTR_VARIANT_SUFFIX + ".mmtr"]
    return [mmtr_path]


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

    # An exact material-name match anywhere in the candidate pool almost
    # always means the mod author literally copied that specific material
    # wholesale from that specific source (e.g. a weapon splicing in named
    # materials borrowed from a monster's own model, all sharing a
    # monster-specific shader) -- confirmed necessary in practice: a weapon
    # mod embedding ~10 monster materials (body_1001/1002/1004/membrane/
    # back_ADD/eye/eye_cover/fulgurite_ADD, all sharing only a couple of
    # monster-specific shaders) had every one of them collapse onto
    # whichever candidate happened to sort first, even though the exact
    # same-named material existed among the candidates every time. This
    # must run BEFORE category/_usesc filtering, not after, since an
    # exact name match is a stronger signal than either.
    exact = [c for c in candidates if c[1]["name"] == mod_mat["name"]]
    if len(exact) == 1:
        return exact[0]
    if exact:
        candidates = exact

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
    own_mmtr = mod_mat["mmtr_path"]

    exact_name = next(((src, b) for src, b in own_pool if b["name"] == mod_mat["name"]), None)
    if exact_name is not None and exact_name[1]["mmtr_path"] == own_mmtr:
        return exact_name[1], exact_name[0], "own-file exact name"

    if exact_name is not None:
        # A same-named vanilla counterpart exists but uses a DIFFERENT mmtr --
        # before trusting it (and its likely-narrower structure) as the
        # donor, check whether the mod's OWN exact mmtr is still genuinely in
        # current use somewhere else in the game. Confirmed real (2026-08-08,
        # a DDDuck "AIO" armor mod): Capcom split a "_NoMultiBlend" sibling
        # out of "Base_Equip.mmtr" for this exact asset's current vanilla
        # file while keeping the material NAME the same -- even though
        # "Base_Equip.mmtr" itself is still fully alive (310 materials use it
        # game-wide right now). Trusting the name match unconditionally here
        # silently discarded the mod's still-fully-supported MultiBlend
        # texture slots/props (matched to the narrower sibling instead) even
        # though nothing about the mod's own material was actually stale.
        # Only fall through to the narrower same-name donor if the mod's own
        # exact mmtr can't be found intact anywhere else in the game either.
        own_exact_mmtr = [(src, b) for src, b in own_pool if b["mmtr_path"] == own_mmtr]
        picked = _pick_best(own_exact_mmtr, mod_mat, log)
        if picked:
            return picked[1], picked[0], "own-file exact mmtr (over narrower same-name donor)"

        if allow_cross_piece:
            global_exact_mmtr = [(src, b) for src, b in global_pool if b["mmtr_path"] == own_mmtr]
            picked = _pick_best(global_exact_mmtr, mod_mat, log, category_hint=category_hint)
            if picked:
                return picked[1], picked[0], "cross-piece exact mmtr (over narrower same-name donor)"

        if whole_game_lookup is not None:
            hits = whole_game_lookup(own_mmtr)
            picked = _pick_best(hits, mod_mat, log, category_hint=category_hint)
            if picked:
                log(f"    [info] material {mod_mat['name']!r}: current vanilla counterpart uses a "
                    f"narrower {exact_name[1]['mmtr_path']!r} -- keeping the mod's own {own_mmtr!r} "
                    f"instead, confirmed still in current use elsewhere ({picked[0]!r})")
                return picked[1], picked[0], "whole-game exact mmtr (over narrower same-name donor)"

        return exact_name[1], exact_name[0], "own-file exact name"

    mmtr_variants = _mmtr_variants(own_mmtr)

    same_mmtr = [(src, b) for src, b in own_pool if b["mmtr_path"] in mmtr_variants]
    picked = _pick_best(same_mmtr, mod_mat, log)
    if picked:
        return picked[1], picked[0], "own-file mmtr match"

    if allow_cross_piece:
        same_mmtr_global = [(src, b) for src, b in global_pool if b["mmtr_path"] in mmtr_variants]
        picked = _pick_best(same_mmtr_global, mod_mat, log, category_hint=category_hint)
        if picked:
            return picked[1], picked[0], "cross-piece mmtr match"

    if whole_game_lookup is not None:
        candidates = []
        seen = set()
        for variant in mmtr_variants:
            for src, blob in whole_game_lookup(variant):
                # dedupe by (source file, material name) -- NOT source file
                # alone: a single file can (and often does) contribute
                # several distinct materials that all match, and those must
                # not collapse into just the first one seen.
                key = (src, blob["name"])
                if key not in seen:
                    seen.add(key)
                    candidates.append((src, blob))
        picked = _pick_best(candidates, mod_mat, log, category_hint=category_hint)
        if picked:
            log(f"    [info] material {mod_mat['name']!r}: no donor in this mod or its equipment set -- "
                f"borrowed from elsewhere in the game ({picked[0]!r})")
            return picked[1], picked[0], "whole-game mmtr match"

    return None
