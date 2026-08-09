"""
Fully automatic entry point: point this at a mod archive (zip/rar/7z) or an
already-extracted mod folder, and it will:
  1. extract the archive if needed
  2. read the CURRENT game version's files directly out of
     re_chunk_000.pak (+ patches) + its sub_000.pak (+ patches) --
     no ree-pak-gui/REtool step, no manual extraction
  3. find each .mdf2 file's vanilla donor(s) -- whether it's a loose file
     under natives/... (handling custom-slot mods where the mod's own path
     doesn't exist in vanilla at all, see donor.py) or an entry inside the
     mod's own standalone .pak file (matched by hash directly against the
     game's own pak index, see pak_mod_fix.py -- no path-guessing needed
     there since a hash match against the live game IS the vanilla donor)
  4. figure out which materials are actually STALE -- note this is NOT the
     same as "the mod's trailing .mdf2.NN version number differs from the
     donor's": Capcom has shipped content changes (different prop/gpbf/
     texture-slot counts) under the *same* trailing number, so the only
     reliable signal is comparing each mod material's structure against
     its resolved donor's structure directly
  5. rebuild only the files that actually need it, splicing in the right
     donor material(s) (possibly borrowed from a *different* piece of the
     same equipment set, when a mod restructures the material list -- see
     slot_merge.py / mdf2_slice.py) with the mod's texture overrides
     reapplied
  6. write a complete, ready-to-install fixed copy of the mod (loose files
     patched in place; standalone .pak mods get a freshly rebuilt .pak)

Usage:
    python auto_fix.py "<mod.zip or mod folder>" [--game <game_dir>] [--output <dir>] [--no-cross-piece]

--game defaults to the MHWilds install this was built against:
    D:\\SteamLibrary\\steamapps\\common\\MonsterHunterWilds

--no-cross-piece restricts donor matching to "safe" cases only (exact name
or unambiguous shader match within the SAME piece's own vanilla file);
anything that would otherwise require borrowing a material from a sibling
piece is skipped instead of guessed.
"""
from __future__ import annotations

import argparse
import copy
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from archive_extract import extract_archive
from donor import candidate_donor_paths
from game_archive import GameArchive
from mdf2 import Mdf2File, numVersion_from_filename
from mdf2_slice import assemble_mdf2, extract_material
from pfb_fix import find_pfb_files, resolve_and_fix_pfbs, resolve_and_fix_avp_files
from mesh_check import check_mesh_mdf2_consistency
from slot_merge import find_donor_for_material

DEFAULT_GAME_DIR = r"D:\SteamLibrary\steamapps\common\MonsterHunterWilds"
MDF2_RE = re.compile(r"\.mdf2\.(\d+)$", re.IGNORECASE)


def find_mdf2_files(root: Path):
    for p in root.rglob("*"):
        if p.is_file() and MDF2_RE.search(p.name):
            yield p


def to_pak_style_path(rel: Path) -> str:
    """Turns a filesystem-relative path (as found under the extracted mod
    folder) into the natives/... form the game's pak entries actually use.
    Mods are often packaged with a wrapper folder before natives/ (e.g.
    "[MM] Banshee/natives/STM/..."), so we anchor on the natives/ segment
    itself rather than assuming the mod's root IS the natives root."""
    parts = rel.parts
    for i, p in enumerate(parts):
        if p.lower() == "natives":
            return "natives/" + "/".join(parts[i + 1:])
    return "natives/" + "/".join(parts)


def _structure_key(mat: dict) -> tuple:
    """What actually determines byte-layout compatibility with the current
    game build. Texture PATHS are deliberately excluded -- a working mod's
    textures always differ from vanilla's by design, so that's not a sign
    of staleness. Prop/texture/gpbf *counts* (and which texture slot NAMES
    exist) changing is what signals the shader template moved on."""
    return (
        len(mat["props"]),
        tuple(sorted(t["type"] for t in mat["textures"])),
        mat["gpbf_split"],
        mat["mmtr_path"],
    )


@dataclass
class MaterialPlan:
    mod_mat: dict
    donor_blob: dict | None
    donor_src: str | None
    match_kind: str | None
    stale: bool


@dataclass
class FilePlan:
    rel: Path
    mod_path: Path
    mod_nv: int
    donor_nv: int | None
    materials: list[MaterialPlan] = field(default_factory=list)

    @property
    def unresolved(self) -> bool:
        return any(m.donor_blob is None for m in self.materials)

    @property
    def needs_rebuild(self) -> bool:
        """True iff there's at least one RESOLVED, stale material worth
        writing a fix for -- deliberately independent of `unresolved`
        (process_mod() fixes what it can and leaves any unresolved
        material exactly as shipped, rather than skipping the whole file
        just because one material has no safe donor)."""
        return any(m.stale for m in self.materials if m.donor_blob is not None)


def apply_texture_overrides(donor_mat: dict, mod_mat: dict, log) -> tuple[dict, int]:
    """Returns (new_material_blob, num_textures_changed). Structural fields
    that reflect the CURRENT mdf2 FORMAT (padding, prop/texture slot
    layout, gpbf, mmtr) come from the donor, since those are what actually
    go stale across a game update. shading_type and alpha_flags_raw do
    NOT -- they're per-material RENDER STATE (e.g. two-sided/alpha-blend
    behavior), the same kind of author-set tuning as texture paths and
    prop values, not something a title update changes the "correct" value
    of. Confirmed as a real bug via a Nexus report (Kersiak, 2026-08-08):
    taking alpha_flags_raw from the donor was silently stripping a mod's
    own alpha/two-sided settings on every material this function touched
    -- verified directly against a real mod (Endfield LiJiyan) where all 7
    resolved materials had a mod alpha_flags_raw of 9b000008 replaced with
    the donor's 98000088, matching the reported "meshes that were
    2sided-alpha now look transparent from the inside" symptom exactly.

    The material *name* is kept as the mod's own, not the donor's --
    confirmed via real in-game testing this matters when several materials
    in one file are spliced in from different donor files: Capcom reuses
    generic names (e.g. "lambert2") across many unrelated files, so taking
    the donor's name verbatim can leave two or more materials in the same
    assembled file sharing an identical name (and therefore identical
    name_hash). A known-working reference fix (community-made, confirmed
    working pre-patch) kept each slot's original name unique; a from-
    scratch reassembly that instead copied donor names produced an
    all-materials-collapse-to-one-name file which silently failed to
    render the mod's textures at all despite every other check passing.

    Props are ALSO carried over from the mod (matched by name, falling
    back to the donor's own value for any prop that's new on the donor's
    side) -- confirmed necessary via real in-game testing: a cross-piece/
    whole-game donor can share the exact same mmtr (shader) as the mod's
    material while still being a semantically different object (e.g. a
    leg accessory borrowed for an arm-sleeve material), and props encode
    PER-INSTANCE tuning (pattern/color/tiling), not just shader structure.
    Taking the donor's props wholesale in that case produced a completely
    wrong-looking (but not broken/crashing) result -- random unrelated
    colors and pattern tiling bleeding through despite every texture path
    being correct. Matching by name (not position) is required because
    the same-mmtr donor and the mod's own material can still have a
    different prop count/order when Capcom adds new shader parameters
    over time.

    GPBF (GPU byte-address-buffer) slots get the SAME name-matched
    override treatment, for the same reason -- confirmed real via a Nexus
    report + user in-game screenshot (TiNE's Qipao Ver.R Remastered,
    2026-08-09): the mod's own material has its `MultiBlend_BAB` gpbf slot
    pointed at `systems/rendering/Empty.gpbf` (author's own, deliberate
    "no multi-blend buffer" placeholder -- consistent with its
    MultiBlend_ALBDMap/NRMMap texture slots also being NullGray/NullNormal
    placeholders), but this function was leaving `gpbf_entries` as an
    untouched copy of the DONOR's, so the final material silently pointed
    at the DONOR's real per-character blend buffer instead -- data sized
    and laid out for a completely different mesh/UV layout. The engine
    still renders (no crash, no missing-texture warning: the buffer PATH
    is valid, just semantically wrong), producing exactly the reported
    symptom: correct silhouette/design, wrong color/blending. `gpbf_entries`
    is a flat list of `gpbf_split[0]` (name, h1, h2) slot entries followed
    by `gpbf_split[1]` (path, 0, 1) value entries, paired by matching
    index (i-th slot name <-> i-th path) -- confirmed by direct inspection
    of this material's real data, both counts equal (4, 4)."""
    mod_tex_by_type = {t["type"]: t["path"] for t in mod_mat["textures"]}
    mod_props_by_name = {p["name"]: p["values"] for p in mod_mat["props"]}
    if len(mod_props_by_name) != len(mod_mat["props"]):
        log(f"    [warn] material {mod_mat['name']!r}: mod has duplicate prop name(s) -- "
            f"only the last one of each duplicate will be used as an override source")
    mod_gpbf_names, mod_gpbf_paths = mod_mat["gpbf_entries"][:mod_mat["gpbf_split"][0]], \
        mod_mat["gpbf_entries"][mod_mat["gpbf_split"][0]:]
    mod_gpbf_path_by_slot = {}
    if len(mod_gpbf_names) == len(mod_gpbf_paths):
        mod_gpbf_path_by_slot = {n[0]: p[0] for n, p in zip(mod_gpbf_names, mod_gpbf_paths)}
    new_mat = copy.deepcopy(donor_mat)
    new_mat["name"] = mod_mat["name"]
    new_mat["shading_type"] = mod_mat["shading_type"]
    new_mat["alpha_flags_raw"] = mod_mat["alpha_flags_raw"]
    changed = 0
    donor_types = {t["type"] for t in new_mat["textures"]}
    for t in new_mat["textures"]:
        new_path = mod_tex_by_type.get(t["type"])
        if new_path is not None and new_path != t["path"]:
            t["path"] = new_path
            changed += 1
    extra = set(mod_tex_by_type) - donor_types
    if extra:
        log(f"    [warn] material {mod_mat['name']!r}: mod texture slot(s) {sorted(extra)} "
            f"don't exist on the matched donor material -- dropped")

    donor_prop_names = {p["name"] for p in new_mat["props"]}
    if len(donor_prop_names) != len(new_mat["props"]):
        log(f"    [warn] material {mod_mat['name']!r}: donor has duplicate prop name(s) -- "
            f"all of them will receive the same overridden value")
    for p in new_mat["props"]:
        mod_values = mod_props_by_name.get(p["name"])
        if mod_values is not None and len(mod_values) == len(p["values"]) and mod_values != p["values"]:
            p["values"] = mod_values
    extra_props = set(mod_props_by_name) - donor_prop_names
    if extra_props:
        log(f"    [warn] material {mod_mat['name']!r}: mod prop(s) {sorted(extra_props)} "
            f"don't exist on the matched donor material -- dropped")

    donor_gpbf_names, donor_gpbf_paths = new_mat["gpbf_entries"][:new_mat["gpbf_split"][0]], \
        new_mat["gpbf_entries"][new_mat["gpbf_split"][0]:]
    if mod_gpbf_path_by_slot and len(donor_gpbf_names) == len(donor_gpbf_paths):
        for i, (slot_name, _h1, _h2) in enumerate(donor_gpbf_names):
            mod_path = mod_gpbf_path_by_slot.get(slot_name)
            if mod_path is not None and mod_path != donor_gpbf_paths[i][0]:
                donor_gpbf_paths[i] = (mod_path, donor_gpbf_paths[i][1], donor_gpbf_paths[i][2])
        new_mat["gpbf_entries"] = donor_gpbf_names + donor_gpbf_paths

    return new_mat, changed


def _resolve_loose_files(mod_root: Path, game: GameArchive, global_pool: list, allow_cross_piece: bool,
                          whole_game_lookup, log, progress_cb=None) -> list[FilePlan]:
    progress_cb = progress_cb or (lambda phase, done, total: None)
    mod_files = sorted(find_mdf2_files(mod_root))
    total = len(mod_files)
    per_file: dict[Path, dict] = {}

    for i, mod_path in enumerate(mod_files, start=1):
        progress_cb("loose_scan", i, total)
        rel = mod_path.relative_to(mod_root)
        pak_path = to_pak_style_path(rel)
        base_no_version = MDF2_RE.sub("", pak_path)

        mod_data = mod_path.read_bytes()
        mod_nv = numVersion_from_filename(mod_path.name)
        mod_mdf = Mdf2File(mod_data, mod_nv)

        donor_path = donor_bytes = None
        for cand in candidate_donor_paths(base_no_version):
            found = game.find_versioned(cand, "mdf2")
            if found is not None:
                donor_path, donor_bytes = found
                break

        own_pool = []
        donor_nv = None
        if donor_path is not None:
            donor_nv = numVersion_from_filename(donor_path)
            donor_mdf = Mdf2File(donor_bytes, donor_nv)
            own_pool = [(donor_path, extract_material(donor_mdf, i)) for i in range(len(donor_mdf.materials))]
            global_pool.extend(own_pool)

        per_file[mod_path] = {
            "rel": rel, "mod_mdf": mod_mdf, "mod_nv": mod_nv,
            "donor_nv": donor_nv, "own_pool": own_pool,
        }

    plans = []
    for mod_path in mod_files:
        info = per_file[mod_path]
        mod_mats = [extract_material(info["mod_mdf"], i) for i in range(len(info["mod_mdf"].materials))]
        mat_plans = []
        for mm in mod_mats:
            donor_hit = find_donor_for_material(mm, info["own_pool"], global_pool, allow_cross_piece,
                                                 log=log, whole_game_lookup=whole_game_lookup)
            if donor_hit is None:
                mat_plans.append(MaterialPlan(mm, None, None, None, stale=True))
                continue
            donor_blob, donor_src, match_kind = donor_hit
            stale = _structure_key(mm) != _structure_key(donor_blob)
            mat_plans.append(MaterialPlan(mm, donor_blob, donor_src, match_kind, stale))
        plans.append(FilePlan(info["rel"], mod_path, info["mod_nv"], info["donor_nv"], mat_plans))
    return plans


def plan_mod(mod_root: Path, game: GameArchive, allow_cross_piece: bool, log=lambda s: None, progress_cb=None,
             force_unresolved_pfbs: bool = False, preserve_extra_pfb_components: bool = False):
    """Resolves donors and determines staleness for every .mdf2 file (loose
    or inside the mod's own .pak files), but never writes anything --
    shared by the diagnostic pass (diagnose.py) and the actual fixer
    (process_mod) so they can never disagree. Returns (file_plans, pak_plans).
    `allow_cross_piece` only affects whether pieces can borrow a donor
    material from each other; it's applied when resolving, and unresolved/
    ambiguous materials are simply reported as such regardless.
    `progress_cb(phase, done, total)`, if given, is forwarded to whichever
    of the loose-file / pak-entry scans is running -- see their own
    docstrings for what `phase` can be. There's no single unified 0-100%
    across the whole function (the two scans have unrelated totals); the
    GUI shows `phase` alongside done/total instead of pretending otherwise.
    `force_unresolved_pfbs`/`preserve_extra_pfb_components` only affect
    pak_plans' pfb_entries (a .pfb bundled inside a mod's own .pak); the
    diagnostic pass (diagnose.py) calls this without them, which is fine
    for the CRC-only/close-enough cases (still correctly flagged as
    needing a fix either way) but means a pak-pfb that would ONLY resolve
    with force/preserve-extra on isn't distinguishable from "nothing to
    fix" during diagnosis -- the exact same pre-existing gap loose-file
    pfb staleness already has (diagnose.py doesn't look at pfb_fix.py's
    plans at all), not a new one introduced here."""
    from pak_mod_fix import resolve_pak_files  # local import: avoids a cycle at module load time
    from whole_game_index import LazyWholeGameIndex

    global_pool: list[tuple[str, dict]] = []
    whole_game_lookup = LazyWholeGameIndex(game, log=log).find_by_mmtr
    file_plans = _resolve_loose_files(mod_root, game, global_pool, allow_cross_piece, whole_game_lookup, log,
                                       progress_cb=progress_cb)
    pak_plans = resolve_pak_files(mod_root, game, global_pool, allow_cross_piece, whole_game_lookup, log,
                                   progress_cb=progress_cb, force_unresolved_pfbs=force_unresolved_pfbs,
                                   preserve_extra_pfb_components=preserve_extra_pfb_components)
    return file_plans, pak_plans


def process_mod(mod_root: Path, output_root: Path, game: GameArchive, allow_cross_piece: bool, log,
                 force_unresolved_pfbs: bool = False, preserve_extra_pfb_components: bool = False,
                 progress_cb=None) -> dict:
    from pak_mod_fix import write_fixed_pak

    stats = {"fixed": 0, "already_current": 0, "skipped": 0, "errors": 0, "textures_restored": 0,
              "materials_left_unresolved": 0}

    file_plans, pak_plans = plan_mod(mod_root, game, allow_cross_piece, log=log, progress_cb=progress_cb,
                                      force_unresolved_pfbs=force_unresolved_pfbs,
                                      preserve_extra_pfb_components=preserve_extra_pfb_components)
    if not file_plans and not pak_plans:
        log(f"No .mdf2 content found under {mod_root} (loose or packed) -- nothing to fix "
            f"(other files will still be copied as-is)")
        return stats

    for plan in file_plans:
        log(f"{plan.rel}")

        unresolved_mats = [mp for mp in plan.materials if mp.donor_blob is None]
        resolved_stale = [mp for mp in plan.materials if mp.donor_blob is not None and mp.stale]

        if not resolved_stale:
            # Nothing to fix on the materials we CAN verify -- either every
            # material already matches the current structure (nothing to
            # do at all), or the only stale ones are also unresolved (no
            # donor to fix them against either way), so writing a file
            # would be a byte-identical no-op. Report unresolved materials
            # by name either way -- "0 fixed" must never look the same as
            # "we couldn't tell" (see the batch-summary note below).
            for mp in unresolved_mats:
                log(f"    [skip] no safe donor for material {mp.mod_mat['name']!r} "
                    f"(mmtr {mp.mod_mat['mmtr_path']!r})")
            if unresolved_mats:
                stats["skipped"] += 1
            else:
                log("    [ok] already matches the current game version's structure -- left untouched")
                stats["already_current"] += 1
            continue

        try:
            rebuilt = []
            total_changed = 0
            chosen_nv = plan.donor_nv
            for mp in plan.materials:
                if mp.donor_blob is None:
                    log(f"    [kept as shipped] material {mp.mod_mat['name']!r} -- no safe donor "
                        f"found (mmtr {mp.mod_mat['mmtr_path']!r}); left exactly as the mod shipped it")
                    rebuilt.append(mp.mod_mat)
                    continue
                log(f"    material {mp.mod_mat['name']!r} -> donor {mp.donor_blob['name']!r} "
                    f"from {mp.donor_src!r} ({mp.match_kind})")
                new_mat, changed = apply_texture_overrides(mp.donor_blob, mp.mod_mat, log)
                rebuilt.append(new_mat)
                total_changed += changed
                if chosen_nv is None:
                    chosen_nv = numVersion_from_filename(mp.donor_src)

            result = assemble_mdf2(rebuilt, chosen_nv)
            new_name = MDF2_RE.sub(f".mdf2.{chosen_nv}", plan.mod_path.name)
            out_path = output_root / plan.rel.parent / new_name
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(result)

            old_out_path = output_root / plan.rel
            if old_out_path != out_path and old_out_path.exists():
                old_out_path.unlink()

            if unresolved_mats:
                log(f"    [partial fix] {total_changed} texture path(s) restored on "
                    f"{len(plan.materials) - len(unresolved_mats)} material(s); "
                    f"{len(unresolved_mats)} left as shipped (no safe donor) -> "
                    f"{out_path.relative_to(output_root)}")
                stats["fixed"] += 1
                stats["textures_restored"] += total_changed
                stats["materials_left_unresolved"] += len(unresolved_mats)
            else:
                log(f"    [fixed] {total_changed} texture path(s) restored -> {out_path.relative_to(output_root)}")
                stats["fixed"] += 1
                stats["textures_restored"] += total_changed
        except Exception as e:
            log(f"    [error] {e}")
            stats["errors"] += 1

    # Accumulated across every pak_plan's pfb_entries (a mod can bundle more
    # than one .pak) -- merged with loose-file pfb_fix.py's own stats below
    # under the SAME stats["pfb_*"] keys, since both are just ".pfb needed
    # fixing," regardless of whether it shipped loose or inside a pak.
    pak_pfb_totals = {"fixed": 0, "crc_only": 0, "crc_only_extra": 0, "forced": 0, "unresolved": 0}

    for pak_plan in pak_plans:
        rel = pak_plan.pak_path.relative_to(mod_root)
        log(f"{rel}")

        if pak_plan.unresolved:
            log(f"    [skip] no vanilla donor found (by hash) for the mdf2 entry(ies) in this pak")
            stats["skipped"] += 1
            continue

        if not pak_plan.needs_rebuild:
            log("    [ok] already matches the current game version's structure -- left untouched")
            stats["already_current"] += 1
            continue

        try:
            total_changed, pak_pfb_stats = write_fixed_pak(pak_plan, output_root / rel, log)
            log(f"    [fixed] {total_changed} texture path(s) restored -> {rel}")
            stats["fixed"] += 1
            stats["textures_restored"] += total_changed
            for k in pak_pfb_totals:
                pak_pfb_totals[k] += pak_pfb_stats[k]
        except Exception as e:
            log(f"    [error] {e}")
            stats["errors"] += 1

    if any(pak_pfb_totals.values()):
        log(f"    ({pak_pfb_totals['fixed']} pak-bundled pfb/user/scn file(s) fixed, "
            f"{pak_pfb_totals['unresolved']} left unresolved)")

    pfb_files = list(find_pfb_files(mod_root))
    if pfb_files:
        log("\nRepairing .pfb files...")
        pfb_stats = resolve_and_fix_pfbs(mod_root, output_root, game, log,
                                          force_unresolved=force_unresolved_pfbs,
                                          preserve_extra=preserve_extra_pfb_components)
        if pfb_stats["unresolved"]:
            log(f"    ({pfb_stats['unresolved']} pfb file(s) couldn't be safely verified against the "
                f"current game and were left as-is)")
        if pfb_stats["forced"]:
            log(f"    ({pfb_stats['forced']} pfb file(s) were FORCE-fixed despite not safely "
                f"reconciling -- experimental, please verify these pieces in-game)")
        if pfb_stats["crc_only"]:
            log(f"    ({pfb_stats['crc_only']} pfb file(s) needed only a stale instance CRC patched, "
                f"with the mod's own content otherwise untouched)")
        if pfb_stats["crc_only_extra"]:
            log(f"    ({pfb_stats['crc_only_extra']} pfb file(s) also kept extra instances the current "
                f"donor doesn't have -- experimental option, please verify these pieces in-game)")
        stats["fixed"] += pfb_stats["fixed"]
    else:
        pfb_stats = {"fixed": 0, "unresolved": 0, "forced": 0, "crc_only": 0, "crc_only_extra": 0}

    avp_stats = resolve_and_fix_avp_files(mod_root, output_root, log)
    if avp_stats["fixed"]:
        log(f"\n({avp_stats['fixed']} avp.user file(s) had a self-reference pointing at "
            f"the wrong armor slot, fixed)")
    stats["fixed"] += avp_stats["fixed"]

    stats["pfb_fixed"] = pak_pfb_totals["fixed"] + pfb_stats["fixed"]
    stats["pfb_unresolved"] = pak_pfb_totals["unresolved"] + pfb_stats["unresolved"]
    stats["pfb_forced"] = pak_pfb_totals["forced"] + pfb_stats["forced"]
    stats["pfb_crc_only"] = pak_pfb_totals["crc_only"] + pfb_stats["crc_only"]
    stats["pfb_crc_only_extra"] = pak_pfb_totals["crc_only_extra"] + pfb_stats["crc_only_extra"]

    # Diagnostic-only -- this project has no way to safely reconcile a
    # mesh/mdf2 material mismatch (would need to touch mesh geometry data,
    # completely out of scope), only to warn that one exists before the
    # user finds out the hard way in-game. Runs against the final OUTPUT
    # files, so it catches a pre-existing authoring issue in the mod
    # itself just as well as anything this project's own fixes might
    # (currently never do, but could in the future) introduce.
    stats["mesh_mdf2_mismatches"] = check_mesh_mdf2_consistency(output_root, log)
    if stats["mesh_mdf2_mismatches"]:
        log(f"\n({stats['mesh_mdf2_mismatches']} mesh/mdf2 material mismatch(es) found -- "
            f"these can NOT be auto-fixed by this tool, but are very likely to cause a "
            f"black screen or checkerboard texture in-game for the affected piece(s))")

    return stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mod", type=Path, help="Mod archive (.zip/.rar/.7z) or an already-extracted mod folder")
    ap.add_argument("--game", type=Path, default=Path(DEFAULT_GAME_DIR), help="Monster Hunter Wilds install folder")
    ap.add_argument("--output", type=Path, default=None, help="Where to write the fixed mod (default: <mod>_fixed next to the input)")
    ap.add_argument("--no-cross-piece", action="store_true",
                    help="Safe mode: only fix materials matchable within their own piece's vanilla file; skip the rest")
    ap.add_argument("--force-unresolved-pfbs", action="store_true",
                    help="Experimental: force wholesale-replace even pfb files that don't safely reconcile with "
                         "the current donor. Confirmed working on several real mods' Waist pieces; confirmed to "
                         "pick a wrong donor on at least one real Arm piece with no true vanilla equivalent. "
                         "Off by default -- verify forced pieces in-game before trusting them.")
    ap.add_argument("--preserve-extra-pfb-components", action="store_true",
                    help="Experimental: when a pfb's own RSZ instances are a superset of the current donor's "
                         "(the mod added components vanilla doesn't have), keep the mod's own bytes -- patching "
                         "only stale CRCs among the shared instances -- instead of discarding the extra ones via "
                         "donor-replace. Confirmed to preserve real customization (a mod's own physics chain) on "
                         "one mod; confirmed to diverge from an already-verified-working build on another, where "
                         "the 'extra' instances turned out to be stale pre-simplification leftovers, not real "
                         "customization -- the two are structurally indistinguishable. Off by default -- verify "
                         "affected pieces in-game before trusting them.")
    args = ap.parse_args(argv)

    if not args.game.is_dir():
        print(f"error: game folder not found: {args.game}", file=sys.stderr)
        return 2

    work_dir = None
    if args.mod.is_dir():
        mod_root = args.mod
    elif args.mod.is_file():
        work_dir = Path(tempfile.mkdtemp(prefix="mhwmodfix_"))
        print(f"Extracting {args.mod} -> {work_dir}")
        mod_root = extract_archive(args.mod, work_dir)
    else:
        print(f"error: mod path not found: {args.mod}", file=sys.stderr)
        return 2

    output_root = args.output or args.mod.with_name(
        (args.mod.stem if args.mod.is_file() else args.mod.name) + "_fixed"
    )
    print(f"Output -> {output_root}")

    print("\nCopying mod files to output (will patch .mdf2 files in place after)...")
    if output_root.exists():
        shutil.rmtree(output_root)
    shutil.copytree(mod_root, output_root)

    print("\nIndexing current game version's pak archives...")
    game = GameArchive(args.game, log=print)

    print("\nRepairing .mdf2 files...")
    stats = process_mod(mod_root, output_root, game, allow_cross_piece=not args.no_cross_piece, log=print,
                         force_unresolved_pfbs=args.force_unresolved_pfbs,
                         preserve_extra_pfb_components=args.preserve_extra_pfb_components)

    from fluffy_repackage import repackage_for_fluffy
    repackage_for_fluffy(output_root, log=print)

    if work_dir is not None:
        shutil.rmtree(work_dir, ignore_errors=True)

    print(f"\nDone. fixed={stats['fixed']} already_current={stats['already_current']} "
          f"skipped={stats['skipped']} errors={stats['errors']} "
          f"texture_paths_restored={stats['textures_restored']}")
    print(f"Fixed mod is at: {output_root}")
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
