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
    return {
        "rsz_off": rsz_off, "version": version, "obj_count": obj_count,
        "inst_count": inst_count, "userdata_count": userdata_count, "insts": insts,
    }


def _resource_strings(data: bytes, rsz_off: int) -> set[str]:
    """UTF-16LE strings in the header/resource-table region before the RSZ
    block -- resource paths, gameobject names, etc."""
    region = data[:rsz_off]
    out = set()
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
                out.add("".join(chars))
                i = j
                continue
        i += 1
    return out


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


def _find_substitution(mod_strings: set[str], donor_strings: set[str]):
    """Returns ('close', None) if the two string sets already match closely
    enough (within _MAX_STRING_DIFF, ignoring '@'-prefix noise) with no
    substitution needed; ('close', (donor_code, mod_code)) if replacing
    donor_code with mod_code (same length, e.g. "ch03"->"mh03") throughout
    donor_strings brings it within tolerance of mod_strings; or None if
    neither explains the difference closely enough -- caller should leave
    the file untouched in that case."""
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
            if d <= _MAX_STRING_DIFF and (best is None or d < best[0]):
                best = (d, donor_code, mod_code)
    if best is not None:
        return "close", (best[1], best[2])
    return None


@dataclass
class PfbPlan:
    rel: Path
    mod_path: Path
    donor_path: str | None
    donor_bytes: bytes | None
    substitution: tuple[str, str] | None
    resolvable: bool  # found a donor AND could safely reconcile string differences


def plan_pfb(mod_path: Path, mod_root: Path, game: GameArchive, log) -> PfbPlan:
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

    for cand in candidate_donor_paths(base_no_version):
        found = game.find_versioned(cand, "pfb")
        if found is None:
            continue
        donor_path, donor_bytes = found
        donor_parsed = _parse_rsz(donor_bytes)
        if donor_parsed is None:
            continue
        donor_strings = _resource_strings(donor_bytes, donor_parsed["rsz_off"])
        result = _find_substitution(mod_strings, donor_strings)
        if result is not None:
            _, sub = result
            return PfbPlan(rel, mod_path, donor_path, donor_bytes, sub, True)
        log(f"    [warn] {rel}: found donor {donor_path!r} but its content doesn't reconcile "
            f"with the mod's own -- leaving untouched (possible real customization)")
        return PfbPlan(rel, mod_path, donor_path, donor_bytes, None, False)

    return PfbPlan(rel, mod_path, None, None, None, False)


def resolve_and_fix_pfbs(mod_root: Path, output_root: Path, game: GameArchive, log) -> dict:
    stats = {"fixed": 0, "already_current": 0, "unresolved": 0}
    for mod_path in sorted(find_pfb_files(mod_root)):
        plan = plan_pfb(mod_path, mod_root, game, log)
        if plan.donor_bytes is None:
            stats["unresolved"] += 1
            continue
        if not plan.resolvable:
            stats["unresolved"] += 1
            continue

        result = plan.donor_bytes
        if plan.substitution is not None:
            donor_code, mod_code = plan.substitution
            result = result.replace(donor_code.encode("utf-16-le"), mod_code.encode("utf-16-le"))
            assert len(result) == len(plan.donor_bytes), "substitution must be same-length"

        out_path = output_root / plan.rel
        if result == mod_path.read_bytes():
            stats["already_current"] += 1
            continue
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(result)
        stats["fixed"] += 1
        note = f" (substituted {plan.substitution[0]!r}->{plan.substitution[1]!r})" if plan.substitution else ""
        log(f"    [fixed] {plan.rel}  <-  current donor {plan.donor_path!r}{note}")
    return stats
