"""
Minimal reader for Capcom RE Engine .pak archives (re_chunk_000.pak and its
patch_NNN.pak / sub_000.pak overlays), ported from the open-source C#
reference implementation "REE.PAK.Tool" by Ekey (h4x0r)
(https://github.com/Ekey/REE.PAK.Tool -- the copy this was read from lives
locally at Desktop/몬헌/REE.PAK.Tool-main).

Unlike that tool (and ree-pak-gui), this does NOT extract every entry to
disk -- re_chunk_000.pak is 40+ GB, so doing that just to reach a handful
of small material files isn't practical. Instead we only ever read the
(small) header + entry table into memory, then seek directly to the one
or two entries we actually need and decompress just those.

Ported pieces, byte-for-byte from the C# source:
  - PakHeader / PakEntry layout (major=4 => 48-byte entries)
  - PakCipher: RSA (e=65537) decrypt of the entry table using the
    hardcoded public modulus baked into every community pak tool -- this
    is the same "encryption" every existing unpacker already defeats, not
    something we're breaking that wasn't already broken.
  - PakChunks: the chunk map table + chunk-unwrap logic used by
    CHUNKED_RESOURCES-flagged paks (confirmed present on this game's
    newest patch pak).
  - Murmur3 x86_32 path hashing (PakHash.iGetStringHash): hash(path.lower())
    and hash(path.upper()) concatenated into one 64-bit key.

Deliberately NOT ported: ResourceCipher (per-entry RSA/BigInteger-division
scheme used for a small number of individually encrypted DLC resources).
Ordinary character/armor mdf2 files aren't expected to use it; if one ever
does, we raise a clear error instead of guessing.
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

import zstandard

MAGIC = 0x414B504B  # 'KPKA'

# ---- Murmur3 x86_32, matching REE.Unpacker's Murmur3.HashCore32 --------

def _rotl32(x: int, r: int) -> int:
    x &= 0xFFFFFFFF
    return ((x << r) | (x >> (32 - r))) & 0xFFFFFFFF


def _fmix32(h: int) -> int:
    h &= 0xFFFFFFFF
    h ^= h >> 16
    h = (h * 0x85ebca6b) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 0xc2b2ae35) & 0xFFFFFFFF
    h ^= h >> 16
    return h


def murmur3_x86_32(data: bytes, seed: int = 0xFFFFFFFF) -> int:
    c1 = 0xcc9e2d51
    c2 = 0x1b873593
    h1 = seed
    length = len(data)
    i = 0
    while i + 4 <= length:
        k1 = struct.unpack_from("<I", data, i)[0]
        k1 = (k1 * c1) & 0xFFFFFFFF
        k1 = _rotl32(k1, 15)
        k1 = (k1 * c2) & 0xFFFFFFFF
        h1 ^= k1
        h1 = _rotl32(h1, 13)
        h1 = (h1 * 5 + 0xe6546b64) & 0xFFFFFFFF
        i += 4
    tail = data[i:]
    if tail:
        k1 = 0
        for j, b in enumerate(tail):
            k1 |= b << (8 * j)
        k1 = (k1 * c1) & 0xFFFFFFFF
        k1 = _rotl32(k1, 15)
        k1 = (k1 * c2) & 0xFFFFFFFF
        h1 ^= k1
    h1 ^= length
    return _fmix32(h1)


def pak_string_hash(s: str) -> int:
    return murmur3_x86_32(s.encode("utf-16-le"))


def pak_path_hash64(path: str) -> int:
    """Matches PakList.iLoadProject: hash(lower) in the low 32 bits,
    hash(upper) in the high 32 bits."""
    lo = pak_string_hash(path.lower())
    hi = pak_string_hash(path.upper())
    return (hi << 32) | lo


# ---- RSA-based entry table decryption (PakCipher.iDecryptData) --------

_TABLE_MODULUS = bytes([
    0x7D, 0x0B, 0xF8, 0xC1, 0x7C, 0x23, 0xFD, 0x3B, 0xD4, 0x75, 0x16, 0xD2, 0x33, 0x21, 0xD8, 0x10,
    0x71, 0xF9, 0x7C, 0xD1, 0x34, 0x93, 0xBA, 0x77, 0x26, 0xFC, 0xAB, 0x2C, 0xEE, 0xDA, 0xD9, 0x1C,
    0x89, 0xE7, 0x29, 0x7B, 0xDD, 0x8A, 0xAE, 0x50, 0x39, 0xB6, 0x01, 0x6D, 0x21, 0x89, 0x5D, 0xA5,
    0xA1, 0x3E, 0xA2, 0xC0, 0x8C, 0x93, 0x13, 0x36, 0x65, 0xEB, 0xE8, 0xDF, 0x06, 0x17, 0x67, 0x96,
    0x06, 0x2B, 0xAC, 0x23, 0xED, 0x8C, 0xB7, 0x8B, 0x90, 0xAD, 0xEA, 0x71, 0xC4, 0x40, 0x44, 0x9D,
    0x1C, 0x7B, 0xBA, 0xC4, 0xB6, 0x2D, 0xD6, 0xD2, 0x4B, 0x62, 0xD6, 0x26, 0xFC, 0x74, 0x20, 0x07,
    0xEC, 0xE3, 0x59, 0x9A, 0xE6, 0xAF, 0xB9, 0xA8, 0x35, 0x8B, 0xE0, 0xE8, 0xD3, 0xCD, 0x45, 0x65,
    0xB0, 0x91, 0xC4, 0x95, 0x1B, 0xF3, 0x23, 0x1E, 0xC6, 0x71, 0xCF, 0x3E, 0x35, 0x2D, 0x6B, 0xE3,
])
_TABLE_EXPONENT = 0x00010001  # 65537


def _decrypt_table_key(encrypted_key: bytes) -> bytes:
    enc_int = int.from_bytes(encrypted_key[:128], "little")
    modulus = int.from_bytes(_TABLE_MODULUS, "little")
    key_int = pow(enc_int, _TABLE_EXPONENT, modulus)
    return key_int.to_bytes(128, "little")


def decrypt_entry_table(buf: bytes, encrypted_key: bytes) -> bytearray:
    key = _decrypt_table_key(encrypted_key)
    out = bytearray(buf)
    for i in range(len(out)):
        out[i] ^= (i + key[i % 32] * key[i % 29]) & 0xFF
    return out


# ---- Chunked-resource support (PakChunks) ------------------------------

@dataclass
class ChunkMapEntry:
    offset: int
    size: int  # already >> 10 like the C# code (see below) -- NOTE: kept raw here, see read_chunk_map


def read_chunk_map(f) -> list[ChunkMapEntry]:
    max_block_size, count = struct.unpack("<ii", f.read(8))
    raw = struct.unpack(f"<{count * 2}I", f.read(count * 8))
    offsets = raw[0::2]
    sizes = raw[1::2]
    high = 0
    prev = 0
    table = []
    for i in range(count):
        off = offsets[i]
        if i > 0 and off < prev:
            high += 1 << 32
        table.append(ChunkMapEntry(offset=high | off, size=sizes[i] >> 10))
        prev = off
    return table


def unwrap_chunks(f, entry: "PakEntry", chunk_map: list[ChunkMapEntry]) -> bytes:
    MAX_CHUNK = 524288
    remaining = entry.compressed_size
    chunk_id = entry.offset  # for chunked entries, dwOffset is actually a chunk index
    out = bytearray()
    while remaining > 0:
        c = chunk_map[chunk_id]
        f.seek(c.offset)
        src = f.read(c.size)
        if c.size == MAX_CHUNK:
            out += src
        else:
            out += zstandard.ZstdDecompressor().decompress(src)
        chunk_id += 1
        remaining -= c.size
    return bytes(out[: entry.decompressed_size])


# ---- Entry / header -----------------------------------------------------

COMPRESSION_NONE = 0
COMPRESSION_DEFLATE = 1
COMPRESSION_ZSTD = 2

FEATURE_NONE = 0
FEATURE_ENCRYPTED_RESOURCES = 8
FEATURE_DLC_EXTRA_DATA1 = 12
FEATURE_EXTRA_DATA = 24
FEATURE_CHUNKED_RESOURCES = 40
FEATURE_DLC_EXTRA_DATA2 = 44

_ENCRYPTED_TABLE_FEATURES = {
    FEATURE_ENCRYPTED_RESOURCES, FEATURE_DLC_EXTRA_DATA1,
    FEATURE_EXTRA_DATA, FEATURE_CHUNKED_RESOURCES, FEATURE_DLC_EXTRA_DATA2,
}
_CHUNKED_FEATURES = {FEATURE_CHUNKED_RESOURCES, FEATURE_DLC_EXTRA_DATA2}


@dataclass
class PakEntry:
    hash_lower: int
    hash_upper: int
    offset: int
    compressed_size: int
    decompressed_size: int
    attributes: int
    checksum: int

    @property
    def hash64(self) -> int:
        return (self.hash_upper << 32) | self.hash_lower

    @property
    def compression(self) -> int:
        return self.attributes & 0xF

    @property
    def encryption(self) -> int:
        return (self.attributes & 0x00FF0000) >> 16


class PakArchive:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.entries: dict[int, PakEntry] = {}
        self.chunk_map: list[ChunkMapEntry] | None = None
        self._parse()

    def _parse(self):
        with open(self.path, "rb") as f:
            hdr = f.read(16)
            if len(hdr) < 16:
                raise ValueError(f"{self.path}: too small to be a pak")
            magic, major, minor, feature, total_files, fingerprint = struct.unpack("<IBBhii", hdr)
            if magic != MAGIC:
                raise ValueError(f"{self.path}: bad magic 0x{magic:08X}")
            if major == 2:
                entry_size = 24
            elif major == 4:
                entry_size = 48
            else:
                raise ValueError(f"{self.path}: unsupported major version {major}")

            table = f.read(total_files * entry_size)

            if feature in _ENCRYPTED_TABLE_FEATURES:
                if feature == FEATURE_EXTRA_DATA:
                    f.read(4)
                elif feature in (FEATURE_DLC_EXTRA_DATA1, FEATURE_DLC_EXTRA_DATA2):
                    f.read(9)
                enc_key = f.read(128)
                table = decrypt_entry_table(table, enc_key)
                if feature in _CHUNKED_FEATURES:
                    self.chunk_map = read_chunk_map(f)

            self.major = major
            self.minor = minor
            self.feature = feature

            off = 0
            for _ in range(total_files):
                if major == 2:
                    o, dsize, hlo, hhi = struct.unpack_from("<qqII", table, off)
                    e = PakEntry(hlo, hhi, o, 0, dsize, 0, 0)
                    off += 24
                else:
                    hlo, hhi, o, csize, dsize, attrs, checksum = struct.unpack_from("<IIqqqqQ", table, off)
                    e = PakEntry(hlo, hhi, o, csize, dsize, attrs, checksum)
                    off += 48
                self.entries[e.hash64] = e

    def has(self, path: str) -> PakEntry | None:
        return self.entries.get(pak_path_hash64(path))

    def read_raw_compressed(self, entry: PakEntry) -> bytes:
        """The exact on-disk bytes for this entry, whatever compression
        (or none) they're already in -- for passing an unchanged entry
        through to a rebuilt pak without any decompress/recompress
        round-trip, so it's guaranteed byte-identical to the source."""
        with open(self.path, "rb") as f:
            f.seek(entry.offset)
            return f.read(entry.compressed_size)

    def read(self, entry: PakEntry) -> bytes:
        with open(self.path, "rb") as f:
            is_chunked_entry = self.chunk_map is not None and entry.attributes in (0x1000000, 0x1000400)
            if is_chunked_entry:
                return unwrap_chunks(f, entry, self.chunk_map)

            f.seek(entry.offset)
            raw = f.read(entry.compressed_size)

            if entry.encryption != 0:
                raise NotImplementedError(
                    f"entry has per-resource encryption (type {entry.encryption}) which this reader "
                    f"doesn't implement -- extract this one manually with ree-pak-gui/REtool instead"
                )

            comp = entry.compression
            if comp == COMPRESSION_NONE:
                return raw[: entry.decompressed_size]
            elif comp == COMPRESSION_DEFLATE:
                return zlib.decompress(raw, -15)
            elif comp == COMPRESSION_ZSTD:
                return zstandard.ZstdDecompressor().decompress(raw, max_output_size=entry.decompressed_size)
            else:
                raise ValueError(f"unknown compression type {comp}")

    def read_path(self, path: str) -> bytes | None:
        e = self.has(path)
        if e is None:
            return None
        return self.read(e)
