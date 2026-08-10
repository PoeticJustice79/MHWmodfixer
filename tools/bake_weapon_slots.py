"""Bakes a weapon-model compatibility dataset from the currently installed
game, analogous to `bake_armor_slots.py` / `armor_slots_ch03.json.gz` for
armor -- built for a possible future "무기 변환" (change weapon) retargeting
feature, mirroring `slot_retarget.py`'s armor feature.

**Re-running this REBUILDS `weapon_slots.json.gz` from scratch, wiping out
any `names` field `tools/bake_weapon_names.py` already merged in** -- the
two scripts write the SAME file but neither is aware of the other's data.
Confirmed real 2026-08-10: rebaking to test a widened subid probe silently
discarded all 380 already-merged weapon names, which only surfaced later
as the GUI showing raw `it00/00/0000`-style ids instead of real names.
**Always re-run `bake_weapon_names.py --live-dump <path>` (or the
game-file-reading `resolve_names()` path) immediately after any
`bake_weapon_slots.py` run**, before shipping/rebuilding the exe.

Unlike armor, there is no community spreadsheet needed for the
compatibility half: everything here is derived directly from the live
game's own files (existence probing + RSZ instance-type scanning), the
same "don't trust a spreadsheet if the game's own data answers it more
reliably" discipline `bake_armor_slots.py` moved to for names (see
CLAUDE.md #39).

Path convention (confirmed empirically against the live game, 2026-08-10):
  natives/stm/art/model/item/it<NN>/<subid>/<itemid>/it<NN><subid>_<itemid>_0.mdf2   (material)
  natives/stm/art/model/item/it<NN>/<subid>/<itemid>/it<NN><subid>_<itemid>_0.mesh   (mesh)
  natives/stm/GameDesign/equip/_prefab/weapon/wp<NN>/<subid>/<itemid>/it<NN><subid>_<itemid>_0.pfb  (equip pfb, wp<NN> == it<NN> numerically)

`it00`-`it13` (14 codes) map 1:1 onto the game's 14 weapon types -- no
it14+ exists. Confirmed via existence brute-force, not assumed.

Two pieces of data are baked per weapon model:
  - `materials`: the mesh's own material name list (`mesh_check.py`'s
    `read_mesh_material_names()`) -- the same "mesh/mdf2 material count
    and names must match exactly" rule already enforced for armor
    (CLAUDE.md #19/#20) would apply here too, for a future retarget
    feature's target-compatibility check.
  - `physics`: which chain/cloth/fur-physics RSZ instance types (if any)
    the weapon's own EQUIP pfb carries. Confirmed 2026-08-10: ~96% of all
    622 scanned weapons' equip pfbs already carry `app.ChainSetting` +
    `via.motion.Chain2`/`ChainWind` as baseline game structure (almost
    certainly the sheathed-weapon dangle/sway physics) -- this does NOT
    make plain reskin mods (mesh+mdf2 only, no bundled pfb, the common
    case) unsafe to retarget, since those never touch the pfb at all and
    the vanilla target pfb keeps working unmodified either way. It only
    matters for a mod that bundles its OWN equip pfb (e.g. an "Effect"
    variant adding a glow/particle trail) -- reconciling THAT pfb against
    a different target inherits the exact same `app.ChainSetting`
    transplant risk CLAUDE.md #18 already confirmed is unsafe at boot.

No weapon name resolution is attempted yet -- `weaponseries.msg.23` exists
(confirmed) but only has 47 entries for 622 real models, meaning it names
SERIES, not individual tiers, unlike `armorseries.msg`'s coverage of
armor. Names are left for a follow-up once that scheme is understood;
this bake is scoped to IDs + compatibility data only.
"""
from __future__ import annotations

import gzip
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import auto_fix
import pfb_fix
import rsz_layout
from game_archive import GameArchive
from mesh_check import read_mesh_material_names

OUT_PATH = Path(__file__).resolve().parent / "weapon_slots.json.gz"

NUM_IT_CODES = 14  # confirmed empirically 2026-08-10 -- it00..it13, no it14+
SUBID_PROBE_RANGE = range(0, 100)
# subid=100 is a REAL third band in WeaponData.cData -- confirmed
# 2026-08-10 via the live game's own app.VariousDataManager singleton
# (mhwmodfixer_weapon_name_dump.lua), which returned real names for
# `_ModelId` 100000+ rows (Artian base tiers I/II + real unique/
# quest-reward final weapons, e.g. Fulgurcleaver Guardiana, Varianza).
# The earlier ITEMID_PROBE_EXTRA guess below had the WRONG axis: model_id
# 100000 decodes to (sid=100, iid=0000), not (sid=00..99, iid=100000).
# SUBID_PROBE_EXTRA below fixes that axis -- but even so, `discover_itemids`
# finds ZERO mesh files anywhere under `art/model/item/<code>/100/<iid>/`
# for ANY type (checked directly against the live game's own paks, not
# just this baker's own probe range). `_CustomModelId` (the field right
# after `_ModelId`) is also 0 for every sid=100 row checked, ruling out
# "points at a different physical model" as the explanation. **Unsolved**:
# these weapons are real (nameable, presumably equippable in-game) but
# this project doesn't know where their mesh/pfb assets actually live --
# either a different file-path convention entirely, or they share an
# existing sid=00/10 model through some mechanism not yet found. Left
# unresolved rather than guessed at; `scan_weapon()` naturally returns an
# empty dict (no mdf2/mesh/pfb data) for any sid=100 entry until this is
# cracked, same as any other real-but-unscannable model.
SUBID_PROBE_EXTRA = [100]
ITEMID_PROBE_RANGE = range(0, 100)
# large special IDs seen in a community weapon-ID list (likely DLC/collab
# equipment/save-data IDs, not literal mesh-file IDs -- probed here just
# in case, confirmed absent from Model/Item under every subid tried so far)
ITEMID_PROBE_EXTRA = [10000, 100000, 100001, 100002, 100003, 100004]

PHYSICS_TYPE_NAMES = {
    "via.motion.Chain2", "via.motion.ChainWind", "via.motion.ChildSecondary",
    "app.ChainSetting", "app.ChainSettingCollection",
    "via.dynamics.GpuCloth", "app.ClothSetting", "app.ClothSettingCollection",
    "via.render.ShellFurParam", "via.render.ShellFurMesh",
    "ace.cDampingParam", "via.dynamics.cloth.CurveWind",
    "app.CLSPVirtualGround", "app.CollisionShapePresetController",
}


def _mesh_base(code: str, sid: str, iid: str) -> str:
    return f"natives/stm/art/model/item/{code}/{sid}/{iid}/{code}{sid}_{iid}_0"


def _pfb_base(code: str, sid: str, iid: str) -> str:
    nn = code[2:]
    return f"natives/stm/GameDesign/equip/_prefab/weapon/wp{nn}/{sid}/{iid}/{code}{sid}_{iid}_0"


def discover_it_codes(game: GameArchive) -> list[str]:
    # Probe several low itemids, not just 0000 -- confirmed real gap:
    # it01 and it13 both have no 00/0000 entry at all (their lowest real
    # itemid is 0001/0002), so a single-itemid probe silently drops whole
    # weapon TYPES, not just a few slots -- caught by cross-checking this
    # function's output count against the earlier ad-hoc scan's 622 and
    # finding exactly it01+it13's entry counts (47+41=88) accounted for
    # the 622-534 gap.
    codes = []
    for n in range(30):
        code = f"it{n:02d}"
        for iid_n in range(4):
            if game.find_versioned_path(_mesh_base(code, "00", f"{iid_n:04d}"), "mdf2", version_range=range(40, 50)):
                codes.append(code)
                break
    return codes


def discover_subids(game: GameArchive, code: str) -> list[str]:
    hits = []
    probe = list(range(0, 4)) + ITEMID_PROBE_EXTRA
    for sid_n in list(SUBID_PROBE_RANGE) + SUBID_PROBE_EXTRA:
        sid = f"{sid_n:02d}"
        for iid_n in probe:
            iid = f"{iid_n:04d}"
            if game.find_versioned_path(_mesh_base(code, sid, iid), "mdf2", version_range=range(40, 50)):
                hits.append(sid)
                break
    return hits


def discover_itemids(game: GameArchive, code: str, sid: str) -> list[int]:
    found = []
    for iid_n in list(ITEMID_PROBE_RANGE) + ITEMID_PROBE_EXTRA:
        iid = f"{iid_n:04d}"
        if game.find_versioned_path(_mesh_base(code, sid, iid), "mdf2", version_range=range(40, 50)):
            found.append(iid_n)
    return found


def scan_weapon(game: GameArchive, registry: dict, code: str, sid: str, iid: str) -> dict:
    entry = {}

    if game.find_versioned_path(_mesh_base(code, sid, iid), "mdf2", range(40, 50)) is not None:
        entry["has_mdf2"] = True

    # mesh version numbers are large build-date-derived stamps, not a
    # small sequential range -- reuse the same known-good candidate list
    # `slot_retarget.py`'s own `verify_target_vanilla()` already uses for
    # armor mesh lookups, rather than brute-forcing a huge numeric range.
    mesh_found = game.find_versioned(_mesh_base(code, sid, iid), "mesh", [241111606, 240820143, 230517984])
    if mesh_found is not None:
        _, mesh_bytes = mesh_found
        materials = read_mesh_material_names(mesh_bytes)
        if materials is not None:
            entry["materials"] = materials

    pfb_found = game.find_versioned(_pfb_base(code, sid, iid), "pfb", version_range=range(1, 50))
    if pfb_found is None:
        entry["has_pfb"] = False
    else:
        entry["has_pfb"] = True
        _, pfb_bytes = pfb_found
        try:
            parsed = pfb_fix._parse_rsz(pfb_bytes)
            type_names = set()
            for t, _c in parsed["insts"][1:]:
                reg_entry = registry.get(format(t, "x"))
                if reg_entry and reg_entry.get("n"):
                    type_names.add(reg_entry["n"])
            physics_hit = sorted(type_names & PHYSICS_TYPE_NAMES)
            if physics_hit:
                entry["physics"] = physics_hit
        except Exception as e:  # noqa: BLE001 -- diagnostic bake, never fatal
            entry["pfb_parse_error"] = str(e)

    return entry


def bake(game_dir: str = "") -> tuple[dict, int]:
    game = GameArchive(game_dir or auto_fix.DEFAULT_GAME_DIR)
    registry = rsz_layout._registry()

    t0 = time.time()
    it_codes = discover_it_codes(game)
    print(f"discovered {len(it_codes)} weapon type codes: {it_codes}")

    out = {}
    total = 0
    for code in it_codes:
        subids = discover_subids(game, code)
        for sid in subids:
            itemids = discover_itemids(game, code, sid)
            for iid_n in itemids:
                iid = f"{iid_n:04d}"
                key = f"{code}/{sid}/{iid}"
                out[key] = scan_weapon(game, registry, code, sid, iid)
                total += 1
        print(f"  {code}: {len(subids)} subid group(s), running total {total}")

    print(f"baked {total} weapon models in {time.time() - t0:.1f}s")
    return out, total


def main():
    game_dir = sys.argv[1] if len(sys.argv) > 1 else ""
    entries, total = bake(game_dir)
    payload = {
        "_meta": {
            "baked_at": "2026-08-10",
            "source": "live game scan (bake_weapon_slots.py)",
            "entry_count": total,
        },
        "entries": entries,
    }
    with gzip.open(OUT_PATH, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes, {total} entries)")


if __name__ == "__main__":
    main()
