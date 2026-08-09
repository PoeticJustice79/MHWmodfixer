"""
Handles mods packaged as their own standalone .pak file, as opposed to
loose files under natives/... -- confirmed real-world case: some variants
in "Summer Fleet Weapons" ship this way, and the .pak turned out to be the
exact same KPKA format the game's own paks use (just unencrypted, with no
chunking), so pak_reader.py opens it with zero changes.

The key difference from the loose-file case: entries inside a mod's own
.pak carry no filename, only a hash64 -- so there's nothing to path-match
against vanilla, and no mh->ch-style guessing is possible (or needed): if
an entry's hash64 exactly matches one of the game's own CURRENT entries,
that IS the vanilla donor, unambiguously (game_archive.GameArchive.read_by_hash).
Similarly there's no filename to read the mdf2 "version number" from, so
we brute-force it the same way pak_mod_fix always would need to
(mdf2.detect_numVersion) for both the mod's own blob and the donor's.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from auto_fix import MaterialPlan, _material_needs_fix, apply_texture_overrides
from game_archive import GameArchive
from mdf2 import Mdf2File, detect_numVersion
from mdf2_slice import assemble_mdf2, extract_material
from pak_reader import PakArchive
from pak_writer import compress_for, write_pak
from pfb_fix import _crc_only_fix, _find_substitution, _parse_rsz, _resource_strings
from slot_merge import find_donor_for_material


_PROGRESS_STEP = 20  # how often progress_cb fires -- frequent enough to feel live, rare enough not to flood a GUI queue on a multi-thousand-entry pak


def find_pak_files(root: Path):
    yield from root.rglob("*.pak")


@dataclass
class PakMdfEntryPlan:
    hash64: int
    mod_numVersion: int
    donor_numVersion: int | None
    donor_bytes: bytes | None = None
    donor_src: str | None = None
    materials: list[MaterialPlan] = field(default_factory=list)

    @property
    def unresolved(self) -> bool:
        return any(m.donor_blob is None for m in self.materials)

    @property
    def needs_rebuild(self) -> bool:
        return any(m.stale for m in self.materials) and not self.unresolved


_RSZ_MAGICS = {b"PFB\x00": "pfb", b"USR\x00": "user", b"SCN\x00": "scn"}
# All three are RE Engine's RSZ-serialized formats (prefab / userdata / scene)
# -- confirmed by inspecting a another community MHWilds mod-fixer's source,
# which treats all three identically for exactly this kind of repair.
# pfb_fix.py's _parse_rsz() finds the "RSZ" block by string search rather
# than a fixed per-format offset, so the same repair logic already works
# on any of them unmodified -- only the entry-type detection needed to widen.


@dataclass
class PakRszEntryPlan:
    """An RSZ-serialized entry (.pfb / .user / .scn -- see _RSZ_MAGICS)
    bundled inside the mod's own pak. Unlike loose-file pfb repair
    (pfb_fix.py), the donor here is found by matching this entry's hash64
    directly against the current game's pak index -- exact and
    unambiguous, no mh<->ch custom-slot guessing needed (see this module's
    docstring) -- so `_find_substitution()`'s substitution-pair search is
    reused only for its "are these two string sets close enough" verdict;
    any actual substitution pair it proposes is meaningless here (there's
    no path to translate) and is ignored."""
    hash64: int
    ext: str = "pfb"  # "pfb" | "user" | "scn" -- for logging only, see _RSZ_MAGICS
    result: bytes | None = None  # the exact bytes to write; None means "leave this entry exactly as shipped"
    kind: str = "unresolved"  # "already_current" | "crc" | "crc_extra" | "replace" | "forced" | "unresolved"

    @property
    def unresolved(self) -> bool:
        return self.kind == "unresolved"

    @property
    def needs_rebuild(self) -> bool:
        return self.result is not None


@dataclass
class PakPlan:
    pak_path: Path
    mdf_entries: list[PakMdfEntryPlan] = field(default_factory=list)
    rsz_entries: list[PakRszEntryPlan] = field(default_factory=list)

    @property
    def applicable(self) -> bool:
        return len(self.mdf_entries) > 0 or len(self.rsz_entries) > 0

    @property
    def unresolved(self) -> bool:
        """Deliberately mdf-only (unchanged from before pfb entries existed):
        this gates whether auto_fix.py attempts to write the pak AT ALL, and
        an unresolved pfb entry shouldn't block mdf fixes that already work
        fine on their own -- write_fixed_pak() already skips each pfb entry
        independently (see its own unresolved check), so an unresolved pfb
        alongside fully-resolved mdf entries still gets the mdf fixes
        written, just with that one pfb entry correctly left untouched."""
        return any(e.unresolved for e in self.mdf_entries)

    @property
    def rsz_unresolved_count(self) -> int:
        return sum(1 for e in self.rsz_entries if e.unresolved)

    @property
    def needs_rebuild(self) -> bool:
        return any(e.needs_rebuild for e in self.mdf_entries) or any(e.needs_rebuild for e in self.rsz_entries)


def _plan_pak_rsz_entry(mod_bytes: bytes, donor_bytes: bytes | None, ext: str,
                         force_unresolved: bool, preserve_extra: bool) -> PakRszEntryPlan | None:
    """An RSZ-serialized entry (.pfb/.user/.scn) bundled in the mod's own
    pak, planned the same safe way loose-file pfb repair works (pfb_fix.py)
    -- CRC-only patch tried first, then a resource-string closeness check
    before falling back to a wholesale donor-bytes replace -- except
    there's no path to path-match or character-code substitute here at
    all: the donor was already found by an exact hash64 match (see this
    module's docstring), so whenever a "wholesale replace" is warranted
    the result is simply the donor's own current bytes verbatim. Confirmed
    real case this was written for: a mod's own bundled .pfb AND .user
    (SilverWolf, Nexus 964) silently never got touched at all before this
    existed (pak-packaged mods only ever got their .mdf2 entries checked),
    leaving genuinely stale RSZ content in place -- REFramework reported
    both [Invalid file] and the character rendered fully invisible, the
    same failure signature loose-file pfb staleness produces (see
    pfb_fix.py). Returns None if the entry can't be parsed as RSZ at all
    (caller leaves it untouched, unrelated to this repair)."""
    if donor_bytes is None:
        return PakRszEntryPlan(hash64=0, ext=ext, result=None, kind="unresolved")  # hash64 filled in by caller

    mod_info = _parse_rsz(mod_bytes)
    donor_info = _parse_rsz(donor_bytes)
    if mod_info is None or donor_info is None:
        return None

    crc_result = _crc_only_fix(mod_bytes, mod_info, donor_info, preserve_extra=preserve_extra, require_fits=True)
    if crc_result is not None:
        patch, used_extra = crc_result
        return PakRszEntryPlan(hash64=0, ext=ext, result=patch, kind="crc_extra" if used_extra else "crc")

    mod_strings = _resource_strings(mod_bytes, mod_info["rsz_off"])
    donor_strings = _resource_strings(donor_bytes, donor_info["rsz_off"])
    sub_result = _find_substitution(mod_strings, donor_strings, force=force_unresolved)
    if sub_result is None:
        return PakRszEntryPlan(hash64=0, ext=ext, result=None, kind="unresolved")

    kind_tag, _sub = sub_result  # any substitution pair found is meaningless here -- see docstring
    if donor_bytes == mod_bytes:
        return PakRszEntryPlan(hash64=0, ext=ext, result=None, kind="already_current")
    return PakRszEntryPlan(hash64=0, ext=ext, result=donor_bytes, kind="forced" if kind_tag == "forced" else "replace")


def resolve_pak_files(mod_root: Path, game: GameArchive, global_pool: list, allow_cross_piece: bool,
                       whole_game_lookup, log, progress_cb=None,
                       force_unresolved_pfbs: bool = False, preserve_extra_pfb_components: bool = False) -> list[PakPlan]:
    """`progress_cb(phase: str, done: int, total: int)`, if given, is called
    periodically (not on every single entry -- see _PROGRESS_STEP) during
    the two genuinely slow passes over a large pak's entry table: "pak_scan"
    (reading + donor-extracting every entry) and "pak_resolve" (matching
    each mod material against the accumulated donor pool). A big
    texture-pack-style mod's pak can hold thousands of entries, and this is
    what was silently stuck at "Diagnosing mod state..." with no feedback
    before this was added."""
    progress_cb = progress_cb or (lambda phase, done, total: None)
    pak_paths = sorted(find_pak_files(mod_root))
    archives = []
    for pak_path in pak_paths:
        try:
            archives.append((pak_path, PakArchive(pak_path)))
        except Exception as e:
            log(f"[warn] couldn't open {pak_path.name} as a pak: {e}")

    total_entries = sum(len(archive.entries) for _, archive in archives)
    raw_infos = []  # (pak_path, [unit dicts])
    scanned = 0

    for pak_path, archive in archives:
        units = []
        rsz_plans = []
        for h, entry in archive.entries.items():
            scanned += 1
            if scanned % _PROGRESS_STEP == 0 or scanned == total_entries:
                progress_cb("pak_scan", scanned, total_entries)
            try:
                raw = archive.read(entry)
            except Exception as e:
                log(f"    [warn] {pak_path.name}: couldn't read an entry ({e}), leaving it untouched")
                continue

            rsz_ext = _RSZ_MAGICS.get(raw[:4])
            if rsz_ext is not None:
                donor_bytes = game.read_by_hash(h)
                plan = _plan_pak_rsz_entry(raw, donor_bytes, rsz_ext, force_unresolved_pfbs, preserve_extra_pfb_components)
                if plan is None:
                    log(f"    [warn] {pak_path.name}#{h:016X}: couldn't parse this .{rsz_ext} entry's RSZ structure, leaving it untouched")
                    continue
                plan.hash64 = h
                rsz_plans.append(plan)
                continue

            if raw[:4] != b"MDF\x00":
                continue

            mod_nv = detect_numVersion(raw)
            if mod_nv is None:
                log(f"    [warn] {pak_path.name}: found an mdf2 entry but couldn't determine its version, skipping")
                continue
            mod_mdf = Mdf2File(raw, mod_nv)

            donor_bytes = game.read_by_hash(h)
            donor_mdf = donor_nv = None
            own_pool = []
            donor_src = f"{pak_path.name}#{h:016X}"
            if donor_bytes is not None:
                donor_nv = detect_numVersion(donor_bytes)
                if donor_nv is not None:
                    donor_mdf = Mdf2File(donor_bytes, donor_nv)
                    own_pool = [(donor_src, extract_material(donor_mdf, i))
                                for i in range(len(donor_mdf.materials))]
                    global_pool.extend(own_pool)

            units.append({
                "hash64": h, "mod_mdf": mod_mdf, "own_pool": own_pool,
                "donor_nv": donor_nv, "donor_bytes": donor_bytes, "donor_src": donor_src,
            })

        raw_infos.append((pak_path, units, rsz_plans))

    total_units = sum(len(units) for _, units, _ in raw_infos)
    resolved = 0
    plans = []
    for pak_path, units, rsz_plans in raw_infos:
        entry_plans = []
        for u in units:
            resolved += 1
            if resolved % _PROGRESS_STEP == 0 or resolved == total_units:
                progress_cb("pak_resolve", resolved, total_units)
            mod_mats = [extract_material(u["mod_mdf"], i) for i in range(len(u["mod_mdf"].materials))]
            mat_plans = []
            for mm in mod_mats:
                donor_hit = find_donor_for_material(mm, u["own_pool"], global_pool, allow_cross_piece,
                                                     log=log, whole_game_lookup=whole_game_lookup)
                if donor_hit is None:
                    mat_plans.append(MaterialPlan(mm, None, None, None, stale=True))
                    continue
                donor_blob, donor_src, match_kind = donor_hit
                stale = _material_needs_fix(mm, donor_blob)
                mat_plans.append(MaterialPlan(mm, donor_blob, donor_src, match_kind, stale))
            entry_plans.append(PakMdfEntryPlan(
                hash64=u["hash64"], mod_numVersion=u["mod_mdf"].numVersion, donor_numVersion=u["donor_nv"],
                donor_bytes=u["donor_bytes"], donor_src=u["donor_src"], materials=mat_plans,
            ))
        plans.append(PakPlan(pak_path, entry_plans, rsz_plans))
    return plans


def _rebuild_entry(entry_plan: "PakMdfEntryPlan", log) -> tuple[bytes, int]:
    """Prefer in-place texture patching of a fresh copy of the SAME donor
    file's bytes whenever every material maps to that one donor 1:1 (the
    common case -- no restructuring needed): that reuses mdf2.py's
    set_texture_path, which is proven byte-for-byte correct against real
    game files (round-trip tested), instead of mdf2_slice.assemble_mdf2's
    from-scratch reconstruction. The full reassembly path is only needed
    when materials are genuinely spliced together from different donor
    files (e.g. a restructured custom-slot mod, see slot_merge.py) --
    reassembly turned out to have at least two subtle correctness gaps
    (16-byte prop-block padding, and a checksum field that should've been
    left as 0) found only by real in-game testing, so it's used as a
    fallback, not the default, now that there's a safer option available."""
    same_single_donor = (
        entry_plan.donor_bytes is not None
        and all(mp.donor_src == entry_plan.donor_src for mp in entry_plan.materials)
    )

    if same_single_donor:
        donor_mdf = Mdf2File(entry_plan.donor_bytes, entry_plan.donor_numVersion)
        donor_names = [m.name for m in donor_mdf.materials]
        if len(set(donor_names)) != len(donor_names):
            # Two+ materials share a name in the donor file (Capcom reuses
            # generic names like "lambert2") -- name-based lookup below
            # can't tell them apart and would silently patch the wrong
            # slot, so fall back to the per-material path in slot_merge.py's
            # already-resolved donor_blob (matched more carefully, not by
            # a plain name lookup at this point).
            same_single_donor = False
        if same_single_donor and len(donor_mdf.materials) == len(entry_plan.materials):
            changed = 0
            for mp in entry_plan.materials:
                donor_mat = next((m for m in donor_mdf.materials if m.name == mp.donor_blob["name"]), None)
                if donor_mat is None:
                    same_single_donor = False
                    break
                mod_tex_by_type = {t["type"]: t["path"] for t in mp.mod_mat["textures"]}
                for tex in donor_mat.textures:
                    new_path = mod_tex_by_type.get(tex.type_str)
                    if new_path is not None and new_path != tex.path_str:
                        donor_mdf.set_texture_path(tex, new_path)
                        changed += 1
                log(f"    material {mp.mod_mat['name']!r} -> donor {mp.donor_blob['name']!r} "
                    f"(in-place patch, matched by direct pak-hash lookup against the current game, {mp.match_kind})")
            if same_single_donor:
                return donor_mdf.to_bytes(), changed

    # fallback: genuine cross-file splicing needed
    rebuilt = []
    total_changed = 0
    chosen_nv = entry_plan.donor_numVersion or entry_plan.mod_numVersion
    for mp in entry_plan.materials:
        log(f"    material {mp.mod_mat['name']!r} -> donor {mp.donor_blob['name']!r} "
            f"from {mp.donor_src!r} (reassembled, {mp.match_kind})")
        new_mat, changed = apply_texture_overrides(mp.donor_blob, mp.mod_mat, log)
        rebuilt.append(new_mat)
        total_changed += changed
    result = assemble_mdf2(rebuilt, chosen_nv)
    return result, total_changed


def write_fixed_pak(pak_plan: PakPlan, out_path: Path, log) -> tuple[int, dict]:
    """Rebuilds pak_plan.pak_path into out_path: entries whose mdf2 needed
    fixing get the rebuilt bytes (compressed the same way the ORIGINAL
    entry was -- verified against a real mod .pak that these are stored
    uncompressed, not zstd, so "upgrading" them was itself enough to hang
    the game even with byte-identical decompressed content). Everything
    else is passed through as its exact original compressed bytes, and
    entry order is preserved as-is (not re-sorted) -- see pak_writer.py's
    module docstring for why all of this matters.

    Each pfb entry (see PakRszEntryPlan) is resolved independently of every
    mdf entry and of every OTHER pfb entry -- one unresolved pfb doesn't
    stop a resolved one, or any mdf fix, from being written.

    Returns (total_changed_texture_paths, pfb_stats) -- pfb_stats has the
    same key names as pfb_fix.py's resolve_and_fix_pfbs() for consistency:
    fixed/crc_only/crc_only_extra/forced/already_current/unresolved."""
    archive = PakArchive(pak_plan.pak_path)
    total_changed = 0
    fixed: dict[int, tuple[bytes, int]] = {}  # hash64 -> (new_result_bytes, decompressed_size)
    pfb_stats = {"fixed": 0, "crc_only": 0, "crc_only_extra": 0, "forced": 0, "already_current": 0, "unresolved": 0}

    for entry_plan in pak_plan.mdf_entries:
        if entry_plan.unresolved or not entry_plan.needs_rebuild:
            continue
        result, changed = _rebuild_entry(entry_plan, log)
        total_changed += changed
        fixed[entry_plan.hash64] = (result, len(result))

    for rsz_plan in pak_plan.rsz_entries:
        if rsz_plan.kind == "already_current":
            pfb_stats["already_current"] += 1
        elif rsz_plan.kind == "unresolved":
            pfb_stats["unresolved"] += 1
        elif rsz_plan.result is not None:
            fixed[rsz_plan.hash64] = (rsz_plan.result, len(rsz_plan.result))
            pfb_stats["fixed"] += 1
            if rsz_plan.kind == "crc":
                pfb_stats["crc_only"] += 1
                log(f"    [crc-patched] .{rsz_plan.ext}#{rsz_plan.hash64:016X} -- structure identical to "
                    f"current donor, only stale instance CRC(s) updated")
            elif rsz_plan.kind == "crc_extra":
                pfb_stats["crc_only_extra"] += 1
                log(f"    [crc-patched, custom parts kept] .{rsz_plan.ext}#{rsz_plan.hash64:016X} -- some "
                    f"instances the current donor doesn't have were left as shipped; only stale CRC(s) "
                    f"among shared instances updated -- experimental option, verify in-game")
            elif rsz_plan.kind == "forced":
                pfb_stats["forced"] += 1
                log(f"    [forced-fix] .{rsz_plan.ext}#{rsz_plan.hash64:016X} -- structure didn't safely "
                    f"reconcile; forced anyway (experimental option), verify in-game")
            else:
                log(f"    [fixed] .{rsz_plan.ext}#{rsz_plan.hash64:016X} <- current donor (direct pak-hash match)")

    out_entries = []
    for h, entry in archive.entries.items():
        if h in fixed:
            result, dsize = fixed[h]
            data = compress_for(entry.compression, result)
        else:
            data = archive.read_raw_compressed(entry)
            dsize = entry.decompressed_size
        out_entries.append({"hash64": h, "data": data, "decompressed_size": dsize, "compression": entry.compression})

    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_pak(out_entries, str(out_path))

    # Read the just-written pak back and check it describes exactly the same
    # set of entries as the input -- confirmed useful pattern from
    # another community fixer's pak_patch.py (fix_pak()'s post-write check).
    # We write to a fresh output path rather than in place, so this can't
    # protect the user's original mod the way theirs does; it exists to
    # catch a packing bug (a dropped or duplicated entry) here, before the
    # user finds out in-game instead.
    verify_archive = PakArchive(out_path)
    if len(verify_archive.entries) != len(archive.entries):
        raise RuntimeError(
            f"{pak_plan.pak_path.name}: wrote {len(verify_archive.entries)} entries but "
            f"input had {len(archive.entries)} -- internal packing bug, not shipping this pak")
    if set(verify_archive.entries) != set(archive.entries):
        raise RuntimeError(
            f"{pak_plan.pak_path.name}: output entry hashes don't match the input's -- "
            f"internal packing bug, not shipping this pak")
    return total_changed, pfb_stats
