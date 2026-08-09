"""
Auto-repairs stale .pfb (RE Engine "RSZ" prefab) files the same
conservative way mdf2 repair works: find the CURRENT vanilla donor for the
same asset (by exact path, or via the same custom-slot character-code
substitution used for mdf2 -- see donor.py), and if the mod's own pfb
turns out to be content-equivalent to that donor (identical, or differing
only by the expected path/character-code substitution), replace the whole
file with a fresh copy of the donor.

Why whole-file replacement rather than patching specific fields: mirrors
two confirmed real-world cases, found via actual in-game testing (both
originally diagnosed and fixed by hand before being generalized here):

- A mod using a custom-slot fake character code (e.g. "mh03" standing in
  for real "ch03") whose GameDesign/Equip/_Prefab/Armor/... file carried
  stale RSZ instances (leftover fur/chain-physics components) the current
  vanilla version no longer has -- referencing the now-gone components
  aborted the whole GameObject's instantiation (character rendered fully
  invisible, not just a bad texture). Fixed by cloning the CURRENT donor
  (found via the ch03-substituted path) and substituting ch03->mh03 back
  into its bytes (same string length both ways, in-place, no offset math
  needed at all).
- A mod directly overriding a weapon's own equip prefab at its real
  vanilla path (no custom-slot trick involved), whose file was only
  slightly stale (a handful of RSZ instances' stored crc no longer
  matched what the CURRENT donor uses) -- REFramework reported it as
  "[Invalid file]" and the weapon failed to load (black screen). Its
  resource-string table was otherwise byte-identical to the current
  donor's, meaning nothing about it was actually mod-specific. Fixed by
  replacing the file with the donor's current bytes wholesale.

Type-id/crc validation against an external type registry (rszmhwilds.json
from the REasy project) was tried and found UNRELIABLE as a diagnostic --
even a live, currently-working vanilla donor file can "fail" that check,
which only makes sense if the registry snapshot doesn't perfectly track
the exact shipped build, or crc isn't actually what the runtime validates
at all. Diffing the mod's own pfb directly against the current donor
(structure counts, instance (type_id, crc) multiset, resource strings) is
the reliable signal instead.

Deliberately conservative: a pfb is only ever replaced when a donor is
found AND its resource-string set (after undoing any detected
custom-slot substitution) matches the mod's own closely enough to be
confident nothing mod-specific would be discarded. Anything else --
no donor found, or the mod's pfb genuinely diverges from the donor in a
way this heuristic can't explain -- is left completely untouched and
reported as unresolved. Guessing wrong here means silently throwing away
real customization; that's the same "leave it unresolved rather than
pick a bad donor" philosophy the mdf2 side already follows.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path

import rsz_layout
from donor import candidate_donor_paths
from game_archive import GameArchive

_CODE_RE = re.compile(r"[a-z]{2}\d{2}", re.IGNORECASE)


def find_pfb_files(root: Path):
    yield from root.rglob("*.pfb.*")


def _parse_rsz(data: bytes):
    rsz_off = data.find(b"RSZ")
    if rsz_off < 0:
        return None
    version, obj_count, inst_count, userdata_count, reserved = struct.unpack_from("<IIIII", data, rsz_off + 4)
    instance_offset, data_offset, userdata_offset = struct.unpack_from("<QQQ", data, rsz_off + 4 + 20)
    inst_table_pos = rsz_off + instance_offset
    insts = [struct.unpack_from("<II", data, inst_table_pos + i * 8) for i in range(inst_count)]
    # RSZUserDataInfo entries (16 bytes each: instanceIndex i32, hash u32,
    # stringOffset u64) -- their instance indices carry no inline field data
    # in the block below, see rsz_layout.fits_current_layout().
    ud_pos = rsz_off + userdata_offset
    external = {struct.unpack_from("<i", data, ud_pos + i * 16)[0] for i in range(userdata_count)}
    return {
        "rsz_off": rsz_off, "version": version, "obj_count": obj_count,
        "inst_count": inst_count, "userdata_count": userdata_count, "insts": insts,
        "inst_table_pos": inst_table_pos, "external": external,
        "data": data[rsz_off + data_offset:],
    }


def _scan_utf16_strings(region: bytes, base_offset: int = 0) -> list[tuple[int, str]]:
    """UTF-16LE printable-ASCII runs anywhere in `region`, paired with each
    string's starting byte offset (relative to the start of the original
    buffer, via `base_offset`), so a caller can patch one specific
    occurrence in place rather than a blind buffer-wide substring replace."""
    out = []
    i = 0
    n = len(region)
    while i < n - 1:
        if region[i + 1] == 0 and 0x20 <= region[i] < 0x7F:
            j = i
            chars = []
            while j < n - 1 and region[j + 1] == 0 and region[j] != 0:
                chars.append(chr(region[j]))
                j += 2
            if len(chars) > 2:
                out.append((base_offset + i, "".join(chars)))
                i = j
                continue
        i += 1
    return out


def _resource_strings_with_offsets(data: bytes, rsz_off: int) -> list[tuple[int, str]]:
    """UTF-16LE strings in the header/resource-table region before the RSZ
    block -- resource paths, mainly -- used for the structural mod-vs-donor
    comparison in plan_pfb()/_find_substitution(), which is deliberately
    scoped to just this region so RSZ instance-data noise doesn't pollute
    the diff. NOT used for the actual substitution pass -- see
    _scan_utf16_strings() for that, which covers the whole file."""
    return _scan_utf16_strings(data[:rsz_off])


def _resource_strings(data: bytes, rsz_off: int) -> set[str]:
    return {s for _, s in _resource_strings_with_offsets(data, rsz_off)}


def _mod_provided_file_keys(mod_root: Path) -> set[str]:
    """Lowercased '<stem>.<ext>' (trailing version number stripped) for
    every file the mod actually ships, e.g. 'mh03_003_0011.jcns.5' on disk
    becomes the key 'mh03_003_0011.jcns'. A pfb's resource strings never
    carry the trailing version number, so this is what lets substitution
    tell "the mod really does bundle a custom-slot copy of this specific
    resource" apart from "the current donor references something newer
    the mod predates and never shipped a copy of at all"."""
    keys = set()
    for p in mod_root.rglob("*"):
        if not p.is_file():
            continue
        m = re.match(r"^(.+)\.(\d+)$", p.name)
        keys.add((m.group(1) if m else p.name).lower())
    return keys


_MAX_STRING_DIFF = 2  # tolerate a couple of stray *genuine* differences
# (e.g. a component whose resource the current donor no longer references
# at all, seen on a real confirmed-safe-to-replace armor pfb) without
# treating the mod as having customization worth preserving.


def _strip_at(s: str) -> str:
    return s[1:] if s.startswith("@") else s


def _residual_diff(a: set[str], b: set[str]) -> set[str]:
    """Symmetric difference after normalizing away a leading '@' (a
    streaming-flag prefix confirmed to vary inconsistently between a mod's
    own pfb and the current donor for reasons unrelated to any actual
    customization -- e.g. present on the donor's copy of a string but not
    the mod's, or vice versa, for the exact same underlying resource)."""
    a_norm = {_strip_at(s) for s in a}
    b_norm = {_strip_at(s) for s in b}
    return a_norm.symmetric_difference(b_norm)


def _find_substitution(mod_strings: set[str], donor_strings: set[str], force: bool = False):
    """Returns ('close', None) if the two string sets already match closely
    enough (within _MAX_STRING_DIFF, ignoring '@'-prefix noise) with no
    substitution needed; ('close', (donor_code, mod_code)) if replacing
    donor_code with mod_code (same length, e.g. "ch03"->"mh03") throughout
    donor_strings brings it within tolerance of mod_strings; or None if
    neither explains the difference closely enough -- caller should leave
    the file untouched in that case.

    `force=True` (the GUI's opt-in "experimental: force-fix" checkbox):
    instead of giving up when even the best candidate exceeds
    _MAX_STRING_DIFF, returns ('forced', best_pair_or_None) for the
    lowest-residual-diff candidate found (or no substitution at all, if no
    plausible code pair exists) -- the caller then does a wholesale
    donor-bytes replace anyway. Confirmed safe for the common real-world
    case (current donor gained purely-additive content the mod predates,
    e.g. a newly-added attached accessory on a Waist piece) across
    multiple real mods; confirmed UNSAFE for at least one real case (an
    Arm piece whose donor mixed two different character codes and had no
    real vanilla equivalent at all -- forcing picked a plausible-looking
    but wrong whole-game material donor). This is exactly why it's opt-in
    and off by default, not folded into the normal safety gate."""
    if len(_residual_diff(mod_strings, donor_strings)) <= _MAX_STRING_DIFF:
        return "close", None

    # Candidate codes present on only one side -- try every same-digits
    # pairing (not just a lone pair) and keep whichever minimizes the
    # residual diff, since an unrelated shared-asset code (e.g. "ch02" in
    # a "CommonTextures" reference the mod's own file simply doesn't
    # happen to include) can otherwise make a perfectly good substitution
    # look ambiguous.
    mod_blob = "\n".join(mod_strings)
    donor_blob = "\n".join(donor_strings)
    only_mod = {m.group(0) for m in _CODE_RE.finditer(mod_blob)} - {m.group(0) for m in _CODE_RE.finditer(donor_blob)}
    only_donor = {m.group(0) for m in _CODE_RE.finditer(donor_blob)} - {m.group(0) for m in _CODE_RE.finditer(mod_blob)}

    best = None
    for donor_code in only_donor:
        for mod_code in only_mod:
            if mod_code[2:] != donor_code[2:]:  # require same trailing digits
                continue
            substituted = {s.replace(donor_code, mod_code) for s in donor_strings}
            d = len(_residual_diff(mod_strings, substituted))
            if best is None or d < best[0]:
                best = (d, donor_code, mod_code)

    if best is not None and best[0] <= _MAX_STRING_DIFF:
        return "close", (best[1], best[2])
    if force:
        return "forced", (best[1], best[2]) if best is not None else None
    return None


def _crc_only_fix(mod_bytes: bytes, mod_info: dict, donor_info: dict,
                   preserve_extra: bool = False, require_fits: bool = False) -> tuple[bytes, bool] | None:
    """A CRC is a property of the CLASS (type_id), not of any one instance
    of it -- every instance of the same type_id must carry the same
    current CRC. Build a `type_id -> current crc` map straight from the
    donor's own instance table (freshly read from the installed game, so
    it's definitionally correct for whatever's currently live), then walk
    the MOD's OWN instance table and patch just the (up to) 4 CRC bytes
    of any instance whose type_id is a KNOWN donor type with a stale
    value. Nothing else in the mod's own bytes -- resource strings, the
    entire RSZ data block -- is ever touched. Returns `(patched_bytes,
    used_preserve_extra)`, or None if nothing needed patching (or the
    mod has extra instances and `preserve_extra` wasn't set -- see
    below).

    If every one of the mod's own instance types is also present in the
    donor (the mod's structure is a plain subset/reorder of current
    vanilla -- by far the common case), this is unconditionally safe and
    always tried: the file's shape hasn't genuinely changed, only a
    class's registered CRC was bumped.

    If the mod has instances of a type the donor DOESN'T have at all,
    that means the mod's file structurally diverges from current
    vanilla -- and that's genuinely ambiguous, not a clear-cut case:
    - It can be real customization the modder intentionally added (e.g.
      a `via.motion.Chain2` physics chain bundled with its own resource
      file) that donor-replace would otherwise silently delete.
    - It can equally be STALE leftover structure from an OLDER vanilla
      shape that Capcom has since simplified away (confirmed real case:
      Mangie's "Banshee" Arm piece ships `via.render.ShellFurParam` /
      `ShellFurMesh` + the same 3 chain-physics instances as an
      unrelated DOTEI mod, but Banshee's case was independently
      confirmed working in-game via the OPPOSITE choice -- discarding
      them via ordinary donor-replace). The two cases are
      indistinguishable from instance-type structure alone.
    Because of that ambiguity this half is opt-in: only attempted when
    `preserve_extra=True`, and only ever patches CRCs for the types the
    donor DOES recognize -- the extra/unmatched instances are always
    left completely as shipped either way, never guessed at.

    Deliberately not a general byte-accurate RSZ field walker (which
    could migrate an ACTUALLY-reshaped class's field data too) --
    building that needs a maintained snapshot of the PREVIOUS game
    version's field layouts, which this project doesn't keep. Always
    verify a build that hit this path in-game before trusting it,
    especially with `preserve_extra` on."""
    donor_types = {t for t, _ in donor_info["insts"]}
    mod_types = {t for t, _ in mod_info["insts"]}
    has_extra = bool(mod_types - donor_types)

    if require_fits and rsz_layout.fits_current_layout(mod_info) is not True:
        # A crc match doesn't prove the field LAYOUT is unchanged -- only
        # that some version stamp matches. Confirmed the hard way: a real
        # mod's pak-embedded pfb crashed the game after a crc-only patch
        # (2026-08-08), for exactly this reason. require_fits demands
        # positive proof (every field parses to exactly the instance's
        # byte length under the CURRENT registry) before trusting a
        # crc-only patch; "unverifiable" (registry has no field dump for
        # a type involved) counts as a refusal here too, not a pass --
        # see rsz_layout.py's module docstring for why that's the safe
        # default even though it costs some coverage.
        return None

    donor_crc_by_type: dict[int, int] = {}
    inconsistent: set[int] = set()
    for t, c in donor_info["insts"]:
        if t in donor_crc_by_type and donor_crc_by_type[t] != c:
            inconsistent.add(t)
            continue
        donor_crc_by_type[t] = c
    for t in inconsistent:
        donor_crc_by_type.pop(t, None)

    result = bytearray(mod_bytes)
    changed = 0
    for i, (mod_type, mod_crc) in enumerate(mod_info["insts"]):
        current_crc = donor_crc_by_type.get(mod_type)
        if current_crc is None or current_crc == mod_crc:
            continue
        struct.pack_into("<I", result, mod_info["inst_table_pos"] + i * 8 + 4, current_crc)
        changed += 1

    # has_extra only matters once we're about to WRITE a patch -- deciding
    # whether mod-only instances are real customization or stale leftovers
    # (see the docstring above) is irrelevant when changed == 0, since
    # nothing about those instances is being touched or judged either way.
    # Gating a zero-change, fits()-verified result on preserve_extra was
    # itself the bug: it sent an ALREADY-CURRENT file down the wholesale
    # donor-replace path instead, silently discarding its mod-only
    # instances there -- confirmed real on Forte's Leg piece (2026-08-08).
    if changed and has_extra and not preserve_extra:
        return None

    # Always return once the gates above are passed, even when changed ==
    # 0 -- that means the mod's own bytes ALREADY match the
    # current game with zero patching needed, which is strictly safe
    # regardless (nothing is being written that wasn't already there).
    # Returning None here used to be indistinguishable from "refused,
    # unsafe" to the caller, incorrectly sending an ALREADY-CURRENT file
    # (mod-only extra instances and all) down the wholesale donor-replace
    # path instead -- confirmed real on a mod (Forte's Leg piece, 2026-08-08)
    # whose 4 mod-only RSZ instances were silently discarded by that
    # fallback, making the leg mesh disappear in-game, even though the
    # file needed zero actual changes (require_fits confirmed True, zero
    # CRC mismatches among the shared instance types).
    return bytes(result), has_extra


def _transplant_reshaped(mod_bytes: bytes, mod_info: dict, donor_info: dict, log) -> bytes | None:
    """Tier 2 of the crc-only path, tried when `_crc_only_fix()` refuses
    because `fits_current_layout()` isn't True: keep the MOD's own file as
    the structural ground truth (its Object Table, component order,
    GameObjectInfo, resource manifest -- every piece of engine bookkeeping
    -- stays byte-identical), and rebuild only the field data of instances
    whose layout genuinely no longer parses. For each such instance, first
    try `rsz_layout.try_suffix_field_migration()` -- on the narrow,
    confirmed-real hypothesis that the type only grew fields APPENDED at
    the end, this recovers the mod's OWN values for every field that
    still exists and takes the donor's current value only for the
    genuinely new trailing field(s). When that hypothesis doesn't
    uniquely resolve (ambiguous or no exact-length fit), falls back to the
    older behavior: the WHOLE instance's values come from the current
    donor's own instance of the same type at the same position. Then
    patch stale CRCs among donor-known types exactly like tier 1 does.

    Why this exists -- the inverted lesson of the instance-splicing saga
    (see CLAUDE.md #17): grafting mod content ONTO donor structure failed
    5 times in-game because it required replicating engine bookkeeping
    this project provably doesn't fully understand. This direction never
    touches that bookkeeping at all: the mod file is a live proof that its
    own structure + component set loads (it worked in-game for months
    before the update), so the only thing that can be wrong with it is
    the DATA of reshaped types and stale CRCs -- both of which the donor
    supplies verbatim.

    The trigger case, confirmed byte-level (Esthe/Mask Bikini, 2026-08-09):
    Capcom added a field to `app.ChainSetting` (`_WindAssetOverwrite`, a
    second variable-length string) WITHOUT changing the class's crc -- the
    mod's copy is 20 bytes where the current donor's is 27, so the engine
    misreads a float (0x3f800000) as a string length and rejects the whole
    file. This breaks `_crc_only_fix()`'s core assumption (crc as the
    structure stamp) for this specific class: no crc anywhere in the file
    is stale in a way that names ChainSetting as the culprit. Suffix-field
    migration (added 2026-08-09) recovers the mod's own `v0_Enabled`/
    `_ObjectRegisterHandle`/`_WindBias`/etc. wholesale and takes only the
    new field(s) from the donor -- narrower and safer than the original
    all-donor transplant, which assumed (only true by luck for ChainSetting
    specifically: it's plumbing config, not mod customization) that taking
    every field from the donor loses nothing anyone authored. That
    assumption does NOT extend automatically to every reshaped type -- e.g.
    a reshaped `app.CharacterEditRegion` might carry real character-edit
    content that field migration can't recover -- which is why the
    all-donor fallback still exists (for when migration can't uniquely
    resolve) and this logs exactly what it did per instance, staying
    behind the same `preserve_extra` opt-in as tier 1's extra-keeping half,
    to be verified in-game per mod.

    Refuses (returns None) unless every one of these holds:
    - the mod's walk (with resync recovery) lands exactly on len(data),
    - the donor's own walk is fully clean with ZERO recoveries,
    - every unparseable mod instance has the donor's instance at the SAME
      index with the SAME type (positional match -- the value source),
    - every instance from the first transplant onward re-serializes
      without error (alignment padding is recomputed per position, see
      rsz_layout._write_instance_values()),
    - the rebuilt file passes `fits_current_layout()` is True.
    The caller falls through to the substitution path in that case,
    exactly as if this tier didn't exist."""
    spans, ok, recovered = rsz_layout.walk_instances_with_recovery(mod_info)
    if not ok or not recovered:
        return None
    donor_spans, donor_ok, donor_recovered = rsz_layout.walk_instances_with_recovery(donor_info)
    if not donor_ok or donor_recovered:
        return None

    donor_insts = donor_info["insts"]
    donor_span_by_index = {i: (s, e) for i, t, c, s, e in donor_spans}
    for i in recovered:
        if i >= len(donor_insts) or donor_insts[i][0] != mod_info["insts"][i][0]:
            return None
        if i in donor_info["external"] or i not in donor_span_by_index:
            return None

    registry = rsz_layout._registry()
    mod_data = mod_info["data"]
    donor_data = donor_info["data"]
    first = min(recovered)
    span_by_index = {i: (s, e) for i, t, c, s, e in spans}
    first_start = span_by_index[first][0]

    # An RSZ instance referencing a resource path that the pfb's own
    # ResourceInfo manifest doesn't declare crashes the game outright
    # (confirmed real during the splicing saga, CLAUDE.md #17) -- so donor
    # values are only accepted if every path-like string in them is one the
    # mod's own manifest already declares. In the confirmed trigger case
    # (app.ChainSetting) the donor's string fields are all empty, so this
    # guard costs nothing there; it exists for whatever reshaped type shows
    # up next.
    mod_manifest = {_strip_at(s).lower() for s in _read_resource_strings(mod_bytes)}

    out = bytearray(mod_data[:first_start])
    pos = first_start
    transplanted_names = []
    migrated_names = []
    try:
        for i, t, c, s, e in spans:
            if i < first or s == e:  # before the rebuild point, or carries no inline data
                continue
            entry = registry.get(format(t, "x"))
            if entry is None:
                return None
            if i in recovered:
                d_s, _d_e = donor_span_by_index[i]
                donor_values, _ = rsz_layout._extract_instance_values(donor_data, d_s, entry["f"])
                # Prefer keeping the mod's OWN field values where possible --
                # see rsz_layout.try_suffix_field_migration()'s docstring for
                # the narrow "new fields only ever get appended at the end"
                # hypothesis this relies on, and why an ambiguous result
                # (None) must fall back to the old all-donor behavior rather
                # than guess which candidate is real.
                migration = rsz_layout.try_suffix_field_migration(mod_data, s, e, entry["f"])
                if migration is not None:
                    mod_values, k = migration
                    new_field_values = donor_values[len(entry["f"]) - k:]
                    new_fields = entry["f"][len(entry["f"]) - k:]
                    values = mod_values + new_field_values
                    migrated_names.append(f"{entry.get('n', f'type_{t:x}')} ({k} new field(s) from donor)")
                else:
                    new_field_values = donor_values
                    new_fields = entry["f"]
                    values = donor_values
                    transplanted_names.append(entry.get("n", f"type_{t:x}"))
                # Only the DONOR-sourced fields need the dangling-resource-ref
                # guard (CLAUDE.md #17) -- the mod's own values are already
                # its own shipped bytes, not something being grafted in.
                for (_name, _size, _align, _is_array, is_variable), val in zip((f[:5] for f in new_fields), new_field_values):
                    if not is_variable:
                        continue
                    blobs = val[2] if val[0] == "array" else [val[1]]
                    for blob in blobs:
                        ref = blob[4:].decode("utf-16-le", errors="ignore").rstrip("\x00")
                        if "/" in ref and _strip_at(ref).lower() not in mod_manifest:
                            return None
            else:
                values, _ = rsz_layout._extract_instance_values(mod_data, s, entry["f"])
            pos = rsz_layout._write_instance_values(out, pos, entry["f"], values)
    except rsz_layout._LayoutError:
        return None

    data_offset_abs = len(mod_bytes) - len(mod_data)  # data block always extends to EOF for a pfb
    result = bytearray(mod_bytes[:data_offset_abs] + bytes(out))

    # Same stale-CRC patch as _crc_only_fix() tier 1, applied to the rebuilt
    # bytes. Safe under the same SilverWolf rule (#9/#12): every patched
    # instance's data is now layout-current -- non-recovered ones parsed
    # cleanly at their span, recovered ones carry the donor's own current
    # values by construction.
    donor_crc_by_type: dict[int, int] = {}
    inconsistent: set[int] = set()
    for t, c in donor_insts:
        if t in donor_crc_by_type and donor_crc_by_type[t] != c:
            inconsistent.add(t)
            continue
        donor_crc_by_type[t] = c
    for t in inconsistent:
        donor_crc_by_type.pop(t, None)
    crc_patched = 0
    for i, (mod_type, mod_crc) in enumerate(mod_info["insts"]):
        current_crc = donor_crc_by_type.get(mod_type)
        if current_crc is None or current_crc == mod_crc:
            continue
        struct.pack_into("<I", result, mod_info["inst_table_pos"] + i * 8 + 4, current_crc)
        crc_patched += 1

    # Final proof: the rebuilt data block must strict-parse (no resync
    # recovery allowed this time) to EXACTLY its full length. Deliberately
    # NOT fits_current_layout() here: that also demands all-zero alignment
    # padding, and these mods' own untouched instances carry nonzero
    # padding bytes Capcom's own writer left behind (confirmed real:
    # app.CharacterEditRegion/via.render.StreamingTextureController in
    # every Esthe/Mask Bikini piece) -- bytes the engine demonstrably
    # accepted for months and which this function raw-copies verbatim.
    # Rejecting the file over pre-existing donor-era padding would refuse
    # every real case this tier exists for. Tier 1's require_fits gate is
    # unaffected and stays strict.
    new_info = _parse_rsz(bytes(result))
    if new_info is None:
        return None
    new_data = new_info["data"]
    pos_check = 0
    for i, (t, _c) in enumerate(new_info["insts"]):
        if i == 0 or i in new_info["external"]:
            continue
        entry = registry.get(format(t, "x"))
        if entry is None:
            return None
        if entry.get("fieldless"):
            continue
        try:
            pos_check, _clean = rsz_layout._parse_instance(new_data, pos_check, entry["f"])
        except rsz_layout._LayoutError:
            return None
    if pos_check != len(new_data):
        return None

    detail_parts = []
    if migrated_names:
        detail_parts.append(f"{len(migrated_names)} migrated, mod's own values kept "
                             f"({', '.join(migrated_names)})")
    if transplanted_names:
        detail_parts.append(f"{len(transplanted_names)} rebuilt entirely from the current donor's "
                             f"field data ({', '.join(transplanted_names)})")
    log(f"    [transplant] {len(recovered)} reshaped instance(s): {'; '.join(detail_parts)}, "
        f"{crc_patched} stale CRC(s) patched; everything else (structure, components, mod "
        f"content) kept as shipped -- experimental option, verify in-game")
    return bytes(result)


def _dominant_code(strings: set[str]) -> str | None:
    """The single character code (via `_CODE_RE`) that appears most often
    across a pfb's own resource-path strings -- used as the "self code"
    for a file that resolves via `_crc_only_fix()`, where no donor_code/
    mod_code substitution pair exists at all (the file's own bytes are
    kept as-is, or only CRC-patched in place). `_fix_dangling_physics_refs()`
    still needs SOME code representing "this file's own slot" to build a
    same-suffix candidate replacement path against `mod_provided_keys` --
    this is that code, inferred directly from what the file's own strings
    predominantly use rather than from any substitution result."""
    counts: dict[str, int] = {}
    for s in strings:
        for m in _CODE_RE.finditer(s):
            counts[m.group(0)] = counts.get(m.group(0), 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


@dataclass
class PfbPlan:
    rel: Path
    mod_path: Path
    donor_path: str | None
    donor_bytes: bytes | None
    substitution: tuple[str, str] | None
    resolvable: bool  # found a donor AND could safely (or forcibly) reconcile string differences
    forced: bool = False  # resolved only because force=True was passed to plan_pfb()
    crc_patch: bytes | None = None  # set instead of substitution: write these exact bytes (mod's own content, only stale CRCs patched) rather than a donor-replace
    crc_patch_preserved_extra: bool = False  # crc_patch also kept mod-only instances the donor doesn't have -- only possible when preserve_extra_pfb_components=True was passed in
    transplanted: bool = False  # crc_patch came from _transplant_reshaped(): reshaped instances' field data was rebuilt from the donor, not just CRCs patched
    self_code: str | None = None  # this pfb's own dominant character code (see _dominant_code()) -- used to run _fix_dangling_physics_refs() on the crc_patch path, which has no donor_code/mod_code substitution pair to reuse


def plan_pfb(mod_path: Path, mod_root: Path, game: GameArchive, log, force: bool = False,
             preserve_extra: bool = False) -> PfbPlan:
    rel = mod_path.relative_to(mod_root)
    parts = rel.parts
    natives_idx = next((i for i, p in enumerate(parts) if p.lower() == "natives"), None)
    if natives_idx is None:
        return PfbPlan(rel, mod_path, None, None, None, False)
    pak_style = "natives/" + "/".join(parts[natives_idx + 1:])
    base_no_version = re.sub(r"\.pfb\.\d+$", "", pak_style, flags=re.IGNORECASE)

    mod_bytes = mod_path.read_bytes()
    mod_parsed = _parse_rsz(mod_bytes)
    if mod_parsed is None:
        return PfbPlan(rel, mod_path, None, None, None, False)
    mod_strings = _resource_strings(mod_bytes, mod_parsed["rsz_off"])
    self_code = _dominant_code(mod_strings)

    for cand in candidate_donor_paths(base_no_version):
        found = game.find_versioned(cand, "pfb")
        if found is None:
            continue
        donor_path, donor_bytes = found
        donor_parsed = _parse_rsz(donor_bytes)
        if donor_parsed is None:
            continue

        crc_result = _crc_only_fix(mod_bytes, mod_parsed, donor_parsed, preserve_extra=preserve_extra, require_fits=True)
        if crc_result is not None:
            crc_patch, used_preserve_extra = crc_result
            return PfbPlan(rel, mod_path, donor_path, donor_bytes, None, True,
                            crc_patch=crc_patch, crc_patch_preserved_extra=used_preserve_extra,
                            self_code=self_code)

        if preserve_extra:
            transplant = _transplant_reshaped(mod_bytes, mod_parsed, donor_parsed, log)
            if transplant is not None:
                return PfbPlan(rel, mod_path, donor_path, donor_bytes, None, True,
                                crc_patch=transplant, crc_patch_preserved_extra=True,
                                transplanted=True, self_code=self_code)

        donor_strings = _resource_strings(donor_bytes, donor_parsed["rsz_off"])
        result = _find_substitution(mod_strings, donor_strings, force=force)
        if result is not None:
            kind, sub = result
            return PfbPlan(rel, mod_path, donor_path, donor_bytes, sub, True, forced=(kind == "forced"),
                            self_code=self_code)
        log(f"    [warn] {rel}: found donor {donor_path!r} but its content doesn't reconcile "
            f"with the mod's own -- leaving untouched (possible real customization)")
        return PfbPlan(rel, mod_path, donor_path, donor_bytes, None, False)

    return PfbPlan(rel, mod_path, None, None, None, False)


_PHYSICS_EXTS = (".chain2", ".jcns", ".mesh", ".mdf2")
# Started as just chain2/jcns (physics rigs); widened to include mesh/mdf2
# after a real report (Forte, 2026-08-08) showed the identical dangling-
# third-code pattern on optional variant sub-parts (e.g. "..._0.mesh",
# "..._9.mdf2") once #14's fix made Leg/Arm/Helm/Waist resolve via
# crc_patch instead of substitution -- REFramework logged "[Missing file]"
# for them at load, harmless in practice (the engine just skips an
# unresolvable optional sub-part) but still worth eliminating the same way.


def _fix_dangling_physics_refs(data: bytearray, mod_code: str, mod_provided_keys: set[str],
                                game: GameArchive, log) -> int:
    """Some donor pfbs reference resources -- their chain2 (cloth/fur sway
    physics) or jcns (joint constraints) rig, or an optional mesh/mdf2
    variant sub-part -- under a THIRD character code -- neither the
    donor's own real code nor the mod's custom-slot code -- that turns
    out not to exist anywhere in the currently installed game at all.
    Confirmed real on two separate mods (Mangie "Afterglow" and "Forte"):
    the current vanilla ch03 piece's own resource table references
    "ch02_017_0001.chain2", and game.find_versioned() confirms that file
    doesn't exist in this game build -- a dangling reference Capcom
    apparently left behind. _apply_substitution()'s normal donor_code ->
    mod_code swap never touches this string at all (it doesn't contain
    donor_code), so it survives into the output completely unchanged --
    still dangling. Left alone, a physics reference silently gets no
    physics (the engine just skips a chain2/jcns it can't find); a mesh/
    mdf2 reference just logs a "[Missing file]" warning and is skipped --
    even though the mod bundles its own working file for the identical
    numbered slot under its own code.

    `mod_code` is either the actual substitution target (pieces resolved
    via _apply_substitution()) or the file's own dominant character code
    (see _dominant_code()) for pieces that resolved via _crc_only_fix()
    with no substitution pair at all -- either way it's "what this file's
    own code for this slot is", which is all this function needs to build
    a same-suffix candidate replacement path.

    Only redirects a reference that's PROVEN dangling (still resolves ->
    left alone, matching this project's existing donor_code substitution
    safety principle) AND for which the mod actually provides a same-
    suffix replacement file. Returns the count fixed."""
    fixed = 0
    for offset, s in _scan_utf16_strings(bytes(data)):
        if "/" not in s:
            continue
        ext = next((e for e in _PHYSICS_EXTS if s.lower().endswith(e)), None)
        if ext is None:
            continue
        m = _CODE_RE.search(Path(_strip_at(s)).name)
        if m is None or m.group(0).lower() == mod_code.lower():
            continue
        this_code = m.group(0)
        if game.find_versioned("natives/STM/" + _strip_at(s), ext[1:]) is not None:
            continue  # resolves to a real current file -- leave it alone
        candidate = s.replace(this_code, mod_code)
        key = Path(_strip_at(candidate)).name.lower()
        if key not in mod_provided_keys:
            continue  # mod doesn't provide a replacement for this slot either
        mod_code_bytes = mod_code.encode("utf-16-le")
        search_start = 0
        while True:
            idx = s.find(this_code, search_start)
            if idx == -1:
                break
            char_offset = offset + idx * 2
            data[char_offset:char_offset + len(this_code) * 2] = mod_code_bytes
            search_start = idx + len(this_code)
        log(f"    [physics-fix] dangling reference to {this_code!r}'s {s!r} redirected -> "
            f"mod's own {candidate!r}")
        fixed += 1
    return fixed


def _apply_substitution(donor_bytes: bytes, donor_code: str, mod_code: str,
                         mod_provided_keys: set[str]) -> bytes:
    """Same-length in-place substitution over the WHOLE file (not just the
    pre-RSZ resource-string header) -- two cases, handled differently:

    - Resource-path occurrences (contain '/'): only substituted when the
      substituted form actually corresponds to a file the mod bundles --
      confirmed necessary in practice: blindly substituting every
      occurrence of the donor's character code (e.g. "ch03"->"mh03") can
      turn a reference to a file the CURRENT donor needs but the mod never
      shipped (e.g. a ".jcns" joint-constraint file introduced after the
      mod was built) into a reference to a custom-slot path that simply
      doesn't exist -- REFramework then reports it as "[Missing File]" and
      the character fails to load. Left un-substituted, that reference
      correctly falls back to the real, always-present vanilla file.

    - Bare identifier occurrences (no '/', e.g. a GameObject's own Name
      field, which RSZ stores inline in the instance data -- well past
      rsz_off, outside the header region the resource-path case above
      scans): always substituted unconditionally, no mod_provided_keys
      gate. These can't create a dangling file reference since they're not
      paths at all. Confirmed necessary via real in-game testing: leaving
      a GameObject's own name as the donor's original "ch03_..." instead
      of the mod's "mh03_..." made that GameObject -- and everything under
      it, including the actual mesh renderer -- fail some internal
      name-based lookup and render fully invisible, even though every
      resource-path reference in the same file was already correct. This
      was a real regression from an earlier version of this function that
      scanned only the pre-RSZ header (see _resource_strings_with_offsets)
      -- that scope was right for the mod-vs-donor structural diff in
      plan_pfb() but wrong here, since it silently skipped this field."""
    result = bytearray(donor_bytes)
    mod_code_bytes = mod_code.encode("utf-16-le")
    for offset, s in _scan_utf16_strings(donor_bytes):
        if donor_code not in s:
            continue
        if "/" in s:
            candidate = s.replace(donor_code, mod_code)
            key = Path(_strip_at(candidate)).name.lower()
            if key not in mod_provided_keys:
                continue
        search_start = 0
        while True:
            idx = s.find(donor_code, search_start)
            if idx == -1:
                break
            char_offset = offset + idx * 2  # UTF-16LE: 2 bytes per char
            result[char_offset:char_offset + len(donor_code) * 2] = mod_code_bytes
            search_start = idx + len(donor_code)
    return bytes(result)


def find_avp_files(root: Path):
    yield from root.rglob("*_avp.user.*")


_AVP_OWN_SLOT_RE = re.compile(r"[\\/](\d{3})[\\/](\d{3})[\\/]\1_\2_avp\.user", re.IGNORECASE)
_AVP_REF_RE = re.compile(r"Armor/(?:Male|Female)/(\d+)/(\d+)/(\d+)_(\d+)_avp\.user$", re.IGNORECASE)


def _report_avp_cross_slot_reference(data: bytes, own_set: str, own_variant: str, rel: Path, log):
    """DIAGNOSTIC ONLY -- this used to REWRITE the reference and that was a
    real, in-game-confirmed mistake (2026-08-09, full reversal of the
    original same-day "fix").

    A `..._avp.user` file (`app.user_data.PlayerArmorVisualParam` --
    governs per-piece visual params including hair-hide flags and optional
    decorative sub-meshes) carries an inline resource-path string that
    references an avp.user by armor-set/variant numbers. Every CURRENT
    vanilla file self-references its own slot, so a mod avp referencing a
    DIFFERENT slot looked like an obvious templating leftover, and the
    original version of this code "corrected" it to the mod's own slot.

    Confirmed wrong on the exact mod that motivated it (OVR Rogue
    "Bifrost"): its helm borrows armor set 036's MESH (the material is
    literally named `ch03_036_0003_helm_UseSC`), and its avp referencing
    036's avp is how the borrowed helm gets 036's correct hair-hide
    parameters. Rewriting that reference to the mod's own slot (041) made
    the character's BASE HAIR poke through the helm in-game -- while the
    original mod, the author's own updated release, and a build that
    skipped this rewrite (all keeping the "wrong"-looking 036 reference)
    all render correctly. The author's own update keeping it is the
    decisive part: this is a deliberate cross-slot borrow, not a mistake,
    and there is no way to distinguish the two cases from file structure
    alone. The rewrite also never fixed anything real -- the white-texture
    symptom it was built chasing turned out to be the retired-shader issue
    (#24/#25), entirely unrelated.

    What remains is a log line so the information isn't lost (a cross-slot
    reference IS still worth knowing about when debugging a visual issue)
    -- but the file is never modified."""
    expected = (f"GameDesign/Equip/_Prefab/Armor/Male/{own_set}/{own_variant}/"
                f"{own_set}_{own_variant}_avp.user")
    for off, s in _scan_utf16_strings(data):
        if not _AVP_REF_RE.search(s) or s == expected:
            continue
        log(f"    [info] {rel}: avp references another slot's avp ({s!r} rather than its own "
            f"{expected!r}) -- deliberate cross-slot borrows like this are real (borrowed-mesh "
            f"hair-hide params, confirmed on OVR Rogue Bifrost), left untouched")


def resolve_and_fix_avp_files(mod_root: Path, output_root: Path, log) -> dict:
    """Diagnostic-only since 2026-08-09 (name kept so callers don't churn):
    scans avp.user files and LOGS cross-slot self-references without ever
    modifying anything -- see _report_avp_cross_slot_reference() for the
    in-game-confirmed reversal story. `output_root` is unused now but kept
    in the signature for call-site stability."""
    for avp_path in sorted(find_avp_files(mod_root)):
        rel = avp_path.relative_to(mod_root)
        m = _AVP_OWN_SLOT_RE.search(str(rel))
        if not m:
            continue
        own_set, own_variant = m.group(1), m.group(2)
        _report_avp_cross_slot_reference(avp_path.read_bytes(), own_set, own_variant, rel, log)
    return {"fixed": 0}


def _read_resource_strings(data: bytes) -> list[str]:
    """The PFB-level `ResourceInfo` table (see file_re_pfb.py, a real
    working reference PFB parser found in another community tool's vendored
    source) -- a flat manifest of every resource path this pfb depends
    on, entirely separate from the resource-path strings scattered inline
    through the RSZ instance data itself (see `_resource_strings()`/
    `_scan_utf16_strings()`). Each entry is just an 8-byte absolute
    stringOffset into a shared, null-terminated UTF16LE string pool."""
    resource_count = struct.unpack_from("<I", data, 8)[0]
    resource_info_offset = struct.unpack_from("<Q", data, 32)[0]
    out = []
    for i in range(resource_count):
        str_off = struct.unpack_from("<Q", data, resource_info_offset + i * 8)[0]
        end = str_off
        while end + 1 < len(data) and not (data[end] == 0 and data[end + 1] == 0):
            end += 2
        out.append(data[str_off:end].decode("utf-16-le", errors="replace"))
    return out




def resolve_and_fix_pfbs(mod_root: Path, output_root: Path, game: GameArchive, log,
                          force_unresolved: bool = False, preserve_extra: bool = False) -> dict:
    """`force_unresolved` is the GUI's opt-in "experimental: force-fix"
    checkbox -- see _find_substitution()'s docstring for what it does and
    why it's not the default. Confirmed working in-game on several real
    mods' Waist pieces (current donor gained purely-additive attached-
    accessory content); confirmed to pick a wrong donor on at least one
    real Arm piece with no true vanilla equivalent. Off by default.

    `preserve_extra` is a SEPARATE opt-in -- see _crc_only_fix()'s
    docstring. Confirmed working on a real mod (DOTEI's "LEG PHYS HEAVY")
    that bundles its own via.motion.Chain2 physics chain, which
    donor-replace was silently deleting; confirmed to diverge from an
    already-verified-working build on another real mod (Mangie
    "Banshee") whose Arm piece happens to carry the same kind of "extra"
    instances but as stale pre-simplification leftovers, not real
    customization -- the two look identical structurally. Off by
    default; always verify a build that used this in-game."""
    stats = {"fixed": 0, "already_current": 0, "unresolved": 0, "forced": 0, "crc_only": 0, "crc_only_extra": 0}
    mod_provided_keys = _mod_provided_file_keys(mod_root)
    for mod_path in sorted(find_pfb_files(mod_root)):
        plan = plan_pfb(mod_path, mod_root, game, log, force=force_unresolved, preserve_extra=preserve_extra)
        if plan.donor_bytes is None:
            stats["unresolved"] += 1
            continue
        if not plan.resolvable:
            stats["unresolved"] += 1
            continue

        if plan.crc_patch is not None:
            result = plan.crc_patch
            if plan.self_code:
                result_arr = bytearray(result)
                if _fix_dangling_physics_refs(result_arr, plan.self_code, mod_provided_keys, game, log):
                    result = bytes(result_arr)
        else:
            result = plan.donor_bytes
            if plan.substitution is not None:
                donor_code, mod_code = plan.substitution
                result = _apply_substitution(plan.donor_bytes, donor_code, mod_code, mod_provided_keys)
                result_arr = bytearray(result)
                if _fix_dangling_physics_refs(result_arr, mod_code, mod_provided_keys, game, log):
                    result = bytes(result_arr)

        out_path = output_root / plan.rel
        if result == mod_path.read_bytes():
            stats["already_current"] += 1
            continue
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(result)
        stats["fixed"] += 1
        if plan.crc_patch is not None:
            stats["crc_only"] += 1
            if plan.transplanted:
                log(f"    [transplanted] {plan.rel}  -- reshaped instance data rebuilt from current donor "
                    f"{plan.donor_path!r}, all mod structure/content kept -- experimental option, verify in-game")
            elif plan.crc_patch_preserved_extra:
                stats["crc_only_extra"] += 1
                log(f"    [crc-patched, custom parts kept] {plan.rel}  -- some instances the current donor "
                    f"doesn't have were left as shipped (possible custom content); only stale CRC(s) among "
                    f"the shared instances were updated -- experimental option, verify in-game")
            else:
                log(f"    [crc-patched] {plan.rel}  -- structure identical to current donor, only stale "
                    f"instance CRC(s) updated; every other byte (including the mod's own content) preserved unchanged")
            continue
        note = f" (substituted {plan.substitution[0]!r}->{plan.substitution[1]!r})" if plan.substitution else ""
        if plan.forced:
            stats["forced"] += 1
            log(f"    [forced-fix] {plan.rel}  <-  current donor {plan.donor_path!r}{note} "
                f"-- structure didn't safely reconcile; forced anyway (experimental option), verify in-game")
        else:
            log(f"    [fixed] {plan.rel}  <-  current donor {plan.donor_path!r}{note}")
    return stats
