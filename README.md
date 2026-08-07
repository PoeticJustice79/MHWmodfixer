# MHWmodfixer by Littlefish (PoeticJustice79)

*English | [한국어](README.ko.md)*

A tool that automatically repairs Monster Hunter Wilds cosmetic mods broken
by official game updates. Point it at a single mod archive and it handles
everything: extract the archive → pull the vanilla files it needs directly
out of the current game version's paks → figure out exactly which parts
actually changed structurally → reassemble materials against the current
shader → repackage in the mod's original structure. No need to run
ree-pak-gui/REtool/Blender or any other external tool by hand.

## Running it

**Just use the GUI**: double-click `dist\MHWmodfixer.exe`. No need to install
Python, Bandizip, or 7-Zip — everything is bundled into the exe. Check the
game folder on screen → drag a mod archive (zip/7z/rar) into the list, or
pick one with the "Add" button (multiple at once is fine; dropping a whole
folder makes it auto-discover archives inside) → click "Start Repair" and
that's it. With multiple mods queued, they're processed one at a time in
list order, each going through its own diagnosis confirmation and its own
save-location prompt.

**"Experimental: force-fix parts that don't safely reconcile" checkbox**:
off by default. Some `.pfb` (prefab) files differ too much in structure
from the donor (the current game version) to be safely auto-repaired, and
the default is to leave those files untouched — safer than guessing wrong
and wiping out the mod's own customization. But leaving a part unresolved
like that can mean more than a color glitch or invisibility when actually
worn in-game — **it has been directly confirmed to hang the game mid-load**
(Mangie's "Snow Trigger" mod, 2026-08-06). Turning this checkbox on forces
a full donor-replace on those parts too — confirmed working well on
several mods' Waist pieces, but also confirmed to pick the wrong donor on
one other mod's Arm piece and make things worse. That's why it's an
opt-in option rather than the default — always verify the result in-game
before trusting it.

**"Experimental: try to preserve custom parts the donor doesn't have"
checkbox**: off by default. If a mod adds its own RSZ component (e.g. a
`via.motion.Chain2` physics chain bundled directly onto a leg piece, plus
its own resource file), the default behavior (full donor-replace) deletes
that component entirely — a real, reported, confirmed issue from the
DOTEI modder. Turning this checkbox on keeps components the donor doesn't
have exactly as the mod shipped them, and only patches the CRC of shared
components that have gone stale. That said, "extra component the donor
doesn't have" isn't always something the modder added on purpose — the
same pattern has also been seen the other way around (Mangie "Banshee"'s
Arm piece carried old structure Capcom had already removed, and the
existing behavior of discarding it — not preserving it — was the
in-game-verified correct outcome). There's no way to tell the two cases
apart from structure alone, which is why this is opt-in rather than
default — always verify the result in-game before trusting it.

**Development / command line**:
```
cd D:\MHWildsModFixer
python gui.py                              # GUI
python auto_fix.py "mod.zip"               # command line
```

## How the GUI works

1. Pick a mod archive → it's extracted automatically
2. The current game version's paks get indexed (a few seconds the first
   time only, instant afterward via cache)
3. **Diagnosis**: checks whether each of the mod's mdf2 files is actually
   structurally out of date. It doesn't just look at the version number in
   the file extension (`mdf2.45`) — it directly compares the real material
   structure (property count, texture slots, shader) against the current
   version, since Capcom has shipped internal structure changes under an
   unchanged extension number, so the number alone can't be trusted.
   - If everything's already current: reports "nothing to fix" and exits
     (produces no output)
   - If something's out of date: shows which files and why, and asks for
     confirmation before updating
4. On confirmation, the actual repair runs (see "How it works" below)
5. Pick a save folder and it's rezipped in the mod's original structure
   (including modinfo.ini). A completion message is shown.

While diagnosis/repair is running (a large texture-pack mod packaged as
its own `.pak` can have thousands of entries and take a while), the
screen shows a "Verifying — please don't close the program, this may
take a while" notice plus a percentage progress bar — earlier versions
just looked frozen during this stretch, which was confusing feedback.

## How it works

- **Pulls vanilla files directly out of the paks**: only reads the
  header/entry table of `re_chunk_000.pak` (+`patch_NNN.pak`) and
  `re_chunk_000.pak.sub_000.pak` (+its patches) — no full extraction, just
  seek + decrypt + decompress the one entry needed, even from a 40GB+
  file — by hashing the path with MurmurHash3. The format is ported
  directly from the open-source `REE.PAK.Tool` (Ekey) C# source, including
  RSA-based entry-table decryption, zstd decompression, and the
  chunked-resource streaming used by recent patches. The entry table is
  cached locally, keyed off the detected game folder.
- **Matches a mod's own file paths to the real game paths**: if a mod uses
  a fake slot code like `mh03` (injected by mod managers to avoid slot
  conflicts, not present in real vanilla), it's automatically substituted
  with the real vanilla code (`ch03`) to find the donor. The version
  number is brute-forced without knowing it in advance.
- **Reassembles material-by-material**: full-body custom mods often
  collapse several of vanilla's submesh materials down into fewer, so
  "same position in the same file" matching doesn't hold. Instead, each of
  the mod's own materials is matched by shader (mmtr): first within the
  same piece's own file, then borrowed from another piece in the same
  equipment set if the shader isn't found there. The matched donor
  material's own structure is kept as-is, with only its texture paths
  overwritten by the mod's, to assemble a brand-new mdf2 from scratch.
- Every assembled mdf2 is immediately re-parsed to self-verify its
  structure is valid.

## Rebuilding the exe (for distribution)

```
pip install -r requirements.txt
pyinstaller --noconfirm --onedir --windowed --name "MHWmodfixer" ^
    --add-data "tools/UnRAR.exe;tools" ^
    --add-data "tools/mdf2_filelist.txt;tools" ^
    --collect-all tkinterdnd2 ^
    --hidden-import pak_mod_fix ^
    --hidden-import whole_game_index ^
    gui.py
```
The result is a `dist\MHWmodfixer\` folder (`MHWmodfixer.exe` plus its
support files) — zip the whole folder for distribution. This used to be
`--onefile` (a single self-contained exe), but a single exe that
self-extracts into a temp folder at runtime is a much more common target
for antivirus false positives (the behavior itself resembles how some
malware droppers work) than a plain folder of files sitting next to the
exe; several real users hit exactly this with v0.3. `--onedir` avoids
that specific behavioral trigger. Either way, zip (stdlib) / 7z (py7zr,
pure Python) / rar (bundled UnRAR.exe, redistributable under RARLAB's
freeware license) extraction all happen inside the exe, so nothing needs
to be installed on the recipient's machine.

## Mods packaged as their own `.pak`

Some mods (especially weapon cosmetics) ship as a single standalone
`.pak` file instead of loose files under `natives/...` (e.g. "Summer
Fleet Weapons", "Wyvern Impact" weapons). That `.pak` turns out to be
exactly the same KPKA format the game's own paks use (just unencrypted,
unchunked), so the existing pak reader opens it directly. Since entries
inside it carry no filename (only a hash), two things are handled
differently:
- Which vanilla file an entry replaces is found **by matching the
  entry's hash directly against the current game's pak index, with no
  path guessing** — a match IS the exact correct vanilla donor,
  definitive enough that no mh↔ch-style heuristic is needed.
- The mdf2's internal version number (the `45` in `.mdf2.45`) also can't
  be read from a filename, so it's auto-detected by finding the candidate
  version whose parse-then-reserialize round-trips back to the exact
  original bytes (`mdf2.detect_numVersion`).
- When materials map 1:1 to a single donor file (the common case for
  most weapon mods), the donor file is **patched in place rather than
  reassembled from scratch** (`pak_mod_fix._rebuild_entry`) — only cases
  that genuinely need to splice together several equipment-set pieces
  (full-body armor mods) fall through to material-level reassembly
  (`mdf2_slice.assemble_mdf2`). See "Bugs found" below — several bugs on
  the reassembly path only ever showed up via real in-game testing, so
  in-place patching is now preferred whenever possible.
- Every other entry besides the fixed mdf2(s) **reuses its original
  compressed bytes verbatim** (compression scheme untouched), keeping the
  original entry order, to write the new `.pak` (`pak_writer.py`).

### Bugs found (only ever showed up via real in-game testing — keep this in mind for the next one)

Fixing one weapon mod (Wyvern Impact) produced a black screen at the
game's title menu. Every structural self-check (parse/reserialize
round-trip, field-by-field comparison against the donor) passed, yet it
was still broken in-game — **"does my own parser find this internally
consistent" is not the same guarantee as "does the real game accept
it."** The actual causes, found one at a time:

1. **`sizeOfFloatStr` (the property data block size) wasn't padded to a
   16-byte boundary.** Real files round this field up to a multiple of
   16, but the reassembly code computed only the exact bytes needed,
   coming up about 8 bytes short. (A real bug, but — as it turned out —
   not the actual cause of this particular black screen.)
2. **Pak entry checksums were being genuinely computed.** The official
   formula (xxHash-based) from REE.Packer's documentation was ported
   faithfully, but real mod files all just use checksum=0 (never
   computed). A "plausible but wrong" value turned out to be more
   dangerous than a plain zero.
3. **gpbf (GPU buffer name reference) offsets weren't tracked at all.**
   `mdf2.py` neither parsed gpbf entries nor included them in its offset
   list, so when editing a texture path changed a string's length, the
   gpbf name string's position downstream didn't shift with it and was
   left stale. Re-parsing the file itself doesn't catch this (it just
   reads the same wrong offset again) — only comparing against the real
   donor exposes it.
4. **(The actual cause) the pak container's own compression scheme and
   entry order.** Even after fixing all three of the above, the black
   screen persisted, so a **"passthrough" test — repacking the original
   11 entries with zero content changes, just recompressing them as-is —
   was built to check**, and it ALSO produced a black screen, confirming
   the bug had nothing to do with mdf2 content and was purely a
   container-level issue. A precise byte-for-byte diff against the
   original found:
   - The original entries were **stored uncompressed**, while the
     reassembly code was force-recompressing everything with zstd (the
     decompressed content was identical, but this alone was the problem)
   - The original entry order was **not sorted by hash**, while the
     reassembly code always re-sorted entries by hash before writing

   Fixing both of these (preserving the original compression AND the
   original order) is what actually resolved it.

**Lesson**: round-tripping through your own parser and matching the real
donor field-by-field only proves "internally consistent with the format
rules I understood" — it does not guarantee "matches how the real game
actually reads it." When a suspected content-level fix doesn't work,
building a **zero-change passthrough reassembly** to cleanly separate
"content problem" from "container/format problem" is much faster than
continuing to hypothesize about content.

### A long-hidden bug in `mdf2_slice.assemble_mdf2` itself (from-scratch reassembly)

Separately from the pak-container bugs above, real issues found in cases
that genuinely require reassembling from scratch via `assemble_mdf2`
(full-body armor mods borrowing materials from other pieces in the same
equipment set, or a weapon that needs to borrow a shader donor from
anywhere in the whole game):

- **The header's "reserved" u64 field (offset 8) was always written as
  0.** `mdf2.py`'s parser never even read this field, just skipped past
  it, so it looked like genuine padding — but every real file checked (1
  material or many) stores **1** there. Writing 0 makes the game treat
  the file as invalid and silently ignore it, falling back to plain
  vanilla — no crash, no black screen, just **the mod appearing to have
  no effect at all** (a different symptom than the usual "invisible
  weapon" signature of a genuinely broken file), which made it
  particularly hard to notice.
- In-place patching (writing the donor file's bytes as-is and only
  editing strings) never touches this header, so it was unaffected by
  this bug — simple 1:1-within-the-same-file cases (most single-mdf2
  weapon mods) were fine, and this bug only ever showed up **when
  several sources genuinely needed to be spliced together**.
- Found as a separate issue while picking a whole-game shader donor: the
  candidates' **category (item vs. character, etc.) wasn't considered at
  all**, just picking whichever appeared first in the list — a weapon
  sometimes ended up borrowing a character asset (this overlapped with
  and compounded the bug above in the same case). Fixed to prefer donors
  in the same category (`slot_merge._category`).
- **Material names were carried over verbatim from the donor.**
  `apply_texture_overrides` built each new material via
  `copy.deepcopy(donor_mat)`, which also kept the donor's own `name` —
  but Capcom reuses generic names like "lambert2"/"lambert1" across many
  unrelated files. One weapon (Rocket Hammer) had 10 materials each
  splicing in a different shader (each pulling textures from a different
  source file), yet all 10 ended up sharing the donor's own "lambert2"
  name, giving every material in the assembled file an identical
  name_hash. Just like the reserved-field bug, this produced no crash and
  no black screen — just **the mod appearing to have no effect at all**
  (plain vanilla). Comparing against a community Blender fix that
  actually worked confirmed the working version kept each material's own
  unique name, just like the source mod (`lambert2, lambert31~39`).
  Fixed by keeping the MOD's own name rather than the donor's:
  `apply_texture_overrides` now sets `new_mat["name"] = mod_mat["name"]`.

**Important**: both the "reserved=1" bug and the "material name
collision" bug affected every case that used `assemble_mdf2` (i.e. every
case that genuinely needed splicing), so **any output built before these
two fixes that needed reassembly (e.g. a full-body armor mod like
Banshee that spliced together several equipment-set pieces) should be
rebuilt** — those passed structural validation at the time but were
never actually confirmed in-game, and were very likely silently ignored
by the game in exactly the same way.

## Whole-game donor search (last resort)

Some weapon mods have 10+ materials in a single piece, where only one of
them uses a different shader from the rest (e.g. "Rocket Hammer" — 9
rocket-exhaust/effect materials share one shader, and 1 uses a different
one). Weapons like this have no equipment-set concept (no multiple piece
files like armor has), so if no donor can be found within the same
file/set, there's genuinely nowhere else to look within that scope.

As a **last resort**, the whole game is searched in that case: every
current-version file listed in `tools/mdf2_filelist.txt` (mdf2 paths
extracted from a community-maintained file list, 9,939 of them) is read
and indexed by shader (mmtr) (once, on demand, cached until the game
folder changes — about 20–30 seconds the first time). A donor found this
way is less certain than one found within the same file/set (picked out
of dozens to hundreds of candidates), but the same safety principle
still applies — only the texture paths are overwritten with the mod's
own, everything else is left as the donor's — so it stays safe; the one
caveat is that shader parameters the mod may have customized (tint,
etc.) could end up at the donor's own defaults rather than the mod's
intended values.

## Limitations

- Only texture-path overrides are restored. If a mod directly customized
  shader parameters (color tint, etc.), that value isn't carried over —
  the donor's own default is used instead.
- If no donor with a matching shader can be found anywhere (same file,
  same equipment set, or whole game), that file is skipped.
- The whole-game search only covers paths present in the bundled file
  list (`tools/mdf2_filelist.txt`) — a genuinely new path not in that
  list won't be found.
- Entries under per-resource encryption (ResourceCipher, used by some
  DLC-exclusive content) aren't supported (essentially never encountered
  in ordinary character/armor mdf2 files).

## File layout

- `gui.py` — GUI entry point (tkinter + tkinterdnd2 drag-and-drop)
- `pak_reader.py` — RE Engine `.pak` reader (header/RSA decryption/zstd/chunk streaming)
- `pak_writer.py` — simple (unencrypted) KPKA pak writer (for reassembling `.pak`-packaged mods)
- `xxhash_re.py` — xxHash32/64 port used for pak entry checksums
- `game_archive.py` — layer that merges multiple paks so the current version of any file can be read directly; includes local caching, version-number brute-forcing, and direct hash lookup (`read_by_hash`)
- `archive_extract.py` — zip (stdlib) / 7z (py7zr) / rar (bundled UnRAR.exe) extraction
- `mdf2.py` — MDF2 binary parser + in-place texture-path patching + version-number brute-force detection when there's no filename (`detect_numVersion`)
- `mdf2_slice.py` — per-material extraction/reassembly (building a new file from scratch)
- `donor.py` — custom-slot path substitution heuristic (mh↔ch etc., loose files only)
- `slot_merge.py` — shader (mmtr)-based donor material matching (expands from same file → same equipment set → whole game)
- `whole_game_index.py` — the last-resort whole-game shader index (lazily built + cached)
- `auto_fix.py` — core diagnose+repair logic and CLI (`plan_mod`/`process_mod`, loose-file handling)
- `pak_mod_fix.py` — handling specific to mods packaged as their own `.pak` (direct hash matching + reassembly)
- `diagnose.py` — the "is there anything to fix" diagnosis the GUI uses (reuses auto_fix's `plan_mod`)
- `tools/UnRAR.exe` — bundled RAR extraction tool
- `test_*.py` — test/regression scripts verified against real game files (for reference)
