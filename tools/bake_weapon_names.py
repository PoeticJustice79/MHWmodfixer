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
    """Every (index, model_id) row from Common/Weapon/<type_file>.user.3's
    WeaponData.cData instances. Empty list if the file doesn't exist."""
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
            rows.append((idx, model_id))
        pos = newpos
    return rows


def _load_msg_names(game: GameArchive, type_file: str) -> dict[int, str]:
    """1-indexed msg suffix -> English display name, for <type_file>.msg.23."""
    found = game.find_versioned(f"natives/stm/gamedesign/text/excel_equip/{type_file}", "msg", version_range=range(1, 50))
    if found is None:
        return {}
    _, data = found
    result = parse_msg(data)
    langs = result["languages"]
    en_idx = langs.index(1) if 1 in langs else None
    if en_idx is None:
        return {}
    pat = re.compile(rf"^{re.escape(type_file)}_(\d+)$", re.IGNORECASE)
    names = {}
    for e in result["entries"]:
        m = pat.match(e["name"])
        if m:
            names[int(m.group(1))] = e["content"][en_idx]
    return names


def resolve_names(game_dir: str = "") -> dict[str, str]:
    """Returns {"it<code>/<sid>/<iid>": name} for every weapon model this
    project's own game-data reading can confidently name."""
    game = GameArchive(game_dir or auto_fix.DEFAULT_GAME_DIR)
    registry = rsz_layout._registry()

    out: dict[str, str] = {}
    for code, type_file in TYPE_FILES.items():
        rows = _extract_index_model_id(game, registry, type_file)
        msg_names = _load_msg_names(game, type_file)
        if not rows or not msg_names:
            print(f"it{code} ({type_file}): no data rows or no msg names, skipping")
            continue
        # lowest msg index per unique model_id -> that model's representative name
        best_index_by_model: dict[int, int] = {}
        for idx, model_id in rows:
            if model_id not in best_index_by_model or idx < best_index_by_model[model_id]:
                best_index_by_model[model_id] = idx
        resolved = 0
        for model_id, idx in best_index_by_model.items():
            name = msg_names.get(idx + 1)  # msg suffix is 1-indexed
            if name is None:
                continue
            sid = f"{model_id // 1000:02d}"
            iid = f"{model_id % 1000:04d}"
            out[f"it{code}/{sid}/{iid}"] = name
            resolved += 1
        print(f"it{code} ({type_file}): {resolved} model(s) named")
    return out


def main():
    game_dir = sys.argv[1] if len(sys.argv) > 1 else ""
    names = resolve_names(game_dir)

    with gzip.open(SLOTS_PATH, "rt", encoding="utf-8") as f:
        payload = json.load(f)

    matched = 0
    for key, name in names.items():
        if key in payload["entries"]:
            payload["entries"][key]["name"] = name
            matched += 1
    print(f"resolved {len(names)} names, {matched} matched a real baked weapon_slots.json.gz entry")

    payload["_meta"]["names_baked_at"] = "2026-08-10"
    with gzip.open(SLOTS_PATH, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {SLOTS_PATH} ({SLOTS_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
