"""One-time baker: converts the community armor-slot physics reference
spreadsheet ("MHWs 방어구ID" -- community-compiled, originally by
Quaysar/RayVVV, Korean translation by 몬붕이) into the compact
tools/armor_slots_ch03.json.gz bundled with the app, powering the
"적용 방어구 변경" (retarget) tab's compatibility list.

Only the objective columns are baked (slot number, armor name, variant,
per-piece physics tokens, slinger presence) -- the spreadsheet's personal
mod-pack annotation columns are deliberately dropped.

Usage:  python tools/bake_armor_slots.py "<path to the .xlsx>"
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

from openpyxl import load_workbook

OUT_PATH = Path(__file__).resolve().parent / "armor_slots_ch03.json.gz"

# Column layout in the source sheet (1-based): B=set number, C=name,
# D=variant, E..I=pieces 1-5 (arm/body/helm/leg/waist), J=slinger √/×.
COL_SET, COL_NAME, COL_VARIANT = 2, 3, 4
COL_PIECES = [5, 6, 7, 8, 9]
COL_SLINGER = 10
DATA_START_ROW = 5

KNOWN_TOKENS = {"clsp", "chain", "gpuc"}


def _parse_piece_cell(value) -> list[str] | None:
    """Returns the list of physics tokens for one piece, or None when the
    cell carries no usable per-piece data. Cells like "chain X"/"chain O"
    (shorthand rows the sheet uses for accessories/simple sets, not tied
    to a specific piece) also yield None -- those slots get an "unknown"
    profile and are excluded from automatic compatibility matching rather
    than guessed at."""
    if value is None:
        return None
    tokens = str(value).replace(" ", " ").split()
    if any(t in ("X", "O", "x", "o") for t in tokens):
        return None
    out = [t for t in tokens if t.lower() in KNOWN_TOKENS]
    return out if out else None


def _assign_genders(slots: dict[str, dict]) -> None:
    """Fills in each entry's "gender" field ('male'/'female'/None), in
    place. The sheet's 번호2 (variant) column doesn't carry an explicit
    gender marker -- per the user, a variant ending in 0 is the 남성
    (male) cut and the SIBLING variant ending in 1 (same set, same
    leading digits) is the 여성 (female) cut of the identical armor.
    Only labeled when BOTH siblings actually exist for that set --
    single-variant entries (accessories like glasses/necklaces, e.g.
    "089 깃 한 가닥 목걸이" variant 000 alone) are NOT a male/female pair
    and are deliberately left unlabeled rather than guessed at from the
    trailing digit alone, which would mislabel every ungendered
    accessory as "male"."""
    by_set: dict[str, set[str]] = {}
    for v in slots.values():
        by_set.setdefault(v["set"], set()).add(v["variant"])
    for v in slots.values():
        variant, set_no = v["variant"], v["set"]
        if not variant or variant[-1] not in ("0", "1"):
            v["gender"] = None
            continue
        sibling = variant[:-1] + ("1" if variant[-1] == "0" else "0")
        if sibling in by_set.get(set_no, ()):
            v["gender"] = "male" if variant[-1] == "0" else "female"
        else:
            v["gender"] = None


def bake(xlsx_path: Path) -> dict:
    wb = load_workbook(xlsx_path, data_only=True)
    ws = wb[wb.sheetnames[0]]

    slots: dict[str, dict] = {}
    current_set = None
    current_name = None
    for row in ws.iter_rows(min_row=DATA_START_ROW, values_only=False):
        cells = {c.column: c.value for c in row}
        set_no = cells.get(COL_SET)
        name = cells.get(COL_NAME)
        variant = cells.get(COL_VARIANT)
        if set_no is not None:
            current_set = str(set_no).strip()
        if name is not None:
            current_name = str(name).strip()
        if current_set is None or variant is None:
            continue
        variant = str(variant).strip()
        if not variant.isdigit():
            continue

        pieces = {}
        any_data = False
        for i, col in enumerate(COL_PIECES, start=1):
            tokens = _parse_piece_cell(cells.get(col))
            if tokens is not None:
                pieces[str(i)] = tokens
                any_data = True
        slinger_raw = cells.get(COL_SLINGER)
        slinger = None
        if slinger_raw is not None:
            s = str(slinger_raw).strip()
            slinger = True if "√" in s else False if s in ("×", "x", "X") else None

        slots[f"{current_set}/{variant}"] = {
            "set": current_set,
            "variant": variant,
            "name": current_name or "?",
            "pieces": pieces if any_data else None,  # None => profile unknown
            "slinger": slinger,
        }
    _assign_genders(slots)
    return slots


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    slots = bake(Path(sys.argv[1]))
    known = sum(1 for v in slots.values() if v["pieces"])
    payload = {"_meta": {"source": "community armor-slot physics reference (personal columns stripped)",
                          "entries": len(slots), "with_profile": known},
               "slots": slots}
    with gzip.open(OUT_PATH, "wt", encoding="utf-8", compresslevel=9) as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"baked {len(slots)} slot-variants ({known} with a usable physics profile) -> {OUT_PATH}")


if __name__ == "__main__":
    main()
