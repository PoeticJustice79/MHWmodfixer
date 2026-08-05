"""
Extract a single material (with all its textures/properties/gpbf refs) out
of a parsed Mdf2File as a self-contained plain-data blob, and assemble a
brand-new MDF2 file from a list of such blobs.

Why this exists: simple texture-replacer mods can be fixed by patching
texture Path strings inside an unchanged vanilla skeleton (see mdf2.py's
Mdf2File.set_texture_path). But some mods (e.g. full custom-slot outfits)
rebuild the mesh so that a single material in the mod's file doesn't
correspond to any material in ITS OWN same-path vanilla donor -- the
donor material with a matching mmtr (shader) might only exist in a
*different* file's material list (see slot_merge.py). To build a valid
result in that case we have to actually splice materials pulled from
different source files into one new file, which means re-serializing
from scratch rather than patching in place.

Deliberately dropped when assembling: the "uknStructs"/TexID array (an
optional per-material block of uncertain semantics, believed related to
LOD/decal texture-ID groups). The format's own 010 template treats
uknStructsOffs == 0 as a fully valid "nothing here" case, so omitting it
is a disclosed simplification, not a hack -- see mdf2.py module docstring
for the same philosophy applied to texture edits.
"""
from __future__ import annotations

import struct

from mdf2 import Mdf2File, read_u32, read_u64, read_wstring


def extract_material(mdf: Mdf2File, index: int) -> dict:
    """Re-walks one material's fixed header fields (which Mdf2File._parse
    doesn't fully expose) directly from the buffer, plus all of its
    textures/props/gpbf entries with their actual string/float payloads."""
    buf = mdf.buf
    mat = mdf.materials[index]
    pos = mat.hdr_pos

    pos += 8  # nameOffs (already have mat.name)
    pos += 4  # hash (recomputed as a pure function of name at assembly time)
    if mdf.numVersion == 6:
        pos += 8
    pos += 4  # sizeOfFloatStr (recomputed at assembly time)
    pos += 4  # propCount (re-derived from len(props))
    pos += 4  # texCount (re-derived from len(textures))
    if mdf.has_gpbf:
        gpbf0, gpbf1 = struct.unpack_from("<ii", buf, pos)
        pos += 8
    else:
        gpbf0 = gpbf1 = 0
    shading_type = read_u32(buf, pos); pos += 4
    if mdf.isV2:
        unk_0x24 = read_u32(buf, pos); pos += 4
    else:
        unk_0x24 = None
    alpha_flags_raw = bytes(buf[pos:pos + 4]); pos += 4
    if mdf.isV2:
        unk_0x2C, unk_0x30 = struct.unpack_from("<ii", buf, pos)
        pos += 8
    else:
        unk_0x2C = unk_0x30 = None
    # (propHdrsOffs, texHdrOffs, [gpbfOffs], propsOffs, mmtrOffs, [uknStructsOffs] follow;
    #  we already have everything we need via mat._* and mat.textures/props)

    gpbf_offs = getattr(mat, "_gpbf_offs", None)
    gpbf_entries = []
    if mdf.has_gpbf and (gpbf0 + gpbf1) > 0 and gpbf_offs:
        p = gpbf_offs
        for _ in range(gpbf0 + gpbf1):
            name_offs, h1, h2 = struct.unpack_from("<Qii", buf, p)
            name_str, _ = read_wstring(buf, name_offs)
            gpbf_entries.append((name_str, h1, h2))
            p += 16

    textures = []
    p = mat._tex_hdr_offs
    for t in mat.textures:
        ukn = None
        if mdf.numVersion >= 13:
            ukn_pos = t.path_offs_pos + 8
            ukn = read_u64(buf, ukn_pos)
        textures.append({"type": t.type_str, "path": t.path_str, "ukn": ukn})

    props = []
    p = mat._prop_hdrs_offs
    for pr in mat.props:
        # entry layout: propNameOffs(8) + nameUIF16Hash(4) + nameASCIIHash(4) + (propOffs/numParams)(8)
        if mdf.numVersion >= 13:
            prop_offs, num_params = struct.unpack_from("<ii", buf, p + 16)
        else:
            num_params, prop_offs = struct.unpack_from("<ii", buf, p + 16)
        p += 24
        values = list(struct.unpack_from(f"<{num_params}f", buf, mat._props_offs + prop_offs))
        props.append({"name": pr.name_str, "values": values})

    header_version = struct.unpack_from("<H", buf, 4)[0]

    return {
        "name": mat.name,
        "mmtr_path": mat.mmtr_path,
        "shading_type": shading_type,
        "alpha_flags_raw": alpha_flags_raw,
        "isV2_unk_0x24": unk_0x24,
        "isV2_unk_0x2C": unk_0x2C,
        "isV2_unk_0x30": unk_0x30,
        "gpbf_split": (gpbf0, gpbf1),
        "gpbf_entries": gpbf_entries,
        "textures": textures,
        "props": props,
        "header_version": header_version,
    }


def _wstr_bytes(s: str) -> bytes:
    return s.encode("utf-16-le") + b"\x00\x00"


def _pad16(n: int) -> int:
    """Each material's own properties-values block is padded up to a
    16-byte boundary -- confirmed against real game files, where the
    stored 'sizeOfFloatStr' field is consistently the *padded* size, not
    the raw sum of each prop's (numParams * 4) bytes (e.g. 1128 raw bytes
    of actual float data is stored as 1136). Almost certainly there for
    GPU constant-buffer alignment. Getting this wrong doesn't corrupt
    what mdf2.py's own reader sees (it trusts per-prop offsets, not this
    field), but the real engine evidently reads the properties block
    sized by this field -- under-sizing it here previously caused a
    freshly ASSEMBLED file's tail (or whatever follows in memory) to be
    read as extra float data, which is the kind of corruption that can
    hang the renderer instead of just look wrong."""
    return (n + 15) // 16 * 16


def assemble_mdf2(materials: list[dict], numVersion: int) -> bytes:
    """Builds a brand-new, self-consistent MDF2 file from extracted material
    blobs (see extract_material). Materials can come from different source
    files -- each blob is fully self-contained."""
    from pak_reader import murmur3_x86_32  # same murmur3 impl the format itself uses

    isV2 = 30 <= numVersion < 100
    has_gpbf = 19 <= numVersion < 100000
    header_version = materials[0]["header_version"] if materials else 1

    mtrl_count = len(materials)

    entry_size = 8 + 4  # nameOffs + hash
    if numVersion == 6:
        entry_size += 8
    entry_size += 4 + 4 + 4  # sizeOfFloatStr, propCount, texCount
    if has_gpbf:
        entry_size += 8
    entry_size += 4  # shadingType
    if isV2:
        entry_size += 4  # unk_0x24
    entry_size += 4  # alpha flags
    if isV2:
        entry_size += 8  # unk_0x2C/0x30
    entry_size += 8 + 8  # propHdrsOffs, texHdrOffs
    if has_gpbf:
        entry_size += 8  # gpbfOffs
    entry_size += 8 + 8  # propsOffs, mmtrOffs
    if isV2:
        entry_size += 8  # uknStructsOffs (always written as 0 -- see module docstring)

    header_size = 16
    mtrls_size = mtrl_count * entry_size

    tex_hdr_entry_size = 8 + 4 + 4 + 8 + (8 if numVersion >= 13 else 0)
    prop_hdr_entry_size = 8 + 4 + 4 + 8  # nameOffs, 2 hashes, (propOffs+numParams)

    tex_counts = [len(m["textures"]) for m in materials]
    prop_counts = [len(m["props"]) for m in materials]
    gpbf_counts = [sum(m["gpbf_split"]) for m in materials]

    tex_hdrs_size = sum(tex_counts) * tex_hdr_entry_size
    prop_hdrs_size = sum(prop_counts) * prop_hdr_entry_size
    gpbf_size = sum(gpbf_counts) * 16 if has_gpbf else 0
    props_values_size = sum(_pad16(sum(len(p["values"]) for p in m["props"]) * 4) for m in materials)

    off_mtrls = header_size
    off_tex_hdrs = off_mtrls + mtrls_size
    off_prop_hdrs = off_tex_hdrs + tex_hdrs_size
    off_gpbf = off_prop_hdrs + prop_hdrs_size
    off_props_values = off_gpbf + gpbf_size
    off_strings = off_props_values + props_values_size

    buf = bytearray(off_strings)
    string_pool_offsets: dict[str, int] = {}

    def intern_string(s: str) -> int:
        if s in string_pool_offsets:
            return string_pool_offsets[s]
        offset = len(buf)
        buf.extend(_wstr_bytes(s))
        string_pool_offsets[s] = offset
        return offset

    # header. The last field looked like inert padding (mdf2.py's own
    # _parse never reads it, only skips 8 bytes) so it was written as 0 --
    # but every real file checked (single- and multi-material alike)
    # stores 1 here, never 0. Writing 0 was found, by real in-game
    # testing, to make a fully-reassembled mod silently not apply at all
    # (looked like pure vanilla, no crash) -- consistent with this being a
    # validity/flags field the engine's loader actually checks, rejecting
    # the override and falling back to vanilla rather than a "reserved"
    # field nothing reads.
    struct.pack_into("<4sHHQ", buf, 0, b"MDF\x00", header_version, mtrl_count, 1)

    tex_hdr_cursor = off_tex_hdrs
    prop_hdr_cursor = off_prop_hdrs
    gpbf_cursor = off_gpbf
    props_values_cursor = off_props_values

    for i, m in enumerate(materials):
        mat_pos = off_mtrls + i * entry_size
        name_offset = intern_string(m["name"])
        mmtr_offset = intern_string(m["mmtr_path"])
        name_hash = murmur3_x86_32(m["name"].encode("utf-16-le"))

        this_tex_hdr_offs = tex_hdr_cursor
        this_prop_hdr_offs = prop_hdr_cursor
        this_gpbf_offs = gpbf_cursor if has_gpbf else 0
        this_props_offs = props_values_cursor

        pos = mat_pos
        struct.pack_into("<Q", buf, pos, name_offset); pos += 8
        struct.pack_into("<I", buf, pos, name_hash & 0xFFFFFFFF); pos += 4
        if numVersion == 6:
            struct.pack_into("<II", buf, pos, 0, 0); pos += 8
        size_of_float_str = _pad16(sum(len(p["values"]) for p in m["props"]) * 4)
        struct.pack_into("<III", buf, pos, size_of_float_str, len(m["props"]), len(m["textures"])); pos += 12
        if has_gpbf:
            g0, g1 = m["gpbf_split"]
            struct.pack_into("<ii", buf, pos, g0, g1); pos += 8
        struct.pack_into("<I", buf, pos, m["shading_type"]); pos += 4
        if isV2:
            struct.pack_into("<I", buf, pos, m["isV2_unk_0x24"] or 0); pos += 4
        buf[pos:pos + 4] = m["alpha_flags_raw"]; pos += 4
        if isV2:
            struct.pack_into("<ii", buf, pos, m["isV2_unk_0x2C"] or 0, m["isV2_unk_0x30"] or 0); pos += 8
        struct.pack_into("<Q", buf, pos, this_prop_hdr_offs); pos += 8
        struct.pack_into("<Q", buf, pos, this_tex_hdr_offs); pos += 8
        if has_gpbf:
            struct.pack_into("<Q", buf, pos, this_gpbf_offs); pos += 8
        struct.pack_into("<Q", buf, pos, this_props_offs); pos += 8
        struct.pack_into("<Q", buf, pos, mmtr_offset); pos += 8
        if isV2:
            struct.pack_into("<Q", buf, pos, 0); pos += 8  # uknStructsOffs: always empty

        for t in m["textures"]:
            type_offset = intern_string(t["type"])
            path_offset = intern_string(t["path"])
            type_hash = murmur3_x86_32(t["type"].encode("utf-16-le"))
            type_hash_ascii = murmur3_x86_32(t["type"].encode("ascii", "ignore"))
            p = tex_hdr_cursor
            struct.pack_into("<Q", buf, p, type_offset); p += 8
            struct.pack_into("<II", buf, p, type_hash & 0xFFFFFFFF, type_hash_ascii & 0xFFFFFFFF); p += 8
            struct.pack_into("<Q", buf, p, path_offset); p += 8
            if numVersion >= 13:
                struct.pack_into("<Q", buf, p, t["ukn"] or 0); p += 8
            tex_hdr_cursor = p

        for pr in m["props"]:
            name_offset = intern_string(pr["name"])
            name_hash_u = murmur3_x86_32(pr["name"].encode("utf-16-le"))
            name_hash_a = murmur3_x86_32(pr["name"].encode("ascii", "ignore"))
            p = prop_hdr_cursor
            struct.pack_into("<Q", buf, p, name_offset); p += 8
            struct.pack_into("<II", buf, p, name_hash_u & 0xFFFFFFFF, name_hash_a & 0xFFFFFFFF); p += 8
            n = len(pr["values"])
            prop_offs_in_block = props_values_cursor - this_props_offs
            if numVersion >= 13:
                struct.pack_into("<ii", buf, p, prop_offs_in_block, n); p += 8
            else:
                struct.pack_into("<ii", buf, p, n, prop_offs_in_block); p += 8
            prop_hdr_cursor = p

            struct.pack_into(f"<{n}f", buf, props_values_cursor, *pr["values"])
            props_values_cursor += n * 4

        # skip past this material's padding (bytearray is already zero-filled)
        # so the next material's props block starts on a 16-byte boundary.
        props_values_cursor = this_props_offs + size_of_float_str

        if has_gpbf:
            for name_str, h1, h2 in m["gpbf_entries"]:
                name_offset = intern_string(name_str)
                p = gpbf_cursor
                struct.pack_into("<Qii", buf, p, name_offset, h1, h2)
                gpbf_cursor = p + 16

    return bytes(buf)
