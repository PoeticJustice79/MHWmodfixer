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

# Confirmed real, in-game verified (2026-08-09): "OVR Rogue - Bifrost" white-
# material/missing-wings report (CLAUDE.md #19) traced to `Base_Equip_Fur.mmtr`
# being effectively retired -- only 2 materials in the whole game still use it
# (`WholeGameIndex.find_by_mmtr()`), so donor-matching always falls back to a
# distant, semantically-unrelated candidate. The mod's OWN author's real fix
# (a freshly obtained, independently authored update, #24) rebuilt every
# affected material under plain `Base_Equip.mmtr` instead of patching data
# under the old shader. Reproducing that exact transformation mechanically
# (this map + `apply_texture_overrides()`'s existing name-matched field
# carryover) against a real whole-game `Base_Equip.mmtr` donor matched the
# author's own new file almost field-for-field (only creative retuning --
# recolored props, one VFX texture swap -- differed, which no automated tool
# should invent), and the rebuilt file was confirmed to fix the white-
# material/missing-wings symptom in a live in-game test. Deliberately a
# hardcoded, individually-verified map, NOT a general "find any shader with
# a similar name" heuristic -- a wrong guess here would silently reshape a
# material under an unrelated schema. Only ever consulted when the caller
# opts in (`shader_migration_map` param), matching this project's existing
# `preserve_extra_pfb_components`/`force_unresolved_pfbs` opt-in pattern for
# anything that changes MORE than a stale field value.
SHADER_MIGRATION_MAP = {
    "MaterialShader/Variation/Base_Equip_Fur.mmtr": "MaterialShader/Variation/Base_Equip.mmtr",
}


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


def _find_shader_migration_donor(
    mod_mat: dict, target_mmtr: str, whole_game_lookup, log,
) -> tuple[dict, str, str] | None:
    """Looks for a donor under `target_mmtr` specifically -- an EXACT match
    first (no `_NoMultiBlend`-variant tolerance): the whole point of a
    shader migration is reaching the FULL-featured current shader, and the
    same-path vanilla donor for a migrated material is often only the
    narrower NoMultiBlend sibling (confirmed for the Bifrost case -- using
    that instead of a true whole-game `Base_Equip.mmtr` match produced a
    smaller field set than the real author's own fix). Falls back to
    variant-tolerant matching only if no exact match exists anywhere.
    Returns None (never guesses further) if neither search finds anything --
    the caller falls through to this material's normal, non-migrated
    resolution."""
    if whole_game_lookup is None:
        return None
    exact_hits = whole_game_lookup(target_mmtr)
    picked = _pick_best(exact_hits, mod_mat, log)
    if picked:
        return picked[1], picked[0], f"shader migration ({mod_mat['mmtr_path']!r} -> {target_mmtr!r})"
    for variant in _mmtr_variants(target_mmtr):
        if variant == target_mmtr:
            continue
        hits = whole_game_lookup(variant)
        picked = _pick_best(hits, mod_mat, log)
        if picked:
            return picked[1], picked[0], f"shader migration ({mod_mat['mmtr_path']!r} -> {variant!r})"
    return None


def find_donor_for_material(
    mod_mat: dict,
    own_pool: list[tuple[str, dict]],
    global_pool: list[tuple[str, dict]],
    allow_cross_piece: bool,
    log=lambda s: None,
    whole_game_lookup=None,
    shader_migration_map: dict[str, str] | None = None,
) -> tuple[dict, str, str] | None:
    """own_pool / global_pool: [(source_path, material_blob), ...].
    whole_game_lookup: optional callable(mmtr_path) -> [(source_path, blob), ...]
    (see whole_game_index.LazyWholeGameIndex.find_by_mmtr), consulted only
    as a last resort. `shader_migration_map`: optional, see
    `SHADER_MIGRATION_MAP`'s docstring -- opt-in only, tried BEFORE this
    material's own mmtr tiers (a known-retired shader would otherwise
    "successfully" match a bad donor via its own tiers and never reach
    here). Falls through to normal resolution if the migration search
    itself finds nothing. Returns (donor_blob, source_path, match_kind) or
    None."""
    own_mmtr = mod_mat["mmtr_path"]
    if shader_migration_map and own_mmtr in shader_migration_map:
        migrated = _find_shader_migration_donor(
            mod_mat, shader_migration_map[own_mmtr], whole_game_lookup, log)
        if migrated is not None:
            return migrated

    # own_pool's own source path (a real, known-good in-game path, whether
    # from a loose-file donor or a pak-hash-matched one) tells us what
    # asset category this mod file itself belongs to, for preferring
    # same-category donors if the whole-game tier ends up needed.
    category_hint = _category(own_pool[0][0]) if own_pool else None

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

    # EXACT-mmtr tiers first, across ALL scopes, before any variant-tolerant
    # tier gets a chance -- the no-exact-name-donor twin of #16's fix,
    # confirmed real the hard way (DOA "Rachel", 2026-08-09, GAME CRASH):
    # that mod's materials use `Base_Equip.mmtr` (fully alive game-wide,
    # 310 users) but have no same-named vanilla counterpart, so the old
    # tier order went straight to the own-file VARIANT-tolerant match --
    # the current vanilla file for that slot only carries the narrower
    # `_NoMultiBlend` sibling, so the rebuild silently DOWNGRADED the
    # material's own shader (mmtr comes from the donor by design, see
    # apply_texture_overrides()) and stripped its MultiBlend slots/props.
    # The author's own working update proves the correct fix: keep
    # `Base_Equip.mmtr`, just refresh the prop set to current. A wider-
    # scope donor with the RIGHT shader beats a nearby donor with the
    # wrong one; variant tolerance below remains only for the case where
    # the mod's exact mmtr has genuinely no live user anywhere (a
    # retired/split shader, _mmtr_variants()' original purpose).
    same_mmtr_exact = [(src, b) for src, b in own_pool if b["mmtr_path"] == own_mmtr]
    picked = _pick_best(same_mmtr_exact, mod_mat, log)
    if picked:
        return picked[1], picked[0], "own-file exact mmtr"

    if allow_cross_piece:
        global_exact = [(src, b) for src, b in global_pool if b["mmtr_path"] == own_mmtr]
        picked = _pick_best(global_exact, mod_mat, log, category_hint=category_hint)
        if picked:
            return picked[1], picked[0], "cross-piece exact mmtr"

    if whole_game_lookup is not None:
        hits = whole_game_lookup(own_mmtr)
        picked = _pick_best(hits, mod_mat, log, category_hint=category_hint)
        if picked:
            log(f"    [info] material {mod_mat['name']!r}: no exact-shader donor in this mod or its "
                f"equipment set -- borrowed from elsewhere in the game ({picked[0]!r})")
            return picked[1], picked[0], "whole-game exact mmtr"

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
