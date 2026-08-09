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

# Korean armor-set name -> official/community English name, for the
# non-Korean UI languages (en/ja/zh_tw/zh_cn all fall back to this one
# English string -- per the user, a real ja/zh translation isn't worth
# building if it's not readily available; English-only is an acceptable
# fallback for those). ONLY the entries this project could actually
# verify are included -- deliberately incomplete rather than guessed.
#
# Source: cross-referenced two independent sources, not translated by
# guesswork --
#   1. The user's own installed REFramework Lua mod ("FemaleBodySliders",
#      tools/autorun/FemaleBodySliders/ExtraLayeredArmorDictionary.lua)
#      maintains a real (set,variant)-keyed English armor-piece-name
#      table for its own UI. Parsed programmatically, matched against
#      this project's own (set,variant) keys, and only names with a
#      consistent majority across a set's variant/piece entries were
#      trusted.
#   2. A few of that table's names were stale/garbled (internal dev
#      names, not the shipped monster name -- e.g. "Rey Sand..." /
#      "Udra Mire..." / "Dahaad Shard...") -- corrected against
#      game8.co's full Monster Hunter Wilds armor-set list (the
#      confirmed shipped monster roster) before trusting them.
#
# Entries this project could NOT confidently resolve (mostly unique/DLC
# accessory items with no monster-name convention to cross-check against)
# are deliberately left OUT -- those keep showing their Korean name in
# every UI language rather than risk shipping a wrong guess. A few of
# these were later confirmed directly by the user (playing the actual
# game, or recognizing a name on sight) rather than any written source --
# noted individually below.
#
# Second pass (2026-08-09): cross-checked the whole table against
# mhwilds.kiranico.com's armor-series list, fetched in BOTH Korean
# (/ko/data/armor-series) and English (/data/armor-series) -- the two
# pages list every series in the same underlying order, so aligning them
# position-by-position gives a direct, non-guessed Korean<->English pair
# for each entry (confirmed reliable across 90+ consecutive positions
# with zero mismatches before diverging into content outside this
# project's own ch03-only scope). This corrected several earlier
# over-specified guesses of my own -- Kiranico's official set names use a
# shorter form than the full monster name for several of these (armor
# menus abbreviate; "고어"/"Gore" != the monster's full "Gore Magala",
# etc.) -- and added a handful of previously-unresolved names outright.
NAME_EN_OVERRIDES = {
    "가쟈우": "Gajau", "게리오스": "Gypceros", "고어": "Gore",
    "고우키": "Akuma",  # confirmed by the user directly -- MH's Street Fighter collab set
    "그라비드": "Gravios", "길드 크로스": "Guild Cross", "길드나이트(사전예약)": "Guild Knight",
    "병사의 갑주(디럭스)": "Feudal Soldier",  # confirmed by the user directly (Deluxe Edition bonus set)
    "길드에이스": "Guild Ace", "깃 한 가닥 목걸이": "Pinion Necklace", "다마스크": "Damascus",
    "다이버": "Diver", "다하딜라": "Dahaad", "데스기어": "Death Stench",
    "네라치카": "Comaqchi", "도베르": "Dober", "도샤구마": "Doshaguma", "라기아": "Lagiacrus",
    "라바라": "Lala Barina", "랑고스타": "Vespoid", "레기오스": "Seregios",
    "레다젤트": "Rey Dau", "레더": "Leather", "레우스": "Rathalos",
    "레이아": "Rathian", "멜호아": "Melahoa", "모험의 호크하트": "Hawkheart",
    "무구한 용": "Numinous", "미츠네": "Mizutsune", "발라": "Balahara",
    "배틀": "Battle", "본": "Bone", "봉인의 안대": "Sealed Eyepatch",
    "봉인의 용해포": "Sealed Dragon Cloth", "블랑고": "Blango", "블로썸": "Blossom",
    "브라치카": "Bulaqchi",
    "수호룡세크레트": "Guardian Seikret", "슈바르카": "Arkveld", "스퀘어글라스": "Square Glasses",
    "스자의 허리띠": "Suja's Belt", "스큐라": "Nerscylla", "시이우": "Xu Wu", "실드후드": "Sild",
    "아자라": "Ajarakan", "아즈즈": "Azuz", "아티어": "Artian",
    "아피": "Afi", "앵파": "Sakuratide", "언더림글라스": "Half Rim Glasses",
    "얼로이": "Alloy", "옷1": "Innerwear", "옷2": "Innerwear",
    "옷3": "Innerwear", "옷4": "Innerwear", "용왕의 척안": "Dragonking's Third Eye",
    "이그졸스": "Nu Udra",
    "잉곳": "Ingot", "조사단": "Commission", "지략의 안경": "Strategist Spectacles",
    "차타": "Chatacabra", "체인": "Chainmail", "콩가": "Conga",
    "쿠나파": "Kunafa", "쿡크": "Kut-Ku", "크라노다스": "Kranodath", "탈리오스": "Talioth",
    "클러크": "Clerk", "킹비트": "King Beetle", "투나물": "Uth Duna",
    "트리스": "Quematrice", "파피메르": "Butterfly", "푸포루": "Rompopolo",
    "필라길": "Piragill", "하이메탈": "High Metal", "하트글라스": "Lovely Shades",
    "헌신의 피어스": "Earrings of Dedication", "대식가의 귀걸이": "Gourmand's Earring",
    "호뢰악룡": "Guardian Fulgur", "호벽수": "Guardian Doshaguma",
    "호쇄인룡": "Guardian Arkveld", "호프": "Hope", "호화룡": "Guardian Rathalos",
    "호흉조룡": "Guardian Ebony", "히라바미": "Hirabami", "노블레스": "Noblesse",
}


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

        ko_name = current_name or "?"
        slots[f"{current_set}/{variant}"] = {
            "set": current_set,
            "variant": variant,
            "name": ko_name,
            "name_en": NAME_EN_OVERRIDES.get(ko_name),  # None => no confident translation, UI falls back to Korean
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
