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

from auto_fix import MaterialPlan, _structure_key, apply_texture_overrides
from game_archive import GameArchive
from mdf2 import Mdf2File, detect_numVersion
from mdf2_slice import assemble_mdf2, extract_material
from pak_reader import PakArchive
from pak_writer import compress_for, write_pak
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


@dataclass
class PakPlan:
    pak_path: Path
    mdf_entries: list[PakMdfEntryPlan] = field(default_factory=list)

    @property
    def applicable(self) -> bool:
        return len(self.mdf_entries) > 0

    @property
    def unresolved(self) -> bool:
        return any(e.unresolved for e in self.mdf_entries)

    @property
    def needs_rebuild(self) -> bool:
        return any(e.needs_rebuild for e in self.mdf_entries)


def resolve_pak_files(mod_root: Path, game: GameArchive, global_pool: list, allow_cross_piece: bool,
                       whole_game_lookup, log, progress_cb=None) -> list[PakPlan]:
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
        for h, entry in archive.entries.items():
            scanned += 1
            if scanned % _PROGRESS_STEP == 0 or scanned == total_entries:
                progress_cb("pak_scan", scanned, total_entries)
            try:
                raw = archive.read(entry)
            except Exception as e:
                log(f"    [warn] {pak_path.name}: couldn't read an entry ({e}), leaving it untouched")
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

        raw_infos.append((pak_path, units))

    total_units = sum(len(units) for _, units in raw_infos)
    resolved = 0
    plans = []
    for pak_path, units in raw_infos:
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
                stale = _structure_key(mm) != _structure_key(donor_blob)
                mat_plans.append(MaterialPlan(mm, donor_blob, donor_src, match_kind, stale))
            entry_plans.append(PakMdfEntryPlan(
                hash64=u["hash64"], mod_numVersion=u["mod_mdf"].numVersion, donor_numVersion=u["donor_nv"],
                donor_bytes=u["donor_bytes"], donor_src=u["donor_src"], materials=mat_plans,
            ))
        plans.append(PakPlan(pak_path, entry_plans))
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


def write_fixed_pak(pak_plan: PakPlan, out_path: Path, log) -> int:
    """Rebuilds pak_plan.pak_path into out_path: entries whose mdf2 needed
    fixing get the rebuilt bytes (compressed the same way the ORIGINAL
    entry was -- verified against a real mod .pak that these are stored
    uncompressed, not zstd, so "upgrading" them was itself enough to hang
    the game even with byte-identical decompressed content). Everything
    else is passed through as its exact original compressed bytes, and
    entry order is preserved as-is (not re-sorted) -- see pak_writer.py's
    module docstring for why all of this matters."""
    archive = PakArchive(pak_plan.pak_path)
    total_changed = 0
    fixed: dict[int, tuple[bytes, int]] = {}  # hash64 -> (new_result_bytes, decompressed_size)

    for entry_plan in pak_plan.mdf_entries:
        if entry_plan.unresolved or not entry_plan.needs_rebuild:
            continue
        result, changed = _rebuild_entry(entry_plan, log)
        total_changed += changed
        fixed[entry_plan.hash64] = (result, len(result))

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
    return total_changed
