"""
Parser/writer for Capcom RE Engine MDF2 material files (used by Monster Hunter Wilds).

Binary layout reverse-engineered from the community-maintained 010 Editor template
"RE_Engine_MDF.bt" (authors: Che, Darkness, alphaZomega -
https://github.com/alphazolam/RE-Engine-010-Templates).

Key fact from that template: the format version that gates which optional fields
are present is NOT read from a header byte -- it is parsed out of the trailing
number in the file's own extension, e.g. "foo.mdf2.45" -> numVersion = 45.
That's why Capcom can silently change the internal layout between game patches:
the game just starts writing files with a new trailing number, and anything
still using the old number embeds a stale layout assumption.

This module only implements exactly what's needed to safely reuse the *whole
structural skeleton* of a known-good ("vanilla", extracted fresh from the
current game version) MDF2 file, while swapping in texture path overrides
copied from a mod's (possibly stale-version) MDF2 file for the same material.
It deliberately never re-derives offsets from scratch: every edit is done as
an in-place UTF-16 string replace + "fix up all offsets greater than the edit
point" pass, mirroring the template's own `mdf_st_write`/`Fix_Off` functions.
That keeps every byte we don't touch bit-for-bit identical to the vanilla
file, which is the only way to be sure the result stays loadable by the game.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field


def numVersion_from_filename(filename: str) -> int:
    """foo.mdf2.45 -> 45 (mirrors the .bt template's Atoi(FileNameGetExtension))."""
    m = re.search(r"\.(\d+)$", filename)
    if not m:
        raise ValueError(f"Can't find a trailing version number in filename: {filename!r}")
    return int(m.group(1))


def detect_numVersion(data: bytes, candidates=range(1, 200)) -> int | None:
    """When an mdf2 blob comes from inside a custom mod .pak (see
    pak_reader.py), there's no filename to read the version number from --
    the format doesn't store it anywhere else, so we brute-force it: try
    parsing with each candidate and keep the one where re-serializing
    without any edits reproduces the exact input bytes. A wrong guess
    USUALLY misaligns every offset downstream and doesn't round-trip by
    accident -- but not always: confirmed real case (external bug report,
    verified against 9,939 known game mdf2 files), a low version number
    can make every material look degenerate (propCount/texCount parsed
    as 0, mmtr_path empty) and that degenerate-but-internally-consistent
    shape still round-trips byte-for-byte on 842 of them, because a
    lower numVersion's layout can make the parser skip past the file's
    real content entirely and just treat it as an opaque tail. Reject
    those: every real material has a shader path, so an empty mmtr_path
    on any material means this candidate's layout is wrong even though
    the bytes matched."""
    for nv in candidates:
        try:
            m = Mdf2File(data, nv)
            if m.to_bytes() == data and all(mat.mmtr_path for mat in m.materials):
                return nv
        except Exception:
            continue
    return None


def read_u16(buf, off): return struct.unpack_from("<H", buf, off)[0]
def read_u32(buf, off): return struct.unpack_from("<I", buf, off)[0]
def read_u64(buf, off): return struct.unpack_from("<Q", buf, off)[0]


def read_wstring(buf: bytes, off: int) -> tuple[str, int]:
    """Null-terminated UTF-16LE string. Returns (text, byte_length_including_null)."""
    end = off
    n = len(buf)
    while end + 1 < n and not (buf[end] == 0 and buf[end + 1] == 0):
        end += 2
    text = buf[off:end].decode("utf-16-le")
    return text, (end - off) + 2  # + the 2-byte null terminator


@dataclass
class TexEntry:
    type_offs_pos: int    # file position of the typeOffs field (8 bytes)
    path_offs_pos: int    # file position of the pathOffs field (8 bytes)
    type_str: str
    path_str: str
    type_str_pos: int     # file position of the actual type string data
    path_str_pos: int     # file position of the actual path string data


@dataclass
class PropEntry:
    name_offs_pos: int
    name_str: str
    name_str_pos: int


@dataclass
class GpbfEntry:
    name_offs_pos: int
    name_str: str
    name_str_pos: int


@dataclass
class Material:
    index: int
    hdr_pos: int
    name: str
    name_offs_pos: int
    name_str_pos: int
    mmtr_path: str
    mmtr_offs_pos: int
    mmtr_str_pos: int
    tex_hdr_offs_pos: int
    prop_hdr_offs_pos: int
    textures: list[TexEntry] = field(default_factory=list)
    props: list[PropEntry] = field(default_factory=list)
    gpbf: list[GpbfEntry] = field(default_factory=list)


class Mdf2File:
    """Parses just enough of an MDF2 file to read/patch texture path strings."""

    def __init__(self, data: bytes, numVersion: int):
        self.buf = bytearray(data)
        self.numVersion = numVersion
        self.isV2 = 30 <= numVersion < 100
        self.has_gpbf = 19 <= numVersion < 100000
        self.materials: list[Material] = []
        self._offset_fields: list[int] = []  # file positions holding an offset value that must shift on edits
        self._parse()

    # ---- low level helpers -------------------------------------------------

    def _track_offset_field(self, pos: int):
        self._offset_fields.append(pos)

    def _read_off_field(self, pos: int, width: int) -> int:
        self._track_offset_field(pos)
        return read_u64(self.buf, pos) if width == 8 else read_u32(self.buf, pos)

    # ---- parsing -------------------------------------------------------------

    def _parse(self):
        buf = self.buf
        if bytes(buf[0:4]) != b"MDF\x00":
            raise ValueError("Not an MDF2 file (bad magic)")
        version = read_u16(buf, 4)
        mtrl_count = read_u16(buf, 6)
        # reserved u64 at offset 8
        pos = 16

        mat_hdr_positions = []
        for i in range(mtrl_count):
            hdr_pos = pos
            name_offs_pos = pos
            name_offs = self._read_off_field(pos, 8); pos += 8
            hash_pos = pos; pos += 4  # uint32 hash

            if self.numVersion == 6:
                pos += 8  # two uknRE7 uint32s

            size_of_float_str_pos = pos; pos += 4
            prop_count = read_u32(buf, pos); pos += 4
            tex_count = read_u32(buf, pos); pos += 4

            if self.has_gpbf:
                gpbf0, gpbf1 = struct.unpack_from("<ii", buf, pos)
                pos += 8  # int32 gpbf[0], int32 gpbf[1]
            else:
                gpbf0 = gpbf1 = 0

            pos += 4  # MaterialShadingType (uint32 enum)

            if self.isV2:
                pos += 4  # unkInt_0x24

            pos += 4  # Alpha_Flag_Preset(1) + ALPHAFLAG(4) overlapping same start -> total 4 bytes

            if self.isV2:
                pos += 8  # unkInt_0x2C, unkInt_0x30

            prop_hdr_offs_pos = pos
            prop_hdrs_offs = self._read_off_field(pos, 8); pos += 8
            tex_hdr_offs_pos = pos
            tex_hdr_offs = self._read_off_field(pos, 8); pos += 8

            if self.has_gpbf:
                gpbf_offs_pos = pos
                gpbf_offs = self._read_off_field(pos, 8)
                pos += 8
            else:
                gpbf_offs = None

            props_offs_pos = pos
            props_offs = self._read_off_field(pos, 8); pos += 8
            mmtr_offs_pos = pos
            mmtr_path_offs = self._read_off_field(pos, 8); pos += 8

            if self.isV2:
                uknstructs_pos = pos
                uknstructs_offs = self._read_off_field(pos, 8)
                pos += 8

            name_str, _ = read_wstring(buf, name_offs)
            mmtr_str, _ = read_wstring(buf, mmtr_path_offs)

            mat = Material(
                index=i,
                hdr_pos=hdr_pos,
                name=name_str,
                name_offs_pos=name_offs_pos,
                name_str_pos=name_offs,
                mmtr_path=mmtr_str,
                mmtr_offs_pos=mmtr_offs_pos,
                mmtr_str_pos=mmtr_path_offs,
                tex_hdr_offs_pos=tex_hdr_offs_pos,
                prop_hdr_offs_pos=prop_hdr_offs_pos,
            )
            mat._tex_count = tex_count       # stashed for pass 2
            mat._prop_count = prop_count
            mat._tex_hdr_offs = tex_hdr_offs
            mat._prop_hdrs_offs = prop_hdrs_offs
            mat._props_offs = props_offs
            mat._gpbf_offs = gpbf_offs
            mat._gpbf_split = (gpbf0, gpbf1)
            self.materials.append(mat)

        # pass 2: texture headers (each material's array lives at its own tex_hdr_offs)
        for mat in self.materials:
            p = mat._tex_hdr_offs
            for _ in range(mat._tex_count):
                type_offs_pos = p
                type_offs = self._read_off_field(p, 8); p += 8
                p += 8  # texUTF16Hash(4) + texASCIIHash(4)
                path_offs_pos = p
                path_offs = self._read_off_field(p, 8); p += 8
                if self.numVersion >= 13:
                    p += 8  # ukn
                type_str, _ = read_wstring(buf, type_offs)
                path_str, _ = read_wstring(buf, path_offs)
                mat.textures.append(TexEntry(
                    type_offs_pos=type_offs_pos,
                    path_offs_pos=path_offs_pos,
                    type_str=type_str,
                    path_str=path_str,
                    type_str_pos=type_offs,
                    path_str_pos=path_offs,
                ))

        # pass 3: property headers
        for mat in self.materials:
            p = mat._prop_hdrs_offs
            for _ in range(mat._prop_count):
                name_offs_pos = p
                name_offs = self._read_off_field(p, 8); p += 8
                p += 8  # nameUIF16Hash(4) + nameASCIIHash(4)
                p += 8  # propOffs(4) + numParams(4) (order doesn't matter, fixed width either way)
                name_str, _ = read_wstring(buf, name_offs)
                mat.props.append(PropEntry(
                    name_offs_pos=name_offs_pos,
                    name_str=name_str,
                    name_str_pos=name_offs,
                ))

        # pass 4: gpbf (GPU buffer name) entries -- these were previously
        # not parsed at all, so their nameOffs fields were never tracked in
        # _offset_fields; an in-place string edit elsewhere in the file
        # would then leave a stale/wrong offset here without any error,
        # silently pointing a shader's GPU buffer binding at the wrong
        # name string. Found via real in-game testing (title-screen hang
        # on a rebuilt weapon mod), not by any self-consistency check --
        # nothing here trips up round-tripping the file through this same
        # parser, since the parser reads whatever offset happens to be
        # there without validating it points at a sensible string.
        if self.has_gpbf:
            for mat in self.materials:
                if not mat._gpbf_offs:
                    continue
                p = mat._gpbf_offs
                total = sum(mat._gpbf_split)
                for _ in range(total):
                    name_offs_pos = p
                    name_offs = self._read_off_field(p, 8)
                    p += 16  # nameOffs(8) + nameUIF16Hash(4) + nameASCIIHash(4)
                    name_str, _ = read_wstring(buf, name_offs)
                    mat.gpbf.append(GpbfEntry(
                        name_offs_pos=name_offs_pos,
                        name_str=name_str,
                        name_str_pos=name_offs,
                    ))

    # ---- editing ---------------------------------------------------------

    def _fix_offsets(self, edit_pos: int, delta: int):
        """Mirror the .bt template's Fix_Off: any tracked offset field whose
        *value* points past the edit point shifts by delta."""
        if delta == 0:
            return
        buf = self.buf
        for field_pos in self._offset_fields:
            # all tracked fields in this format are 8-byte offsets
            val = read_u64(buf, field_pos)
            if val > edit_pos:
                struct.pack_into("<Q", buf, field_pos, val + delta)

    def _count_string_refs(self, str_pos: int) -> int:
        """RE Engine's exporter deduplicates identical strings (e.g. common
        default textures like NullBlack_Alpha_MSK4.tex), so many unrelated
        fields can point at the exact same byte offset. Mutating that offset
        in place would silently corrupt every other slot that shares it --
        this is what the .bt template's "Make Unique" helper exists to avoid.
        We must detect sharing before deciding how to edit."""
        count = 0
        for m in self.materials:
            if m.name_str_pos == str_pos:
                count += 1
            if m.mmtr_str_pos == str_pos:
                count += 1
            for t in m.textures:
                if t.type_str_pos == str_pos:
                    count += 1
                if t.path_str_pos == str_pos:
                    count += 1
            for p in m.props:
                if p.name_str_pos == str_pos:
                    count += 1
            for g in m.gpbf:
                if g.name_str_pos == str_pos:
                    count += 1
        return count

    def set_texture_path(self, tex: TexEntry, new_path: str):
        """Replace a texture's Path string.

        If the current string is only referenced by this one texture slot,
        it's edited in place (delete old bytes, insert new, fix up every
        offset field that pointed past the edit -- mirrors the template's
        mdf_st_write/Fix_Off). If the string is shared with other slots, we
        instead append a fresh copy at end-of-file and repoint only this
        slot's pathOffs field, leaving the shared original untouched so
        every other slot that still needs it keeps working."""
        buf = self.buf
        old_pos = tex.path_str_pos
        new_bytes = new_path.encode("utf-16-le") + b"\x00\x00"

        if self._count_string_refs(old_pos) > 1:
            new_offset = len(buf)
            buf.extend(new_bytes)
            struct.pack_into("<Q", buf, tex.path_offs_pos, new_offset)
            tex.path_str = new_path
            tex.path_str_pos = new_offset
            return

        _, old_bytelen = read_wstring(buf, old_pos)
        delta = len(new_bytes) - old_bytelen

        del buf[old_pos:old_pos + old_bytelen]
        buf[old_pos:old_pos] = new_bytes

        # the pathOffs field itself doesn't move (it lives earlier in the
        # file, in the fixed-size header region) but every offset >= old_pos
        # elsewhere in the file needs shifting -- including tex.path_offs_pos
        # itself is UNCHANGED (still old_pos), that's correct: the string now
        # starts at old_pos still.
        self._fix_offsets(old_pos, delta)

        # update our own bookkeeping so subsequent edits use correct positions
        tex.path_str = new_path
        for m in self.materials:
            for t in m.textures:
                # any string that lived after old_pos moved by delta
                if t.path_str_pos > old_pos:
                    t.path_str_pos += delta
                if t.type_str_pos > old_pos:
                    t.type_str_pos += delta
            if m.name_str_pos > old_pos:
                m.name_str_pos += delta
            if m.mmtr_str_pos > old_pos:
                m.mmtr_str_pos += delta
            for p in m.props:
                if p.name_str_pos > old_pos:
                    p.name_str_pos += delta
            for g in m.gpbf:
                if g.name_str_pos > old_pos:
                    g.name_str_pos += delta

    def to_bytes(self) -> bytes:
        return bytes(self.buf)
