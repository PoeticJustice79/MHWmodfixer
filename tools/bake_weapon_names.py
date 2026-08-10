"""Resolves real per-model weapon names directly from the game's own data
tables, analogous to `bake_armor_slots.py`'s `_load_armor_series_names()`
for armor (see CLAUDE.md #39) -- and merges them into the existing
`tools/weapon_slots.json.gz` (built by `bake_weapon_slots.py`) rather than
a separate file, so every weapon model's data (materials/physics/name)
lives in one place.

Two real game data sources, found and verified 2026-08-10 (see CLAUDE.md):

1. `natives/stm/GameDesign/text/excel_equip/<TypeFile>.msg.23` -- one file
   per weapon TYPE (not one unified file the way `weaponseries.msg` is),
   holding entries named `<TypeFile>_<N>` (1-indexed display names, e.g.
   `LongSword_1` -> "Hope Blade I") and matching `<TypeFile>_EXP<N>`
   flavor-text twins (skipped here). **The TypeFile name does not
   reliably match the real English weapon type** -- confirmed the hard
   way: `longsword.msg`'s own flavor text literally says "A great sword
   ...its large blade can clear the area in one sweep", i.e. it's
   actually GREAT SWORD; `tachi.msg` ("...imbued with spirit to aid its
   mighty swings", referencing Long Sword's actual Spirit Gauge mechanic)
   is the real LONG SWORD file. Always verify a TypeFile's real meaning
   via its own flavor text before trusting the filename, exactly the
   lesson this project already learned once this session.

2. `natives/stm/GameDesign/Common/Weapon/<TypeFile>.user.3` -- the SAME
   TypeFile naming, holding `app.user_data.WeaponData.cData` RSZ
   instances, one per (msg index). Relevant fields (confirmed via the
   registry): `_Index` (0-indexed, = msg suffix minus 1), `_ModelId`.
   **`_ModelId` decodes to (subid, iid) via `subid = model_id // 1000,
   iid = model_id % 1000`** -- verified against 3 independent weapon
   types (the mislabeled-"LongSword" file = Great Sword, Hammer, Lance)
   before trusting it project-wide. Multiple msg indices legitimately
   share one `_ModelId` (different rarity tiers of a weapon tree often
   reuse the same visual model, confirmed real: `LongSword_1` through
   `_5`, i.e. tiers I-V of the starter "Hope Blade" line, all point at
   the identical `_ModelId=4`) -- this baker keeps the LOWEST msg index
   per unique (subid, iid) as that model's representative display name,
   since a tier-I name reads as the more natural "base" label.

Every (type_code, subid, iid) IT-CODE MAPPING used here was independently
verified against real Nexus mod files this session (see CLAUDE.md's
weapon-retargeting sections) -- not guessed:
  it00=GreatSword(file:longsword) it01=Sword&Shield(file:shortsword)
  it02=DualBlades(file:twinsword) it03=LongSword(file:tachi)
  it04=Hammer it05=HuntingHorn(file:whistle) it06=Lance
  it07=GunLance it08=SwitchAxe(file:slashaxe) it09=ChargeBlade(file:chargeaxe)
  it10=InsectGlaive(file:rod) it11=Bow it13=LightBowgun(file:lightbowgun)
  it12=HeavyBowgun(file:heavybowgun) -- the only one NOT directly
  mod-tested; resolved by elimination (13 of 14 types confirmed directly,
  exactly one type -- Heavy Bowgun -- and one code -- it12 -- left over).
"""
from __future__ import annotations

import gzip
import json
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import auto_fix
import pfb_fix
import rsz_layout
from game_archive import GameArchive
from tools.msg_reader import parse_msg

SLOTS_PATH = Path(__file__).resolve().parent / "weapon_slots.json.gz"

# (it-code -> msg/user TypeFile name), verified per the module docstring.
TYPE_FILES = {
    "00": "longsword",   # Great Sword (misleading filename, content-verified)
    "01": "shortsword",  # Sword & Shield
    "02": "twinsword",   # Dual Blades
    "03": "tachi",       # Long Sword
    "04": "hammer",
    "05": "whistle",     # Hunting Horn
    "06": "lance",
    "07": "gunlance",
    "08": "slashaxe",    # Switch Axe
    "09": "chargeaxe",   # Charge Blade
    "10": "rod",         # Insect Glaive
    "11": "bow",
    "12": "heavybowgun",  # resolved by elimination, see module docstring
    "13": "lightbowgun",
}

_WEAPONDATA_CDATA_ID = int("45cb10d", 16)


def _extract_index_model_id(game: GameArchive, registry: dict, type_file: str) -> list[tuple[int, int]]:
    """Every (index, model_id, name_guid) row from
    Common/Weapon/<type_file>.user.3's WeaponData.cData instances --
    `name_guid` is the raw 16-byte `_Name` field (hex string), a DIRECT
    link to a msg entry's own UUID (see `_load_msg_names`) -- far more
    reliable than matching by position (`index+1 == msg suffix`), which
    silently mismatches whenever an entry's numbering doesn't line up
    1:1 with its data row (confirmed real 2026-08-10: switching from
    index-matching to UUID-matching took Hammer's own match rate from a
    positional guess to 84/85 direct hits). `_Name` sits right after the
    four leading S32 fields + 14 per-type S32 cross-reference fields
    (18 x 4 = 72 bytes), 8-byte aligned (already is, 72 % 8 == 0) --
    read directly rather than walking `_parse_instance`'s full field
    list a second time, since only this one field's bytes are needed.
    Empty list if the file doesn't exist."""
    found = game.find_versioned(f"natives/stm/GameDesign/Common/Weapon/{type_file}", "user", version_range=range(1, 50))
    if found is None:
        return []
    _, data = found
    parsed = pfb_fix._parse_rsz(data)
    insts_data = parsed["data"]
    external = parsed["external"]
    pos = 0
    rows = []
    for i, (type_id, _crc) in enumerate(parsed["insts"]):
        if i == 0 or i in external:
            continue
        entry = registry.get(format(type_id, "x"))
        if entry is None:
            break
        if entry.get("fieldless"):
            continue
        start = pos
        try:
            newpos, _ok = rsz_layout._parse_instance(insts_data, pos, entry["f"])
        except rsz_layout._LayoutError:
            break
        if type_id == _WEAPONDATA_CDATA_ID:
            idx, _wtype, model_id, _custom_id = struct.unpack_from("<iiii", insts_data, start)
            name_guid = insts_data[start + 72:start + 88].hex()
            rows.append((idx, model_id, name_guid))
        pos = newpos
    return rows


_LANG_CODE_MAP = {"ko": 11, "en": 1, "ja": 0, "zh_tw": 12, "zh_cn": 13}


def _is_placeholder_name(text: str) -> bool:
    """Filters out internal QA/dev-leftover entries the game's own msg data
    still carries verbatim, found 2026-08-10 via the live singleton dump:
    exactly ONE `<COLOR FF0000>#Rejected#</COLOR> <TypeFile>_<N></COLOR>`-style
    entry per weapon type (e.g. `<COLOR FF0000>#Rejected#</COLOR>
    LongSword_97`) -- a rejected-during-development weapon design Capcom
    never removed from the shipped data table. This is real text the game
    itself stores (not a bug in this project's reading of it), but it's
    never a real player-facing weapon name -- showing raw rich-text markup
    in a selection UI is actively confusing, so it's excluded here rather
    than baked in as if it were a legitimate name. Confirmed present in
    ALL 14 weapon types' data, so this needed a general filter, not a
    one-off exclusion for a single id."""
    return "<COLOR" in text or "#Rejected#" in text


def _load_msg_names(game: GameArchive, type_file: str) -> dict[str, dict[str, str]]:
    """msg entry UUID (hex) -> {"ko"/"en"/"ja"/"zh_tw"/"zh_cn": text}, for
    <type_file>.msg.23. Unlike armor (bake_armor_slots.py), there's no
    external spreadsheet supplying Korean -- every language here,
    Korean included, comes straight from the game's own msg data via the
    same via.Language codes bake_armor_slots.py already uses."""
    found = game.find_versioned(f"natives/stm/gamedesign/text/excel_equip/{type_file}", "msg", version_range=range(1, 50))
    if found is None:
        return {}
    _, data = found
    result = parse_msg(data)
    langs = result["languages"]
    lang_idx = {code: langs.index(via_code) for code, via_code in _LANG_CODE_MAP.items() if via_code in langs}
    if not lang_idx:
        return {}
    names = {}
    for e in result["entries"]:
        content = e["content"]
        d = {
            code: content[idx].strip() for code, idx in lang_idx.items()
            if idx < len(content) and content[idx].strip()
        }
        if d:
            names[e["uuid"]] = d
    return names


def resolve_names(game_dir: str = "") -> dict[str, dict[str, str]]:
    """Returns {"it<code>/<sid>/<iid>": {"ko"/"en"/"ja"/"zh_tw"/"zh_cn": name}}
    for every weapon model this project's own game-data reading can
    confidently name."""
    game = GameArchive(game_dir or auto_fix.DEFAULT_GAME_DIR)
    registry = rsz_layout._registry()

    out: dict[str, dict[str, str]] = {}
    for code, type_file in TYPE_FILES.items():
        rows = _extract_index_model_id(game, registry, type_file)
        msg_names = _load_msg_names(game, type_file)
        if not rows or not msg_names:
            print(f"it{code} ({type_file}): no data rows or no msg names, skipping")
            continue
        # lowest msg index per unique model_id -> that model's representative row
        best_row_by_model: dict[int, tuple[int, str]] = {}
        for idx, model_id, name_guid in rows:
            if model_id not in best_row_by_model or idx < best_row_by_model[model_id][0]:
                best_row_by_model[model_id] = (idx, name_guid)
        resolved = 0
        for model_id, (idx, name_guid) in best_row_by_model.items():
            names = msg_names.get(name_guid)
            if not names:
                continue
            names = {lang: text for lang, text in names.items() if not _is_placeholder_name(text)}
            if not names:
                continue
            sid = f"{model_id // 1000:02d}"
            iid = f"{model_id % 1000:04d}"
            out[f"it{code}/{sid}/{iid}"] = names
            resolved += 1
        print(f"it{code} ({type_file}): {resolved} model(s) named")
    return out


def resolve_names_from_live_dump(dump_path: Path) -> dict[str, dict[str, str]]:
    """Alternative to `resolve_names()`, reading a REFramework Lua dump
    (`mhwmodfixer_weapon_name_dump.lua`'s own JSON output) instead of
    static game files. The live singleton (`app.VariousDataManager`'s
    `_Setting._EquipDatas._Weapon<Key>`) holds every `WeaponData.cData`
    row already resolved-in-memory -- confirmed 2026-08-10 to cover FAR
    more than the static file-reading approach: subid=10 turned out to
    be an ordinary named weapon tree (not Artian-dynamic as earlier
    assumed -- that assumption was wrong), and a THIRD subid band
    (subid=100, `_ModelId` 100000+) exists with real static names
    (Artian base tiers I/II plus real unique/quest-reward final names)
    that the old static scan never even attempted to probe for. subid=01/03/99
    still come back with zero rows in this live data too -- confirms
    (doesn't just repeat) the earlier static-file finding that those
    genuinely have no data anywhere, live or static."""
    with open(dump_path, encoding="utf-8") as f:
        dump = json.load(f)
    weapons = dump.get("weapons") or {}

    out: dict[str, dict[str, str]] = {}
    for type_key, rows in weapons.items():  # type_key already "it00".."it13"
        best_row_by_model: dict[int, tuple[int, dict]] = {}
        for row in rows:
            model_id = row["model_id"]
            idx = row["index"]
            if model_id not in best_row_by_model or idx < best_row_by_model[model_id][0]:
                best_row_by_model[model_id] = (idx, row)
        for model_id, (idx, row) in best_row_by_model.items():
            names = {lang: text for lang, text in row["names"].items()
                      if text and not _is_placeholder_name(text)}
            if not names:
                continue
            out[f"{type_key}/{row['sid']}/{row['iid']}"] = names
    return out


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--live-dump":
        names = resolve_names_from_live_dump(Path(sys.argv[2]))
        source = f"live dump ({sys.argv[2]})"
    else:
        game_dir = sys.argv[1] if len(sys.argv) > 1 else ""
        names = resolve_names(game_dir)
        source = "static file reading"

    with gzip.open(SLOTS_PATH, "rt", encoding="utf-8") as f:
        payload = json.load(f)

    # Clear any stale "names"/"name" from a PREVIOUS run first -- otherwise
    # a key that resolved before but no longer does (e.g. filtered out by
    # _is_placeholder_name after this script itself already merged it in
    # once) keeps its old value forever, since the merge loop below only
    # ever touches keys present in the CURRENT `names` dict. Confirmed real
    # 2026-08-10: the 14 "Rejected" placeholder entries survived two
    # supposedly-clean re-bakes this way before this fix.
    for entry in payload["entries"].values():
        entry.pop("names", None)
        entry.pop("name", None)

    matched = 0
    for key, name_dict in names.items():
        if key in payload["entries"]:
            payload["entries"][key]["names"] = name_dict
            matched += 1
    print(f"resolved {len(names)} names via {source}, {matched} matched a real baked weapon_slots.json.gz entry")

    payload["_meta"]["names_baked_at"] = "2026-08-10"
    payload["_meta"]["names_source"] = source
    with gzip.open(SLOTS_PATH, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {SLOTS_PATH} ({SLOTS_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
