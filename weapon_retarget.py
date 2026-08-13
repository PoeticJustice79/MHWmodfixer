"""무기 모델 변경 (weapon slot retargeting): relocate a mod built for one
weapon model onto a different, compatible model of the SAME weapon type.

Mirrors slot_retarget.py's armor feature (CLAUDE.md #33/#34) using the
compatibility dataset baked by tools/bake_weapon_slots.py
(tools/weapon_slots.json.gz, 622 weapon models across all 14 weapon types,
baked directly from the live game -- see that script's own docstring for
the confirmed path convention and scan methodology).

**Not yet verified against a real weapon mod archive or in-game.** This
module was written from the confirmed game-side path convention alone --
no community weapon mod has been inspected yet to confirm mods actually
follow that same convention, unlike armor's Chinese-community pipeline,
which WAS directly inspected before slot_retarget.py was written. Treat
`detect_mod_weapon()`'s regexes as a first draft to correct against a
real mod archive before trusting output from this module, not as already
confirmed the way the armor version is. (Groundwork started 2026-08-10,
paused for a computer switch -- see CLAUDE.md's "weapon-slot groundwork"
entry -- and resumed once the game was available again to verify against.)

Compatibility rule, adapted from bake_weapon_slots.py's own reasoning AND
corrected against 4 real weapon mods (2026-08-10 -- Ebony And Ivory Dual
Pistol, Hirabami Great Sword, Tailless Miyabi's Katana, Uth Duna Sword And
Shield): 3 of the 4 real mods bundle a loose `.chain2` file with NO pfb at
all -- a real, common case bake_weapon_slots.py's own docstring didn't
anticipate ("only a mod bundling its OWN pfb needs the physics check").
That's wrong for this shape: a bundled chain2-with-no-pfb mod relies on
the TARGET's own vanilla equip pfb to reference it (by the target's own
numbered filename, which is exactly what `retarget_tree()` renames the
bundled chain2 file to match) -- so the target still needs SOME baseline
chain physics for that reference to mean anything, or the bundled physics
file just silently goes unreferenced (feature lost, not broken -- no
crash risk, unlike the bundled-pfb case below).

- The weapon TYPE (it-code, e.g. it00 = Great Sword) is a hard boundary --
  never offered as a candidate outside the source's own type. Different
  weapon types use different skeletons/animations/hitboxes; there is no
  equivalent of armor's cross-set relocation here.
- A mod that ships ONLY mesh+mdf2 (no chain2/jcns/clsp/sfur, no pfb) is
  safe to retarget to ANY same-type target regardless of physics profile
  -- the target's own vanilla equip pfb keeps working completely
  unmodified either way, since the mod never touches or references
  physics at all.
- A mod that bundles a LOOSE physics file (`.chain2`/`.jcns`/`.clsp`/
  `.sfur`) but no pfb of its own needs the target's baseline physics
  profile to include the game's near-universal chain baseline
  (`app.ChainSetting`+`via.motion.Chain2`+`via.motion.ChainWind`, present
  on ~94% of all 622 catalogued weapon models) -- graded `partial`, not
  `refused`, when it doesn't: the bundled file just goes unreferenced
  (silent feature loss), never a crash or corruption risk.
- A mod that bundles its OWN equip pfb needs the target's physics profile
  to be a superset of the source's (mirroring armor's `chain`/`gpuc`
  grading) -- reconciling a mismatched bundled pfb against a different
  target's structure would need the same `app.ChainSetting`-transplant
  mechanism CLAUDE.md #18 already confirmed is unsafe at boot, so this is
  REFUSED outright (not offered as a lower grade) rather than attempted.
"""
from __future__ import annotations

import gzip
import json
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from pak_mod_fix import find_pak_files
from pak_reader import PakArchive, pak_path_hash64
from pak_writer import write_pak

_HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
WEAPON_TABLE_PATH = _HERE / "tools" / "weapon_slots.json.gz"

_weapon_table_cache: dict | None = None

# Mirrors bake_weapon_slots.py's own confirmed path convention:
#   .../art/model/item/it<NN>/<sid>/<iid>/...   (mesh/mdf2)
#   .../equip/_prefab/weapon/wp<NN>/<sid>/<iid>/...   (equip pfb -- dir uses
#     "wp", but the FILENAME itself still uses the "it" code, confirmed in
#     bake_weapon_slots.py's own `_pfb_base()`)
# A mod is assumed (not yet confirmed) to reuse this same directory shape.
_MODEL_DIR_RE = re.compile(r"item[\\/]it(\d{2})[\\/](\d{2})[\\/](\d{4})[\\/]", re.IGNORECASE)
_PFB_DIR_RE = re.compile(r"weapon[\\/]wp(\d{2})[\\/](\d{2})[\\/](\d{4})[\\/]", re.IGNORECASE)
# Filename itself, e.g. "it0000_0006_0.mdf2.45" / "it0000_0006_0.pfb.12" --
# used both as a fallback when a mod flattens its directory structure, and
# to tell which of mdf2/mesh/pfb a given file actually is.
_FILE_RE = re.compile(r"it(\d{2})(\d{2})_(\d{4})_0\b", re.IGNORECASE)

# Loose physics-carrying file types a mod can bundle WITHOUT a pfb (armor's
# equivalent is `pfb_fix.py`'s `_PHYSICS_EXTS`) -- confirmed real on 3 of 4
# real weapon mods inspected 2026-08-10 (all shipped `.chain2`, no pfb).
_PHYSICS_FILE_EXTS = (".chain2", ".jcns", ".clsp", ".sfur")
# The near-universal baseline physics types (~94% of all 622 catalogued
# weapon models per bake_weapon_slots.py -- see that script's own docstring)
# a bundled loose physics file needs the TARGET to also carry, or the
# bundled file simply goes unreferenced by the target's own vanilla pfb.
_BASELINE_CHAIN_TYPES = {"app.ChainSetting", "via.motion.Chain2", "via.motion.ChainWind"}

# Mods packaged as their own standalone .pak (Fluffy-installed alongside a
# modinfo.ini, no loose files at all) carry no filename per entry, only a
# hash64 -- the same "no plaintext directory listing" property the game's
# own paks have (see pak_reader.py's own docstring). Confirmed real
# 2026-08-10: every weapon mod a user actually had on hand ("Dreaming
# Dalamadur" and others) turned out to be this shape, not loose files --
# `detect_mod_weapon()`'s path-regex approach can never find anything in
# one, since there are no paths to match at all.
#
# The fix mirrors `pak_mod_fix.py`'s own established technique for the
# regular repair pipeline (`read_by_hash()`'s docstring: "if a mod's entry
# hash exactly matches one of the game's own current entries, that IS the
# vanilla donor, unambiguously, no path-guessing needed") -- except here
# we need to know WHICH real weapon slot an entry corresponds to, not just
# get its donor bytes. Since `weapon_slots.json.gz` already enumerates
# every real (type, sid, iid) triple this project knows about, computing
# each one's canonical path (at every plausible version suffix) and
# checking membership in the mod's own pak's hash set identifies the
# source slot exactly, with no path string ever needed from the mod
# itself. Verified directly against "Dreaming Dalamadur" (a real Nexus
# weapon mod): its pak's 6 entries include exactly 2 that hash-match a
# known vanilla path (mdf2 + mesh for it00/01/0004) -- the other 4 are the
# mod's own custom-named textures, which never hash-match anything (by
# design -- their paths were never derived from the weapon's slot number).
_MDF2_VERSIONS = range(1, 80)
_PFB_VERSIONS = range(1, 60)
_MESH_VERSIONS = [241111606, 240820143, 230517984]
_LOOSE_PHYSICS_EXT_VERSIONS = range(1, 40)


def _pak_candidate_hashes(code: str, sid: str, iid: str):
    """Yields (ext, version, hash64) for every plausible pak-entry hash a
    real weapon model at (code, sid, iid) could occupy -- mdf2/mesh always
    exist for a real model; pfb and loose physics files only exist for
    SOME models (a hash simply won't be present in ANY pak if that file
    type doesn't exist for this model, which is fine -- membership testing
    doesn't need to know that in advance)."""
    mesh_base = f"natives/stm/art/model/item/it{code}/{sid}/{iid}/it{code}{sid}_{iid}_0"
    pfb_base = f"natives/stm/GameDesign/equip/_prefab/weapon/wp{code}/{sid}/{iid}/it{code}{sid}_{iid}_0"
    for n in _MDF2_VERSIONS:
        yield "mdf2", n, pak_path_hash64(f"{mesh_base}.mdf2.{n}")
    for n in _MESH_VERSIONS:
        yield "mesh", n, pak_path_hash64(f"{mesh_base}.mesh.{n}")
    for n in _PFB_VERSIONS:
        yield "pfb", n, pak_path_hash64(f"{pfb_base}.pfb.{n}")
    for ext in _PHYSICS_FILE_EXTS:
        ext_bare = ext.lstrip(".")
        for n in _LOOSE_PHYSICS_EXT_VERSIONS:
            yield ext_bare, n, pak_path_hash64(f"{mesh_base}.{ext_bare}.{n}")


def detect_mod_weapon_pak(pak_path: Path) -> tuple[ModWeaponInfo, None] | tuple[None, list[str]]:
    """Same contract as `detect_mod_weapon()`'s return shape, for a single
    standalone-.pak mod file. Returns (info, None) on exactly one match, or
    (None, sorted_key_list) on zero/multiple."""
    archive = PakArchive(pak_path)
    pak_hashes = set(archive.entries.keys())

    triples: set[tuple[str, str, str]] = set()
    matches: list[dict] = []  # {"hash64", "ext", "version", "base_no_ext"}
    for key in weapon_table():
        m = re.match(r"it(\d{2})/(\d{2})/(\d{4})", key)
        if not m:
            continue
        code, sid, iid = m.groups()
        for ext, version, h in _pak_candidate_hashes(code, sid, iid):
            if h in pak_hashes:
                triples.add((code, sid, iid))
                base = (f"natives/stm/art/model/item/it{code}/{sid}/{iid}/it{code}{sid}_{iid}_0"
                        if ext != "pfb" else
                        f"natives/stm/GameDesign/equip/_prefab/weapon/wp{code}/{sid}/{iid}/it{code}{sid}_{iid}_0")
                matches.append({"hash64": h, "ext": ext, "version": version, "base_no_ext": base})

    if len(triples) != 1:
        return None, sorted(f"it{a}/{b}/{c}" for a, b, c in triples)

    code, sid, iid = next(iter(triples))
    info = ModWeaponInfo(type_code=code, sid=sid, iid=iid, pak_path=pak_path, pak_matches=matches)
    for m in matches:
        if m["ext"] == "mdf2":
            info.has_mdf2 = True
        elif m["ext"] == "mesh":
            info.has_mesh = True
        elif m["ext"] == "pfb":
            info.has_pfb = True
        else:
            info.has_physics_files = True
    return info, None


def weapon_table() -> dict:
    """{"itNN/SID/IID": {"has_mdf2", "has_pfb", "materials": [...], "physics": [...]}}"""
    global _weapon_table_cache
    if _weapon_table_cache is None:
        try:
            with gzip.open(WEAPON_TABLE_PATH, "rt", encoding="utf-8") as f:
                _weapon_table_cache = json.load(f)["entries"]
        except OSError:
            _weapon_table_cache = {}
    return _weapon_table_cache


def weapon_label(key: str, lang: str = "ko") -> str:
    """UI-facing label for a weapon table key. Real per-model names in
    all 5 UI languages, baked by `tools/bake_weapon_names.py` (CLAUDE.md,
    2026-08-10) directly from the game's own WeaponData tables +
    per-type msg files -- mirrors armor's `armor_name()`/`ArmorSeries.msg`
    resolution (#39), just via a different real data source (weapon
    names aren't 1:1 in any single msg file the way armor's are).
    Unlike armor_name(), every language here -- Korean included -- comes
    straight from the game's own msg data (armor's Korean instead came
    from an external spreadsheet, with only en/ja/zh_tw/zh_cn
    game-sourced), so there's no separate "always Korean for a Korean
    UI" special case: just look up the requested language, falling back
    to English, then to zh_cn (a real subset of entries -- subid=01/03,
    which the game's own per-type msg data has zero rows for at all --
    are only resolvable via a cross-verified third-party community
    database that's zh_cn-only, see bake_weapon_names.py's own
    `load_community_zh_cn_names()`; showing that real Chinese name is
    still strictly more useful than a raw id even to a non-Chinese-reading
    user), then finally to the raw id for whatever this project's own
    data reading still couldn't confidently name at all -- never guessed,
    same "show the id, don't invent a name" rule this tool follows
    everywhere else."""
    entry = weapon_table().get(key)
    names = entry.get("names") if entry else None
    if names:
        return names.get(lang) or names.get("en") or names.get("zh_cn") or key
    return key


@dataclass
class ModWeaponInfo:
    type_code: str      # "00".."13" (it<NN> without the "it" prefix)
    sid: str             # subid, e.g. "00"
    iid: str              # itemid, e.g. "0006"
    has_mdf2: bool = False
    has_mesh: bool = False
    has_pfb: bool = False
    has_physics_files: bool = False   # bundles a loose .chain2/.jcns/.clsp/.sfur, no pfb -- see module docstring
    files: list[Path] = field(default_factory=list)
    pak_path: Path | None = None      # set when this mod is its own standalone .pak, not loose files
    pak_matches: list[dict] = field(default_factory=list)  # {"hash64","ext","version","base_no_ext"}

    @property
    def key(self) -> str:
        return f"it{self.type_code}/{self.sid}/{self.iid}"


def detect_mod_weapon(mod_root: Path) -> ModWeaponInfo | list[str]:
    """Scans an extracted mod for the weapon model it targets. Returns a
    ModWeaponInfo when exactly ONE (type, sid, iid) triple is found -- or
    the sorted list of distinct keys seen when zero/multiple are found
    (multi-option FOMOD-style mods aren't supported for automatic
    retargeting here either, mirroring slot_retarget.detect_mod_slot).

    Tries loose-file path matching first (the original, path-regex-based
    approach); if that finds nothing at all, falls back to treating any
    bundled .pak file(s) as a standalone-pak mod (see detect_mod_weapon_pak
    -- confirmed 2026-08-10 to be the actual common case for real weapon
    mods, not the loose-file layout this module was originally written
    against)."""
    triples: set[tuple[str, str, str]] = set()
    files = []
    for p in mod_root.rglob("*"):
        if not p.is_file():
            continue
        files.append(p)
        rel = str(p.relative_to(mod_root))
        m = _MODEL_DIR_RE.search(rel) or _PFB_DIR_RE.search(rel)
        if m:
            triples.add((m.group(1), m.group(2), m.group(3)))
            continue
        m = _FILE_RE.search(p.name)
        if m:
            triples.add((m.group(1), m.group(2), m.group(3)))

    if not triples:
        pak_files = list(find_pak_files(mod_root))
        if len(pak_files) == 1:
            info, unmatched = detect_mod_weapon_pak(pak_files[0])
            if info is not None:
                return info
            if unmatched:
                return unmatched
        elif len(pak_files) > 1:
            # More than one bundled pak (e.g. a multi-page FOMOD) -- try
            # each independently rather than merging their hash sets
            # together, which could spuriously "detect" a triple that's
            # really two different pages' two different weapons.
            per_pak: set[tuple[str, str, str]] = set()
            for pf in pak_files:
                _, unmatched = detect_mod_weapon_pak(pf)
                per_pak.update(tuple(k.split("/")) for k in (unmatched or []))
            if per_pak:
                return sorted(f"it{a}/{b}/{c}" for a, b, c in per_pak)

    if len(triples) != 1:
        return sorted(f"it{a}/{b}/{c}" for a, b, c in triples)
    type_code, sid, iid = next(iter(triples))
    info = ModWeaponInfo(type_code=type_code, sid=sid, iid=iid, files=files)
    for p in files:
        name = p.name.lower()
        if ".mdf2" in name:
            info.has_mdf2 = True
        elif ".mesh" in name:
            info.has_mesh = True
        elif ".pfb" in name:
            info.has_pfb = True
        elif any(ext in name for ext in _PHYSICS_FILE_EXTS):
            info.has_physics_files = True
    return info


def _flags_from_files(info: ModWeaponInfo) -> None:
    """Sets has_mdf2/has_mesh/has_pfb/has_physics_files on `info` by
    inspecting its OWN `files` list -- shared by both the single- and
    multi-target detection paths so they can never drift apart."""
    for p in info.files:
        name = p.name.lower()
        if ".mdf2" in name:
            info.has_mdf2 = True
        elif ".mesh" in name:
            info.has_mesh = True
        elif ".pfb" in name:
            info.has_pfb = True
        elif any(ext in name for ext in _PHYSICS_FILE_EXTS):
            info.has_physics_files = True


def detect_mod_weapons(mod_root: Path) -> tuple[list[ModWeaponInfo], list[Path]]:
    """Plural counterpart to `detect_mod_weapon()`, for a mod that bundles
    MORE than one weapon model's worth of files (e.g. several FOMOD pages
    merged into one archive -- confirmed real 2026-08-10 against a real
    mod, "ReyDau_Fixed.zip", which surfaced exactly this: two distinct
    (type,sid,iid) triples in one flat loose-file tree). Mirrors
    slot_retarget.detect_mod_slots()'s exact shape: every distinct triple
    becomes its own `ModWeaponInfo` group (holding only ITS OWN files),
    plus the list of files matching no weapon pattern at all (FOMOD
    config, readmes, covers, ...) that always pass through untouched
    regardless of what any group is assigned to.

    Falls back to pak-based detection when no loose triples are found at
    all (mirrors `detect_mod_weapon()`'s own fallback) -- confirmed real
    2026-08-10: this fallback was accidentally left out of the first
    version of this function, which silently broke every previously-working
    standalone-.pak weapon mod (e.g. "Dreaming Dalamadur") the moment this
    function replaced the singular one as the dialog's detection call.
    Each bundled .pak that resolves to exactly ONE triple becomes its own
    group (`ModWeaponInfo.pak_path` set); a pak resolving to zero or
    multiple triples is skipped entirely (still not supported -- a real
    multi-weapon standalone .pak has never been observed, unlike the
    multi-weapon LOOSE-file case this function was built for)."""
    triple_files: dict[tuple[str, str, str], list[Path]] = {}
    unmatched: list[Path] = []
    for p in mod_root.rglob("*"):
        if not p.is_file():
            continue
        rel = str(p.relative_to(mod_root))
        m = _MODEL_DIR_RE.search(rel) or _PFB_DIR_RE.search(rel)
        if not m:
            m = _FILE_RE.search(p.name)
        if m:
            triple_files.setdefault((m.group(1), m.group(2), m.group(3)), []).append(p)
        else:
            unmatched.append(p)

    groups = []
    if not triple_files:
        pak_files = list(find_pak_files(mod_root))
        resolved_pak_paths = set()
        for pf in pak_files:
            info, _unmatched_keys = detect_mod_weapon_pak(pf)
            if info is not None:
                groups.append(info)
                resolved_pak_paths.add(pf)
        unmatched = [p for p in mod_root.rglob("*") if p.is_file() and p not in resolved_pak_paths]
    else:
        for (type_code, sid, iid), files in triple_files.items():
            info = ModWeaponInfo(type_code=type_code, sid=sid, iid=iid, files=files)
            _flags_from_files(info)
            groups.append(info)
    groups.sort(key=lambda g: (-len(g.files), g.type_code, g.sid, g.iid))
    return groups, unmatched


@dataclass
class TargetWeaponCandidate:
    key: str            # "itNN/SID/IID"
    type_code: str
    sid: str
    iid: str
    grade: str           # "exact" | "partial" | "refused"
    missing_physics: list[str] = field(default_factory=list)  # physics types the target lacks
    verified: bool = False


def find_compatible_weapon_targets(source: ModWeaponInfo) -> list[TargetWeaponCandidate]:
    """Every OTHER weapon model of the SAME type (it-code) with known table
    data, ranked best first. Three grades, per this module's own docstring:
    - A mod with no pfb AND no loose physics file always grades "exact" --
      the target's own vanilla pfb (and whatever it references) is never
      touched either way.
    - A mod with no pfb but a bundled loose physics file (.chain2 etc.)
      grades "partial" when the target's baseline physics profile doesn't
      include the near-universal chain baseline -- the bundled file would
      just go unreferenced (silent feature loss, not a crash risk).
    - A mod bundling its OWN pfb grades "refused" (never "partial") when
      the target's baseline physics isn't a superset of the source's own
      -- see the module docstring for why this one is a hard block, not a
      soft warning.

    Candidates with no real resolved name (weapon_table()'s "names" field
    empty/missing) are excluded entirely, not just shown with a raw id --
    decided 2026-08-10 after finding that a chunk of these are literal
    development leftovers (a `<COLOR FF0000>#Rejected#</COLOR>`-tagged
    weapon design Capcom never removed from the shipped data, one per
    weapon type, plus ~163 other real-but-unnamed models of unknown
    origin). A user picking a retarget TARGET needs to recognize what
    they're choosing -- unlike showing a raw id elsewhere in this project
    (never inventing a name, but never hiding real data either), here the
    id alone can't inform a safe choice, and at least one confirmed
    real-world case of "unnamed" already meant "known-bad leftover
    content." The SOURCE mod's own detection is unaffected -- this only
    trims the TARGET list."""
    table = weapon_table()
    src_key = source.key
    src_entry = table.get(src_key, {})
    src_physics = set(src_entry.get("physics", []))

    out = []
    for key, cand in table.items():
        m = re.match(r"it(\d{2})/(\d{2})/(\d{4})", key)
        if not m or key == src_key:
            continue
        t_code, t_sid, t_iid = m.groups()
        if t_code != source.type_code:
            continue
        if not cand.get("has_mdf2"):
            continue  # no usable donor data at all -- exclude, never guess
        if not cand.get("names"):
            continue  # no recognizable name -- exclude, don't offer a blind pick
        cand_physics = set(cand.get("physics", []))
        if source.has_pfb:
            missing = sorted(src_physics - cand_physics)
            grade = "refused" if missing else "exact"
        elif source.has_physics_files:
            missing = sorted(_BASELINE_CHAIN_TYPES - cand_physics)
            grade = "partial" if missing else "exact"
        else:
            grade, missing = "exact", []
        out.append(TargetWeaponCandidate(
            key=key, type_code=t_code, sid=t_sid, iid=t_iid,
            grade=grade, missing_physics=missing,
        ))
    grade_rank = {"exact": 0, "partial": 1, "refused": 2}
    out.sort(key=lambda c: (grade_rank[c.grade], c.sid, c.iid))
    return out


def find_target_occupant(game_dir, target: TargetWeaponCandidate) -> Path | None:
    """Checks whether this target slot's mdf2 already has a REAL loose
    file sitting under <game_dir>/natives/... -- meaning some other
    currently-active mod (Fluffy Mod Manager, or any tool that does real
    loose-file deployment -- MO2's virtualized overlay is a known,
    accepted exception, decided with the user 2026-08-10) already
    occupies this slot. Returns the conflicting file's path, or None if
    free. Checking mdf2 alone (not mesh/pfb too) is a deliberately cheap,
    single-glob check -- any mod touching a weapon slot at all bundles a
    material file, so this is already a reliable signal, and staying
    cheap is what makes it safe to run for every candidate in a list up
    front (see game_archive.find_loose_files's own docstring on why this
    never constructs a full GameArchive)."""
    from game_archive import find_loose_files
    code, sid, iid = target.type_code, target.sid, target.iid
    base = f"natives/stm/art/model/item/it{code}/{sid}/{iid}/it{code}{sid}_{iid}_0"
    found = find_loose_files(game_dir, base, "mdf2")
    return found[0] if found else None


def verify_target_vanilla(game, source: ModWeaponInfo, target: TargetWeaponCandidate) -> tuple[bool, list[str]]:
    """Live-game completeness check: the target must have every file type
    the mod itself ships (mdf2/mesh always; pfb only if the mod bundles
    its own -- a mod with no pfb never needs the target to have one,
    since it never gets touched). Mirrors slot_retarget.verify_target_vanilla."""
    missing = []
    code, sid, iid = target.type_code, target.sid, target.iid
    base = f"natives/stm/art/model/item/it{code}/{sid}/{iid}/it{code}{sid}_{iid}_0"
    if source.has_mdf2 and game.find_versioned_path(base, "mdf2", range(1, 200)) is None:
        missing.append("mdf2")
    if source.has_mesh and game.find_versioned(base, "mesh", [241111606, 240820143, 230517984]) is None:
        missing.append("mesh")
    if source.has_pfb:
        pfb_base = f"natives/stm/GameDesign/equip/_prefab/weapon/wp{code}/{sid}/{iid}/it{code}{sid}_{iid}_0"
        if game.find_versioned_path(pfb_base, "pfb", range(1, 50)) is None:
            missing.append("pfb")
    return (not missing), missing


def retarget_tree(mod_root: Path, out_root: Path, source: ModWeaponInfo,
                   dst_code: str, dst_sid: str, dst_iid: str, log=lambda s: None) -> int:
    """Copies the mod into out_root with every weapon-identifying path part
    and filename renamed from the source model to the target -- the same
    PART-level rename primitive slot_retarget.retarget_tree() uses (never
    a whole-path substring replace). File contents are copied
    byte-identical; nothing inside any file is touched."""
    src_code, src_sid, src_iid = source.type_code, source.sid, source.iid
    # Matches the ID prefix only (not a hardcoded trailing "_0") -- a real
    # ReyDau Greatsword "Effect" mod (2026-08-10) showed this matters: its
    # bundled sound bank is named "it0010_0002_m.sbnk...", not "..._0...",
    # so a "_0"-only pattern silently left the OLD id in that filename
    # (and the safety leftover-scan below didn't catch it either, since it
    # requires a separator between the type code and sid that a bare
    # filename like this doesn't have). Also covers numbered sub-variants
    # like "_1" (confirmed real: Dual Blades' two-pistol reskins).
    file_re = re.compile(rf"it{src_code}{src_sid}_{src_iid}", re.IGNORECASE)
    moved = 0
    for p in source.files:
        parts = list(p.relative_to(mod_root).parts)
        new_parts = []
        i = 0
        while i < len(parts):
            part = parts[i]
            if part.lower() == f"it{src_code}" and i + 2 < len(parts) and \
                    parts[i + 1] == src_sid and parts[i + 2] == src_iid:
                new_parts.extend([f"it{dst_code}", dst_sid, dst_iid])
                i += 3
                continue
            if part.lower() == f"wp{src_code}" and i + 2 < len(parts) and \
                    parts[i + 1] == src_sid and parts[i + 2] == src_iid:
                new_parts.extend([f"wp{dst_code}", dst_sid, dst_iid])
                i += 3
                continue
            np = file_re.sub(f"it{dst_code}{dst_sid}_{dst_iid}", part)
            new_parts.append(np)
            i += 1
        dst = out_root.joinpath(*new_parts)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dst)
        if new_parts != parts:
            moved += 1
    # The separator between the type code and sid is OPTIONAL here (not
    # just "[\\/_]") -- a bare filename like "it0010_0002_m.sbnk" has NO
    # separator there at all ("it00"+"10" concatenated directly), which a
    # required-separator pattern silently missed (the same real gap that
    # motivated widening file_re above).
    leftover = [str(q.relative_to(out_root)) for q in out_root.rglob("*")
                if re.search(rf"it{src_code}[\\/_]?{src_sid}[\\/_]{src_iid}|wp{src_code}[\\/]{src_sid}[\\/]{src_iid}",
                              str(q.relative_to(out_root)), re.IGNORECASE)]
    if leftover:
        raise RuntimeError(f"retarget left {len(leftover)} source-weapon path(s) behind: {leftover[:3]}")
    log(f"    [retarget] {moved} file(s) relocated it{src_code}/{src_sid}/{src_iid} "
        f"-> it{dst_code}/{dst_sid}/{dst_iid}")
    return moved


def retarget_pak(pak_path: Path, out_pak_path: Path, source: ModWeaponInfo,
                  dst_code: str, dst_sid: str, dst_iid: str, log=lambda s: None) -> int:
    """Rebuilds a standalone-.pak weapon mod at a new weapon slot. Every
    entry whose hash was identified (in `source.pak_matches`) as the
    SOURCE slot's own mdf2/mesh/pfb/physics file gets re-hashed under the
    TARGET slot's equivalent path (same ext, same version suffix, only the
    code/sid/iid substituted) -- the raw on-disk bytes (still compressed,
    whatever compression they already used) are copied through completely
    unchanged, only the hash64 key changes. Every OTHER entry (almost
    always the mod's own custom-named textures) is passed through with its
    ORIGINAL hash64 untouched -- their paths were never derived from the
    weapon's slot number in the first place (mdf2/pfb reference them by
    their own custom string, unaffected by which slot the file now
    occupies), and since a pak hash isn't invertible there's no way to
    "relocate" an entry whose original path string was never known."""
    archive = PakArchive(pak_path)
    hash_to_match = {m["hash64"]: m for m in source.pak_matches}

    def _dst_hash(m: dict) -> int:
        base = (f"natives/stm/art/model/item/it{dst_code}/{dst_sid}/{dst_iid}/it{dst_code}{dst_sid}_{dst_iid}_0"
                if m["ext"] != "pfb" else
                f"natives/stm/GameDesign/equip/_prefab/weapon/wp{dst_code}/{dst_sid}/{dst_iid}/"
                f"it{dst_code}{dst_sid}_{dst_iid}_0")
        return pak_path_hash64(f"{base}.{m['ext']}.{m['version']}")

    out_entries = []
    relocated = 0
    for h, entry in archive.entries.items():
        new_hash = h
        m = hash_to_match.get(h)
        if m is not None:
            new_hash = _dst_hash(m)
            relocated += 1
        out_entries.append({
            "hash64": new_hash,
            "data": archive.read_raw_compressed(entry),
            "decompressed_size": entry.decompressed_size,
            "compression": entry.compression,
        })

    write_pak(out_entries, str(out_pak_path))
    log(f"    [retarget] {relocated} pak entr{'y' if relocated == 1 else 'ies'} relocated "
        f"it{source.type_code}/{source.sid}/{source.iid} -> it{dst_code}/{dst_sid}/{dst_iid} "
        f"({len(out_entries) - relocated} other entr{'y' if len(out_entries) - relocated == 1 else 'ies'} unchanged)")
    return relocated


def retarget_archive(archive_or_dir: Path, out_zip: Path, dst_code: str, dst_sid: str, dst_iid: str,
                      log=lambda s: None) -> ModWeaponInfo:
    """End-to-end: extract (if an archive), detect, relocate, and write
    out_zip. Raises ValueError with the detected weapon-id list when the
    mod doesn't target exactly one weapon model. Handles both loose-file
    mods (retarget_tree) and standalone-.pak mods (retarget_pak, see that
    function's docstring for why the two need genuinely different logic)."""
    import tempfile
    from archive_extract import extract_archive
    work = Path(tempfile.mkdtemp(prefix="weapon_retarget_"))
    try:
        mod_root = archive_or_dir if archive_or_dir.is_dir() else extract_archive(archive_or_dir, work)
        info = detect_mod_weapon(mod_root)
        if not isinstance(info, ModWeaponInfo):
            raise ValueError(f"mod does not target exactly one weapon model (found: {info or 'none'})")
        out_root = work / "out"
        out_root.mkdir(parents=True, exist_ok=True)
        if info.pak_path is not None:
            # Copy the whole mod tree through unchanged (modinfo.ini,
            # preview image, any other loose files alongside the pak),
            # then overwrite just the pak itself with the relocated build.
            # The file list is materialized BEFORE copying starts -- out_root
            # lives inside mod_root (both under `work`), so a live
            # mod_root.rglob("*") re-discovers each freshly-copied file as
            # a new source to copy, recursing into its own output forever
            # (confirmed real 2026-08-10: caught a live test still copying
            # the same 3 files in a loop after 180+ seconds). retarget_tree()
            # never had this bug since it iterates a pre-captured
            # `source.files` list from detect_mod_weapon(), not a live scan.
            for p in list(mod_root.rglob("*")):
                if not p.is_file():
                    continue
                dst = out_root / p.relative_to(mod_root)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, dst)
            out_pak = out_root / info.pak_path.relative_to(mod_root)
            retarget_pak(info.pak_path, out_pak, info, dst_code, dst_sid, dst_iid, log=log)
        else:
            retarget_tree(mod_root, out_root, info, dst_code, dst_sid, dst_iid, log=log)
        out_zip.parent.mkdir(parents=True, exist_ok=True)
        if out_zip.exists():
            out_zip.unlink()
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in out_root.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(out_root))
        return info
    finally:
        shutil.rmtree(work, ignore_errors=True)


def retarget_tree_multi(mod_root: Path, out_root: Path, groups: list[ModWeaponInfo],
                         unmatched: list[Path], assignments: dict, log=lambda s: None) -> dict:
    """Relocates every detected weapon group independently per
    `assignments` ({group.key: (dst_code, dst_sid, dst_iid) | None}) --
    `None` means "leave this group's files exactly where they are,
    untouched," a real, deliberate choice mirroring
    slot_retarget.retarget_tree_multi()'s own semantics exactly. Every
    unmatched file (FOMOD config, readmes, ...) is always copied through
    byte-identical regardless of any group's assignment. Returns
    {group.key: files actually relocated} for reporting.

    Handles BOTH loose-file groups and pak-bearing groups (`pak_path` set,
    from detect_mod_weapons()'s pak fallback) -- a pak group rebuilds its
    own pak directly via retarget_pak() (no staging needed, the rebuild is
    already self-contained) instead of going through the loose-file
    retarget_tree() path."""
    import tempfile
    moved_counts = {}
    for group in groups:
        dst = assignments.get(group.key)
        if group.pak_path is not None:
            out_pak = out_root / group.pak_path.relative_to(mod_root)
            out_pak.parent.mkdir(parents=True, exist_ok=True)
            if dst is None:
                shutil.copyfile(group.pak_path, out_pak)
                moved_counts[group.key] = 0
                log(f"    [retarget] {group.key} (pak) left unchanged")
            else:
                dst_code, dst_sid, dst_iid = dst
                moved_counts[group.key] = retarget_pak(
                    group.pak_path, out_pak, group, dst_code, dst_sid, dst_iid, log=log)
            continue
        if dst is None:
            for p in group.files:
                out = out_root / p.relative_to(mod_root)
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, out)
            moved_counts[group.key] = 0
            log(f"    [retarget] {group.key} left unchanged ({len(group.files)} file(s))")
            continue
        dst_code, dst_sid, dst_iid = dst
        # Each reassigned group is built in an ISOLATED staging directory
        # first, then merged into out_root -- retarget_tree()'s own
        # leftover-trace safety scan covers the whole tree it's given, and
        # running several groups directly into a shared out_root would let
        # one group's own output accidentally satisfy (or fail) another's
        # scan (same reasoning as slot_retarget.retarget_tree_multi()).
        stage = Path(tempfile.mkdtemp(prefix="weapon_retarget_stage_"))
        try:
            moved_counts[group.key] = retarget_tree(mod_root, stage, group, dst_code, dst_sid, dst_iid, log=log)
            for f in stage.rglob("*"):
                if f.is_file():
                    out = out_root / f.relative_to(stage)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(f, out)
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    for p in unmatched:
        out = out_root / p.relative_to(mod_root)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, out)
    return moved_counts


def retarget_archive_multi(archive_or_dir: Path, out_zip: Path, assignments: dict,
                            log=lambda s: None, password: str | None = None) -> tuple[list[ModWeaponInfo], dict]:
    """End-to-end multi-weapon version: extract, detect every weapon
    group, apply `assignments`, write out_zip. Every detected group MUST
    have an entry in `assignments` (even if the value is `None`, meaning
    "leave it") -- a group the caller never decided on is refused rather
    than silently left as a default, so a GUI can't accidentally ship a
    half-decided mod. Mirrors slot_retarget.retarget_archive_multi()
    exactly, including the `password` re-extraction caveat documented there."""
    import tempfile
    from archive_extract import extract_archive
    work = Path(tempfile.mkdtemp(prefix="weapon_retarget_multi_"))
    try:
        mod_root = archive_or_dir if archive_or_dir.is_dir() else extract_archive(archive_or_dir, work, password=password)
        groups, unmatched = detect_mod_weapons(mod_root)
        missing = [g.key for g in groups if g.key not in assignments]
        if missing:
            raise ValueError(f"no decision provided for detected weapon(s): {missing}")
        out_root = work / "out"
        out_root.mkdir(parents=True, exist_ok=True)
        moved_counts = retarget_tree_multi(mod_root, out_root, groups, unmatched, assignments, log=log)
        out_zip.parent.mkdir(parents=True, exist_ok=True)
        if out_zip.exists():
            out_zip.unlink()
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in out_root.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(out_root))
        return groups, moved_counts
    finally:
        shutil.rmtree(work, ignore_errors=True)
