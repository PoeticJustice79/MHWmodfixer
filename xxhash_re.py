"""
xxHash32/64, ported from REE.Packer's xxHash.cs (used for the per-entry
data checksum in custom mod .pak files -- PakHash.iGetDataHash there is
xxHash64(data) combined with xxHash32(bytes-of-that-hash) into one 64-bit
value). The community reader never actually validates this checksum, but
writing a correct one costs nothing and avoids being the one tool that
produces obviously-wrong paks if something ever does check it.
"""
from __future__ import annotations

import struct

_MASK32 = 0xFFFFFFFF
_MASK64 = 0xFFFFFFFFFFFFFFFF

P32_1, P32_2, P32_3, P32_4, P32_5 = 0x9E3779B1, 0x85EBCA77, 0xC2B2AE3D, 0x27D4EB2F, 0x165667B1
P64_1, P64_2, P64_3, P64_4, P64_5 = (
    0x9E3779B185EBCA87, 0xC2B2AE3D27D4EB4F, 0x165667B19E3779F9,
    0x85EBCA77C2B2AE63, 0x27D4EB2F165667C5,
)


def _rotl32(x, r): return ((x << r) | (x >> (32 - r))) & _MASK32
def _rotl64(x, r): return ((x << r) | (x >> (64 - r))) & _MASK64


def _round32(acc, val):
    acc = (acc + val * P32_2) & _MASK32
    acc = _rotl32(acc, 13)
    return (acc * P32_1) & _MASK32


def _round64(acc, val):
    acc = (acc + val * P64_2) & _MASK64
    acc = _rotl64(acc, 31)
    return (acc * P64_1) & _MASK64


def _merge64(acc, val):
    val = _round64(0, val)
    acc ^= val
    return (acc * P64_1 + P64_4) & _MASK64


def xxhash32(data: bytes, seed: int = 0xFFFFFFFF) -> int:
    off, end = 0, len(data)
    if end < 16:
        h = (seed + P32_5) & _MASK32
    else:
        v1, v2 = (seed + P32_1 + P32_2) & _MASK32, (seed + P32_2) & _MASK32
        v3, v4 = seed & _MASK32, (seed - P32_1) & _MASK32
        while off <= end - 16:
            v1 = _round32(v1, struct.unpack_from("<I", data, off)[0]); off += 4
            v2 = _round32(v2, struct.unpack_from("<I", data, off)[0]); off += 4
            v3 = _round32(v3, struct.unpack_from("<I", data, off)[0]); off += 4
            v4 = _round32(v4, struct.unpack_from("<I", data, off)[0]); off += 4
        h = (_rotl32(v1, 1) + _rotl32(v2, 7) + _rotl32(v3, 12) + _rotl32(v4, 18)) & _MASK32

    h = (h + end) & _MASK32
    while off + 4 <= end:
        h = (h + struct.unpack_from("<I", data, off)[0] * P32_3) & _MASK32
        h = (_rotl32(h, 17) * P32_4) & _MASK32
        off += 4
    while off < end:
        h = (h + data[off] * P32_5) & _MASK32
        h = (_rotl32(h, 11) * P32_1) & _MASK32
        off += 1

    h ^= h >> 15
    h = (h * P32_2) & _MASK32
    h ^= h >> 13
    h = (h * P32_3) & _MASK32
    h ^= h >> 16
    return h


def xxhash64(data: bytes, seed: int = 0xFFFFFFFF) -> int:
    off, end = 0, len(data)
    if end < 32:
        h = (seed + P64_5) & _MASK64
    else:
        v1, v2 = (seed + P64_1 + P64_2) & _MASK64, (seed + P64_2) & _MASK64
        v3, v4 = seed & _MASK64, (seed - P64_1) & _MASK64
        while off <= end - 32:
            v1 = _round64(v1, struct.unpack_from("<Q", data, off)[0]); off += 8
            v2 = _round64(v2, struct.unpack_from("<Q", data, off)[0]); off += 8
            v3 = _round64(v3, struct.unpack_from("<Q", data, off)[0]); off += 8
            v4 = _round64(v4, struct.unpack_from("<Q", data, off)[0]); off += 8
        h = (_rotl64(v1, 1) + _rotl64(v2, 7) + _rotl64(v3, 12) + _rotl64(v4, 18)) & _MASK64
        h = _merge64(h, v1)
        h = _merge64(h, v2)
        h = _merge64(h, v3)
        h = _merge64(h, v4)

    h = (h + end) & _MASK64
    while off + 8 <= end:
        h ^= _round64(0, struct.unpack_from("<Q", data, off)[0])
        h = (_rotl64(h, 27) * P64_1 + P64_4) & _MASK64
        off += 8
    if off + 4 <= end:
        h ^= (struct.unpack_from("<I", data, off)[0] * P64_1) & _MASK64
        h = (_rotl64(h, 23) * P64_2 + P64_3) & _MASK64
        off += 4
    while off < end:
        h ^= (data[off] * P64_5) & _MASK64
        h = (_rotl64(h, 11) * P64_1) & _MASK64
        off += 1

    h ^= h >> 33
    h = (h * P64_2) & _MASK64
    h ^= h >> 29
    h = (h * P64_3) & _MASK64
    h ^= h >> 32
    return h


def pak_data_checksum(data: bytes, seed: int = 0xFFFFFFFF) -> int:
    """Matches REE.Packer's PakHash.iGetDataHash."""
    h64 = xxhash64(data, seed)
    h32 = xxhash32(struct.pack("<Q", h64), seed)
    return ((h64 << 32) | h32) & _MASK64
