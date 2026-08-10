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


def weapon_label(key: str) -> str:
    """UI-facing label for a weapon table key. Raw id only for now --
    unlike armor's armor_name()/ArmorSeries.msg (CLAUDE.md #39),
    weaponseries.msg only names 47 SERIES for 622 individual models (not
    1:1), so no reliable per-model name resolution exists yet
    (bake_weapon_slots.py's own docstring defers this deliberately).
    Don't guess a name here -- show the id, exactly like the tool does
    everywhere else it genuinely doesn't know something."""
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

    @property
    def key(self) -> str:
        return f"it{self.type_code}/{self.sid}/{self.iid}"


def detect_mod_weapon(mod_root: Path) -> ModWeaponInfo | list[str]:
    """Scans an extracted mod for the weapon model it targets. Returns a
    ModWeaponInfo when exactly ONE (type, sid, iid) triple is found -- or
    the sorted list of distinct keys seen when zero/multiple are found
    (multi-option FOMOD-style mods aren't supported for automatic
    retargeting here either, mirroring slot_retarget.detect_mod_slot)."""
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
      soft warning."""
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


def retarget_archive(archive_or_dir: Path, out_zip: Path, dst_code: str, dst_sid: str, dst_iid: str,
                      log=lambda s: None) -> ModWeaponInfo:
    """End-to-end: extract (if an archive), detect, relocate, and write
    out_zip. Raises ValueError with the detected weapon-id list when the
    mod doesn't target exactly one weapon model."""
    import tempfile
    from archive_extract import extract_archive
    work = Path(tempfile.mkdtemp(prefix="weapon_retarget_"))
    try:
        mod_root = archive_or_dir if archive_or_dir.is_dir() else extract_archive(archive_or_dir, work)
        info = detect_mod_weapon(mod_root)
        if not isinstance(info, ModWeaponInfo):
            raise ValueError(f"mod does not target exactly one weapon model (found: {info or 'none'})")
        out_root = work / "out"
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
