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
community RE Engine modding toolkit (by NSA Cloud/
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

import datetime
import gzip
import json
import shutil
import struct
import sys
import tempfile
import urllib.request
from pathlib import Path

_HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
CURRENT_PATH = _HERE / "tools" / "rsz_fields_mhwilds.json.gz"
PREVIOUS_PATH = _HERE / "tools" / "rsz_fields_mhwilds_previous.json.gz"
OBJECT_FIELDS_PATH = _HERE / "tools" / "rsz_object_fields.json.gz"
_REGISTRY_PATH = CURRENT_PATH  # old name, kept for anything still importing it directly
_registry_cache: dict | None = None
_object_fields_cache: dict | None = None


def _registry() -> dict:
    global _registry_cache
    if _registry_cache is None:
        try:
            with gzip.open(CURRENT_PATH, "rt", encoding="utf-8") as f:
                _registry_cache = json.load(f)
        except OSError:
            _registry_cache = {}
    return _registry_cache


def _object_fields_registry() -> dict:
    """`{type_id_hex: [field_index, ...]}` -- which of a type's fields (by
    position in `_registry()[type_id]["f"]`) are RSZ "Object" type, i.e.
    hold an instance-index reference to ANOTHER RSZ instance, not plain
    data. `_registry()` itself doesn't carry this (it only has enough to
    compute byte lengths -- size/align/array/isVariable -- not RE Engine's
    actual field type enum), so this is baked from a SEPARATE, richer
    source: a fresh fetch of the REasy project's raw dump (which does
    carry real field types), cross-verified field-by-field against
    `_registry()`'s own compact entries and keeping ONLY the field indices
    where both agree on size/align/array -- seen a real, unignorable
    field mismatch rate even between same-crc dumps from different tools
    (`tools/rszmhwilds.json`, this project's own long-bundled REasy dump,
    turned out to be a whole title update stale relative to `_registry()`
    -- see CLAUDE.md; a FRESH same-day pull from REasy's GitHub was needed
    to get an actually-current comparison), so trusting a field's identity
    without this cross-check is not safe.

    Existing purely to let `pfb_fix.py`'s `_splice_mod_extras()` correctly
    remap an instance-index reference when the instance it points to gets
    relocated to a new index -- confirmed necessary the hard way (a real
    crash, 2026-08-08: splicing a mod's own `via.motion.Chain2` instance
    without remapping its `EnvWind` reference to the relocated
    `via.motion.ChainWind` instance's new index left that reference
    pointing at a garbage/out-of-range instance)."""
    global _object_fields_cache
    if _object_fields_cache is None:
        try:
            with gzip.open(OBJECT_FIELDS_PATH, "rt", encoding="utf-8") as f:
                _object_fields_cache = json.load(f)
        except OSError:
            _object_fields_cache = {}
    return _object_fields_cache


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

    Each field is [name, size, align, isArray, isVariable, type?] (compact
    snapshot tuple -- see module docstring; the trailing type string is a
    2026-08-09 addition and not every source has it yet, hence the `[:5]`
    slice-unpack below tolerating either length); name is unused here,
    kept only because it's cheaper to carry through than to strip on
    load."""
    clean = True
    for _name, size, align, is_array, is_variable in (f[:5] for f in fields):
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


def _next_string_offset(data: bytes, after: int) -> int | None:
    """First UTF16LE printable-ASCII run starting strictly after `after`,
    returned as the offset of its own 4-byte length-prefix (offset - 4 from
    where the text itself starts) -- i.e. where a String/Resource field's
    OWN field data would begin. Deliberately a lightweight local scanner
    (not pfb_fix.py's `_scan_utf16_strings`) to avoid a circular import;
    only used by `walk_instances_with_recovery()`'s resync fallback, where
    "first non-garbage-looking run" is all that's needed, not every string
    in the buffer."""
    i = max(after, 0)
    n = len(data)
    while i < n - 1:
        if data[i + 1] == 0 and 0x20 <= data[i] < 0x7F:
            j = i
            count = 0
            while j < n - 1 and data[j + 1] == 0 and data[j] != 0:
                count += 1
                j += 2
            if count > 2:
                return i - 4 if i >= 4 else None
            i = j if j > i else i + 1
        else:
            i += 1
    return None


def walk_instances_with_recovery(rsz_info: dict) -> tuple[list[tuple[int, int, int, int, int]], bool]:
    """Like `fits_current_layout()`, but returns per-instance byte spans
    instead of a single verdict, and tries to recover from a single
    unwalkable instance instead of giving up at the first one.

    Confirmed necessary for real mods (Mangie "Esthe"/"Mask Bikini",
    2026-08-08): both bundle a custom `app.ChainSetting` instance built
    against an OLDER field shape than this registry describes (neither the
    current registry's crc-matched entry -- Capcom apparently changed
    ChainSetting's own wind-related fields without bumping its crc -- nor
    the archived TU4 snapshot's entry actually fit the mod's raw bytes;
    the mod predates both). Guessing that field's true shape isn't
    attempted -- instead, on a parse failure the walk resyncs by finding
    the next recognizable UTF16 string in the buffer (via
    `_next_string_offset()`) and resumes from there, on the theory that
    whatever the failed instance's TRUE length actually is, the NEXT
    instance's own first string field (if it has one) is still findable
    directly. This only recovers the byte BOUNDARY, never reconstructs
    what the failed instance's own fields "really" are -- callers that
    need to preserve that instance's bytes (see pfb_fix.py's
    `_splice_mod_extras()`) must treat it as an opaque blob, not
    reinterpret its fields.

    Returns (spans, ok, recovered). Each span is (instance_index, type_id,
    crc, start, end) in `rsz_info["data"]`-relative byte offsets
    (start==end for the null instance and external/userdata instances,
    which carry no inline data). `ok` is True only if the walk (with any
    resyncs) landed EXACTLY on `len(data)` at the end -- the same "no
    leftover, no overshoot" proof `fits_current_layout()` requires, and
    the only reason a resync is trusted at all: a wrong resync point would
    need an almost impossible coincidence to still sum to the exact total
    length across every remaining instance. `recovered` is the set of
    instance indices whose own bytes did NOT parse (their span boundary
    came from a resync, not a clean parse) -- exactly the instances a
    caller must treat as opaque/reshaped; every index NOT in it parsed
    cleanly under the current registry at its recorded span."""
    registry = _registry()
    data = rsz_info["data"]
    external = rsz_info["external"]
    spans = []
    recovered = set()
    pos = 0
    for i, (type_id, crc) in enumerate(rsz_info["insts"]):
        if i == 0 or i in external:
            spans.append((i, type_id, crc, pos, pos))
            continue
        entry = registry.get(format(type_id, "x"))
        if entry is None:
            return spans, False, recovered
        if entry.get("fieldless"):
            spans.append((i, type_id, crc, pos, pos))
            continue
        start = pos
        try:
            pos, _clean = _parse_instance(data, pos, entry["f"])
        except _LayoutError:
            resync = _next_string_offset(data, pos)
            if resync is None or resync < pos:
                return spans, False, recovered
            pos = resync
            recovered.add(i)
        spans.append((i, type_id, crc, start, pos))
    return spans, pos == len(data), recovered


def _extract_instance_values(data: bytes, pos: int, fields: list) -> tuple[list, int]:
    """Like `_parse_instance()`, but returns the actual field VALUE bytes
    (padding discarded) instead of just a position -- padding is always
    zero and position-dependent, so it's meaningless to preserve; it gets
    recomputed fresh by `_write_instance_values()` for wherever the
    instance ends up. Each returned value is `("scalar", bytes)` or
    `("array", count, [elem_bytes, ...])`."""
    values = []
    for _name, size, align, is_array, is_variable in (f[:5] for f in fields):
        if is_array:
            pos += (-pos) % 4
            count = _u32(data, pos)
            if count > 0xFFFFFF:
                raise _LayoutError(f"implausible array count {count} at {pos}")
            pos += 4
            elems = []
            for _ in range(count):
                pos += (-pos) % align
                length = _field_length(data, pos, size, is_variable)
                if pos + length > len(data):
                    raise _LayoutError(f"array element past end of block at {pos}")
                elems.append(data[pos:pos + length])
                pos += length
            values.append(("array", count, elems))
        else:
            pos += (-pos) % align
            length = _field_length(data, pos, size, is_variable)
            if pos + length > len(data):
                raise _LayoutError(f"field past end of block at {pos}")
            values.append(("scalar", data[pos:pos + length]))
            pos += length
    return values, pos


def _write_instance_values(out: bytearray, pos: int, fields: list, values: list) -> int:
    """Inverse of `_extract_instance_values()`: appends one instance's
    field values to `out`, inserting fresh zero-padding computed for
    wherever `pos` (the position in `out`, i.e. in the NEW file) actually
    is -- NOT wherever it was in the source the values came from. This is
    what makes relocating an instance to a different absolute position
    (as `_splice_mod_extras()` does) safe: alignment padding is
    position-dependent, so copying a source instance's raw bytes verbatim
    into a new position can silently misalign it (confirmed real,
    2026-08-08: byte-identical instance content produced a DIFFERENT
    parsed length once moved, because a 4-byte-aligned field picked up 2
    extra padding bytes at its new position)."""
    for (_name, size, align, is_array, is_variable), val in zip((f[:5] for f in fields), values):
        if is_array:
            pad = (-pos) % 4
            out += b"\x00" * pad
            pos += pad
            _kind, count, elems = val
            out += struct.pack("<I", count)
            pos += 4
            for elem_bytes in elems:
                pad2 = (-pos) % align
                out += b"\x00" * pad2
                pos += pad2
                out += elem_bytes
                pos += len(elem_bytes)
        else:
            pad = (-pos) % align
            out += b"\x00" * pad
            pos += pad
            _kind, content = val
            out += content
            pos += len(content)
    return pos


def try_suffix_field_migration(data: bytes, start: int, end: int, fields: list) -> tuple[list, int] | None:
    """Attempt to recover a reshaped instance's OWN field values (rather
    than discarding them wholesale, as `pfb_fix.py`'s `_transplant_reshaped()`
    otherwise does) on the narrow, confirmed-real hypothesis that the type
    only grew NEW fields APPENDED at the end since the mod was built --
    never that an existing field changed name, type, position, or that a
    field was removed or inserted in the middle. This matches the actual
    confirmed case (`app.ChainSetting`, CLAUDE.md #18): Capcom's
    C#-reflection-based serialization appends new fields, it doesn't
    reorder or retype existing ones.

    Tries every truncation depth k (1..len(fields)-1, dropping the last k
    fields of the CURRENT registry's shape) and parses the instance's own
    bytes [start:end) against each truncated shape via
    `_extract_instance_values()`. A truncation only counts as a fit if it
    parses without error AND consumes the span EXACTLY (`pos == end`) --
    the same boundary-exactness proof `fits_current_layout()` and
    `walk_instances_with_recovery()` both require, chosen because a wrong
    truncation depth landing on the exact byte count by chance is
    vanishingly unlikely for real field-size mixes.

    Returns None if zero or more than one depth fits: multiple simultaneous
    fits mean this heuristic genuinely cannot tell which is real, and
    guessing anyway is exactly the kind of speculative RSZ engineering
    this project has been burned by before -- the caller must fall back to
    discarding the instance's own values entirely (never fall back to
    picking one of several ambiguous candidates).

    On a unique fit, returns `(values, k)`: `values` are the mod's own
    field values for `fields[:len(fields) - k]`, and `k` is how many
    trailing fields the caller still has to source from elsewhere (e.g.
    the donor) since the mod's bytes genuinely don't contain them."""
    n = len(fields)
    fits = []
    for k in range(1, n):
        truncated = fields[:n - k]
        try:
            values, pos = _extract_instance_values(data, start, truncated)
        except _LayoutError:
            continue
        if pos == end:
            fits.append((values, k))
    if len(fits) != 1:
        return None
    return fits[0]


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


# ---- snapshot management -------------------------------------------------
#
# The registry above goes stale exactly when a game title update reshapes
# RSZ classes -- the same day it's needed most. These functions manage the
# CURRENT snapshot plus an unlimited ARCHIVE_DIR of every snapshot that was
# ever current, so that gap can be closed by installing a fresh snapshot
# (baked by a maintainer, fetched straight from its source, or shared by
# someone else) without waiting for a whole new MHWmodfixer release. Used
# by both gui.py (Settings -> RSZ Snapshot dialog) and
# tools/bake_rsz_snapshot.py (the maintainer-side CLI, which additionally
# knows how to bake a snapshot from a raw ~100MB community registry dump --
# not needed here since an end user only ever installs an already-baked,
# few-MB snapshot file).
#
# Originally this kept only ONE prior snapshot (a fixed "previous" slot,
# overwritten every time a new one rotated in) -- changed to a growing,
# dated archive per the user's own reasoning (2026-08-08): "스냅샷도
# 버전별로 계속 저장될 수 있게 해야할것 같아" ("snapshots should keep
# accumulating per version too") -- a single previous slot loses anything
# more than one update back, which would block migrating across a gap
# wider than one title update once real field migration gets built.

ARCHIVE_DIR = _HERE / "tools" / "rsz_archive"
PREVIOUS_PATH = ARCHIVE_DIR  # old name, now a directory rather than one file -- see above


class SnapshotError(Exception):
    pass


def _entries_only(snapshot: dict) -> dict:
    return {k: v for k, v in snapshot.items() if k != "_meta"}


def snapshot_meta(path: Path) -> dict | None:
    """The _meta block of a snapshot at `path`, or None if unreadable."""
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            snap = json.load(f)
    except (OSError, gzip.BadGzipFile, json.JSONDecodeError):
        return None
    meta = dict(snap.get("_meta", {}))
    meta.setdefault("entry_count", len(_entries_only(snap)))
    return meta


def _archive_filename(meta: dict) -> str:
    """A filesystem-safe, sorts-in-date-order name for archiving one
    snapshot: <game_update_date-or-baked_at>_<sanitized label>.json.gz."""
    date = meta.get("game_update_date")
    if not date or date == "unknown":
        date = meta.get("baked_at", "unknown-date")
    label = meta.get("label") or "snapshot"
    safe_label = "".join(c if c.isalnum() or c in "-_." else "_" for c in label)[:60]
    return f"{date}_{safe_label}.json.gz"


def _unique_path(directory: Path, filename: str) -> Path:
    """filename, or filename with -2/-3/... inserted before the extension
    if it already exists -- archiving must never silently overwrite an
    earlier entry just because two snapshots share a label."""
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = filename[:-len(".json.gz")] if filename.endswith(".json.gz") else candidate.stem
    n = 2
    while True:
        candidate = directory / f"{stem}-{n}.json.gz"
        if not candidate.exists():
            return candidate
        n += 1


def list_snapshots() -> list[dict]:
    """The current snapshot plus every archived one, newest first by
    game_update_date (falling back to baked_at). Each entry: role
    ("current" or "archived"), path, exists, file_size, meta (or None if
    unreadable/missing)."""
    out = []
    meta = snapshot_meta(CURRENT_PATH) if CURRENT_PATH.exists() else None
    out.append({
        "role": "current", "path": CURRENT_PATH, "exists": CURRENT_PATH.exists(),
        "file_size": CURRENT_PATH.stat().st_size if CURRENT_PATH.exists() else 0,
        "meta": meta,
    })

    archived = []
    if ARCHIVE_DIR.is_dir():
        for path in ARCHIVE_DIR.glob("*.json.gz"):
            meta = snapshot_meta(path)
            archived.append({
                "role": "archived", "path": path, "exists": True,
                "file_size": path.stat().st_size, "meta": meta,
            })
    archived.sort(key=lambda e: (e["meta"] or {}).get("game_update_date")
                  or (e["meta"] or {}).get("baked_at") or "", reverse=True)
    out.extend(archived)
    return out


# Every type_id (hex, matching this module's registry keys) referenced
# anywhere in the two real mods (Mangie "Esthe"/"Mask Bikini") this
# project's ONLY verified `app.ChainSetting` transplant-resolution path has
# ever been tested against (2026-08-09, is_variable precision patch --
# see the "surgical is_variable patch" work earlier that session). That
# resolution depends on `walk_instances_with_recovery()`'s byte-content
# resync landing at the exact right offset after `app.ChainSetting` throws
# (the mod's instance predates the registry's current field shape), and
# that resync's landing point is `pos`-dependent: correcting `is_variable`
# for ANY of these types (even ones walked before ChainSetting itself,
# confirmed real: `app.CharacterEditRegion`) shifts where the resync
# search starts, silently moving the recovery point -- confirmed to break
# the walk at a completely unrelated later instance during that
# investigation. `_bake_raw_dump()`'s merge path excludes these
# specifically so a future registry refresh (this function, run either via
# the GUI's "Check GitHub" button or a manual import) can never reintroduce
# that regression, even though a plain shape-agreement check would
# otherwise consider some of them safe to "correct".
_TRANSPLANT_VERIFIED_TYPE_IDS = frozenset([
    "0", "206169e6", "23f9647a", "253f86ee", "278c2bbe", "3dd0b54", "45301b93",
    "4d94fbe4", "5882a4b", "6c00c472", "6c13b6a3", "7091fa", "8d8f9b0b", "91c5fed4",
    "acab5fe7", "addf3bf7", "b67210e9", "bc86cc1f", "be980941", "c20504c1",
    "c348b8db", "c902a417", "ce514949", "cf318533", "dfac3046", "ed683451",
    "eff0c408", "f829f958", "f9b54376", "fdcea1a0",
])


def _bake_raw_dump(raw_path: Path, merge_with: dict | None = None) -> tuple[dict, dict]:
    """Confirmed real bug, fixed 2026-08-09: this used to treat any field
    typed `Resource` the same as `String` (variable-length, 4-byte count
    prefix + inline UTF-16 chars). A `Resource` field is NOT
    variable-length at all -- it's a plain fixed-size value (an index/
    handle into the resource table, same shape as `size` says, no inline
    string data whatsoever). Cross-checked directly against a real
    REasy dump (`rszmhwilds_fresh.json`, confirmed live-crc-matching):
    of every field this project's OLD registry had marked variable,
    826 were actually `Resource` -- a systematic misclassification
    across hundreds of real classes, not a one-off. It only ever stayed
    invisible because a variable-length parse of a zero/null value
    happens to consume the identical 4 bytes a fixed-size parse of the
    same zero value would -- any instance where that specific field held
    a genuinely non-zero Resource index would have silently misaligned
    every byte after it. `String` is the only type this project has ever
    found real evidence needs variable-length treatment (checked the
    reverse direction too: zero fields this project called fixed-size
    that the fresh dump calls `String`).

    Each field's real `type` string is now also kept (6th list element,
    previously absent) -- not used for parsing yet (only `is_variable`,
    now derived correctly as `type == "String"`, is), but available for
    a future field-level migration pass that needs to know more than
    "same size" to migrate a reshaped instance's data correctly.

    `merge_with`, if given (the CURRENT registry's own entries, same
    `{type_key: {"n":..., "f":...}, ...}` shape this function returns),
    switches this from a wholesale rebake to a SAFE MERGE -- required
    after a real close call, 2026-08-09: rebaking wholesale straight from
    a fresh raw dump (exactly what the GUI's "Check GitHub for latest
    data" button used to do) silently dropped total entries from 323,073
    to 48,448, because raw dumps have no reliable "confirmed fieldless"
    marker (unlike `_bake_two_version_snapshot()`'s format, which has an
    explicit separate fieldless list) -- this function's own `if not
    fields: continue` can't tell "genuinely zero fields" from "just not
    dumped", so a wholesale rebake treats both as "drop this type
    entirely". It also broke a real mod's resolution by mismatching a
    NATIVE (`via.*`) type's field count (`via.render.Mesh`: 82 trusted
    fields vs 83 in the fresh dump, a real size mismatch at one position)
    -- native types are inherently less reliable in ANY raw RSZ dump,
    confirmed even by REFramework's own official dumping pipeline, which
    documents native-type field layouts as CPU-emulation "guesses", unlike
    managed (`app.*`) types that come from real C#-reflection metadata.
    The original fix for this was a one-off manual script; this generalizes
    it into the actual code path so every future refresh (via the GUI
    button or a manual import) is safe by construction, not just the one
    the script happened to be run against.

    Merge rule, per type already in `merge_with`: correct `is_variable`
    (+ append the type string) ONLY if the raw dump agrees with the
    trusted entry on every field's `(size, align, is_array)` at the same
    position; ANY shape disagreement anywhere leaves that entire type's
    trusted entry completely untouched (a mismatch at one position means
    later same-index fields might not even be the same field, so nothing
    past it can be trusted positionally either) -- same "only trust
    cross-source agreement at the same position" principle already used
    for `is_variable_patched_at`/Object-field detection elsewhere in this
    project's history. A type the raw dump doesn't mention at all, or has
    no usable field data for, is also left completely untouched. A type
    genuinely new to `merge_with` gets added from the raw dump wholesale
    -- there's no existing trusted data to protect there, so gaining
    (possibly still-guessed, for a native type) information beats having
    none at all.

    Returns `(entries, stats)`. `stats` is `{}` when `merge_with` is None
    (a plain wholesale bake, e.g. installing this as a brand new registry
    with nothing yet to protect); otherwise `{"corrected": N,
    "shape_mismatches": N, "added": N}`."""
    with open(raw_path, encoding="utf-8") as f:
        raw = json.load(f)

    if merge_with is None:
        out = {}
        for key, entry in raw.items():
            if not isinstance(entry, dict):
                continue
            fields = entry.get("fields")
            if not fields:
                continue  # can't tell "zero fields" from "not dumped"
            out[key] = {
                "n": entry.get("name", ""),
                "f": [
                    [f["name"], f["size"], f["align"], bool(f["array"]),
                     f["type"] == "String", f["type"]]
                    for f in fields
                ],
            }
        return out, {}

    out = dict(merge_with)
    corrected = shape_mismatches = added = 0
    for key, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        fields = entry.get("fields")
        old = out.get(key)
        if old is None:
            if fields:
                out[key] = {
                    "n": entry.get("name", ""),
                    "f": [
                        [f["name"], f["size"], f["align"], bool(f["array"]),
                         f["type"] == "String", f["type"]]
                        for f in fields
                    ],
                }
                added += 1
            continue
        if not fields or old.get("fieldless") or "f" not in old:
            continue
        if key in _TRANSPLANT_VERIFIED_TYPE_IDS:
            continue
        old_fields = old["f"]
        if len(old_fields) != len(fields):
            continue
        shapes_match = all(
            of[1] == rf["size"] and of[2] == rf["align"] and of[3] == bool(rf["array"])
            for of, rf in zip(old_fields, fields)
        )
        if not shapes_match:
            shape_mismatches += 1
            continue
        new_fields = [
            [of[0], of[1], of[2], of[3], rf["type"] == "String", rf["type"]]
            for of, rf in zip(old_fields, fields)
        ]
        if new_fields != [list(f) for f in old_fields]:
            corrected += 1
        out[key] = {"n": old.get("n") or entry.get("name", ""), "f": new_fields}

    return out, {"corrected": corrected, "shape_mismatches": shape_mismatches, "added": added}


def _bake_two_version_snapshot(path: Path, half: str) -> tuple[dict, str]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        snap = json.load(f)
    version = snap["versions"][half]
    out = {key: {"n": e["n"], "f": e["f"]} for key, e in version["types"].items()}
    for key in version.get("fieldless", {}):
        out[key] = {"n": "", "f": [], "fieldless": True}
    return out, version.get("label", half)


def detect_and_convert(path: Path, half: str | None = None,
                        merge_with: dict | None = None) -> tuple[dict, str, dict]:
    """Returns (entries, default_label, stats) for any snapshot shape this
    project knows how to read: this project's own compact format, a raw
    rszmhwilds.json-style community dump, or a community fixer's two-version
    rszlayouts_MHWILDS.json.gz (pass half= for that one).
    Raises SnapshotError if the file matches none of them.

    `merge_with` (see `_bake_raw_dump()`'s own docstring for the full
    rationale) only affects the raw-dump branch -- a compact-format or
    two-version source is already self-contained/trusted on its own, so
    there's nothing to merge-protect there. `stats` is `{}` whenever
    merging wasn't applicable."""
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            data = json.load(f)
    except gzip.BadGzipFile:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"couldn't read {path.name}: {exc}") from exc

    if not isinstance(data, dict):
        raise SnapshotError(f"{path.name} isn't a recognized snapshot (not a JSON object)")

    if "versions" in data:
        if half is None:
            raise SnapshotError(f"{path.name} is a two-version snapshot -- specify which half to use")
        try:
            entries, label = _bake_two_version_snapshot(path, half)
            return entries, label, {}
        except KeyError as exc:
            raise SnapshotError(f"{path.name}: missing expected data ({exc})") from exc

    sample = next((v for k, v in data.items() if k != "_meta" and isinstance(v, dict)), None)
    if sample is not None and "f" in sample and "n" in sample:
        return _entries_only(data), (data.get("_meta") or {}).get("label", path.stem), {}

    try:
        entries, stats = _bake_raw_dump(path, merge_with=merge_with)
    except (KeyError, TypeError) as exc:
        raise SnapshotError(f"{path.name} doesn't match any known snapshot format ({exc})") from exc
    if not entries:
        raise SnapshotError(f"{path.name} doesn't match any known snapshot format")
    return entries, path.stem, stats


def _write_gz(dest: Path, payload: dict):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=9) as f:
        json.dump(payload, f, separators=(",", ":"))
    tmp.replace(dest)


def archive_current() -> Path | None:
    """Copies the existing "current" snapshot into ARCHIVE_DIR under a name
    derived from its own metadata, without touching CURRENT_PATH itself.
    Returns the archived path, or None if there was no current snapshot to
    archive. Called automatically by install_snapshot(as_role="current")
    before it overwrites current -- exposed separately too, in case a
    caller ever needs to archive without immediately replacing it."""
    if not CURRENT_PATH.exists():
        return None
    meta = snapshot_meta(CURRENT_PATH) or {}
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dest = _unique_path(ARCHIVE_DIR, _archive_filename(meta))
    shutil.copyfile(CURRENT_PATH, dest)
    return dest


def install_snapshot(source_path: Path, as_role: str, label: str | None = None,
                      game_update_date: str | None = None, rotate: bool = True,
                      half: str | None = None) -> dict:
    """Installs `source_path` as either:
    - "current": the single active snapshot fits_current_layout() reads.
      When rotate is True (the default -- see this module's docstring on
      why losing history is the exact gap that blocked full migration on
      2026-08-08), whatever was current before this call is archived
      first via archive_current(), so nothing is ever silently discarded.
    - "archive": stashed directly into ARCHIVE_DIR without touching
      "current" at all -- for saving a snapshot for possible future
      migration use without activating it.

    Returns the new snapshot's _meta dict. Raises SnapshotError on anything
    that would leave a broken or empty snapshot installed -- never writes a
    partial result.

    When `as_role == "current"` and a current snapshot already exists,
    that existing snapshot's own entries are passed to `detect_and_convert()`
    as a merge base (see `_bake_raw_dump()`'s docstring) -- this only
    changes behavior for a raw-dump source (the GUI's "Check GitHub for
    latest data" button, or manually importing a raw dump and choosing
    "current"): instead of a wholesale rebake silently discarding whatever
    the current registry already had confirmed, it reinforces the
    existing trusted registry with whatever the fresh dump agrees on, adds
    genuinely new types, and leaves everything else untouched. A compact-
    format or two-version source is unaffected either way -- those are
    already self-contained."""
    if as_role not in ("current", "archive"):
        raise SnapshotError(f"unknown role {as_role!r}")
    merge_with = None
    if as_role == "current" and CURRENT_PATH.exists():
        try:
            with gzip.open(CURRENT_PATH, "rt", encoding="utf-8") as f:
                merge_with = _entries_only(json.load(f))
        except (OSError, gzip.BadGzipFile, json.JSONDecodeError):
            merge_with = None  # current snapshot unreadable -- fall back to a plain wholesale bake
    entries, default_label, merge_stats = detect_and_convert(source_path, half, merge_with=merge_with)
    if not entries:
        raise SnapshotError(f"{source_path.name} converted to zero typed classes -- refusing to install it")

    payload = dict(entries)
    payload["_meta"] = {
        "label": label or default_label,
        "baked_at": datetime.date.today().isoformat(),
        "game_update_date": game_update_date or "unknown",
        "source": f"imported from {source_path.name}",
        "entry_count": len(entries),
    }
    if merge_stats:
        payload["_meta"]["merge_stats"] = merge_stats

    if as_role == "current":
        if rotate:
            archive_current()
        _write_gz(CURRENT_PATH, payload)
        global _registry_cache
        _registry_cache = None  # next fits_current_layout() call re-reads the new file
    else:
        dest = _unique_path(ARCHIVE_DIR, _archive_filename(payload["_meta"]))
        _write_gz(dest, payload)

    return payload["_meta"]


# ---- fetching a fresh dump straight from its source ----------------------
#
# Confirmed live source (2026-08-08): the REasy project (github.com/
# seifhassine/REasy) keeps a per-game RSZ type-registry dump under
# resources/data/dumps/ -- this is the same origin this project's own
# tools/rszmhwilds.json (the TU4 "previous" snapshot) was fetched from
# earlier in this project's history. Checked again while wiring this up:
# the file there is already 103,929,358 bytes, larger than this project's
# bundled 103,163,427-byte copy -- i.e. REasy's own dump had already moved
# on since this project's copy was taken, which is exactly the kind of gap
# this fetch-and-bake feature exists to close without a whole new
# MHWmodfixer release.

GITHUB_DUMP_URL = "https://raw.githubusercontent.com/seifhassine/REasy/master/resources/data/dumps/rszmhwilds.json"

# A real vanilla (non-mod) .pfb, identified by its path hash -- used only to
# sanity-check a freshly fetched/imported "current" snapshot against
# whatever game build is actually installed, the same way this project's
# own bundled registry was caught being one whole title update stale
# (2026-08-08, see CLAUDE.md #9). Any equip .pfb would do; this one was
# already confirmed reachable via GameArchive.read_by_hash() on that date.
SAMPLE_PFB_HASH = 0x93538AED5435EFA9


def fetch_latest_dump(progress_cb=None, timeout: int = 30) -> Path:
    """Downloads the current rszmhwilds.json from GITHUB_DUMP_URL to a fresh
    temp file and returns its path. progress_cb(bytes_done, bytes_total), if
    given, is called after each chunk; bytes_total is -1 if the server
    didn't send a Content-Length. Raises on any network/HTTP error --
    callers should not treat a partial temp file as usable."""
    req = urllib.request.Request(GITHUB_DUMP_URL, headers={"User-Agent": "MHWmodfixer"})
    dest = Path(tempfile.mkdtemp(prefix="mhwmodfix_rsz_")) / "rszmhwilds.json"
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length", -1))
        done = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(done, total)
    return dest


def verify_against_live_game(game) -> bool | None:
    """Sanity-checks the just-installed "current" snapshot against a real
    file from `game` (a GameArchive). Returns True/False/None with the same
    meaning as fits_current_layout() -- see that function's docstring --
    applied to SAMPLE_PFB_HASH specifically. None also covers "the sample
    itself isn't present in this install" (e.g. a non-standard game
    location), which should be treated as inconclusive, not a failure."""
    from pfb_fix import _parse_rsz  # local import: pfb_fix imports this module at load time

    data = game.read_by_hash(SAMPLE_PFB_HASH)
    if data is None:
        return None
    info = _parse_rsz(data)
    if info is None:
        return None
    return fits_current_layout(info)
