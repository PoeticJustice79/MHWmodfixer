"""
Reads just the material-name list a `.mesh` file itself expects, by
independently parsing its file/LOD-group header -- NOT full geometry.
This project has no need to touch vertex/skeleton/UV data at all, only
the material name list every RE Engine mesh embeds, to check it against
what the matching `.mdf2` actually provides.

Why this check exists: two independent community write-ups (see
CLAUDE.md #19/#20 -- Havens-Night's English wiki and Caimogu's Chinese
"mesh与mdf2不完全讲解" tutorial) both document the same hard rule: a
mesh's own material name list must match its mdf2's material set EXACTLY
in count and name, or the game black-screens/checkerboards on entry.
This project had no way to detect that mismatch before shipping a fix --
it only ever touches mdf2/pfb/user content, never mesh, so a mismatch
between a mod's own bundled mesh and its own bundled mdf2 (a pre-existing
authoring issue, not something this project's fixes could cause or
correct) went completely undiagnosed.

Byte layout derived from directly testing NSACloud/RE-Mesh-Editor's own
(GPL-licensed) `file_re_mesh.py` parser against real current-game files
this session (both a real mod's own mesh and the current donor's, the
donor requiring a "streaming" companion file the mod's own self-contained
mesh doesn't) and cross-verifying its output byte-for-byte against this
independently-written, clean-room implementation of the same header
layout -- this file contains no code derived from or copied out of that
(or any other) GPL project, only facts about the file format learned by
observing real files, the same way this project's PFB/RSZ format
understanding was built. Only supports the MHWilds-era header shape
(files whose version is at or above RE-Mesh-Editor's own "VERSION_ONI2"
cutoff); anything else returns None rather than guessing at an
unverified older layout.
"""
from __future__ import annotations

import re
import struct
from collections import Counter
from pathlib import Path

from mdf2 import Mdf2File, numVersion_from_filename

_MESH_MAGIC = 1213416781
_MIN_SUPPORTED_VERSION = 127  # RE-Mesh-Editor's VERSION_ONI2 -- the header shape this file implements; MHWilds (130) shares it
_MESH_RE = re.compile(r"\.mesh\.\d+$", re.IGNORECASE)


def find_mesh_files(root: Path):
    yield from root.rglob("*.mesh.*")


def _read_cstring(data: bytes, offset: int) -> str:
    end = data.index(b"\x00", offset)
    return data[offset:end].decode("utf-8", errors="replace")


def read_mesh_material_names(data: bytes) -> list[str] | None:
    """Returns the mesh's own expected material name list (may contain
    duplicates -- a mesh can reference the same material for more than
    one submesh, e.g. left/right mirrored pieces), or None if this isn't
    a supported/parseable mesh file. Never raises."""
    if len(data) < 4 or struct.unpack_from("<I", data, 0)[0] != _MESH_MAGIC:
        return None
    try:
        version = struct.unpack_from("<I", data, 4)[0]
        if version < _MIN_SUPPORTED_VERSION:
            return None
        name_count = struct.unpack_from("<h", data, 20)[0]
        mesh_group_offset = struct.unpack_from("<Q", data, 48)[0]
        material_name_remap_offset = struct.unpack_from("<Q", data, 128)[0]
        name_offsets_offset = struct.unpack_from("<Q", data, 152)[0]
        if not (mesh_group_offset and material_name_remap_offset and name_offsets_offset and name_count > 0):
            return None
        material_count = data[mesh_group_offset + 1]
        if material_count == 0:
            return None
        name_offsets = struct.unpack_from(f"<{name_count}Q", data, name_offsets_offset)
        raw_names = [_read_cstring(data, off) for off in name_offsets]
        remap = struct.unpack_from(f"<{material_count}H", data, material_name_remap_offset)
        return [raw_names[i] for i in remap]
    except (struct.error, IndexError, UnicodeDecodeError):
        return None


def check_mesh_mdf2_consistency(output_root: Path, log) -> int:
    """Warns (never fixes -- this project has no way to safely reconcile
    a genuine mismatch, only to notice one) whenever a mesh's own
    material name list doesn't match its correspondingly-named mdf2's
    material set exactly, in count AND name -- the exact rule documented
    independently by both Havens-Night's wiki and Caimogu's "mesh与mdf2
    不完全讲解" tutorial (see CLAUDE.md #19/#20), where any mismatch
    means the game black-screens or checkerboards on entry.

    Runs against OUTPUT_ROOT (after this project's own mdf2/pfb/user
    fixes are already written) rather than the original mod -- catches a
    pre-existing authoring mismatch in the mod itself just as well, and
    would also catch this project's OWN fixes accidentally introducing
    one, even though nothing here currently touches material counts.

    A mesh whose own material name list can't be read at all (see
    `read_mesh_material_names()` -- unsupported version, MPLY stage
    mesh, anything not matching the expected header shape) is silently
    skipped, not reported as a mismatch -- this check only ever warns
    when it has high-confidence real data on both sides.

    Returns the number of mismatches found (0 if everything checked out,
    including if nothing was checkable at all)."""
    mismatches = 0
    for mesh_path in sorted(find_mesh_files(output_root)):
        mesh_names = read_mesh_material_names(mesh_path.read_bytes())
        if mesh_names is None:
            continue
        base = _MESH_RE.sub("", mesh_path.name)
        mdf2_candidates = list(mesh_path.parent.glob(f"{re.escape(base)}.mdf2.*"))
        if not mdf2_candidates:
            continue
        mdf2_path = mdf2_candidates[0]
        try:
            mdf = Mdf2File(mdf2_path.read_bytes(), numVersion_from_filename(mdf2_path.name))
        except Exception:
            continue
        mdf2_names = [m.name for m in mdf.materials]

        if Counter(mesh_names) == Counter(mdf2_names):
            continue
        mismatches += 1
        mesh_only = sorted((Counter(mesh_names) - Counter(mdf2_names)).elements())
        mdf2_only = sorted((Counter(mdf2_names) - Counter(mesh_names)).elements())
        log(f"    [warn] {mesh_path.name}: mesh expects {len(mesh_names)} material(s), "
            f"{mdf2_path.name} provides {len(mdf2_names)} -- MISMATCH, likely to "
            f"black-screen or checkerboard in-game")
        if mesh_only:
            log(f"        mesh wants but mdf2 doesn't have: {mesh_only}")
        if mdf2_only:
            log(f"        mdf2 has but mesh never references: {mdf2_only}")
    return mismatches
