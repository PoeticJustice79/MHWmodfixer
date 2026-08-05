"""
Writer for the simple (unencrypted, non-chunked) KPKA pak variant that mod
tools use for small standalone "mod .pak" files -- as opposed to the
game's own re_chunk_000.pak, which is always encrypted and sometimes
chunked (see pak_reader.py, which only ever needs to READ that side).

Modeled directly on REE.Packer's PakPack.cs (the reference C# packer this
whole project's pak format understanding is ported from), but CORRECTED
against a real, untouched mod .pak wherever the two disagreed -- that
comparison caught two real problems:

  - checksum/fingerprint: the real file has 0 for every entry and for the
    header, not an xxHash-based value like PakPack.cs computes.
  - entry order: the real file's table is NOT sorted by hash64 (verified:
    consecutive hashes are not monotonic) -- so don't reorder entries at
    all, just preserve whatever order the caller passes in (normally the
    original pak's own iteration order).
  - compression: the real file stores every entry UNCOMPRESSED
    (attributes=0). A from-scratch rebuild that recompresses everything
    with zstd changes nothing semantically (bytes decompress identically)
    but still made a real mod's pak hang the game at the title screen in
    testing -- so entries must preserve whatever compression the source
    entry actually used, not get "upgraded" to zstd. See pak_mod_fix.py.

Header is magic + version(4, no separate minor/feature split needed since
mod paks never set those bits) + total_files + fingerprint(0); entries are
the same 48-byte layout pak_reader.py already parses.
"""
from __future__ import annotations

import struct

import zstandard

_MAGIC = 0x414B504B
_FINGERPRINT = 0x00000000


def write_pak(entries: list[dict], output_path: str) -> None:
    """entries: [{"hash64": int, "data": bytes (already in final on-disk
    form for the given compression), "decompressed_size": int,
    "compression": int}, ...], in the exact order to write them (NOT
    re-sorted -- see module docstring)."""
    total_files = len(entries)

    header = struct.pack("<IiiI", _MAGIC, 4, total_files, _FINGERPRINT)
    table_placeholder = bytes(total_files * 48)

    with open(output_path, "wb") as f:
        f.write(header)
        f.write(table_placeholder)

        table_rows = []
        for e in entries:
            offset = f.tell()
            f.write(e["data"])
            attributes = e["compression"] & 0xF
            table_rows.append(struct.pack(
                "<IIqqqqQ",
                e["hash64"] & 0xFFFFFFFF, (e["hash64"] >> 32) & 0xFFFFFFFF,
                offset, len(e["data"]), e["decompressed_size"], attributes, 0,
            ))

        f.seek(16)
        f.write(b"".join(table_rows))


def compress_zstd(data: bytes, level: int = 5) -> bytes:
    return zstandard.ZstdCompressor(level=level).compress(data)


def compress_deflate(data: bytes) -> bytes:
    import zlib
    co = zlib.compressobj(level=9, wbits=-15)  # raw deflate, matches pak_reader's zlib.decompress(raw, -15)
    return co.compress(data) + co.flush()


def compress_for(compression_type: int, data: bytes) -> bytes:
    """Compress `data` using whatever compression an entry originally
    used, so a passed-through entry's compression method never changes
    even when its content does. compression_type: pak_reader's
    COMPRESSION_NONE / COMPRESSION_DEFLATE / COMPRESSION_ZSTD."""
    from pak_reader import COMPRESSION_DEFLATE, COMPRESSION_NONE, COMPRESSION_ZSTD
    if compression_type == COMPRESSION_NONE:
        return data
    if compression_type == COMPRESSION_DEFLATE:
        return compress_deflate(data)
    if compression_type == COMPRESSION_ZSTD:
        return compress_zstd(data)
    raise ValueError(f"unknown compression type {compression_type}")
