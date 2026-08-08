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
_REGISTRY_PATH = CURRENT_PATH  # old name, kept for anything still importing it directly
_registry_cache: dict | None = None


def _registry() -> dict:
    global _registry_cache
    if _registry_cache is None:
        try:
            with gzip.open(CURRENT_PATH, "rt", encoding="utf-8") as f:
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


def _bake_raw_dump(raw_path: Path) -> dict:
    with open(raw_path, encoding="utf-8") as f:
        raw = json.load(f)
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
                 f["type"] in ("String", "Resource")]
                for f in fields
            ],
        }
    return out


def _bake_two_version_snapshot(path: Path, half: str) -> tuple[dict, str]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        snap = json.load(f)
    version = snap["versions"][half]
    out = {key: {"n": e["n"], "f": e["f"]} for key, e in version["types"].items()}
    for key in version.get("fieldless", {}):
        out[key] = {"n": "", "f": [], "fieldless": True}
    return out, version.get("label", half)


def detect_and_convert(path: Path, half: str | None = None) -> tuple[dict, str]:
    """Returns (entries, default_label) for any snapshot shape this project
    knows how to read: this project's own compact format, a raw
    rszmhwilds.json-style community dump, or another community fixer's
    two-version rszlayouts_MHWILDS.json.gz (pass half= for that one).
    Raises SnapshotError if the file matches none of them."""
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
            return _bake_two_version_snapshot(path, half)
        except KeyError as exc:
            raise SnapshotError(f"{path.name}: missing expected data ({exc})") from exc

    sample = next((v for k, v in data.items() if k != "_meta" and isinstance(v, dict)), None)
    if sample is not None and "f" in sample and "n" in sample:
        return _entries_only(data), (data.get("_meta") or {}).get("label", path.stem)

    try:
        entries = _bake_raw_dump(path)
    except (KeyError, TypeError) as exc:
        raise SnapshotError(f"{path.name} doesn't match any known snapshot format ({exc})") from exc
    if not entries:
        raise SnapshotError(f"{path.name} doesn't match any known snapshot format")
    return entries, path.stem


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
    partial result."""
    if as_role not in ("current", "archive"):
        raise SnapshotError(f"unknown role {as_role!r}")
    entries, default_label = detect_and_convert(source_path, half)
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
