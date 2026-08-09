"""적용 방어구 변경 (armor slot retargeting): relocate a mod built for one
ch03 armor slot onto a different, physics-compatible slot.

The whole approach was validated manually before becoming a feature
(CLAUDE.md #33, both moves confirmed working in-game 2026-08-09):
OVR Rogue Bifrost 041/001 -> 051/001, then TFD Bunny 051/001 -> 012/001.
The recipe this module implements is exactly what those moves did:

1. Compatibility = per-piece physics profile match, using the bundled
   community reference table (tools/armor_slots_ch03.json.gz, baked by
   tools/bake_armor_slots.py): a piece with `chain` physics on the source
   slot needs `chain` on the target too, or that piece's cloth/jiggle
   physics silently dies; a target piece with `gpuc` (GPU cloth) is
   flagged -- no community tool can edit gpuc, so replacing such a piece
   is explicitly warned against by the reference table's own authors.
2. Relocation is PATH renaming only -- directory parts and filename
   prefixes. File CONTENT is never touched: internal cross-slot
   references (e.g. an avp borrowing another slot's hair-hide params,
   #30) and old-slot vanilla texture paths are all slot-independent and
   remain valid wherever the files live. (Both verified moves confirmed
   this: Bifrost's avp references 036's, Bunny's references 023's --
   untouched, both work.)
3. Version-suffix differences between what the mod ships and what the
   target's vanilla files use are preserved as-is when they MIRROR the
   source slot's own relationship (e.g. mods shipping chain2.14 over
   vanilla .13 -- already the shipped, working state at the source).
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
SLOT_TABLE_PATH = _HERE / "tools" / "armor_slots_ch03.json.gz"

_slot_table_cache: dict | None = None

# .../ch03/<set>/<variant>/... in art/model paths, and
# .../Armor/<gender>/<set>/<variant>/... in GameDesign prefab paths.
_MODEL_SLOT_RE = re.compile(r"ch0[23][\\/](\d{3})[\\/](\d{3})[\\/]", re.IGNORECASE)
_PREFAB_SLOT_RE = re.compile(r"armor[\\/](?:fe)?male[\\/](\d{3})[\\/](\d{3})[\\/]", re.IGNORECASE)
# piece number comes from filenames like ch03_051_0011.* (variant 001 + piece 1).
# ch02 = male hunter model, ch03 = female -- the game ships BOTH in parallel
# for every armor set/variant number (confirmed live), so a mod's ch02 and
# ch03 copies of the same slot are always the same logical armor and must
# move together, never treated as two different things.
_PIECE_FILE_RE_TMPL = r"ch0[23]_{set}_{var}(\d)\b"


def slot_table() -> dict:
    """{ "SSS/VVV": {set, variant, name, pieces: {"1": [tokens]}|None, slinger: bool|None} }"""
    global _slot_table_cache
    if _slot_table_cache is None:
        try:
            with gzip.open(SLOT_TABLE_PATH, "rt", encoding="utf-8") as f:
                _slot_table_cache = json.load(f)["slots"]
        except OSError:
            _slot_table_cache = {}
    return _slot_table_cache


_GENDER_LABEL = {"male": {"ko": "남성", "en": "Male"}, "female": {"ko": "여성", "en": "Female"}}


def gender_label(gender: str | None, lang: str = "ko") -> str:
    """UI-facing gender text for a slot's variant number ('남성'/'Male',
    '여성'/'Female', or '' when the sheet has no male/female sibling pair
    for that variant -- see bake_armor_slots.py's _assign_genders(). Never
    display a raw 000/001 variant number as if it meant something on its
    own -- it doesn't outside this pairing."""
    if gender not in _GENDER_LABEL:
        return ""
    return _GENDER_LABEL[gender].get(lang, _GENDER_LABEL[gender]["en"])


def armor_name(name_ko: str, name_en: str | None, lang: str = "ko") -> str:
    """UI-facing armor/set name -- Korean for a Korean UI, otherwise the
    English name when this project could confidently resolve one (see
    bake_armor_slots.py's NAME_EN_OVERRIDES), falling back to the Korean
    name when it couldn't. Per the user, ja/zh_tw/zh_cn intentionally
    share the English fallback rather than getting their own translation
    -- not worth building without a source to verify against."""
    if lang != "ko" and name_en:
        return name_en
    return name_ko


@dataclass
class ModSlotInfo:
    set_no: str
    variant: str
    pieces_shipped: set[int]           # piece numbers (1..6) the mod ships model files for
    files: list[Path] = field(default_factory=list)  # every file in the mod root (for relocation)
    name: str = "?"
    name_en: str | None = None         # see armor_name()
    gender: str | None = None          # "male" | "female" | None (see gender_label())

    @property
    def key(self) -> str:
        return f"{self.set_no}/{self.variant}"


def detect_mod_slot(mod_root: Path) -> ModSlotInfo | list[str]:
    """Scans an extracted mod for the armor slot it targets. Returns a
    ModSlotInfo when exactly ONE (set, variant) pair is found -- or the
    list of distinct pair keys when zero/multiple are found (multi-option
    FOMOD-style mods aren't supported for automatic retargeting; the
    caller shows which slots were seen so the user understands why)."""
    pairs: set[tuple[str, str]] = set()
    files = []
    for p in mod_root.rglob("*"):
        if not p.is_file():
            continue
        files.append(p)
        rel = str(p.relative_to(mod_root))
        for rx in (_MODEL_SLOT_RE, _PREFAB_SLOT_RE):
            m = rx.search(rel)
            if m:
                pairs.add((m.group(1), m.group(2)))
    if len(pairs) != 1:
        return sorted(f"{s}/{v}" for s, v in pairs)
    set_no, variant = next(iter(pairs))
    piece_re = re.compile(_PIECE_FILE_RE_TMPL.format(set=set_no, var=variant), re.IGNORECASE)
    pieces = set()
    for p in files:
        m = piece_re.search(p.name)
        if m:
            pieces.add(int(m.group(1)))
    table_entry = slot_table().get(f"{set_no}/{variant}")
    name = table_entry["name"] if table_entry else "?"
    name_en = table_entry.get("name_en") if table_entry else None
    gender = table_entry["gender"] if table_entry else None
    return ModSlotInfo(set_no=set_no, variant=variant, pieces_shipped=pieces, files=files,
                        name=name, name_en=name_en, gender=gender)


@dataclass
class TargetCandidate:
    key: str          # "SSS/VVV"
    set_no: str
    variant: str
    name: str
    grade: str        # "exact" | "partial" | "gpuc"
    name_en: str | None = None    # see armor_name()
    gender: str | None = None     # "male" | "female" | None -- see gender_label()
    lost_pieces: list[int] = field(default_factory=list)   # pieces whose chain physics would die
    gpuc_pieces: list[int] = field(default_factory=list)   # target pieces carrying uneditable GPU cloth
    cross_variant: bool = False   # variant number differs from the source's (renaming verified only same-variant so far)
    verified: bool = False        # live-game vanilla completeness check passed


def find_compatible_targets(source: ModSlotInfo) -> list[TargetCandidate]:
    """Ranks every table slot with a known physics profile against the
    source slot's profile, best first. Slots with no usable profile in the
    table (accessories/rows the sheet only annotated as chain O/X) are
    excluded outright -- never guessed at. The source slot itself is
    excluded too."""
    table = slot_table()
    src = table.get(f"{source.set_no}/{source.variant}")
    if not src or not src.get("pieces"):
        return []
    src_pieces: dict[str, set] = {k: set(v) for k, v in src["pieces"].items()}
    relevant = [str(p) for p in sorted(source.pieces_shipped) if 1 <= p <= 5 and str(p) in src_pieces]
    need_slinger = 6 in source.pieces_shipped

    out = []
    for key, cand in table.items():
        if key == f"{source.set_no}/{source.variant}" or not cand.get("pieces"):
            continue
        cpieces = {k: set(v) for k, v in cand["pieces"].items()}
        if any(p not in cpieces for p in relevant):
            continue  # target lacks the piece entirely -- not a viable home
        if need_slinger and cand.get("slinger") is False:
            continue
        lost = [int(p) for p in relevant
                if "chain" in src_pieces[p] and "chain" not in cpieces[p]]
        gpuc = [int(p) for p in relevant if "gpuc" in cpieces[p]]
        grade = "gpuc" if gpuc else ("partial" if lost else "exact")
        out.append(TargetCandidate(
            key=key, set_no=cand["set"], variant=cand["variant"], name=cand["name"],
            grade=grade, name_en=cand.get("name_en"), gender=cand.get("gender"),
            lost_pieces=lost, gpuc_pieces=gpuc,
            cross_variant=(cand["variant"] != source.variant),
        ))
    grade_rank = {"exact": 0, "partial": 1, "gpuc": 2}
    out.sort(key=lambda c: (grade_rank[c.grade], c.cross_variant, c.set_no, c.variant))
    return out


def verify_target_vanilla(game, source: ModSlotInfo, target: TargetCandidate) -> tuple[bool, list[str]]:
    """Live-game completeness check for the target slot: every piece the
    mod ships must have a vanilla mdf2+mesh+pfb at the target (piece 6
    checks mesh+pfb only -- some slots have no slinger mdf2), plus the avp.
    Returns (ok, list of missing descriptions)."""
    missing = []
    s, v = target.set_no, target.variant
    piece_dirs = {1: "Arm", 2: "Body", 3: "Helm", 4: "Leg", 5: "Waist", 6: "Slinger"}
    for p in sorted(source.pieces_shipped):
        base = f"natives/stm/art/model/character/ch03/{s}/{v}/{p}/ch03_{s}_{v}{p}"
        if p <= 5 and game.find_versioned_path(base, "mdf2", range(1, 200)) is None:
            missing.append(f"piece {p} mdf2")
        if game.find_versioned_path(base, "mesh", [241111606, 240820143, 230517984]) is None:
            missing.append(f"piece {p} mesh")
        pfb = f"natives/stm/gamedesign/equip/_prefab/armor/female/{s}/{v}/{piece_dirs[p]}/ch03_{s}_{v}{p}"
        if game.find_versioned_path(pfb, "pfb", range(1, 50)) is None:
            missing.append(f"piece {p} pfb")
    for gender_dir in ("female", "male"):
        avp = f"natives/stm/gamedesign/equip/_prefab/armor/{gender_dir}/{s}/{v}/{s}_{v}_avp"
        if game.find_versioned_path(avp, "user", range(1, 50)) is None:
            missing.append(f"{gender_dir} avp.user")
    return (not missing), missing


def retarget_tree(mod_root: Path, out_root: Path, source: ModSlotInfo,
                   dst_set: str, dst_variant: str, log=lambda s: None) -> int:
    """Copies the mod into out_root with every slot-identifying path part
    and filename prefix renamed from the source slot to the target --
    exactly the verified #33 recipe. PART-level directory renaming only
    (never substring-replace on a whole path: that's the bug the first
    manual attempt hit); file contents are copied byte-identical. A
    ch02/ch03 filename prefix is preserved as whichever one it already was
    (ch02 = male hunter model, ch03 = female -- both exist in parallel for
    every slot and must both relocate, but neither should ever be coerced
    into the other). Returns the number of relocated files."""
    src_set, src_var = source.set_no, source.variant
    fname_re = re.compile(rf"(ch0[23])_{src_set}_{src_var}(?=[\d_])")
    avp_re = re.compile(rf"{src_set}_{src_var}_avp")
    moved = 0
    for p in source.files:
        parts = list(p.relative_to(mod_root).parts)
        new_parts = []
        i = 0
        while i < len(parts):
            part = parts[i]
            if part == src_set and i + 1 < len(parts) and parts[i + 1] == src_var:
                new_parts.extend([dst_set, dst_variant])
                i += 2
                continue
            np = fname_re.sub(lambda m: f"{m.group(1)}_{dst_set}_{dst_variant}", part)
            np = avp_re.sub(f"{dst_set}_{dst_variant}_avp", np)
            new_parts.append(np)
            i += 1
        dst = out_root.joinpath(*new_parts)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dst)
        if new_parts != parts:
            moved += 1
    # hard safety: the output tree must carry ZERO traces of the source slot
    leftover = [str(q.relative_to(out_root)) for q in out_root.rglob("*")
                if re.search(rf"(^|[\\/_]){src_set}[\\/_]{src_var}([\\/_]|$)|ch0[23]_{src_set}_{src_var}",
                              str(q.relative_to(out_root)))]
    if leftover:
        raise RuntimeError(f"retarget left {len(leftover)} source-slot path(s) behind: {leftover[:3]}")
    log(f"    [retarget] {moved} file(s) relocated {src_set}/{src_var} -> {dst_set}/{dst_variant}")
    return moved


def retarget_archive(archive_or_dir: Path, out_zip: Path, dst_set: str, dst_variant: str,
                      log=lambda s: None) -> ModSlotInfo:
    """End-to-end: extract (if an archive), detect, relocate, and write
    out_zip. Raises ValueError with the detected slot list when the mod
    doesn't target exactly one slot."""
    import tempfile
    from archive_extract import extract_archive
    work = Path(tempfile.mkdtemp(prefix="retarget_"))
    try:
        if archive_or_dir.is_dir():
            mod_root = archive_or_dir
        else:
            mod_root = extract_archive(archive_or_dir, work)
        info = detect_mod_slot(mod_root)
        if not isinstance(info, ModSlotInfo):
            raise ValueError(f"mod does not target exactly one armor slot (found: {info or 'none'})")
        out_root = work / "out"
        retarget_tree(mod_root, out_root, info, dst_set, dst_variant, log=log)
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


# ---- multi-slot API -------------------------------------------------------
# A single mod archive can legitimately touch several DIFFERENT armor slots
# at once -- confirmed real cases: DOTEI's "EULA" (main armor at 043/600,
# plus custom textures the author stashed under 4 OTHER slots' texture
# folders) and TiNE's Qipao (a "Body" FOMOD page bundling BOTH 006/000 and
# 006/001's full piece files together). The single-slot functions above
# correctly REFUSE these rather than guessing which slot is "the" target --
# but refusing isn't good enough on its own: per the user's own call, the
# right answer is to let a person decide per slot, so EVERYTHING in the mod
# can still end up relocated, not just whichever slot happened to dominate.


@dataclass
class ModSlotGroup:
    """One detected (set, variant) slot within a mod that may span several,
    holding only the files whose own path falls under that specific slot."""
    set_no: str
    variant: str
    pieces_shipped: set[int]
    files: list[Path] = field(default_factory=list)
    name: str = "?"
    name_en: str | None = None
    gender: str | None = None

    @property
    def key(self) -> str:
        return f"{self.set_no}/{self.variant}"


def detect_mod_slots(mod_root: Path) -> tuple[list[ModSlotGroup], list[Path]]:
    """Every distinct ch03 slot a mod touches, each as its own group, plus
    the list of files that match NO slot pattern at all (FOMOD config,
    custom-hashed pak textures, readmes/covers, etc.) -- those always pass
    through untouched regardless of what any group is assigned to. Groups
    are sorted with the largest (by file count -- almost always the mod's
    real main target) first, purely for a sane default UI order; nothing
    downstream treats "first" as special."""
    piece_files: dict[tuple[str, str], list[Path]] = {}
    unmatched: list[Path] = []
    for p in mod_root.rglob("*"):
        if not p.is_file():
            continue
        rel = str(p.relative_to(mod_root))
        hit = None
        for rx in (_MODEL_SLOT_RE, _PREFAB_SLOT_RE):
            m = rx.search(rel)
            if m:
                hit = (m.group(1), m.group(2))
                break
        if hit is None:
            unmatched.append(p)
        else:
            piece_files.setdefault(hit, []).append(p)

    groups = []
    table = slot_table()
    for (set_no, variant), files in piece_files.items():
        piece_re = re.compile(_PIECE_FILE_RE_TMPL.format(set=set_no, var=variant), re.IGNORECASE)
        pieces = set()
        for f in files:
            m = piece_re.search(f.name)
            if m:
                pieces.add(int(m.group(1)))
        entry = table.get(f"{set_no}/{variant}")
        groups.append(ModSlotGroup(
            set_no=set_no, variant=variant, pieces_shipped=pieces, files=files,
            name=entry["name"] if entry else "?", name_en=entry.get("name_en") if entry else None,
            gender=entry["gender"] if entry else None,
        ))
    groups.sort(key=lambda g: (-len(g.files), g.set_no, g.variant))
    return groups, unmatched


def retarget_tree_multi(mod_root: Path, out_root: Path, groups: list[ModSlotGroup],
                         unmatched: list[Path], assignments: dict, log=lambda s: None) -> dict:
    """Relocates every group independently per `assignments`
    ({group.key: (dst_set, dst_variant) | None}); `None` means "leave this
    slot's files exactly where they are, untouched" -- a real, deliberate
    choice (e.g. DOTEI's incidental textures, which must NOT move since
    nothing else in the mod would follow their path). Every unmatched file
    is always copied through byte-identical. Returns {group.key: files
    actually relocated} for reporting.

    Each reassigned group is built in an ISOLATED staging directory first,
    then merged into out_root -- retarget_tree()'s own leftover-trace
    safety scan covers the whole tree it's given, and running several
    groups directly into a shared out_root would let one group's own
    output accidentally satisfy (or fail) another's scan."""
    import tempfile
    moved_counts = {}
    for group in groups:
        dst = assignments.get(group.key)
        if dst is None:
            for p in group.files:
                out = out_root / p.relative_to(mod_root)
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, out)
            moved_counts[group.key] = 0
            log(f"    [retarget] {group.key} left unchanged ({len(group.files)} file(s))")
            continue
        dst_set, dst_variant = dst
        info = ModSlotInfo(set_no=group.set_no, variant=group.variant,
                            pieces_shipped=group.pieces_shipped, files=group.files,
                            name=group.name, gender=group.gender)
        stage = Path(tempfile.mkdtemp(prefix="retarget_stage_"))
        try:
            moved_counts[group.key] = retarget_tree(mod_root, stage, info, dst_set, dst_variant, log=log)
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
                            log=lambda s: None) -> tuple[list[ModSlotGroup], dict]:
    """End-to-end multi-slot version: extract, detect every slot, apply
    `assignments`, write out_zip. Every detected slot MUST have an entry in
    `assignments` (even if the value is `None`, meaning "leave it") -- a
    slot the caller never decided on is refused rather than silently left
    as a default, so a GUI can't accidentally ship a half-decided mod."""
    import tempfile
    from archive_extract import extract_archive
    work = Path(tempfile.mkdtemp(prefix="retarget_multi_"))
    try:
        mod_root = archive_or_dir if archive_or_dir.is_dir() else extract_archive(archive_or_dir, work)
        groups, unmatched = detect_mod_slots(mod_root)
        missing = [g.key for g in groups if g.key not in assignments]
        if missing:
            raise ValueError(f"no decision provided for detected slot(s): {missing}")
        out_root = work / "out"
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
