"""Maintainer tool for the RSZ field-layout snapshot rsz_layout.py loads at
runtime (see that module's docstring for what it's used for).

Why this exists: rsz_layout.fits_current_layout() can only tell a genuinely
safe CRC patch apart from a dangerous one if its registry actually describes
the CURRENTLY installed game build. Every title update can reshape RSZ
classes, so the snapshot goes stale exactly when the game updates -- the
same day mods relying on it start needing repair. Confirmed necessary the
hard way: this project shipped a crash (2026-08-08, SilverWolf mod) that a
stale/absent snapshot couldn't have caught, and separately discovered its
own long-bundled tools/rszmhwilds.json (100MB, gitignored, not this file)
was silently one whole title update behind without anyone noticing.

Three subcommands:

    python tools/bake_rsz_snapshot.py bake <raw_registry.json> [--rotate] [--label L]
    python tools/bake_rsz_snapshot.py list
    python tools/bake_rsz_snapshot.py import <snapshot_file> --as current|previous [--label L]

bake    Turns a raw community RSZ type-registry dump (rszmhwilds.json from
        the REasy project, ~100MB, typeIDHash -> {crc, name, fields}) into
        the compact gzipped snapshot this project actually ships.
        --rotate archives the existing "current" snapshot as "previous"
        first, so today's current survives as tomorrow's previous --
        another community fixer's README states the same rule plainly: "don't
        lose the previous one -- after a game update, today's current
        becomes tomorrow's previous." Skip --rotate on the very first bake
        of a new registry generation; use it when re-baking after a title
        update.

        The raw dump has no way to distinguish "this class truly has zero
        fields" from "this class was never dumped" -- unlike
        another community fixer's own baked snapshot, which keeps a separate
        confirmed-fieldless list. A type with an empty "fields" list here is
        therefore always treated as unverifiable by rsz_layout.py, never as
        confirmed-zero-length -- fewer files can be positively verified than
        with their snapshot, but nothing here is ever guessed.

list    Shows every rsz_fields_mhwilds*.json.gz snapshot next to this
        script -- label, when it was baked, where it came from, how many
        typed classes -- so it's obvious at a glance what "current" and
        "previous" actually are without decompressing anything by hand.

import  Installs a snapshot someone else shares as this project's current
        or previous. Understands three shapes: this project's own compact
        format (just relabels and installs it), a raw rszmhwilds.json-style
        dump (bakes it first), or another community fixer's own two-version
        rszlayouts_MHWILDS.json.gz (pick which half with --half). This is
        how a real "previous" registry gets acquired for a version this
        project never independently dumped -- borrowing one from someone
        who already has it is far cheaper than re-deriving it, and is
        exactly how this project's own TU5 "current" snapshot was obtained
        on 2026-08-08 (see CLAUDE.md).

Nothing under here is read by MHWmodfixer.exe at runtime except whichever
file is literally named rsz_fields_mhwilds.json.gz -- "previous" and any
other labeled snapshot are inert reference material until something (a
future migrate() feature) is built to read a second registry.
"""
import argparse
import datetime
import gzip
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CURRENT_PATH = HERE / "rsz_fields_mhwilds.json.gz"
PREVIOUS_PATH = HERE / "rsz_fields_mhwilds_previous.json.gz"


def _read_snapshot(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def _write_snapshot(path: Path, entries: dict, label: str, source: str, game_update_date: str | None = None):
    payload = dict(entries)
    payload["_meta"] = {
        "label": label,
        "baked_at": datetime.date.today().isoformat(),
        "game_update_date": game_update_date or "unknown",
        "source": source,
        "entry_count": len(entries),
    }
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=9) as f:
        json.dump(payload, f, separators=(",", ":"))


def _entries_only(snapshot: dict) -> dict:
    return {k: v for k, v in snapshot.items() if k != "_meta"}


def bake_raw_dump(raw_path: Path) -> dict:
    """Raw rszmhwilds.json-style dump -> this project's compact per-type shape."""
    with open(raw_path, encoding="utf-8") as f:
        raw = json.load(f)
    out = {}
    for key, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        fields = entry.get("fields")
        if not fields:
            continue  # can't tell "zero fields" from "not dumped" -- see module docstring
        out[key] = {
            "n": entry.get("name", ""),
            "f": [
                [f["name"], f["size"], f["align"], bool(f["array"]),
                 f["type"] in ("String", "Resource")]
                for f in fields
            ],
        }
    return out


def bake_two_version_snapshot(path: Path, half: str) -> tuple[dict, str]:
    """another community fixer's rszlayouts_MHWILDS.json.gz -> (entries, label).

    Keeps its "fieldless" list as explicit zero-field markers, unlike
    bake_raw_dump() -- this format actually distinguishes that case."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        snap = json.load(f)
    version = snap["versions"][half]
    out = {
        key: {"n": entry["n"], "f": entry["f"]}
        for key, entry in version["types"].items()
    }
    for key in version.get("fieldless", {}):
        out[key] = {"n": "", "f": [], "fieldless": True}
    return out, version.get("label", half)


def detect_and_convert(path: Path, half: str | None) -> tuple[dict, str]:
    """Returns (entries, default_label) for any of the three shapes this
    tool understands. Raises ValueError if the file matches none of them."""
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            data = json.load(f)
    except gzip.BadGzipFile:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

    if "versions" in data:
        if half is None:
            raise ValueError("this is a two-version snapshot (has 'versions') -- pass --half current|previous")
        return bake_two_version_snapshot(path, half)

    sample = next((v for k, v in data.items() if k != "_meta" and isinstance(v, dict)), None)
    if sample is not None and "f" in sample and "n" in sample:
        return _entries_only(data), (data.get("_meta") or {}).get("label", path.stem)

    # otherwise assume a raw rszmhwilds.json-style dump
    return bake_raw_dump(path), path.stem


def cmd_bake(args):
    entries = bake_raw_dump(Path(args.raw_registry))
    print(f"baked {len(entries)} typed classes from {args.raw_registry}")
    if not entries:
        sys.exit("nothing to write -- refusing to replace the existing snapshot with an empty one")

    if args.rotate:
        if CURRENT_PATH.exists():
            shutil.copyfile(CURRENT_PATH, PREVIOUS_PATH)
            print(f"archived current -> {PREVIOUS_PATH.name}")
        else:
            print("no existing current snapshot to archive (first bake?)")

    label = args.label or f"baked {datetime.date.today().isoformat()}"
    _write_snapshot(CURRENT_PATH, entries, label, source=f"raw dump {Path(args.raw_registry).name}",
                     game_update_date=args.game_date)
    print(f"wrote {CURRENT_PATH.name} ({CURRENT_PATH.stat().st_size / 1e6:.1f} MB)")
    print("Remember to verify this snapshot against the live game before trusting it "
          "(compare a common type's crc, e.g. via.render.Mesh, from a real donor file "
          "against this dump -- see CLAUDE.md's 2026-08-08 entry for how that was done).")


def cmd_list(args):
    found = sorted(HERE.glob("rsz_fields_mhwilds*.json.gz"))
    if not found:
        print("no snapshots here yet")
        return
    for path in found:
        try:
            snap = _read_snapshot(path)
        except Exception as exc:
            print(f"{path.name}: [unreadable: {exc}]")
            continue
        meta = snap.get("_meta", {})
        n = meta.get("entry_count", len(_entries_only(snap)))
        role = "current" if path == CURRENT_PATH else "previous" if path == PREVIOUS_PATH else "other"
        print(f"{path.name}  [{role}]")
        print(f"  label:            {meta.get('label', '(no metadata -- baked before this tool tracked it)')}")
        print(f"  game_update_date: {meta.get('game_update_date', '?')}")
        print(f"  baked_at:         {meta.get('baked_at', '?')}")
        print(f"  source:           {meta.get('source', '?')}")
        print(f"  types:      {n}")
        print(f"  file size:  {path.stat().st_size / 1e6:.2f} MB")


def cmd_import(args):
    src = Path(args.snapshot_file)
    entries, default_label = detect_and_convert(src, args.half)
    if not entries:
        sys.exit("converted snapshot is empty -- refusing to install it")
    label = args.label or default_label
    dest = CURRENT_PATH if args.as_ == "current" else PREVIOUS_PATH
    if dest.exists() and not args.force:
        sys.exit(f"{dest.name} already exists -- pass --force to overwrite, "
                 f"or `bake --rotate` first if you meant to archive it instead")
    _write_snapshot(dest, entries, label, source=f"imported from {src.name}", game_update_date=args.game_date)
    print(f"installed {len(entries)} typed classes as {dest.name} (label: {label!r})")
    print("This snapshot has NOT been verified against your installed game -- "
          "do that before trusting a fix that relied on it (see CLAUDE.md).")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p_bake = sub.add_parser("bake", help="build the current snapshot from a raw rszmhwilds.json dump")
    p_bake.add_argument("raw_registry")
    p_bake.add_argument("--rotate", action="store_true", help="archive the existing current snapshot as previous first")
    p_bake.add_argument("--label", default=None, help="human-readable label, e.g. 'TU6'")
    p_bake.add_argument("--game-date", default=None, help="date the game update this describes actually shipped, e.g. 2026-08-04 (NOT today's date -- that's baked_at)")
    p_bake.set_defaults(func=cmd_bake)

    p_list = sub.add_parser("list", help="show every snapshot next to this script")
    p_list.set_defaults(func=cmd_list)

    p_import = sub.add_parser("import", help="install a snapshot someone else shared")
    p_import.add_argument("snapshot_file")
    p_import.add_argument("--as", dest="as_", choices=("current", "previous"), required=True)
    p_import.add_argument("--half", choices=("current", "previous"), default=None,
                          help="which half to take, if snapshot_file is a two-version file")
    p_import.add_argument("--label", default=None)
    p_import.add_argument("--game-date", default=None, help="date the game update this describes actually shipped, e.g. 2026-08-04 (NOT today's date)")
    p_import.add_argument("--force", action="store_true", help="overwrite an existing snapshot at the destination")
    p_import.set_defaults(func=cmd_import)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
