"""Maintainer CLI for the RSZ field-layout snapshot rsz_layout.py manages
(a single "current" plus an unlimited, dated archive of everything that
was ever current) -- see that module's "snapshot management" section for
the actual logic; this is a thin command-line wrapper around it, plus the
one thing an ordinary user's GUI never needs: baking a fresh snapshot from
a raw ~100MB community registry dump. See rsz_layout.py's top-of-file
docstring for why this snapshot exists and what it protects.

    python tools/bake_rsz_snapshot.py bake <raw_registry.json> [--rotate] [--label L] [--game-date D]
    python tools/bake_rsz_snapshot.py list
    python tools/bake_rsz_snapshot.py import <snapshot_file> --as current|archive [--half current|previous] [--label L] [--game-date D]

bake    Turns a raw rszmhwilds.json-style dump (typeIDHash -> {crc, name,
        fields}, from the REasy project) into the compact snapshot this
        project ships, and installs it as "current". --rotate archives
        whatever was current first -- every snapshot that's ever been
        current stays available afterward, under tools/rsz_archive/,
        instead of only the single most recent one. Skip --rotate only on
        the very first bake of a new registry generation.

list    Shows current, then every archived snapshot newest-first: label,
        game_update_date (when that title update actually shipped --
        distinct from baked_at, when this project processed it), source,
        how many typed classes.

import  Installs a snapshot someone else shares -- this project's own
        format, a raw community dump, or a community fixer's own
        two-version rszlayouts_MHWILDS.json.gz (pick a half with --half).
        --as archive stashes it without touching current at all. This is
        how a real historical registry gets acquired for a version this
        project never independently dumped -- borrowing one from someone
        who already has it is far cheaper than re-deriving it, and is
        exactly how this project's own TU5 "current" snapshot was
        obtained on 2026-08-08 (see CLAUDE.md #9).

None of this is verified against the live game automatically. Cross-check
a common type's crc (e.g. via.render.Mesh) from a real donor file against
whatever you just installed before trusting a fix that relies on it -- the
same way this was done on 2026-08-08.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import rsz_layout


def cmd_bake(args):
    meta = rsz_layout.install_snapshot(
        Path(args.raw_registry), as_role="current", label=args.label,
        game_update_date=args.game_date, rotate=args.rotate)
    print(f"wrote {rsz_layout.CURRENT_PATH.name}: {meta['entry_count']} typed classes, label={meta['label']!r}")
    if args.rotate:
        print(f"whatever was current before this is now archived under {rsz_layout.ARCHIVE_DIR.name}/")
    print("Remember to verify this against the live game before trusting it "
          "(compare a common type's crc, e.g. via.render.Mesh, from a real donor file -- see CLAUDE.md #9).")


def cmd_list(args):
    for entry in rsz_layout.list_snapshots():
        print(f"{entry['path'].name}  [{entry['role']}]")
        if not entry["exists"]:
            print("  (not present)")
            continue
        meta = entry["meta"] or {}
        print(f"  label:            {meta.get('label', '(no metadata -- baked before this tool tracked it)')}")
        print(f"  game_update_date: {meta.get('game_update_date', '?')}")
        print(f"  baked_at:         {meta.get('baked_at', '?')}")
        print(f"  source:           {meta.get('source', '?')}")
        print(f"  types:            {meta.get('entry_count', '?')}")
        print(f"  file size:        {entry['file_size'] / 1e6:.2f} MB")


def cmd_import(args):
    try:
        meta = rsz_layout.install_snapshot(
            Path(args.snapshot_file), as_role=args.as_, label=args.label,
            game_update_date=args.game_date, rotate=not args.no_rotate, half=args.half)
    except rsz_layout.SnapshotError as exc:
        sys.exit(str(exc))
    where = rsz_layout.CURRENT_PATH.name if args.as_ == "current" else f"{rsz_layout.ARCHIVE_DIR.name}/"
    print(f"installed {meta['entry_count']} typed classes as {where} (label: {meta['label']!r})")
    print("This snapshot has NOT been verified against your installed game -- "
          "do that before trusting a fix that relied on it (see CLAUDE.md #9).")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p_bake = sub.add_parser("bake", help="build the current snapshot from a raw rszmhwilds.json dump")
    p_bake.add_argument("raw_registry")
    p_bake.add_argument("--rotate", action="store_true", help="archive whatever was current first")
    p_bake.add_argument("--label", default=None, help="human-readable label, e.g. 'TU6'")
    p_bake.add_argument("--game-date", default=None, help="date the game update this describes actually shipped (NOT today's date)")
    p_bake.set_defaults(func=cmd_bake)

    p_list = sub.add_parser("list", help="show current and every archived snapshot")
    p_list.set_defaults(func=cmd_list)

    p_import = sub.add_parser("import", help="install a snapshot someone else shared")
    p_import.add_argument("snapshot_file")
    p_import.add_argument("--as", dest="as_", choices=("current", "archive"), required=True)
    p_import.add_argument("--half", choices=("current", "previous"), default=None,
                          help="which half to take, if snapshot_file is a two-version file")
    p_import.add_argument("--label", default=None)
    p_import.add_argument("--game-date", default=None, help="date the game update this describes actually shipped")
    p_import.add_argument("--no-rotate", action="store_true", help="overwrite current without archiving it first")
    p_import.set_defaults(func=cmd_import)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
