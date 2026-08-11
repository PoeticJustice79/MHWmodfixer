"""Minimal read-only parser for RE Engine "GMSG" localization files
(natives/stm/gamedesign/text/.../*.msg.23), used one-off to pull real
armor-series names in every supported language directly from the game's
own data rather than guessing translations or relying on incomplete
community wikis.

Clean-room implementation: format facts (header layout, XOR-chain string
pool decryption, entry table walk) were learned by reading REasy's own
MsgHandler (github.com/seifhassine/REasy, file_handlers/msg/msg_handler.py,
LGPLv3) as a reference -- same provenance approach as this project's
mesh_check.py (see its own docstring) -- but this is fresh, independently
structured code (plain struct.unpack_from, no Qt/BaseFileHandler
dependency), not a port. Read-only: no rebuild/write path, since this
project only ever needs to READ the current game's own text.
"""
from __future__ import annotations

import struct

_KEY = bytes([
    0xCF, 0xCE, 0xFB, 0xF8, 0xEC, 0x0A, 0x33, 0x66,
    0x93, 0xA9, 0x1D, 0x93, 0x50, 0x39, 0x5F, 0x09,
])

LANGUAGE_NAMES = {
    0: "Japanese", 1: "English", 2: "French", 3: "Italian", 4: "German",
    5: "Spanish", 6: "Russian", 7: "Polish", 8: "Dutch", 9: "Portuguese",
    10: "PortugueseBr", 11: "Korean", 12: "TransitionalChinese",
    13: "SimplifiedChinese", 14: "Finnish", 15: "Swedish", 16: "Danish",
    17: "Norwegian", 18: "Czech", 19: "Hungarian", 20: "Slovak",
    21: "Arabic", 22: "Turkish", 23: "Bulgarian", 24: "Greek",
    25: "Romanian", 26: "Thai",
}


def _is_encrypted(version: int) -> bool:
    return version > 12 and version != 0x2022033D


def _by_hash(version: int) -> bool:
    return version > 15 and version != 0x2022033D


def _decrypt_pool(encrypted: bytes) -> bytes:
    decrypted = bytearray(len(encrypted))
    prev = 0
    for i, cipher_byte in enumerate(encrypted):
        decrypted[i] = cipher_byte ^ prev ^ _KEY[i & 0xF]
        prev = cipher_byte
    return bytes(decrypted)


def parse_msg(data: bytes) -> dict:
    """Returns {"languages": [lang_code,...], "entries": [{"name", "content": [str per language]}]}."""
    ver, magic = struct.unpack_from("<I4s", data, 0)
    if magic != b"GMSG":
        raise ValueError("missing GMSG magic")
    encrypted = _is_encrypted(ver)
    is_v12 = not encrypted

    msg_count, param_count, lang_count = struct.unpack_from("<III", data, 16)
    if is_v12:
        data_offset = None
        lang_offset = struct.unpack_from("<Q", data, 40)[0]
    else:
        data_offset = struct.unpack_from("<Q", data, 32)[0]
        lang_offset = struct.unpack_from("<Q", data, 48)[0]

    pool = None
    if encrypted and data_offset is not None:
        pool = _decrypt_pool(data[data_offset:])

    def read_wstr(abs_off: int) -> str:
        if abs_off == 0:
            return ""
        if pool is not None and data_offset is not None and abs_off >= data_offset:
            chunk = pool[abs_off - data_offset:]
        else:
            chunk = data[abs_off:]
        for i in range(0, len(chunk) - 1, 2):
            if chunk[i] == 0 and chunk[i + 1] == 0:
                return chunk[:i].decode("utf-16le", "ignore")
        return chunk.decode("utf-16le", "ignore")

    languages = list(struct.unpack_from(f"<{lang_count}I", data, lang_offset))

    entry_table_base = 64 if is_v12 else 72
    entry_offsets = struct.unpack_from(f"<{msg_count}Q", data, entry_table_base)

    entries = []
    for eoff in entry_offsets:
        uuid_bytes = data[eoff:eoff + 16]
        cur_off = eoff + 16
        cur_off += 4         # skip SoundID
        cur_off += 4         # skip nameHash/index (identical size either way)
        name_ptr, _attr_ptr = struct.unpack_from("<QQ", data, cur_off)
        cur_off += 16
        lang_ptrs = struct.unpack_from(f"<{lang_count}Q", data, cur_off)
        entries.append({
            "name": read_wstr(name_ptr),
            "content": [read_wstr(p) for p in lang_ptrs],
            # Real, direct link to app.user_data.*.cData rows' Guid-typed
            # fields (e.g. WeaponData.cData's own `_Name`) elsewhere in
            # this game's RSZ data -- confirmed 2026-08-10 while chasing
            # weapon name coverage gaps: far more robust than matching by
            # positional index, which silently mismatches whenever an
            # entry's numbering doesn't line up 1:1 with its data row
            # (see bake_weapon_names.py).
            "uuid": uuid_bytes.hex(),
        })

    return {"languages": languages, "entries": entries}
