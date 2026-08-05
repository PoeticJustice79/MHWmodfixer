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
        return any(m.stale for m in self.materials) and not self.unresolved


def apply_texture_overrides(donor_mat: dict, mod_mat: dict, log) -> tuple[dict, int]:
    """Returns (new_material_blob, num_textures_changed). Only textures are
    ever taken from the mod; everything else (props, gpbf, mmtr, shading)
    comes from the donor untouched.

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
    over time."""
    mod_tex_by_type = {t["type"]: t["path"] for t in mod_mat["textures"]}
    mod_props_by_name = {p["name"]: p["values"] for p in mod_mat["props"]}
    new_mat = copy.deepcopy(donor_mat)
    new_mat["name"] = mod_mat["name"]
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
    for p in new_mat["props"]:
        mod_values = mod_props_by_name.get(p["name"])
        if mod_values is not None and len(mod_values) == len(p["values"]) and mod_values != p["values"]:
            p["values"] = mod_values
    extra_props = set(mod_props_by_name) - donor_prop_names
    if extra_props:
        log(f"    [warn] material {mod_mat['name']!r}: mod prop(s) {sorted(extra_props)} "
            f"don't exist on the matched donor material -- dropped")

    return new_mat, changed


def _resolve_loose_files(mod_root: Path, game: GameArchive, global_pool: list, allow_cross_piece: bool,
                          whole_game_lookup, log) -> list[FilePlan]:
    mod_files = sorted(find_mdf2_files(mod_root))
    per_file: dict[Path, dict] = {}

    for mod_path in mod_files:
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


def plan_mod(mod_root: Path, game: GameArchive, allow_cross_piece: bool, log=lambda s: None):
    """Resolves donors and determines staleness for every .mdf2 file (loose
    or inside the mod's own .pak files), but never writes anything --
    shared by the diagnostic pass (diagnose.py) and the actual fixer
    (process_mod) so they can never disagree. Returns (file_plans, pak_plans).
    `allow_cross_piece` only affects whether pieces can borrow a donor
    material from each other; it's applied when resolving, and unresolved/
    ambiguous materials are simply reported as such regardless."""
    from pak_mod_fix import resolve_pak_files  # local import: avoids a cycle at module load time
    from whole_game_index import LazyWholeGameIndex

    global_pool: list[tuple[str, dict]] = []
    whole_game_lookup = LazyWholeGameIndex(game, log=log).find_by_mmtr
    file_plans = _resolve_loose_files(mod_root, game, global_pool, allow_cross_piece, whole_game_lookup, log)
    pak_plans = resolve_pak_files(mod_root, game, global_pool, allow_cross_piece, whole_game_lookup, log)
    return file_plans, pak_plans


def process_mod(mod_root: Path, output_root: Path, game: GameArchive, allow_cross_piece: bool, log) -> dict:
    from pak_mod_fix import write_fixed_pak

    stats = {"fixed": 0, "already_current": 0, "skipped": 0, "errors": 0, "textures_restored": 0}

    file_plans, pak_plans = plan_mod(mod_root, game, allow_cross_piece, log=log)
    if not file_plans and not pak_plans:
        log(f"No .mdf2 content found under {mod_root} (loose or packed) -- nothing to fix "
            f"(other files will still be copied as-is)")
        return stats

    for plan in file_plans:
        log(f"{plan.rel}")

        if plan.unresolved:
            for mp in plan.materials:
                if mp.donor_blob is None:
                    log(f"    [skip] no safe donor for material {mp.mod_mat['name']!r} "
                        f"(mmtr {mp.mod_mat['mmtr_path']!r})")
            stats["skipped"] += 1
            continue

        if not plan.needs_rebuild:
            log("    [ok] already matches the current game version's structure -- left untouched")
            stats["already_current"] += 1
            continue

        try:
            rebuilt = []
            total_changed = 0
            chosen_nv = plan.donor_nv
            for mp in plan.materials:
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

            log(f"    [fixed] {total_changed} texture path(s) restored -> {out_path.relative_to(output_root)}")
            stats["fixed"] += 1
            stats["textures_restored"] += total_changed
        except Exception as e:
            log(f"    [error] {e}")
            stats["errors"] += 1

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
            total_changed = write_fixed_pak(pak_plan, output_root / rel, log)
            log(f"    [fixed] {total_changed} texture path(s) restored -> {rel}")
            stats["fixed"] += 1
            stats["textures_restored"] += total_changed
        except Exception as e:
            log(f"    [error] {e}")
            stats["errors"] += 1

    return stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mod", type=Path, help="Mod archive (.zip/.rar/.7z) or an already-extracted mod folder")
    ap.add_argument("--game", type=Path, default=Path(DEFAULT_GAME_DIR), help="Monster Hunter Wilds install folder")
    ap.add_argument("--output", type=Path, default=None, help="Where to write the fixed mod (default: <mod>_fixed next to the input)")
    ap.add_argument("--no-cross-piece", action="store_true",
                    help="Safe mode: only fix materials matchable within their own piece's vanilla file; skip the rest")
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
    stats = process_mod(mod_root, output_root, game, allow_cross_piece=not args.no_cross_piece, log=print)

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
