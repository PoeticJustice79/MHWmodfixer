"""
Batch-repair Monster Hunter Wilds cosmetic mods broken by a game update.

The problem: a cosmetic mod ships an .mdf2.NN material file. When Capcom
updates the game, the vanilla material layout for that same mesh can change
(new shader params, reordered fields, etc.) even though the mod's texture
overrides are still perfectly good files -- the mod's .mdf2 is just built on
a stale skeleton, so the game rejects/misrenders it.

The fix: for each broken mod .mdf2 file, find the file at the same in-game
path freshly extracted from the CURRENT game version ("vanilla"), copy that
file's structure wholesale, and only reapply the mod's texture path
overrides onto it (matched by material name + texture slot name). See
mdf2.py and merge.py for how that's actually done at the byte level.

You need to supply your own fresh vanilla extraction (e.g. via REtool /
ree-pak-gui / RE.PAK.Tool against the game's current re_chunk_000.pak +
patches) -- this script does not touch the pak files themselves.

Usage:
    python fix_mods.py --mods "D:\\path\\to\\extracted\\mod\\natives" ^
                        --vanilla "D:\\path\\to\\fresh\\extraction" ^
                        [--output "D:\\path\\to\\fixed\\output"] ^
                        [--dry-run] [--no-backup]

If --output is omitted, fixed files are written back into --mods in place
(a .bak copy of each original is kept unless --no-backup is passed).
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path, PurePosixPath

from mdf2 import Mdf2File, numVersion_from_filename
from merge import merge_material_textures

MDF2_RE = re.compile(r"\.mdf2\.(\d+)$", re.IGNORECASE)


def canonical_rel(path: Path, root: Path) -> PurePosixPath:
    """Relative path with any leading .../natives/ wrapper stripped, so mods
    packaged with different wrapper folder layouts still match against a
    vanilla extraction that starts directly at STM/... (or whatever the pak
    root folders are)."""
    parts = path.relative_to(root).parts
    for i, p in enumerate(parts):
        if p.lower() == "natives":
            parts = parts[i + 1:]
            break
    return PurePosixPath(*parts)


def strip_version(rel: PurePosixPath) -> str:
    return MDF2_RE.sub(".mdf2", str(rel))


def find_mdf2_files(root: Path):
    for p in root.rglob("*"):
        if p.is_file() and MDF2_RE.search(p.name):
            yield p


def build_vanilla_index(vanilla_dir: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for p in find_mdf2_files(vanilla_dir):
        key = strip_version(canonical_rel(p, vanilla_dir))
        index[key] = p
    return index


def process_one(mod_path: Path, vanilla_path: Path, mods_root: Path,
                 output_root: Path | None, dry_run: bool, no_backup: bool,
                 log) -> int:
    mod_data = mod_path.read_bytes()
    vanilla_data = vanilla_path.read_bytes()
    mod_nv = numVersion_from_filename(mod_path.name)
    vanilla_nv = numVersion_from_filename(vanilla_path.name)

    mod_mdf = Mdf2File(mod_data, mod_nv)
    vanilla_mdf = Mdf2File(vanilla_data, vanilla_nv)

    changed = merge_material_textures(vanilla_mdf, mod_mdf, log=log)
    result = vanilla_mdf.to_bytes()

    new_name = MDF2_RE.sub(f".mdf2.{vanilla_nv}", mod_path.name)
    mod_rel = mod_path.relative_to(mods_root)

    if output_root is not None:
        out_path = output_root / mod_rel.parent / new_name
    else:
        out_path = mod_path.with_name(new_name)

    log(f"    {changed} texture path(s) restored; version {mod_nv} -> {vanilla_nv}")

    if dry_run:
        log(f"    [dry-run] would write {out_path}")
        return changed

    out_path.parent.mkdir(parents=True, exist_ok=True)

    if output_root is None:
        if not no_backup:
            backup_path = mod_path.with_name(mod_path.name + ".bak")
            if not backup_path.exists():
                shutil.copy2(mod_path, backup_path)
        if out_path != mod_path and mod_path.exists():
            mod_path.unlink()

    out_path.write_bytes(result)
    log(f"    [fixed] wrote {out_path}")
    return changed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mods", required=True, type=Path,
                    help="Folder containing the broken mod's files (a natives/... subtree, or a folder full of them)")
    ap.add_argument("--vanilla", required=True, type=Path,
                    help="Folder with a fresh extraction of the CURRENT game version's files")
    ap.add_argument("--output", type=Path, default=None,
                    help="Write fixed files here instead of overwriting --mods in place")
    ap.add_argument("--dry-run", action="store_true", help="Report what would happen without writing anything")
    ap.add_argument("--no-backup", action="store_true", help="Don't keep a .bak copy when overwriting in place")
    args = ap.parse_args(argv)

    if not args.mods.is_dir():
        print(f"error: --mods path does not exist or is not a folder: {args.mods}", file=sys.stderr)
        return 2
    if not args.vanilla.is_dir():
        print(f"error: --vanilla path does not exist or is not a folder: {args.vanilla}", file=sys.stderr)
        return 2

    vanilla_index = build_vanilla_index(args.vanilla)
    print(f"Indexed {len(vanilla_index)} vanilla .mdf2 file(s) under {args.vanilla}\n")

    fixed = skipped = errors = 0
    total_tex_changed = 0

    mod_files = sorted(find_mdf2_files(args.mods))
    if not mod_files:
        print(f"No .mdf2.<N> files found under {args.mods}")
        return 1

    for mod_path in mod_files:
        rel = canonical_rel(mod_path, args.mods)
        key = strip_version(rel)
        print(str(rel))
        vanilla_path = vanilla_index.get(key)
        if vanilla_path is None:
            print(f"    [skip] no matching vanilla file for {key}")
            skipped += 1
            continue
        try:
            changed = process_one(mod_path, vanilla_path, args.mods, args.output,
                                   args.dry_run, args.no_backup, log=print)
            total_tex_changed += changed
            fixed += 1
        except Exception as e:
            print(f"    [error] {e}")
            errors += 1

    print(f"\nDone. fixed={fixed} skipped={skipped} errors={errors} "
          f"texture_paths_restored={total_tex_changed}")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
