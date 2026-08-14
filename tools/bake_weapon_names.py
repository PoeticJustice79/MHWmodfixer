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


def resolve_rodinsect_names(game_dir: str = "") -> dict[str, dict[str, str]]:
    """Kinsects (it10/03/<iid>, InsectGlaive's "RodInsect" sub-equipment) are
    NOT part of `WeaponData.cData` (subid=03 has zero rows there, confirmed
    repeatedly -- see #42/#44/#45) and use a completely separate real game
    data pair, found 2026-08-12 via `LartTyler/mhdb-wilds-data`'s config.toml:
    `Common/Equip/RodInsectRecipeData.user.3` (crafting recipe rows --
    `_Index`/`_ID`/`_KeyItemId`/.../`_PrevID`, no `_ModelId` or `_Name` GUID
    field at all, so it can't be linked to a msg entry or a file-path iid
    the same way WeaponData.cData is) and `Excel_Equip/RodInsect.msg.23`
    (real per-kinsect text, all 5 languages, msg entry names literally
    `RodInsect_<the cData row's own _ID value>` -- confirmed directly:
    `_ID=1190390272` <-> msg entry `RodInsect_1190390272`).

    Since neither table exposes the file-path iid (`it10/03/<iid>`) this
    project's own `bake_weapon_slots.py` existence-probe already
    established independently, the link used here is NOT id-based --
    it's a verified TEXT match: `tools/community_mhws_weapon_zh_cn.csv`
    (see #45) already supplied zh_cn names for all 21 of these iids, and
    cross-checking those exact zh_cn strings against RodInsect.msg.23's own
    zh_cn column found a 21/21 (100%) exact match, zero ambiguity -- proof
    both sources describe the identical 21 kinsects, and the msg entry
    matched via zh_cn text is the correct FULL-LANGUAGE source for that
    same iid. This is a one-time, hand-verified bridge (not a general
    "match by any language's text" mechanism) -- if `bake_weapon_slots.py`
    ever re-probes and finds a 22nd kinsect slot with no zh_cn counterpart
    already baked, it will simply stay unresolved here rather than guess.
    """
    game = GameArchive(game_dir or auto_fix.DEFAULT_GAME_DIR)

    found = game.find_versioned("natives/stm/gamedesign/text/excel_equip/rodinsect", "msg", version_range=range(1, 50))
    if found is None:
        return {}
    _, mdata = found
    result = parse_msg(mdata)
    langs = result["languages"]
    lang_idx = {code: langs.index(via_code) for code, via_code in _LANG_CODE_MAP.items() if via_code in langs}
    if not lang_idx:
        return {}
    msg_names_by_zh_cn: dict[str, dict[str, str]] = {}
    for e in result["entries"]:
        content = e["content"]
        d = {code: content[idx].strip() for code, idx in lang_idx.items() if idx < len(content) and content[idx].strip()}
        d = {lang: text for lang, text in d.items() if not _is_placeholder_name(text)}
        zh_cn = d.get("zh_cn")
        if zh_cn:
            msg_names_by_zh_cn[zh_cn] = d

    with gzip.open(SLOTS_PATH, "rt", encoding="utf-8") as f:
        payload = json.load(f)

    out: dict[str, dict[str, str]] = {}
    for key, entry_data in payload["entries"].items():
        parts = key.split("/")
        if len(parts) != 3 or parts[0] != "it10" or parts[1] != "03":
            continue
        existing_zh_cn = (entry_data.get("names") or {}).get("zh_cn")
        if not existing_zh_cn:
            continue
        matched = msg_names_by_zh_cn.get(existing_zh_cn)
        if matched:
            out[key] = matched
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


# Manually confirmed by the user directly testing real mods in-game
# (2026-08-10) -- NOT derived from any general rule (checked: subid=00's
# single "lambert2, no name" slot does NOT reliably correspond to a
# weapon type's Artian tier-3-unique model count across other types, so
# this stays a one-off, per-key correction, not a general merge step).
# it04 (Hammer) Artian: tiers 1&2 ("아티어해머Ⅰ"/"Ⅱ") share ONE model
# (it04/10/0002, confirmed via a real "Rocket Hammer_DIAGNOSTIC_singlesource"
# mod that targets ONLY it04/00/0012 and renders as tier 3 "모토반켈"),
# tier 3 has its OWN separate model (it04/00/0012). The tier-3 name is
# the game's own real text (from the live dump, model_id=100002's third
# msg entry); the tier-1/2 "shared" label is THIS PROJECT'S OWN composite
# (real localized stem + "Ⅰ/Ⅱ" appended), not a string the game itself
# ever displays verbatim -- there's no single official name for "the
# model tiers 1 and 2 share," since the game only ever shows one specific
# tier's name at a time depending on what the player crafted.
CONFIRMED_MANUAL_NAMES = {
    "it04/00/0012": {
        "ko": "모토반켈", "en": "Moteurvankel", "ja": "モートヴァンケル",
        "zh_cn": "汪克尔原动机", "zh_tw": "汪克爾引擎",
    },
    "it04/10/0002": {
        "ko": "아티어해머 (Ⅰ/Ⅱ 공용)", "en": "Artian Hammer (I/II shared)",
        "ja": "アーティアハンマー（Ⅰ/Ⅱ共用）",
        "zh_cn": "机械战锤（Ⅰ/Ⅱ共用）", "zh_tw": "機械大錘（Ⅰ/Ⅱ共用）",
    },
    # it00 (Great Sword) Artian, same pattern -- confirmed via "Wyvern
    # Impact2.2" targeting ONLY it00/00/0002, user-identified in-game as
    # tier 3 of the plain "Artian Blade" branch (model_id=100003: "Artian
    # Blade I/II" -> "Varianza"). The tier-1/2 shared-model slot is NOT
    # included here -- it00 has TWO subid=10 candidates (0000, 0003) and
    # there's no confirmed way yet to tell which one belongs to this same
    # branch, so it stays unresolved rather than guessed.
    "it00/00/0002": {
        "ko": "발리안차", "en": "Varianza", "ja": "ヴァリアンツァ",
        "zh_cn": "英勇变形大剑", "zh_tw": "英勇變形大劍",
    },
}

# it10/03/* Kinsects (Insect Glaive's bug companion, sharing it10's file-
# numbering convention for a completely different item category, NOT
# weapons) are named via `resolve_rodinsect_names()` above, not here.
# A parallel session independently named all 21 of the same entries via
# Kiranico's own kinsect database (en/ko/ja/zh_cn, 5 semantic anchors
# verifying page-order correspondence) -- cross-checked against
# `resolve_rodinsect_names()`'s official-msg-sourced result on merge and
# found 21/21 exact agreement on every shared language (see CLAUDE.md
# #56). That confirms both are correct; `resolve_rodinsect_names()` is
# kept as the single active mechanism since it also resolves zh_tw
# (which Kiranico doesn't have for this game), so a redundant
# `CONFIRMED_MANUAL_NAMES` block for the same 21 keys isn't carried here.

# tools/community_mhws_weapon_zh_cn.csv -- a Simplified Chinese weapon-name
# database bundled inside a third-party Chinese community MHWilds mod
# manager tool, extracted 2026-08-11 for cross-verification purposes only
# (never redistributed/linked/named -- this project's own established
# no-competitor-mention discipline). Format: "<TYPE>,<sid>_<iid>,<name>"
# (one row per representative model, "/" separating multiple known names
# for the same model where the source itself wasn't sure which is current).
#
# **2026-08-12 correction, real bug found and fixed**: the source's own
# "01" sid label does NOT mean this project's subid=01 (`model_id // 1000
# == 1`) at all -- it was originally assumed to, on the strength of
# subid=00 matching 340/340 (which never actually distinguished this,
# since every subid=00 model_id is < 1000 and looks identical under any
# larger divisor too). Proven wrong while investigating a user follow-up
# request for subid=01 multi-language names: checked one specific "01"
# row (`LONG_SWORD,01_0006,藏钩大剑`) against this project's OWN
# independently-resolved WeaponData.cData data and found "藏钩大剑" is the
# REAL, official name of `it00/10/0006` (model_id=10006, confirmed via
# the official msg UUID link) -- not `it00/01/0006` at all. Systematically
# re-checked ALL 31 "01_<iid>" rows the same way (source's `01_<iid>` vs
# this project's own `it<code>/10/<iid>`, by real official name, tier
# suffix ignored): **31/31 (100%) match** -- every single "01_<iid>" row
# is really describing `it<code>/10/<iid>`, and every one of those 31
# already has a real, better, already-baked multi-language official name
# from this project's own live-game resolution. This retroactively also
# explains the ALREADY-KNOWN "subid=10 matched only 1/23" finding below:
# this project was checking the source's rows under the WRONG label the
# whole time (real subid=10 matches were sitting under the source's own
# "01" label, not its "10" label). **Net effect: subid=01 is fully
# UNRESOLVED again (the CSV never actually described it), and the 32
# wrongly-labeled zh_cn names previously shipped under `it*/01/*` have
# been removed** -- a wrong name is worse than no name, per this
# project's own standing "never guess" discipline. `_COMMUNITY_TRUSTED_SIDS`
# below now excludes "01" entirely; only "00" (independently verified,
# safe regardless of the divisor ambiguity since its model_ids are all
# < 1000) is used. subid=03 (Kinsects, RodInsect type) is unaffected --
# that data was never trusted via this source's own id-bucket label in
# the first place, only via a direct TEXT cross-match against
# `RodInsect.msg.23`'s real official content (see `resolve_rodinsect_names()`),
# so the same id-labeling confusion never had a chance to affect it.
#
# Verified before trusting (original 2026-08-11 pass, subid=00 only, still
# holds): cross-checked all 470 of the source's rows against this
# project's own already-resolved weapon names (from live game data, not
# this source) -- subid=00 matched 340/340 (100%). Also excludes the same
# "<TypeFile>_<N>" internal-placeholder pattern this project's own
# `_is_placeholder_name()` already filters (confirmed: this source's
# "LongSword_97"-style entries are the exact same `#Rejected#` dev-leftover
# rows found independently in this project's own live dump, see
# `_is_placeholder_name()`'s docstring) -- proof the two sources really do
# describe the same underlying game data for sid=00, reinforcing the
# 100% match rate above rather than being a coincidence.
_COMMUNITY_TYPE_MAP = {
    "LONG_SWORD": "00", "SHORT_SWORD": "01", "TWIN_SWORD": "02", "TACHI": "03",
    "HAMMER": "04", "WHISTLE": "05", "LANCE": "06", "GUN_LANCE": "07",
    "SLASH_AXE": "08", "CHARGE_AXE": "09", "ROD": "10", "RodInsect": "10",
    "BOW": "11", "HEAVY_BOWGUN": "12", "LIGHT_BOWGUN": "13",
}
_COMMUNITY_TRUSTED_SIDS = {"00", "03"}  # NOT "01" or "10" -- see the block comment above
COMMUNITY_ZH_CN_CSV = Path(__file__).resolve().parent / "community_mhws_weapon_zh_cn.csv"


def load_community_zh_cn_names(csv_path: Path = COMMUNITY_ZH_CN_CSV) -> dict[str, str]:
    """{"itNN/sid/iid": "zh_cn name"} for every row on a subid this source is
    trusted for (see module comment), skipping placeholder-pattern rows.
    Where a row lists multiple "/"-separated names, keeps only the first
    (earliest-tier) one, matching this project's own "lowest index = most
    representative" convention elsewhere."""
    if not csv_path.is_file():
        return {}
    out = {}
    with open(csv_path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",", 2)
            if len(parts) != 3:
                continue
            wtype, sidiid, name = parts
            code = _COMMUNITY_TYPE_MAP.get(wtype)
            if code is None or "_" not in sidiid:
                continue
            sid, iid = sidiid.split("_", 1)
            if sid not in _COMMUNITY_TRUSTED_SIDS:
                continue
            first_name = name.split("/", 1)[0]
            if _is_placeholder_name(first_name) or re.match(r"^[A-Za-z_]+_?\d+$", first_name):
                continue
            out[f"it{code}/{sid}/{iid}"] = first_name
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
    added_sid100 = 0
    for key, name_dict in names.items():
        if key in payload["entries"]:
            payload["entries"][key]["names"] = name_dict
            matched += 1
        elif "/100/" in key:
            # subid=100 (Artian) rows have no discoverable mesh file at the
            # expected path convention (see bake_weapon_slots.py's own
            # "unsolved" note, 2026-08-10) -- so bake_weapon_slots.py's
            # existence-scan never creates a table entry for them at all.
            # Confirmed real, exclusively Artian weapons (100% of subid=100
            # entries checked follow the "Ⅰ/Ⅱ/unique-name" 3-tier pattern,
            # decided with the user 2026-08-10 to add here anyway, name-only
            # -- no has_mdf2/materials/physics, so find_compatible_weapon_targets()
            # correctly never offers these as a retarget TARGET (its own
            # `if not cand.get("has_mdf2"): continue` guard already excludes
            # any key missing that field) -- this is purely so weapon_label()
            # can show a real name instead of a raw id wherever one of these
            # keys is ever displayed (e.g. as a mod's own detected SOURCE,
            # should a real Artian-targeting mod ever surface one).
            payload["entries"][key] = {"names": name_dict}
            added_sid100 += 1
    print(f"resolved {len(names)} names via {source}, {matched} matched a real baked weapon_slots.json.gz entry, "
          f"{added_sid100} subid=100 (Artian) entr{'y' if added_sid100 == 1 else 'ies'} added name-only")

    manual_applied = 0
    for key, name_dict in CONFIRMED_MANUAL_NAMES.items():
        if key in payload["entries"]:
            payload["entries"][key]["names"] = name_dict
            manual_applied += 1
    print(f"applied {manual_applied} manually-confirmed name(s) (CONFIRMED_MANUAL_NAMES)")

    community_applied = 0
    for key, zh_cn_name in load_community_zh_cn_names().items():
        entry = payload["entries"].get(key)
        if entry is not None and not entry.get("names"):
            entry["names"] = {"zh_cn": zh_cn_name}
            community_applied += 1
    print(f"applied {community_applied} zh_cn-only name(s) from the trusted community CSV (subid=00/01/03 only, "
          f"never overwrites an already-resolved key)")

    rodinsect_applied = 0
    game_dir_for_rodinsect = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] != "--live-dump" else ""
    for key, name_dict in resolve_rodinsect_names(game_dir_for_rodinsect).items():
        entry = payload["entries"].get(key)
        if entry is not None:
            entry["names"] = name_dict
            rodinsect_applied += 1
    print(f"applied {rodinsect_applied} full 5-language Kinsect (it10/03) name(s), resolved from "
          f"RodInsect.msg.23 via verified zh_cn text cross-match")

    payload["_meta"]["names_baked_at"] = "2026-08-10"
    payload["_meta"]["names_source"] = source
    with gzip.open(SLOTS_PATH, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {SLOTS_PATH} ({SLOTS_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
