"""
Layers re_chunk_000.pak (+ its patch_NNN.pak overlays) and
re_chunk_000.pak.sub_000.pak (+ its own patch_NNN.pak overlays) into one
merged lookup, so a single `read_path()` call gets you the CURRENT
(latest-patched) bytes for any in-game path, straight out of the game
install -- no manual extraction step, no separate tool.

Patch layering: process base first, then patches in ascending numeric
order; a later patch's entry for the same path hash simply overwrites the
earlier one in the merged dict, matching how the game itself resolves
overlapping patches (highest patch number wins).

Indexing every pak's header + entry table takes real time (dozens of
files, one of them ~40GB) even though we never read the bulk file data.
For a GUI that gets re-run often, that adds up, so the merged index is
cached to disk keyed by a fingerprint of the paks' names/sizes/mtimes --
if the game hasn't been patched since, we skip straight to a pickle load.
"""
from __future__ import annotations

import hashlib
import os
import pickle
import re
from pathlib import Path

from pak_reader import PakArchive, PakEntry, pak_path_hash64

_PATCH_RE = re.compile(r"\.patch_(\d+)\.pak$", re.IGNORECASE)

_CACHE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MHWmodfixer" / "pak_index_cache"


def _discover_paks(game_dir: Path) -> list[Path]:
    """Returns [base, patch_001, patch_002, ...] for both re_chunk_000.pak
    and re_chunk_000.pak.sub_000.pak, base-then-ascending-patch for each
    group, sub-archives after main (order across groups doesn't matter
    since hash namespaces don't collide, only within-group order does)."""
    groups: dict[str, list[tuple[int, Path]]] = {}
    for p in game_dir.glob("re_chunk_000.pak*"):
        if p.name == "re_chunk_000.pak":
            groups.setdefault("main", []).append((-1, p))
        elif p.name == "re_chunk_000.pak.sub_000.pak":
            groups.setdefault("sub", []).append((-1, p))
        else:
            m = _PATCH_RE.search(p.name)
            if not m:
                continue
            patch_num = int(m.group(1))
            group = "sub" if ".sub_000.pak." in p.name else "main"
            groups.setdefault(group, []).append((patch_num, p))

    ordered: list[Path] = []
    for group in ("main", "sub"):
        for _, p in sorted(groups.get(group, []), key=lambda t: t[0]):
            ordered.append(p)
    return ordered


def _fingerprint(pak_paths: list[Path]) -> str:
    parts = []
    for p in pak_paths:
        st = p.stat()
        parts.append(f"{p.name}:{st.st_size}:{int(st.st_mtime)}")
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return digest


class GameArchive:
    def __init__(self, game_dir: str | Path, log=lambda s: None, use_cache: bool = True):
        self.game_dir = Path(game_dir)
        # hash64 -> (pak_file_path_str, PakEntry)
        self._entries: dict[int, tuple[str, PakEntry]] = {}
        self._chunk_maps: dict[str, list] = {}

        pak_paths = _discover_paks(self.game_dir)
        if not pak_paths:
            raise FileNotFoundError(f"No re_chunk_000.pak* files found under {self.game_dir}")

        fp = _fingerprint(pak_paths)
        cache_file = _CACHE_DIR / f"{fp}.pkl"

        if use_cache and cache_file.exists():
            log(f"loading cached pak index ({cache_file.name})...")
            try:
                with open(cache_file, "rb") as f:
                    cached = pickle.load(f)
                self._entries = cached["entries"]
                self._chunk_maps = cached["chunk_maps"]
                log(f"total unique paths indexed (from cache): {len(self._entries)}")
                return
            except Exception as e:
                log(f"  [warn] cache load failed ({e}), reindexing from scratch")

        for p in pak_paths:
            log(f"indexing {p.name} ...")
            try:
                archive = PakArchive(p)
            except Exception as e:
                log(f"  [warn] failed to read {p.name}: {e}")
                continue
            path_str = str(p)
            for h, e in archive.entries.items():
                self._entries[h] = (path_str, e)
            if archive.chunk_map is not None:
                self._chunk_maps[path_str] = archive.chunk_map
            log(f"  {len(archive.entries)} entries (feature={archive.feature})")
        log(f"total unique paths indexed: {len(self._entries)}")

        if use_cache:
            try:
                _CACHE_DIR.mkdir(parents=True, exist_ok=True)
                with open(cache_file, "wb") as f:
                    pickle.dump({"entries": self._entries, "chunk_maps": self._chunk_maps}, f)
            except Exception as e:
                log(f"  [warn] failed to write pak index cache: {e}")

    def _read_entry(self, pak_path_str: str, entry: PakEntry) -> bytes:
        archive = PakArchive.__new__(PakArchive)
        archive.path = Path(pak_path_str)
        archive.chunk_map = self._chunk_maps.get(pak_path_str)
        return archive.read(entry)

    def read_path(self, path: str) -> bytes | None:
        hit = self._entries.get(pak_path_hash64(path))
        if hit is None:
            return None
        pak_path_str, entry = hit
        return self._read_entry(pak_path_str, entry)

    def read_by_hash(self, hash64: int) -> bytes | None:
        """For content pulled from a mod's own standalone .pak file: those
        entries carry no filename, only a hash64 -- but if a mod's entry
        hash exactly matches one of the game's own current entries, that
        IS the vanilla donor, unambiguously, no path-guessing needed."""
        hit = self._entries.get(hash64)
        if hit is None:
            return None
        pak_path_str, entry = hit
        return self._read_entry(pak_path_str, entry)

    def has_hash(self, hash64: int) -> bool:
        return hash64 in self._entries

    def find_versioned_path(self, base_path_no_version: str, ext: str, version_range=range(1, 500)) -> str | None:
        """Cheap existence check (no decompression) -- just tells you which
        version suffix currently exists, for fast diagnosis."""
        for n in version_range:
            candidate = f"{base_path_no_version}.{ext}.{n}"
            if pak_path_hash64(candidate) in self._entries:
                return candidate
        return None

    def find_versioned(self, base_path_no_version: str, ext: str, version_range=range(1, 500)) -> tuple[str, bytes] | None:
        """base_path_no_version: full in-pak path WITHOUT the trailing
        `.{ext}.NN` part, e.g. '.../mh03_014_0003'. Tries every plausible
        version suffix and returns the first (path, bytes) that exists in
        the currently installed game version."""
        path = self.find_versioned_path(base_path_no_version, ext, version_range)
        if path is None:
            return None
        pak_path_str, entry = self._entries[pak_path_hash64(path)]
        return path, self._read_entry(pak_path_str, entry)
