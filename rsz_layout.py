"""Whether an RSZ instance's OWN field data still parses cleanly under the
CURRENT game's field layout for its type -- the safety check `_crc_only_fix()`
(pfb_fix.py) didn't have. A CRC is a per-CLASS version stamp; matching type_id
alone doesn't prove the class's field LAYOUT is unchanged, only that the
runtime enforces some version check on it. Patching just the CRC while the
layout actually changed leaves old-shape bytes for the engine to read under
the new shape -- confirmed as the likely cause of a real in-game crash
(SilverWolf mod, 2026-08-08): patched-but-unverified pfb/user CRCs shipped in
a build that crashed on load.

Registry: tools/rsz_fields_mhwilds.json.gz, built from the "current"
(confirmed matching this project's live installed game build -- cross-
checked via.render.Mesh's crc against a real donor file, 2026-08-08) version
of a two-version snapshot (rszlayouts_MHWILDS.json.gz) taken from a
community RE Engine modding toolkit ("another community fixer" by NSA Cloud/
community contributors) that itself bakes from the REasy project's dumps.
Per type key (typeIDHash, hex): {"n": name, "f": [[name, size, align,
isArray, isVariable], ...]}, or {"fieldless": true} for a class confirmed to
carry zero bytes (NOT the same as "not in this registry at all" -- see
fits_current_layout()'s three-way return).

Three possible outcomes, deliberately not collapsed to a bool:
- True  ("fits"): the instance's bytes parse to EXACTLY its length, with
  every alignment pad zero. Its layout is provably identical under the
  current registry -- as safe as this project can currently confirm.
- False ("broken"): parsing ran past the data end, found a padding byte that
  wasn't zero, or left bytes unconsumed. Provable evidence the layout
  changed (or this dump doesn't describe it) -- never patch.
- None ("unverifiable"): a type in the walk has no entry (or an empty field
  list -- indistinguishable from "not dumped") in the registry, so nothing
  past it can be positioned either. This is NOT the same as "broken": most
  vanilla files hit this eventually (the dump is explicitly marked
  incomplete) -- including known-good, currently-shipping donor files, so
  treating it as a failure would refuse almost everything.

Callers decide what "unverifiable" means for their situation -- see
_crc_only_fix()'s require_fits parameter.
"""
from __future__ import annotations

import gzip
import json
import struct
import sys
from pathlib import Path

_HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
_REGISTRY_PATH = _HERE / "tools" / "rsz_fields_mhwilds.json.gz"
_registry_cache: dict | None = None


def _registry() -> dict:
    global _registry_cache
    if _registry_cache is None:
        try:
            with gzip.open(_REGISTRY_PATH, "rt", encoding="utf-8") as f:
                _registry_cache = json.load(f)
        except OSError:
            _registry_cache = {}
    return _registry_cache


class _LayoutError(Exception):
    pass


def _u32(data: bytes, pos: int) -> int:
    if pos + 4 > len(data):
        raise _LayoutError(f"read past end of block at {pos}")
    return struct.unpack_from("<I", data, pos)[0]


def _field_length(data: bytes, pos: int, size: int, is_variable: bool) -> int:
    if is_variable:
        return 4 + _u32(data, pos) * 2
    return size


def _parse_instance(data: bytes, pos: int, fields: list) -> tuple[int, bool]:
    """Consume one instance's fields starting at pos. Returns (new_pos, padding_was_clean).

    Each field is [name, size, align, isArray, isVariable] (compact snapshot
    tuple -- see module docstring); name is unused here, kept only because
    it's cheaper to carry through than to strip on load."""
    clean = True
    for _name, size, align, is_array, is_variable in fields:
        if is_array:
            start = pos
            pos += (-pos) % 4
            clean &= not any(data[start:pos])
            count = _u32(data, pos)
            pos += 4
            if count > 0xFFFFFF:
                raise _LayoutError(f"implausible array count {count} at {pos - 4}")
            for _ in range(count):
                start = pos
                pos += (-pos) % align
                clean &= not any(data[start:pos])
                length = _field_length(data, pos, size, is_variable)
                if pos + length > len(data):
                    raise _LayoutError(f"array element past end of block at {pos}")
                pos += length
        else:
            start = pos
            pos += (-pos) % align
            clean &= not any(data[start:pos])
            length = _field_length(data, pos, size, is_variable)
            if pos + length > len(data):
                raise _LayoutError(f"field past end of block at {pos}")
            pos += length
    return pos, clean


def fits_current_layout(rsz_info: dict) -> bool | None:
    """rsz_info: the dict returned by pfb_fix._parse_rsz() -- needs "insts"
    (list of (type_id, crc)), "external" (set of instance indices that are
    external userdata and carry no inline field data), and "data" (the raw
    instance-data block bytes).

    Returns True/False/None per the module docstring."""
    registry = _registry()
    if not registry:
        return None
    data = rsz_info["data"]
    external = rsz_info["external"]
    pos = 0
    clean = True
    for i, (type_id, _crc) in enumerate(rsz_info["insts"]):
        if i == 0 or i in external:
            continue
        entry = registry.get(format(type_id, "x"))
        if entry is None:
            return None  # not in this registry at all -- can't position anything after it either
        if entry.get("fieldless"):
            continue  # confirmed zero-byte class -- nothing to consume
        try:
            pos, ok = _parse_instance(data, pos, entry["f"])
        except _LayoutError:
            return False
        clean &= ok
    return pos == len(data) and clean
