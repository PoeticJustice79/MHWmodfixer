# MHWmodfixer by Littlefish (PoeticJustice79) — project notes for Claude Code

This file is read automatically by Claude Code when you open this folder.
It exists so that **any user** who hits a mod that MHWmodfixer can't fix
can ask Claude Code, in this folder, to help troubleshoot further — you
don't need the original developer around. Everything below is distilled
from real, hands-on debugging sessions (hours of real in-game testing per
bug), not guesswork. Read this whole file before diagnosing a new issue;
it will save you from re-deriving things the hard way.

## What this tool does

A Windows GUI (`gui.py`, packaged as `dist/MHWmodfixer.exe`) that repairs
Monster Hunter Wilds cosmetic mods broken by official game updates. It
extracts a mod archive, reads the **current installed game version's**
real assets directly out of the live `re_chunk_000.pak` (+patches) /
`sub_000.pak` (+patches), diagnoses which `.mdf2` (material) and `.pfb`
(prefab) files are structurally stale relative to the current game, and
rebuilds only those — never touching files that already match.

**Why mods break**: Capcom can change internal `.mdf2`/`.pfb` structure
(prop counts, texture slots, RSZ component lists, shader variants) under
an *unchanged* file extension version number. A mod's own copy of these
files silently falls out of sync with what the current game expects, and
the game's loader rejects or misapplies the mismatched file — usually
with **no crash and no informative in-game error**, just a wrong or
missing visual.

## Architecture (see README.md for full detail)

- `mdf2.py` — MDF2 material-file parser/writer, in-place texture-path editing.
- `mdf2_slice.py` — extract a single material as a dict; `assemble_mdf2()` rebuilds a file from a list of them (from-scratch splice path).
- `pak_reader.py` / `pak_writer.py` — KPKA pak archive read/write.
- `game_archive.py` — `GameArchive`: reads the CURRENT installed game version's paks, with `find_versioned()`/`read_path()`/`has_hash()`.
- `donor.py` — `candidate_donor_paths()`: custom-slot fake-character-code (e.g. `mh03` standing in for real `ch03`) path substitution.
- `slot_merge.py` — donor-material resolution cascade (own-file exact name → own-file shader match → cross-piece → whole-game), with exact-name preference and shader-variant-suffix tolerance (see below).
- `whole_game_index.py` — indexes ~9,939 known mdf2 files' current shaders for last-resort donor search.
- `auto_fix.py` — main orchestration: `apply_texture_overrides()` (texture+prop carry-over), `process_mod()` (the real entry point both CLI and GUI call).
- `pak_mod_fix.py` — handles mods packaged as their own standalone `.pak`.
- `pfb_fix.py` — `.pfb` (RE Engine "RSZ" prefab) repair: donor lookup + wholesale replace, with or without custom-slot substitution.
- `fluffy_repackage.py` — auto-restructures a single-folder mod into Fluffy Mod Manager's multi-page convention when needed.
- `i18n.py` — GUI chrome localization (ko/en/zh_tw/zh_cn/ja); the detailed processing log is NOT localized, on purpose.
- `diagnose.py` — read-only "what's stale" pass shared by the GUI's confirmation dialog and the real fixer, so they can never disagree.

## Core debugging methodology

These are the load-bearing lessons. If a new mod is "still broken" after
MHWmodfixer runs on it, work through these **in order**:

### 1. Verify the baseline before chasing the tool

Before assuming MHWmodfixer's logic is wrong:
- **Is the input file actually the complete, correct original?** A
  flattened/re-packaged/partial copy of a mod can look "broken" for
  reasons that have nothing to do with repair logic. If in doubt, ask the
  user to point at the exact file they downloaded, or compare against
  another known copy.
- **Does the SAME symptom happen with the mod completely removed (vanilla
  state)?** Several real "mod is broken" reports across this project
  turned out to be pre-existing base-game issues (a specific weapon
  growth-stage appearance that renders as a broken magenta placeholder
  even with zero mods installed) — completely out of scope, not fixable
  by this tool. Always ask the user to check vanilla before spending real
  effort on a symptom.
- **If the symptom only appears at boot (game hangs/crashes loading a
  save into the world) but a content-level check says the fix is clean
  (REFramework `FaultyFileDetector` shows 0 faulty files, structural RSZ
  diffing shows no issue), suspect the SAVE FILE, not the fix.** Confirmed
  real case (Mangie "Snow Trigger"): the game hard-hung at ~80% of the
  title→in-game loading transition with this mod equipped, in every
  tested state — raw/broken, partially fixed, and a fully-fixed 0-error
  build — which looked exactly like a fresh content bug. The breakthrough:
  testing the SAME fully-fixed build via a live, already-running equip
  path instead of a fresh boot (MHWilds' in-game Layered Armor menu, for
  an armor mod) rendered it perfectly, no hang, no invisibility. Root
  cause: the save file's own equipped-loadout record still pointed at the
  OLD pre-fix (broken) content, and resolving that stale reference during
  the synchronous boot-time equipment-init step is what hung — the exact
  same current content loaded live had no such problem. **Fix is a
  save-state cycle, not a code change**: with the game already running
  and the fixed mod active, equip something else via the live path and
  save (to overwrite the stale record), confirm normal boot afterward,
  then re-equip the fixed content via the live path and save again.
  **Takeaway**: don't keep hunting for a content bug once a fix already
  passes every content-level check you have — try reproducing the SAME
  fixed build through a live/already-running equip path before concluding
  the fix itself is wrong. A stale save-file reference to the pre-fix
  state can reproduce the exact original symptom against genuinely
  correct content.

### 2. If a `.mdf2` (material) file is fixed but still looks wrong

- **Checkerboard/missing-texture look**: a texture PATH string doesn't
  resolve to a real file in the current game. Check with
  `GameArchive.read_path()` on the exact path stored in the material.
- **Solid black or wildly wrong colors/pattern, but textures otherwise
  correct**: almost always a **prop cross-contamination** issue — the
  donor material shares the mod's exact shader (mmtr) but is a
  semantically different object (e.g. a leg accessory's material reused
  for an arm-sleeve material). Props encode per-instance tuning (color,
  tiling, blend weights), not just shader structure. `apply_texture_overrides()`
  in `auto_fix.py` already carries mod's own prop values over by name —
  if this is still happening, check whether the donor-matching itself
  picked the wrong donor (see #3).
- **"Mod not reflected at all", vanilla look, no error**: check the
  output file's header `reserved` field (must be `1`, `mdf2_slice.py`'s
  `assemble_mdf2()` already writes this) and material name uniqueness
  (Capcom reuses generic names like `lambert2` across unrelated files;
  spliced materials must each keep the MOD's own name, not the donor's —
  `apply_texture_overrides()` already does this).

### 3. If donor-matching picked the wrong material

`slot_merge.py`'s `_pick_best()` already:
- Prefers an **exact name match** in the candidate pool before falling
  back to category/`_usesc`-suffix heuristics (fixes many-materials-
  collapsing-onto-one-arbitrary-donor when they only share a generic
  shader).
- Tries **known shader-variant spellings** via `_mmtr_variants()` (e.g.
  Capcom periodically splits a `"_NoMultiBlend"` sibling out of an
  existing shader while a material's role is unchanged — strict mmtr
  string equality alone would make an otherwise-correct exact-name donor
  invisible). If you find ANOTHER such suffix pattern breaking donor
  matching, add it to `_MMTR_VARIANT_SUFFIX`/`_mmtr_variants()`.

If a donor still looks wrong, dump both the mod's own material and the
picked donor with `mdf2_slice.extract_material()` and compare `mmtr_path`,
prop names/values, and texture types directly — don't guess.

### 4. If a `.pfb` file is involved (REFramework shows `[Invalid file]`, black screen, or invisible/non-loading model)

**Do NOT trust type_id/crc validation against a downloaded type registry
(e.g. REasy's `rszmhwilds.json`) as a diagnostic** — confirmed
unreliable: a live, currently-working vanilla donor file can itself
"fail" that check. The registry snapshot doesn't reliably track the
exact shipped build.

**The reliable method** (already implemented in `pfb_fix.py`, use its
helpers `_parse_rsz()` / `_resource_strings()` directly for one-off
investigation):
1. Find the CURRENT vanilla donor for the same asset — same path
   directly, or via `donor.py`'s `candidate_donor_paths()` custom-slot
   substitution.
2. Diff the mod's RSZ instance table against the donor's as a **multiset**
   of `(type_id, crc)` pairs (NOT positional — positions shift when
   counts/ordering differ).
3. Diff the resource-string tables (paths/names in the header region
   before the `RSZ` magic). Ignore a lone leading `"@"` prefix difference
   (confirmed cosmetic/inconsistent, not meaningful).
4. If the mod's pfb is close to the donor (within `pfb_fix.py`'s
   `_MAX_STRING_DIFF` tolerance, after undoing any detected custom-slot
   substitution), it's safe to **replace the file wholesale with the
   donor's current bytes** — confirmed working in-game on multiple real
   mods, both armor (with `mh03`↔`ch03`-style substitution) and weapon
   (direct path, no substitution). `pfb_fix.py::resolve_and_fix_pfbs()`
   already does this automatically as part of `process_mod()`.
5. If the diff is large and doesn't reconcile, the pfb is left unresolved
   on purpose — guessing wrong here silently discards real customization.
   Investigate by hand (see below) rather than loosening the tolerance
   blindly.

**When a pfb is left unresolved, look up what the differing RSZ
instances actually ARE before deciding whether to force it anyway.**
This is a different use of `tools/rszmhwilds.json` than the "don't trust
it for pass/fail validity" warning above — that warning is about using
the registry to decide *whether* a file is valid; looking up a specific
`(type_id, crc)` pair's `name`/`parent` fields to understand *what
changed* is reliable and often immediately explains the diff:
```python
import json
registry = json.load(open(r"tools/rszmhwilds.json", encoding="utf-8"))
entry = registry.get(format(type_id, "x"))  # lowercase hex, no "0x"
print(entry["name"], entry["crc"] == format(crc, "x"))
```
Confirmed real case (Mangie "Forte"): a mod's own Arm pfb had
`via.render.ShellFurParam`/`via.render.ShellFurMesh` where the current
donor now has `via.motion.JointConstraintsLayer`/`via.motion.JointConstraints`
— the exact same "Capcom removed an old rendering technique's components"
pattern as the very first pfb bug found on this project. Once you can
name the components, "small diff, looks like a clean old-system→new-system
swap" is a good signal wholesale-replace is safe even though the mod's
resource strings alone made `_find_substitution` call it "doesn't
reconcile" (that string-level check can't see this — it was tripped by
an unrelated residual, see next point).

**Before concluding a forced/wholesale-replaced pfb produced a genuinely
wrong result (not just "still broken"), rule out two common test
confounds first, both confirmed to produce a convincing false negative**:
- **Stale mod source.** Re-diff the RSZ instance `(type_id, crc)` multiset
  using a freshly-downloaded copy of the mod. Confirmed real case: a
  stale copy showed 4 differing instances (2 real, 2 staleness noise from
  the mod predating the game update); the fresh copy showed only the 2
  real ones. Staleness can also make `_find_substitution`'s
  resource-string check report "doesn't reconcile" even when the
  *structural* RSZ diff is small and safe to force.
- **A Fluffy page (usually "Textures") not enabled during the test.**
  A checkerboard/dithered texture is the classic missing-texture signature
  and has nothing to do with the pfb fix — it means the mod's own texture
  files (often in a separate standalone `.pak` page) genuinely weren't
  loaded. Confirmed real case: forcing a pfb looked "wrong" (checkerboard
  coat) purely because Textures wasn't enabled in that specific test;
  redone with the same forced pfb and Textures enabled, it rendered
  correctly. See the Fluffy-deployment-verification point above for how
  to also rule out "wrong build was actually deployed" as a third
  confound in the same family.

**A safer "CRC-only" tier is tried before wholesale donor-replace.**
`pfb_fix.py`'s `_crc_only_fix()` handles a case wholesale donor-replace
structurally can't: sometimes a class's on-disk field layout hasn't
actually changed at all between game versions, but Capcom still bumped
the CRC the engine checks against its live type registry. A CRC is a
property of the CLASS (`type_id`), not of any one instance of it, so the
fix builds a `type_id -> current crc` map straight from the CURRENT
donor's own instance table, then walks the MOD's OWN instance table and
patches just the (up to) 4 stale CRC bytes of any instance whose type is
a known donor type with a mismatched value — in place, in the mod's own
bytes. Nothing else is ever touched: not a resource string, not one byte
of the RSZ data block, not the mod's own customization. This needs no
position/count/length matching (unlike an earlier version of this
function) — it only cares whether a type_id is shared between mod and
donor, so it naturally handles a mod whose instances got reordered, or
that has EXTRA instances the donor doesn't have at all.

That "extra instances" case is exactly where a second, opt-in-only half
of the same function kicks in (`preserve_extra` param / GUI checkbox
"실험적: 도너에 없는 커스텀 부품 보존 시도" / CLI
`--preserve-extra-pfb-components`, all off by default) — and it's opt-in
specifically because it's genuinely ambiguous, confirmed both ways with
real mods in the same investigation:
- Confirmed GOOD (real customization, wholesale-replace was silently
  destroying it): a Nexus commenter (`모리바2`, apparently the DOTEI mod
  author testing with this tool) reported that restoring a pfb where
  they'd added a `via.motion.Chain2` physics chain (with its own bundled
  `.chain2` resource) to a leg piece wiped the whole chain out. Verified
  directly against the reported mod (`DOTEI's EULA`, `[8.EULA] LEG PHYS
  HEAVY`/`LEG PHYS LITE`): the mod's own instance sequence is an exact
  match of the current donor's PLUS 3 extra trailing instances
  (`via.motion.ChildSecondary`, `ChainWind`, `Chain2`) — donor-replace
  was discarding them since its output used to just be the donor's own
  bytes wholesale. With `preserve_extra` on, the fix keeps the mod's own
  bytes (including those 3 instances untouched) and patches only 2 stale
  CRCs among the shared instances (`via.render.Mesh`, `app.MeshSetting`)
  — an 8-byte diff from the original file, chain physics fully intact.
- Confirmed BAD (would have been a silent regression from a build
  already verified working in-game): Mangie's "Banshee" Arm piece has
  the SAME shape of "extra" content — `via.render.ShellFurParam` /
  `ShellFurMesh` + the identical 3 chain-physics instances — but this
  Banshee build was the confirmed-working reference this whole session's
  earlier investigation was anchored on, and that confirmed-good build
  came from ordinary wholesale donor-replace, which DISCARDS those same
  5 instances. They're old vanilla structure Capcom has since simplified
  away, not something the modder deliberately added — structurally
  indistinguishable from DOTEI's genuinely-added Chain2 without deeper
  investigation this project doesn't have the tooling for (no RSZ
  field-data-block parser to check whether the two CRC-stale classes'
  actual field bytes are still layout-compatible with their new CRCs).

Because the two real cases look identical from instance-type structure
alone and produce opposite correct answers, `preserve_extra` stays off
by default (matching every prior mod's previously-verified behavior
exactly — confirmed via byte-diff against the `Fixed-v2` Banshee
reference after this split was added). When it IS turned on, always
verify the affected pieces in-game before trusting the result, same as
`force_unresolved`.

Both halves are tried FIRST, before the resource-string diff /
`_find_substitution()` path, inside `plan_pfb()`'s donor loop.
Deliberately not a general byte-accurate RSZ field walker (which could
migrate an ACTUALLY-reshaped class's field data too) — building that
needs a maintained snapshot of the PREVIOUS game version's field
layouts, which this project doesn't keep (it only ever reads the
CURRENTLY installed game). (Idea prompted by reviewing another community
open-source MHWilds mod fixer that does full field-level RSZ migration
against maintained layout snapshots — worth the general approach, but
that architecture trades away this project's "never goes stale, always
reads the live game" property; the CRC-only tier gets a slice of the
same benefit without that tradeoff. Implemented independently, in this
project's own existing `_parse_rsz()`/`PfbPlan` architecture, not ported
code.)

**Substitution must be selective for resource paths, but must cover the
WHOLE file, not just the pre-RSZ header** — two distinct bugs were found
here, in tension with each other, and both are now fixed in
`pfb_fix.py`'s `_apply_substitution()`:

- *Bug A (blind replace, path-unaware)*: when a custom-slot fake
  character code (`mh03`) is substituted back into a donor's bytes, do
  NOT blindly replace every occurrence of the real code (`ch03`)
  throughout the buffer. Confirmed real case: a donor pfb referenced a
  `.jcns` (joint-constraint) file that didn't exist when the mod was
  originally built, so the mod never bundled a custom-slot copy of it.
  Blind substitution turned `ch03_..._0011.jcns` into `mh03_..._0011.jcns`
  — a path with no corresponding file at all — producing a NEW "[Missing
  File]" error and an invisible character.
- *Bug B (scope-too-narrow regression from fixing Bug A)*: the fix for
  Bug A scoped the scan to `_resource_strings_with_offsets()`, which only
  covers the header/resource-table region **before** the `RSZ` magic.
  That's correct for actual resource-path strings, but a `.pfb`'s
  GameObjects also carry their own **Name field inline inside the RSZ
  instance data itself** — well past that boundary — and got silently
  skipped. Confirmed real case (Mangie's "MooMoo"/"Service Versa" armor
  mods, found via hours of byte-diffing a confirmed-working fixed mod
  against a freshly-rebuilt one that used the exact same donor and
  produced a file only 9 bytes different): the donor's copy of a
  GameObject was still named `"ch03_014_0002"` instead of the expected
  `"mh03_014_0002"`, and that alone made the GameObject — and everything
  under it, including the actual mesh renderer — fail some internal
  name-based lookup and render **fully invisible** (Arm/Body/Leg/Waist
  all showed this; Head/Helm pieces happened not to hit it, producing the
  distinctive "floating head, invisible body" symptom). Every
  resource-path reference in the same file was already correct, so this
  was invisible to every diagnostic that only looks at resource paths —
  including REFramework's `FaultyFileDetector`, which reported 0 faulty
  files the entire time.

The fix distinguishes the two cases by whether the matched string
contains `/`:
- **Path-like** (contains `/`): only substituted if a file matching the
  substituted path actually exists somewhere in the mod's own bundle
  (checked via `_mod_provided_file_keys()`, which strips each shipped
  file's trailing version number since resource strings never carry one)
  — otherwise left pointing at the real, always-present vanilla path.
  This preserves the Bug A fix.
- **Bare identifier** (no `/`, e.g. a GameObject's own Name field):
  always substituted unconditionally, no existence check needed — it
  can't produce a dangling file reference since it isn't a path at all.

This is a per-string, per-occurrence, in-place, whole-file scan now
(`_scan_utf16_strings()` over the entire buffer, offset-tracked), not
scoped to the pre-RSZ header and not a single buffer-wide
`bytes.replace()`. `_resource_strings_with_offsets()` (pre-RSZ-only) is
still used, unchanged, for the mod-vs-donor structural comparison in
`plan_pfb()`/`_find_substitution()` — that comparison is deliberately
scoped to avoid RSZ instance-data noise; only the actual substitution
pass needed to widen its scope.

**How this was actually found** — worth internalizing as a technique:
static analysis (resource-string diffs, RSZ object/instance counts, mdf2
material/prop diffs, mesh file headers) was exhausted first and found
*zero* difference between a working mod (Banshee) and two broken ones
(MooMoo, Service Versa) — because the bug wasn't in anything those
comparisons looked at. What actually cracked it: get a **known-working
fixed output** and a **freshly-rebuilt output using the identical current
code path**, and diff them **byte-for-byte** (`zip(bytes_a, bytes_b)`,
not just size/hash). A 2944-byte file differing in exactly 9 bytes
pointed straight at the one field that mattered. If you're stuck with
"every diagnostic says this should work but it doesn't," find or build a
confirmed-working reference output and byte-diff it directly against the
broken one — don't keep hypothesizing about content you haven't actually
compared.

**Known unsolved limitation**: some mods bundle a custom-named `.pfb`
under `Art/VFX/effectprovider/weapon/...` (e.g. `GS.pfb`) that doesn't
correspond to ANY real vanilla file path, for an optional ambient VFX
(e.g. a looping lightning glow). No donor to diff against, and nothing
found so far (not even the weapon's own equip-prefab) actually references
or triggers it — no crash, no REFramework `FaultyFileDetector` entry,
just silently inert. This suggests an RE Engine weapon-VFX lookup
mechanism this project hasn't figured out (possibly a runtime-constructed
path/hash, not a direct pfb resource reference). If you crack this,
please note the mechanism here for the next person. Untried next step:
REFramework's `DeveloperTools` menu has a log console — never got to
search it for load attempts of the orphan file's name.

### 5. When in-game test results don't add up, verify what Fluffy actually deployed

Fluffy Mod Manager loose-file-deploys directly into the game's own
`natives/...` tree (found at `<game dir>/natives/...`). Before trusting a
confusing/contradictory in-game test result, compare the hash of the
actually-deployed file on disk against what you expect it to be:
```python
open(r"<game dir>\natives\...\some_file.mdf2.45", "rb").read()  # hash this
```
Confirmed real case this session: after building several test zips in a
row and asking for retests, two of them had silently vanished from
Fluffy's `Mods` folder entirely (cause unconfirmed — possibly a user
cleanup, possibly Fluffy itself) between when they were built and when
"still broken" was reported. Comparing deployed-file hashes against each
candidate source zip settles instantly whether a report reflects the
build you think it does. Also: if two mod pages end up with identical or
near-identical display names in Fluffy's list (e.g. two different builds
both auto-titled "Banshee"), the user can enable the wrong one without
realizing it — give test builds an unmistakably different `NameAsBundle`
(e.g. prefix with `[TEST]`) before asking for a re-test.

### 6. General binary-format debugging technique: the passthrough test

If a plausible, verified content-level fix STILL doesn't resolve a
real-world failure (game hangs/crashes/renders wrong), stop hypothesizing
about content and build a **zero-change passthrough test**: rebuild the
container with your own writer while changing NOTHING semantically (or
better, pass raw bytes straight through), and test that. If the
passthrough ALSO fails, the bug is in the writer's container-level
mechanics (compression choice, entry ordering, header fields, alignment),
not any content edit — diff the passthrough's header/table byte-for-byte
against a known-good real file. This is exactly what found the pak
compression/ordering bug that was hanging the game at the title screen
after three other real (but not-the-actual-cause) bugs had already been
fixed.

**Related trap**: a field your own parser only ever skips (never reads
into anything) can still be validated by the real game engine — don't
assume "my reader ignores this, so its value can't matter." Diff every
header/fixed-layout byte a rebuild produces against a real file, not just
the fields your reader happens to expose. (Concretely: MDF2's header
`reserved` u64 field must be `1`; writing `0` — which looked like an inert
padding field — made the game silently reject the file.)

### 7. mdf2 parsing bugs found via an external bug report (2026-08-08)

A Nexus user (`pwtxr`) sent a detailed, independently-verified bug report
against `MHWmodfixer-v0.2.exe` (decompiled the PyInstaller bundle to test
it directly against the live game). Both findings were independently
re-verified against this project's own current source and the live
installed game before fixing -- every specific number in the report
(byte offsets, file paths, exact struct.error messages, the 830/12 nv=6
vs nv=1 split) checked out exactly. Worth remembering the general lesson
even though both are now fixed: **a well-argued external bug report with
concrete repro data is worth verifying independently against the live
game rather than trusting OR dismissing on sight** -- this one came with
enough evidence (a whole-game scan, exact crash messages) to confirm in
under 20 minutes.

- **`mdf2_slice.py`'s property "count" field only uses its low 16 bits.**
  `extract_material()` read the 4-byte `numParams`/`propOffs` header pair
  as a plain int and used it directly as a float-array length. Confirmed
  real case: `natives/stm/art/model/item/it12/00/0006/it1200_0006_0.mdf2.45`
  material `Liquid1`'s `Water_Scale` property stores `0x00010001`, not
  `1` -- the high 16 bits are an undocumented Capcom flag (observed value
  always `1`), and reading the whole field as the count made
  `unpack_from` try to read 65,537 floats from a buffer that only had
  room for 1, crashing with a `struct.error` on any pak-packaged mod that
  touches this donor material during diagnosis (`pak_mod_fix.py`'s
  `resolve_pak_files` -> `extract_material`). A whole-game scan of all
  9,939 known mdf2 files found this on exactly 7 properties across 6
  files (all confirmed still present as of this writing: `it1200_0006_0`,
  `ch05_011_0000` [a character file, so it'll keep recurring], and 4
  others -- see git history for the full list). Fixed by masking:
  `num_params = count_raw & 0xFFFF`, keeping `count_flags = count_raw >>
  16` in the extracted prop dict so `assemble_mdf2()` can write it back
  (`n_field = (len(values) & 0xFFFF) | (count_flags << 16)`) instead of
  silently zeroing it on every splice rebuild.
- **`detect_numVersion()`'s "first byte-identical round-trip wins"
  heuristic has real false positives.** The function's own prior
  docstring claimed a wrong version guess "essentially never round-trips
  by accident" -- false: a whole-game scan found **842 of 9,939** known
  mdf2 files round-trip byte-identically at a WRONG low version (830 at
  `nv=6`, 12 at `nv=1`) in addition to the correct `nv=30`/`45`, because
  the wrong version's layout makes the parser treat the real content as
  an untouched opaque tail -- every material comes back with an EMPTY
  `mmtr_path` and zero props/textures in that case, silently wrong rather
  than crashing (4 of the 12 `nv=1` files do additionally crash in
  `extract_material` with nonsensical giant buffer-size demands, since
  their real property data happens to get misread as an absurd count
  too). Since `range(1, 200)` tries low numbers first, the wrong version
  won every time it was possible. Fixed by rejecting any candidate where
  a material's `mmtr_path` comes back empty -- confirmed via the same
  whole-game scan that this alone correctly separates all 842 false
  positives from every genuine detection with zero new misses.
  **If you're re-deriving this from scratch**, `python -c` snippets
  against `GameArchive(...).read_path(...)` + `tools/mdf2_filelist.txt`
  (9,939 known paths) are enough to re-run either scan in a couple
  minutes -- no need to install anything the mod archive itself.

### 8. pak-packaged mods' own `.pfb`/`.user`/`.scn` entries were never touched at all (2026-08-08)

Confirmed real case: "SilverWolf" (Nexus 964), a mod packaged as its own
standalone `.pak` (see the "Mods packaged as their own `.pak`" section
below), rendered the character fully invisible with REFramework showing
`[Invalid file]` for a `.pfb` AND a `.user` (HairAdjustList) path.
Root cause: `pak_mod_fix.py::resolve_pak_files()` only ever recognized
entries whose magic was `MDF\0` (`if raw[:4] != b"MDF\x00": continue`) --
**any other entry bundled in a mod's own pak was silently skipped
entirely**, never diagnosed or fixed, regardless of how stale it was.
This is a completely different code path from loose-file pfb repair
(`pfb_fix.py`), which was already working correctly -- the gap was
specific to the own-pak case. Re-running the existing regression suite
after fixing this found a SECOND real mod already silently affected:
Mangie "MooMoo"'s `Alma.pak` piece also bundles a stale pfb that was
never being fixed.

First pass only added `PFB\0` recognition -- the user re-tested in-game
and the `.user` (`USR\0`) entry's `[Invalid file]` error was still there,
unsurprisingly, since it's a different magic entirely. Checked the
another community MHWilds mod-fixer reviewed earlier this session
(`C:\Users\User\Desktop\another community fixer\rsz_crc_fix.py`) and
confirmed it treats `.pfb`/`.user`/`.scn` identically -- all three are
RE Engine's RSZ-serialized formats (prefab / userdata / scene). This
project's own `pfb_fix.py::_parse_rsz()` finds the RSZ block by string
search (`data.find(b"RSZ")`) rather than a fixed per-format byte offset
(unlike that other tool, which needs a `{magic: offset}` lookup
table for this), so the exact same repair logic already worked
unmodified on the `.user` entry the moment entry-type detection was
widened to recognize it too -- confirmed directly (`_crc_only_fix()`
returned a valid patch for SilverWolf's `.user` entry on the first try).
`_RSZ_MAGICS = {PFB, USR, SCN}` now gates entry-type detection; `.scn`
is included pre-emptively (same format family, not yet confirmed bundled
in a real mod pak) since it cost nothing extra to support.

Fixed by extending `resolve_pak_files()` to recognize all three magics
and plan a fix via `PakRszEntryPlan`, reusing `pfb_fix.py`'s existing
helpers directly (`_parse_rsz`, `_crc_only_fix`, `_resource_strings`,
`_find_substitution`) rather than reimplementing parallel logic. One
real simplification versus the loose-file case: a pak entry's donor is
already found by an exact hash64 match (see this file's own docstring on
why that's unambiguous), so there's no mh<->ch custom-slot code to
substitute back into the donor's bytes at all -- whenever a wholesale
replace is warranted, the result is simply the donor's own current bytes
verbatim, no substitution step needed. `_find_substitution()` is still
reused for its "are these two string sets close enough" verdict, but any
substitution pair it proposes is just ignored (meaningless in a
hash-matched context).

Ships as core, default-on behavior (not a new checkbox) -- the user's
own call on this ("이건 기능 새로 선택 옵션으로 추가하는게 맞지 않을까?")
was to make it inherit the SAME safe-default / opt-in-experimental split
loose-file pfb repair already has, rather than invent a third toggle:
the always-safe CRC-only tier applies unconditionally, and the two
existing checkboxes (`force_unresolved_pfbs`, `preserve_extra_pfb_components`)
now also govern pak-bundled pfb entries, not just loose ones.

**Design note on `PakPlan.unresolved`**: deliberately kept mdf-only (does
NOT consider `rsz_entries`) -- this property gates whether
`auto_fix.py` attempts `write_fixed_pak()` AT ALL, and an unresolved pfb
entry must not block mdf fixes that already work fine on their own.
`write_fixed_pak()` already resolves each pfb entry fully independently
of every mdf entry and of every OTHER pfb entry (matching the same
per-file independence loose-file pfb/mdf2 repair already has) -- so an
unresolved pfb alongside fully-resolved mdf entries still gets the mdf
fixes written, with just that one pfb entry correctly left untouched.
`stats["pfb_unresolved"]` (and the sibling `pfb_*` stats) are the sum of
BOTH the loose-file and pak-bundled counts, under the same keys, since
conceptually they're the same thing -- a `.pfb` that needed fixing.

## Practical diagnostic workflow for a new broken mod

1. Ask for (or reproduce) the exact original mod archive and the exact
   symptom (screenshot + what growth-stage/appearance/option was active).
2. Run `python auto_fix.py "<mod archive>" --output <folder>` from this
   directory and read the log — it names every donor match and every
   warning (dropped textures/props, ambiguous matches, unresolved
   materials).
3. If the log looks clean but the in-game result is still wrong, use
   `mdf2_slice.py`/`pfb_fix.py`'s helper functions directly in a throwaway
   script to dump and compare the mod's material/prefab against the
   current live donor (`game_archive.GameArchive(<game dir>).find_versioned(...)`).
4. Ask the user to check REFramework's `FaultyFileDetector` and
   `LooseFileLoader` panels (Insert key opens the overlay) for the
   specific file path in question, and to test the vanilla (no-mod)
   baseline per rule #1 above.
5. When you find a new real bug, fix it in the source, verify against a
   real in-game test if at all possible (don't just trust self-consistency
   checks — see the passthrough-test lesson), and **update this file**
   with what you found so the next session doesn't have to rediscover it.

## Rebuilding the exe

See README.md's "Rebuilding the exe" section for the exact PyInstaller
command (must list every module that's only ever imported lazily inside a
function as `--hidden-import`, or PyInstaller's static analysis misses
it — `pak_mod_fix`, `whole_game_index`, `fluffy_repackage`, `pfb_fix` all
need this). Close any running `MHWmodfixer.exe` first — PyInstaller can't
overwrite a locked exe (the GUI now refuses a second simultaneous launch
via a Windows named mutex, but an already-running instance from a prior
session will still lock the file).

**`--onedir` + `--noupx`, not `--onefile` with UPX (changed in v0.3→v0.4).**
Real users hit Windows Defender false-positive detections on the v0.3
`--onefile` build (2026-08-07 Nexus reports) -- a single self-extracting
exe that unpacks itself into a temp folder at runtime behaviorally
resembles how some malware droppers work, which is a much more common
false-positive trigger than a plain folder of files. Switching to
`--onedir` alone wasn't enough, though -- **Nexus's own upload scanner
still auto-quarantined the onedir zip** (2026-08-08), which pointed at UPX:
PyInstaller compresses the exe with UPX by default, and UPX-packed
executables are themselves an extremely common false-positive trigger
(actual malware uses UPX constantly to obfuscate its payload), completely
independent of the onefile/onedir question. `--noupx` disables that.
`MHWmodfixer.spec` (tracked in the repo) already reflects both changes --
`--onedir`'s two-stage `EXE(..., exclude_binaries=True)` + `COLLECT(...)`
structure, and `upx=False` in both the `EXE()` and `COLLECT()` calls --
don't regenerate it back to a single-`EXE()` onefile spec or re-enable
upx. The distributable is `dist/MHWmodfixer/` (a folder), zipped whole for
Nexus, not a single `.exe`. **If a future build still gets flagged despite
both of these**, the next things to try, in order: (1) check whether
Nexus/Defender's specific complaint changed at all (screenshot the exact
detection name -- don't guess), (2) code-signing the exe (costs money,
not yet done), (3) submitting to Microsoft's file-submission portal as a
false positive (https://www.microsoft.com/en-us/wdsi/filesubmission --
requires a Microsoft account sign-in, was in progress as of this writing
but blocked on getting an exact Defender detection name from a reporting
user).

**PyInstaller's bootloader is now self-compiled locally, not the
precompiled one from PyPI (2026-08-09).** This is a real, officially-
documented mitigation -- PyInstaller's own docs
(`doc/bootloader-building.rst` in its source repo, also published at
https://pyinstaller.org/en/stable/bootloader-building.html) list "you
want to avoid anti-virus false positives that result from the
wide-spread use of pre-compiled bootloaders" as an explicit, named
reason to build it yourself. The mechanism: every user who `pip install`s
a given PyInstaller version gets the byte-identical, PyInstaller-team-
built bootloader stub -- AV vendors have signature-matched on that exact
shared binary (both because real malware has used it and because it's
so common), and every legitimate app built with it collaterally gets
flagged too. A locally-compiled bootloader has different bytes (different
compiler/environment) and isn't in anyone's signature database.

**How it was done, and how to redo it if this ever gets lost:**
1. Install a C++ compiler -- Visual Studio Build Tools, C++ workload only
   (not the full IDE): `winget install --id Microsoft.VisualStudio.2022.BuildTools
   -e --override "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools
   --includeRecommended"`. One-time, ~3.5GB.
2. `git clone --branch v<matching version> --depth 1
   https://github.com/pyinstaller/pyinstaller.git` (match whatever
   version is currently installed -- `pip show pyinstaller`).
3. `cd pyinstaller/bootloader && python ./waf all` -- per the docs, no
   need to run `vcvarsall.bat` first, waf finds MSVC on its own.
4. `cd .. && pip install .` -- reinstalls the SAME PyInstaller version,
   now bundling the just-built bootloader instead of the PyPI one.
5. Rebuild `MHWmodfixer.exe` as normal (`python -m PyInstaller
   MHWmodfixer.spec --noconfirm`) -- the build log's "Bootloader ..."
   line should point at the freshly-built one and say "Building because
   ...bootloader...runw.exe changed" the first time.

**This is a per-machine, per-Python-environment state, not something
tracked in git** -- there's no bootloader binary or build artifact
committed to this repo, only this note. **A plain `pip install
--upgrade pyinstaller` (or any fresh venv/machine) silently reverts to
the precompiled PyPI bootloader** with no warning -- if a future build
starts getting flagged again after such a command, redo the steps above
before assuming something else regressed.

Verified before shipping: full regression suite (SilverWolf fixed=1/24,
DoA fixed=4/208) unchanged: this only replaces the bootloader stub, not
any of this project's own logic. Also smoke-tested the rebuilt
`MHWmodfixer.exe` directly (launched, confirmed the main window renders
with the correct title, closed cleanly) since a from-scratch-compiled
bootloader is new, unverified-in-practice territory for this project.

**REVERSED the next day (2026-08-10): real evidence shows this made false
positives WORSE, not better -- do not redo this for local/CI builds.**
The "not yet confirmed" caveat above got its answer fast: comparing real
VirusTotal results across releases (the SAME zip-vs-zip comparison that
should have been done immediately after shipping, not after the fact) --
v0.3 and v0.4 (`--onedir --noupx`, STOCK PyPI bootloader): **0/66 and
0/65 vendors flagged, respectively** -- completely clean. v0.5 (identical
`--onedir --noupx`, but with this self-compiled bootloader added): **5/66
flagged, including WithSecure naming it outright `Trojan.TR/W64.Malware`**
-- a specific malware-family label, not a vague heuristic. The theory
("a locally-compiled bootloader isn't in anyone's signature database")
had a real, unconsidered flip side: a bootloader that ISN'T the extremely
common, widely-whitelisted-by-reputation official PyInstaller build is
also *unusual* -- and "unusual, non-standard compiled executable stub"
is itself exactly the kind of signal some heuristic engines (and
WithSecure's outright Trojan verdict suggests more than a heuristic)
treat as suspicious. Can't rule out that v0.4->v0.5's large feature
growth also contributed (this wasn't a clean single-variable A/B test),
but there's no evidence the bootloader swap helped anything, and real
evidence it may have actively hurt -- not worth the ongoing cost (a
whole VS Build Tools install + a per-machine, easily-silently-lost setup
step, see below) for a net-negative or at best net-zero result.

**Action taken**: reverted to the stock PyPI bootloader via `pip install
--upgrade --force-reinstall pyinstaller==<version>` (confirmed via the
bootloader file's size changing back). Do not recompile the bootloader
locally or in CI going forward -- if a future session is tempted to
redo this (the "how to redo it" steps were left below for historical
reference, not as a recommendation), re-read this reversal first. The
actual, real fix for AV false positives is code signing (see the
GitHub Actions / SignPath Foundation work started 2026-08-10, tracked
separately) -- `--onedir --noupx` alone (matching v0.3/v0.4, confirmed
clean) is the right baseline until signing is live.

**Historical steps (do not use, kept for reference only):**
1. Install a C++ compiler -- Visual Studio Build Tools, C++ workload only
   (not the full IDE): `winget install --id Microsoft.VisualStudio.2022.BuildTools
   -e --override "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools
   --includeRecommended"`. One-time, ~3.5GB.
2. `git clone --branch v<matching version> --depth 1
   https://github.com/pyinstaller/pyinstaller.git` (match whatever
   version is currently installed -- `pip show pyinstaller`).
3. `cd pyinstaller/bootloader && python ./waf all` -- per the docs, no
   need to run `vcvarsall.bat` first, waf finds MSVC on its own.
4. `cd .. && pip install .` -- reinstalls the SAME PyInstaller version,
   now bundling the just-built bootloader instead of the PyPI one.

## In progress: code signing via SignPath Foundation + a real CI build pipeline (started 2026-08-10)

Given the AV-false-positive saga above (onedir+noupx: real fix; UPX/onefile:
real fix; self-compiled bootloader: reverted, made things worse -- see
above), the conclusion reached with the user is that further packaging
tricks are a dead end and **code signing is the only remaining real
fix**. Researched paid options (Sectigo/Comodo OV certs, ~$215-226/yr,
individuals-without-a-company eligible; Azure Trusted Signing, ~$10/mo
but **individual-developer tier is US/Canada-residents-only, not usable
by this project's Korea-based maintainer**) before finding a free one:

**SignPath Foundation** (signpath.org) provides free code signing for
qualifying open-source projects. Eligibility, confirmed via their docs:
OSI-approved license (this repo is MIT -- already satisfies this),
already has release history (v0.3-v0.5 -- satisfies this), actively
maintained (satisfies this), and **the build must run through a
supported CI system (GitHub Actions/GitLab CI/Jenkins/Azure DevOps/
TeamCity) that submits artifacts to SignPath's pipeline** -- a plain
locally-built exe can't be submitted directly. One open question, not
yet resolved: their "no proprietary/non-OSS component" rule and whether
bundling `tools/UnRAR.exe` (RARLab freeware, not open-source itself)
inside the signed package is a problem -- needs asking SignPath
directly during application, not assumed either way.

**Status as of 2026-08-10, end of session:**
- `.github/workflows/build.yml` created: builds `MHWmodfixer.spec` on a
  pinned `windows-2022` runner (not `windows-latest`, so a future GitHub
  image bump can't silently change the "reproducible" build SignPath
  verifies against), triggered on `v*` tag push or manual
  `workflow_dispatch`. Packages `dist/MHWmodfixer` into a zip, uploads it
  as a build artifact, and attaches it to the GitHub Release when
  triggered by a tag push (`softprops/action-gh-release`) -- this
  automates the exact manual "move the v0.5 tag, rebuild the zip,
  `gh release upload --clobber`" sequence this session did by hand every
  single time. **Deliberately does NOT compile the bootloader from
  source** (see the reversal above) -- stock PyInstaller bootloader,
  matching the confirmed-clean v0.3/v0.4 baseline.
- **Update, same day, from a second machine (work PC, browser-only session,
  no local clone there)**: triggered `workflow_dispatch` manually via the
  GitHub web UI (Actions tab -> Build -> Run workflow) -- **Build #1
  (`fe88655`) succeeded, 1m7s total, produced the `MHWmodfixer-dist`
  artifact (25.3MB, `sha256:873324f5f658f3db4c3be8053cef8d69881d131a075d92c379ebc7bf3eb19c4b`,
  run id 31349622848)**. Confirms the workflow itself builds cleanly on a
  cold `windows-2022` runner with no local-environment assumptions baked
  in. One harmless annotation (GitHub's own Node.js 20 deprecation notice
  on `actions/checkout@v4`/`setup-python@v5`/`upload-artifact@v4` --
  infra-side, not this repo's problem).
- **Still not done, deliberately, from that same session**: did NOT
  download the artifact or run the exe -- the work PC this ran from is a
  company machine, and the user judged running an unverified freshly-built
  exe there too risky to do at work. **The actual smoke-test (download the
  zip, launch `MHWmodfixer.exe`, confirm the main window renders with the
  correct title, close cleanly) is still outstanding** and is the right
  next thing for a session running on the user's home PC to do -- the
  build artifact above is already sitting on GitHub, no need to re-trigger
  the workflow again first.
- The SignPath Foundation application has NOT been submitted yet either
  (requires the user's own account/identity, was intentionally left for
  the user to do rather than submitted on their behalf) -- no signing is
  live yet, `MHWmodfixer.exe` is still unsigned.
- **Next steps for a future session**: (1) **on a machine where it's fine
  to run a fresh unsigned exe** (i.e. not a work PC) -- download the
  `MHWmodfixer-dist` artifact from run 31349622848 (or trigger a fresh run
  if it's expired) and confirm the produced exe launches correctly (same
  smoke-test pattern used throughout this project -- launch, check window
  title, close cleanly), (2) help draft the actual SignPath application
  content if the user wants to submit it, (3) once/if approved, wire
  SignPath's actual signing step into `build.yml` (their docs cover the
  GitHub Actions integration specifically), (4) after a real signed build
  exists, re-run the VirusTotal comparison (same method used to catch
  the bootloader regression above) to confirm signing actually helped
  before declaring victory.

**Update, later the same day (2026-08-10): steps (1) and (2) done.** (1)
was effectively superseded by a stronger version of itself: a fresh clone
+ from-source build on the user's home PC (not the CI artifact from run
31349622848) launched cleanly on the first *fixed* attempt -- see #41 for
the real `backports.zstd` packaging bug this surfaced and fixed along the
way, which the untested CI artifact from that run would still have hit.
(2) was completed and submitted: filled out signpath.org/apply live
in-browser (via the Claude in Chrome extension, since the in-app browser
preview couldn't render the embedded form -- iframe content, invisible to
the accessibility tree, and screenshot compositing didn't work in that
surface). Objective/project fields (Project Name, Repository/Homepage/
Download URL, Tagline, Description, Reputation, Maintainer Type =
"Individual maintainer(s)", Build System = "GitHub Actions") were filled
in directly; personal-identity fields (name, email) and the reCAPTCHA/
consent checkboxes were deliberately left for the user to enter/click
themselves. Reputation field points at the project's own Nexus Mods
listing (`nexusmods.com/monsterhunterwilds/mods/4695`) plus GitHub
Releases. **The Download URL field's own stated requirement** ("this page
must mention that the project uses the SignPath Foundation for code
signing") **wasn't satisfied yet at the time of filling the form** -- fixed
by adding a short note to both `README.md` and `README.ko.md` (a new
paragraph right after the intro, before "## Running it") stating the
project has applied for SignPath Foundation signing, committed and pushed
before submitting so the Download URL (set to the repo's own homepage)
would actually satisfy the requirement when reviewed. **The form has no
dedicated field for disclosing a bundled non-OSS component** (the
`tools/UnRAR.exe` question flagged as unresolved above) -- raise it via
SignPath's own follow-up-questions process during review, not by trying
to force it into an unrelated field. **Submitted and confirmed** ("Form
submitted -- Thank you, we'll be in touch soon."). Steps (3) and (4)
remain blocked on SignPath's review outcome.

### 9. A crash from an unverified crc-only patch, and the RSZ snapshot pipeline built to stop it recurring (2026-08-08)

Right after item 8 shipped (pak-bundled pfb/user/scn repair, default-on),
a real user tested it on a real mod (SilverWolf, Nexus 964) and the game
**crashed on load** -- not the pre-existing "[Invalid file]" symptom the
feature was meant to fix, a strictly worse outcome. Root cause: the
existing `_crc_only_fix()` (pfb_fix.py) trusted a bare `type_id` match as
proof that patching just an instance's stale CRC was safe, but a CRC is
the engine's structure-version stamp -- a match only proves the version
check passes, not that the class's field LAYOUT is unchanged between the
version the mod was built for and the currently installed game. Confirmed
directly: SilverWolf's `.pfb` has an `app.CharacterEditRegion` instance
whose CRC really did change between versions, and reading its bytes under
the current field layout produces a `_MotionBank` "string length" of 257
(518 bytes) -- self-evidently garbage, proof the layout genuinely
reshaped, not just re-hashed.

**The fix**: `rsz_layout.py` (new) parses an instance's own bytes against
a real field-layout registry and only returns True ("fits") if they
consume to an exact byte count with clean alignment padding; `False`
means a proven mismatch, `None` means unverifiable (type missing from the
registry -- NOT the same as broken, since even known-good vanilla donor
files hit registry gaps). `_crc_only_fix()` gained a `require_fits`
param; `pak_mod_fix.py`'s `_plan_pak_rsz_entry()` passes `require_fits=True`
(the new, unverified pak-rsz path), while loose-file `plan_pfb()` still
doesn't (mature, independently-tested-in-game path, no crash evidence
there -- don't change its risk profile without a reason).

**The registry problem, and how it got solved without owning a real
dumper.** True field migration (rebuilding a reshaped instance's data,
not just refusing) needs the OLD registry the mod was built against AND
the current one -- this project has no way to generate an RSZ dumper
itself (that needs live memory-scanning of the running game, e.g. what
REasy Toolkit does). But another community tool on this same machine
(`another community fixer`, `C:\Users\User\Desktop\...`) ships exactly that
two-version pair, baked as `rszlayouts_MHWILDS.json.gz` ("current"/TU5-ish
+ "previous"/TU4). Cross-checked its "current" half's `via.render.Mesh`
crc against a real live donor file's actual crc -- exact match -- so it's
confirmed to describe the ACTUALLY installed game build, not a guess.
Separately discovered this project's own long-bundled `tools/rszmhwilds.json`
(100MB, gitignored, REasy-project dump) is itself TU4 -- one whole title
update behind -- confirmed the same way (its `via.render.Mesh` crc matches
their "previous" exactly). So both halves of a real migration pair
already existed on this machine; they just weren't married together or
shipped. **Full field migration (rebuilding a reshaped instance, not just
refusing) is still not implemented** -- SilverWolf's specific crc
(`app.CharacterEditRegion` @ `1077f96c`) matches NEITHER TU4 nor TU5, so
even the other tool's own `rsz_migrate.fits()` refuses this exact
file; migrating it would need a registry for a version older than
anything currently available anywhere on this machine. `fits_current_layout()`
correctly returns `False`/unresolved for it, which is the right answer
given what's available, not a gap to close by guessing.

**Why `fits()` beat guessing field-by-field.** Before settling on the
registry-driven approach, tried hand-patching just the one suspect field
(`_MotionBank`, assumed non-string) to see if the file would parse clean
-- it fixed that one instance but immediately exposed a SECOND, unrelated
mismatch further into the same file (`via.character.CollisionShapePreset`
reading a float bit-pattern as an implausible array count). Confirms this
mod's pfb is multiply-reshaped, not a single-field fluke, and that
manual field-type guessing is not a substitute for an actual registry --
it can look clean on one instance while still being wrong.

**Registry shipped as `tools/rsz_fields_mhwilds.json.gz`** (current, ~3MB
compressed) -- a trimmed/renamed copy of the borrowed snapshot's "current"
half, listed in `MHWmodfixer.spec`'s `datas` so it's bundled in the
onedir build (`_internal/tools/`, loaded via the same
`getattr(sys, "_MEIPASS", ...)` pattern as `tools/UnRAR.exe`). A sibling
`tools/rsz_fields_mhwilds_previous.json.gz` (TU4, ~1.9MB) is tracked in
the repo too but deliberately **not** in the PyInstaller `datas` list --
nothing at runtime reads a second registry yet, so shipping it in the exe
would just be dead weight; it exists purely as reference material for
whenever real migration gets built.

**Also ported from the other tool**: `write_fixed_pak()`
(pak_mod_fix.py) now re-reads the pak it just wrote and verifies the
entry count and hash set match the input before returning success,
matching `pak_patch.py`'s `fix_pak()` post-write check -- catches an
internal packing bug here instead of a user finding a broken pak in-game.
Deliberately did NOT port `mdf_fix.py`'s retired-shader-substitution
rebuild: it's off-by-default in the source tool too, and its own docs
record it having crashed a real mod once -- the same failure category
this session just spent hours root-causing, not something to import
mid-firefight.

**Snapshot maintenance going forward**: `tools/bake_rsz_snapshot.py` (new)
is the maintainer tool for this pipeline -- `bake` turns a fresh raw
rszmhwilds.json-style dump into the compact shipped format, `list` shows
every snapshot's label/game_update_date/source at a glance, `import`
installs a snapshot someone else shares (own format, raw dump, or the
other tool's two-version format) as current or previous. Every
snapshot carries a `_meta` block distinguishing `baked_at` (when this
project processed it) from `game_update_date` (when that title update
actually shipped -- TU5 was 2026-08-04) -- conflating the two would make
future snapshot provenance unreadable. **The rule that matters most**:
before overwriting `rsz_fields_mhwilds.json.gz` after a future title
update, `bake --rotate` (or `import ... --as previous` first) so today's
current survives as tomorrow's previous -- losing that is exactly the gap
that made SilverWolf's specific pfb unmigratable tonight. A freshly baked
or imported snapshot is **not** verified against the live game
automatically; cross-check a common type's crc (e.g. `via.render.Mesh`)
from a real donor file against the new snapshot by hand before trusting
a fix that relies on it, the same way this was done tonight.

**End-user access, not just maintainer CLI.** The user's own framing:
"게임이 업데이트되면 일단 기존 버전 스냅샷은 프로그램이 가지고 있을거고
새로운 스냅샷만 구우면 되는거지" (confirming the rotate model), then "GUI
상단에 설정 메뉴를 넣고 거기에 추가하는게 맞을것 같아", then "설정 >
개발자 옵션이라고 추가해주고 거기에 넣으면 되지" -- so the same
install/list functionality is also exposed as **Settings → Developer
Options → RSZ Snapshot...** in the GUI (`gui.py::_open_snapshot_dialog`),
letting any user install a snapshot someone shares (Nexus comments,
Discord, etc.) the moment it's baked, without waiting for a full new
MHWmodfixer release to close the post-update verification gap. Shares
the exact same functions as the CLI (`rsz_layout.list_snapshots()` /
`install_snapshot()`) -- moved there from `tools/bake_rsz_snapshot.py`
specifically so the GUI and CLI can't drift out of sync. Both shipped
snapshot files (`tools/rsz_fields_mhwilds.json.gz` AND
`..._previous.json.gz`) are now in `MHWmodfixer.spec`'s `datas` as of
this GUI addition -- previous is no longer maintainer-only reference
material once a user-facing "list what's installed" view exists.

**One-click fetch straight from the source, not just "import a shared
file."** User's next ask: "새로운 몬헌 업데이트가 진행되면 나는 어떻게
해야해? RSZ를 내가 굽고 싶은데", then, once a real source was confirmed,
"그래야지" -- wanting to bake a fresh registry themselves rather than
depend on someone else sharing one. Where this project's own
`tools/rszmhwilds.json` (the "previous"/TU4 snapshot) actually came from
had gone unrecorded; grepping this session's own transcript
(`C:\Users\User\.claude\projects\D--\91b1e6e3-....jsonl`, searched via
Grep/a small Python parser since the file is one JSON object per line and
plain grep truncates matches) turned up the answer: an earlier segment of
this same session used WebSearch/WebFetch/the GitHub API to locate it at
**github.com/seifhassine/REasy**, `resources/data/dumps/rszmhwilds.json`
-- confirmed by matching the exact byte count GitHub reported
(103,163,427) against the file already on disk. The user had not
downloaded it themselves.

Confirmed live again while building this (2026-08-08): the raw URL is
`https://raw.githubusercontent.com/seifhassine/REasy/master/resources/data/dumps/rszmhwilds.json`
-- **branch is `master`, not `main`** (checked via
`api.github.com/repos/seifhassine/REasy`'s `default_branch` field before
hardcoding anything; the `main` guess 404s). The file there was already
103,929,358 bytes, larger than this project's own bundled copy from 3
days earlier -- i.e. REasy's dump had already moved on, which is exactly
the gap this feature exists to close without a whole new MHWmodfixer
release.

`rsz_layout.fetch_latest_dump()` streams that URL to a temp file with a
progress callback (stdlib `urllib.request` only, no new dependency);
`verify_against_live_game()` sanity-checks a freshly installed "current"
snapshot by reading one specific real vanilla `.pfb`
(`SAMPLE_PFB_HASH = 0x93538AED5435EFA9`, a Slinger armor piece --
base-game content, not mod-specific, so it's present in any normal
install) and running it through `fits_current_layout()` -- reuses that
function as-is rather than adding new parsing code. **This can return
None (inconclusive) even for a perfectly good fetch**: a raw
`rszmhwilds.json` dump has no "confirmed fieldless" marker the way the
borrowed two-version snapshot does (see above), so
`_bake_raw_dump()`/`detect_and_convert()` treats every empty-fields type
as unverifiable -- confirmed by testing this exact path end-to-end, where
the sample pfb hit the SAME `via.render.StreamingMeshController` gap
found earlier tonight and returned None rather than True. That's an
honest "can't confirm," not a bug -- the GUI reports it as inconclusive,
not as a failure, and doesn't block the install either way (the old
current is already safely preserved as previous via the normal rotate
path).

GUI wiring (`gui.py::_open_snapshot_dialog`'s "Check GitHub for
update..." button): confirms with the user first (states the ~100MB size
and source up front), runs the download+install+verify in a background
thread (`threading.Thread`, matching the existing repair-worker pattern
in this file) with progress reported via `win.after(0, ...)` callbacks
rather than the main window's existing `_progress_queue` (the dialog is
a separate `Toplevel`, and its own small progress bar is simpler than
routing through machinery built for the main window). Mid-test, an
end-to-end run of this exact path (download real ~104MB file, install,
verify) was accidentally left installed as "current" and "previous" --
**caught by `git status` showing both tracked snapshot files modified**,
restored with `git checkout -- tools/rsz_fields_mhwilds*.json.gz` before
committing. Worth remembering: testing `install_snapshot()` against the
real tracked files, not a throwaway copy, is convenient but always needs
this exact check afterward.

**Fixed single "previous" slot replaced with an unlimited, dated
archive.** User's own reasoning: "스냅샷도 버전별로 계속 저장될 수
있게 해야할것 같아" ("snapshots should keep getting saved per version
too") -- correctly spotted that the original current/previous pair loses
anything more than one title update back, since every new rotation just
overwrites the single previous slot. That's fine for the CRC-only-fix
safety check (only ever reads "current"), but would block real field
migration across a gap wider than one update once that gets built --
migrating a mod stuck two versions behind would need the registry from
exactly that older version, and it wouldn't exist anymore.

`PREVIOUS_PATH` (a single file) became `ARCHIVE_DIR`
(`tools/rsz_archive/`, a directory) in `rsz_layout.py`. `install_snapshot(
as_role="current", rotate=True)` now calls `archive_current()` first,
which copies whatever's current into the archive under a name derived
from ITS OWN metadata (`<game_update_date-or-baked_at>_<label>.json.gz`,
collision-safe via `_unique_path()` appending `-2`/`-3`/...) rather than
a fixed filename -- so nothing is ever silently discarded, and `list`
shows the whole history, not just one slot back. `install_snapshot(
as_role="archive")` stashes a snapshot directly into the archive without
touching current at all, for saving something for possible future use
without activating it. The old `tools/rsz_fields_mhwilds_previous.json.gz`
(TU4) was migrated into this archive as its first entry
(`tools/rsz_archive/2026-08-08_TU4.json.gz`) and removed from git; a
first attempt at this migration produced an unusably long filename by
slugifying the ENTIRE label sentence verbatim -- fixed by re-running with
a short explicit `label="TU4"` instead of trusting the existing overly-
long descriptive label to double as a filename source.
`MHWmodfixer.spec` now globs `tools/rsz_archive/*.json.gz` into `datas`
instead of naming one fixed previous-file path, so the archive grows
across releases automatically as more gets added to it.

### 10. Loose `.mdf2` repair was all-or-nothing per file; now per-material (2026-08-08)

Real case: "Endfield LiJiyan" (`C:\Users\User\Desktop\Endfield_LiJiyan.7z`)
has one loose `.mdf2` with 9 materials. 7 (`body_01`, `cloth_01`,
`cloth_02`, `face_01`, `hair_01`, `iris_01`, `guanggao`) matched a donor
fine; 2 (`mb`, `mbface`) use `MaterialShader/Variation/Base_GOLD_Push.mmtr`,
which **zero vanilla `.mdf2` anywhere in the currently installed game
references** (confirmed: `LazyWholeGameIndex.find_by_mmtr(...)` returns
`[]`, vs. 310 for the common `Base_Equip.mmtr`) -- so there is no template
to verify or rebuild those two against, full stop, not a bug or a gap in
donor-search logic. This is the same "coverage decides success, not the
algorithm" limitation `another community fixer`'s own README documents for
its analogous material-template system.

Before this, `process_mod()` treated a `FilePlan` as all-or-nothing: `if
plan.unresolved: skip the WHOLE file`, so this mod's 7 perfectly fixable
materials never got touched just because 2 others had no donor anywhere.
User's framing when asked to fix what's possible anyway: "그래도 일단
가능한대로 복구해볼래?" -- changed `process_mod()`'s loose-`.mdf2` loop
to resolve per material: materials with a donor get rebuilt via the
existing `apply_texture_overrides()`; materials without one get their OWN
`mod_mat` dict (from `extract_material()`) passed into `assemble_mdf2()`
unchanged -- confirmed this is lossless and safe to do, since
`extract_material()`/`assemble_mdf2()` already round-trip arbitrary
materials this way elsewhere (building `global_pool`/`own_pool` from
donor files that later get spliced into OTHER mods' output). Verified
directly on this exact mod: output parses correctly, `mb`'s textures and
props are byte-content-identical before and after.

**A dependent bug this surfaced and fixed in the same pass**: `gui.py`'s
`_run_one()` computed `needs_fix = [p for p in all_plans if not
p.unresolved and p.needs_rebuild]` -- since `FilePlan.unresolved` is still
True for this mod (2 materials genuinely have no donor), `not
p.unresolved` was False, so this mod would never even reach
`process_mod()` at all; the GUI's own pre-check gate would have reported
"nothing could be safely auto-repaired" and returned early without ever
attempting the 7 fixable materials. Fixed by redefining
`FilePlan.needs_rebuild` to mean "at least one RESOLVED, stale material
exists" (independent of `unresolved`, which still means what it always
did: "at least one material has no donor," used for reporting), and
dropping the `not p.unresolved` condition from `needs_fix`'s filter.
Caught by directly checking `plan_mod()`'s output on this exact mod before
trusting the fix -- `unresolved=True, needs_rebuild=True` is now correctly
possible, where before it was a contradiction the old code couldn't
express (`needs_rebuild` was defined to be False whenever `unresolved`
was True).

New `stats["materials_left_unresolved"]` (in `process_mod()`'s return)
and `"partial fix"` log line distinguish this from a fully-clean fix, and
`gui.py` surfaces a dedicated hint (`msg_partial_materials_hint`) when
this happens in a batch run -- deliberately NOT the existing
`msg_unresolved_parts_hint`/force-fix suggestion, since that option only
helps a pfb whose structure didn't safely reconcile with a donor that
DOES exist; it does nothing for a material with zero candidate donors
anywhere in the game to force against.

### 11. `apply_texture_overrides()` was silently discarding a mod's own alpha/render-state flags (2026-08-08)

Real Nexus report (Kersiak, premium/41 kudos, 08 Aug 2026 6:07PM): "This
is removing the alpha layer from textures, even the vanilla ones, plus
the meshes that were 2sided-alpha now are no more, it means they will
look transparent from the inside (an example for both issues on the same
item is the death stench hood)." Took this seriously immediately rather
than assuming user error, given the specificity (a named item, a
specific rendering symptom) and the reporter's standing.

Root cause, confirmed directly: `apply_texture_overrides()` builds
`new_mat` as `copy.deepcopy(donor_mat)` and only ever overrides `name`,
`textures`, and `props` from the mod -- `shading_type` and
`alpha_flags_raw` (both captured per-material by `mdf2_slice.extract_material()`,
see that function) were left as whatever the DONOR had, unconditionally,
for every material this function ever touches. Verified on a real mod
("Endfield LiJiyan," the same one from #10): all 7 resolved materials had
mod `alpha_flags_raw = 9b000008` silently replaced with the donor's
`98000088`/`98000008` -- matching the reported symptom exactly (alpha/
two-sided render behavior is exactly what that flag controls).

This is architecturally the same mistake the function's own docstring
had already caught and fixed once for `props` ("Props are ALSO carried
over from the mod... encode PER-INSTANCE tuning, not just shader
structure") -- `shading_type`/`alpha_flags_raw` are the same kind of
author-set render tuning, not structural layout information (padding,
prop/texture counts) that genuinely needs to track the CURRENT mdf2
format across a game update. The function's own opening docstring line
("Only textures are ever taken from the mod; everything else... comes
from the donor untouched") had gone stale the moment props got the same
treatment, and nobody revisited shading_type/alpha_flags_raw when that
happened -- worth remembering: when one field in a "comes from the
donor" list gets reclassified as "actually per-instance, keep the mod's
value," audit the REST of that list for the same reasoning, don't treat
it as a one-off fix.

Fix: `new_mat["shading_type"] = mod_mat["shading_type"]` and
`new_mat["alpha_flags_raw"] = mod_mat["alpha_flags_raw"]`, added right
next to the existing `new_mat["name"] = mod_mat["name"]` line. Both
fields are fixed-size and present unconditionally per material
(confirmed in `mdf2_slice.py`: read/written outside any `isV2`-gated
block), so swapping the value carries no version-compatibility risk the
way a prop/texture COUNT mismatch would. Verified: re-ran the exact
Endfield case, all materials' `alpha_flags_raw` in the output now match
the mod's original input byte-for-byte; SilverWolf regression suite
unaffected.

This bug affected EVERY material this project has ever "fixed" via the
loose-mdf2 or pak-mdf2 path (both call the same `apply_texture_overrides()`)
since the feature existed -- not a one-mod edge case. Any previously
"fixed" mod a user is still using may be carrying the donor's
shading_type/alpha_flags instead of its own.

### 12. The SilverWolf crash's exact root cause was still live in LOOSE-file pfb repair (2026-08-08)

The `require_fits` safety gate from #9 was only ever added to
`pak_mod_fix.py`'s pak-bundled rsz path -- `pfb_fix.py::plan_pfb()`'s
`_crc_only_fix()` call (loose files) deliberately kept the old,
unverified behavior, on the stated reasoning "mature, independently-
tested-in-game path, no crash evidence there -- don't change its risk
profile without a reason." That reasoning held only until there WAS a
reason.

Real case, reported directly ("이거 복구했는데 두 모드다 외형 선택하면
게임 크래시생겨" -- both mods crash the game when the outfit is
selected): **Mangie Bunny Girl Suit** and **Mangie Harness**, both
already run through this project's own force-fix. Traced each piece's
resolution kind against the ORIGINAL (pre-fix) files the user separately
provided:

- Harness's Helm piece: `plan_pfb()` chose the CRC-only path
  (`crc_patch` set). Ran it through `rsz_layout.fits_current_layout()`
  retroactively -- **False**, a proven structural mismatch, the exact
  same signature as the SilverWolf pfb.
- Bunny Girl Suit's Body piece: same story -- CRC-only patch chosen,
  `fits_current_layout()` **False**.

Both mods reference REAL vanilla equipment paths directly (no custom-
slot trick), so this isn't an edge case specific to slot-substitution
mods either. The other 4 pieces in each mod resolved via ordinary/forced
substitution (wholesale donor replace), which doesn't have this failure
mode at all -- only the two that happened to land on the CRC-only branch
were affected, which is exactly why a "confirmed working on Waist
pieces, no crash evidence" track record for the FEATURE as a whole never
caught this: most pieces take a different path, and the dangerous one is
silent (no error, ships fine, fails only in-game).

**Fix**: added `require_fits=True` to `plan_pfb()`'s
`_crc_only_fix(...)` call, matching the pak-bundled path exactly.
Verified directly: re-planning both crash pieces with the fix in place,
both now fall through to the substitution path instead (Harness/Helm ->
forced substitution, Bunny Girl Suit/Body -> ordinary "close"
substitution) -- no regression on the SilverWolf suite.

**There is no longer a code path in this project that trusts a bare
type_id match for a CRC-only patch without registry verification** --
loose and pak-bundled pfb/user/scn repair now share the identical safety
gate. The "mature path, don't touch it" argument from #9 is retired; it
was survivorship bias from a feature whose failure mode is silent until
someone actually equips the broken piece in-game.

### 13. Substituted pfb pieces can end up with dangling chain2/jcns physics references (2026-08-08)

Real reports, working through a stack of custom-slot mods: Mangie
"Afterglow" (Helm) and Mangie "Forte" (Arm/coat, then confirmed on
Helm/Waist too) -- after `_apply_substitution()`'s normal donor_code ->
mod_code swap, the piece loads and textures correctly, but has **no
physics** (a coat that should sway sits rigid). Traced directly: the
CURRENT vanilla donor's own resource table references its chain2 (cloth/
fur sway) and jcns (joint constraints) rig under a **third character
code** -- not the donor's real code, not the mod's custom-slot code.
Confirmed via `game.find_versioned()`: e.g.
`ch02_017_0001.chain2` doesn't exist anywhere in the currently installed
game at all -- Capcom's own current vanilla piece has a dangling
reference. `_apply_substitution()`'s swap only touches occurrences of
`donor_code` (e.g. "ch03"), so a `ch02`-prefixed string passes through
completely untouched -- still dangling in the output, even though the
mod bundles its own working chain2/jcns file for the identical numbered
slot (`mh03_017_0001.chain2`) that nothing ends up pointing at.

**Fix**: new `_fix_dangling_physics_refs()`, run on the result right
after `_apply_substitution()`. For every chain2/jcns resource-path
string that survived untouched (doesn't contain the primary
`donor_code`): extract its own 4-char code via `_CODE_RE`, confirm via
`game.find_versioned()` that it's genuinely dangling (a reference that
still resolves is left alone -- same safety principle
`_apply_substitution()`'s own docstring already establishes for the
primary swap), then redirect it to the mod's own file **only if**
`mod_provided_keys` confirms the mod actually ships a same-suffix
replacement. Same-length in-place substitution stays safe here because
every RE Engine character code in this game is exactly 4 characters
(`_CODE_RE = [a-z]{2}\d{2}`) -- swapping `ch02` for `mh03` is
mechanically identical to the existing `donor_code`/`mod_code` swap, just
a second, independently-discovered code pair.

Verified directly on Forte: Arm/Helm/Waist (all forced-substitution
pieces) each had 1-2 dangling chain2 references, all correctly
redirected; the Arm piece's `.jcns` reference stayed dangling because
this specific mod doesn't ship a `.jcns` file for that slot at all (not
a regression -- there was never a working replacement available; this
matches pre-fix behavior for that one file, only chain2 physics is
recovered). No regression on the SilverWolf suite. This is very likely
NOT specific to these two mods -- any custom-slot mod whose forced/
substituted donor piece has this pattern in the CURRENT game build would
have hit the identical silent physics loss.

### 14. `_crc_only_fix()` couldn't tell "verified, zero changes needed" apart from "refused" -- silently discarded mod-only instances that needed no fixing at all (2026-08-08)

Immediately after #13's fix, still reported: Forte's Leg piece rendered
with **completely invisible legs**. Traced with the same rigor: Leg's own
pfb has 23 RSZ instances where its current donor has only 19 -- 4 mod-
only "extra" ones. `plan_pfb()` tries `_crc_only_fix()` first; that
function's `require_fits` check (added in #9) actually confirmed the
mod's OWN bytes parse EXACTLY under the current registry
(`fits_current_layout() == True`) with **zero CRC mismatches** among the
19 shared instance types -- meaning the file needs no patching
whatsoever and is already 100% valid, extras included. But
`_crc_only_fix()`'s last line was `return (bytes(result), has_extra) if
changed else None` -- when `changed == 0`, it returned bare `None`,
**indistinguishable to the caller from "refused, unsafe to trust."**
`plan_pfb()` then fell through to `_find_substitution()`'s wholesale
donor-replace, which silently dropped all 4 mod-only instances (the
donor doesn't have them) -- making the leg mesh disappear in-game despite
the file having needed exactly zero changes to already be correct.

**Fix, in two parts:**
1. `_crc_only_fix()` now returns `(bytes(result), has_extra)`
   unconditionally once its safety gates pass, even when `changed == 0` --
   a zero-byte-change result is trivially safe regardless (nothing is
   being written that wasn't already there), so there's no reason to
   collapse it into the same `None` as "verification failed." The
   downstream caller (`resolve_and_fix_pfbs`) already had its own
   `if result == mod_path.read_bytes(): stats["already_current"] += 1`
   check, so this one-line fix was enough to route an already-current
   file correctly without any other code change.
2. The `has_extra and not preserve_extra` refusal was moved to AFTER
   computing `changed`, and now only fires `if changed and has_extra and
   not preserve_extra`. The ambiguity that gate exists for (is an "extra"
   instance real customization or a stale leftover? -- see #`_crc_only_fix`'s
   own docstring) is only relevant when a patch is actually about to be
   WRITTEN; it says nothing about whether a file that needs **no** patch
   is safe to leave alone. Confirmed this matters: with only fix #1,
   Leg still needed `preserve_extra=True` (an opt-in the GUI doesn't
   default to) to resolve correctly; with fix #2 too, it resolves
   correctly with every option left at its default.

Verified: Leg now resolves via `crc_patch` (not substitution), byte-
identical to the mod's own original file, both with and without
`preserve_extra`. Separately discovered while re-testing this on the
user's freshly-fetched modder update ("망기가 수정한 최신 파일 가져왔어"):
Forte's Arm/Helm/Waist pieces -- which an OLDER copy of this same mod
needed force-substitution for -- now ALSO resolve as already-current
against this newer file, meaning the mod author had already fixed them
in their own latest release. Our tool correctly recognized that and left
them completely untouched instead of needlessly (and, per #13, riskily)
re-substituting something that didn't need it. No regression on
SilverWolf, Endfield, or DoA Raise the Sail.

### 15. `_fix_dangling_physics_refs()` widened to mesh/mdf2 and to the crc_patch path -- and a genuinely unfixable case found along the way (2026-08-08)

After #14, Forte's Waist/Body/Leg started resolving via `crc_patch`
("already current") instead of substitution -- which meant #13's fix
never ran on them at all (it was only ever wired into the
`_apply_substitution()` call site in `resolve_and_fix_pfbs()`). The user
then reported REFramework `[Missing file]` warnings at load for several
`ch02_017_*` paths, ending in `.jcns`, `.mesh`, and `.mdf2` -- the mod
still worked (the engine just skips an unresolvable optional sub-part),
but the warnings were new territory: `.mesh`/`.mdf2` weren't in
`_PHYSICS_EXTS` at all, and the crc_patch path had no fix hook regardless
of extension.

**Fix, two parts:**
1. `_PHYSICS_EXTS` widened from `(".chain2", ".jcns")` to add `".mesh"`
   and `".mdf2"` -- same dangling-third-code pattern, just on optional
   mesh/mdf2 variant sub-parts instead of physics rigs.
2. New `_dominant_code()`: the most-frequent `_CODE_RE` match across a
   pfb's own pre-RSZ resource strings. `_apply_substitution()`-resolved
   pieces have an actual `(donor_code, mod_code)` pair to hand
   `_fix_dangling_physics_refs()`; `crc_patch`-resolved pieces don't (no
   substitution happened at all), so `PfbPlan` now carries `self_code`
   (this function's result) for that path instead. `resolve_and_fix_pfbs()`
   runs the same fix on `plan.crc_patch` when `self_code` is set.

**Investigating Forte's specific report turned up something important**:
none of it was fixable. Scanning the mod's own Body/Leg/Waist pfb bytes
(full-file `_scan_utf16_strings`, not the narrower pre-RSZ
`_resource_strings` used for the mod-vs-donor diff -- these dangling
strings live past `rsz_off`, in the RSZ data block) found the exact
`ch02_017_...` paths reported. But cross-checking directly against
`game.find_versioned()`: **the CURRENT VANILLA donor pfb for this same
slot (`ch03_017_0005`, fetched fresh, unrelated to any mod) contains the
identical `ch02_017_0005_RS.jcns` / `_SC.jcns` / `_cloth.jcns` /
`.chain2` references verbatim**, and none of them resolve under `ch02`,
`ch03`, or the mod's own `mh03` custom-slot code anywhere in the
currently installed game. This is a bare Capcom-side leftover in the
game's own current data -- a genuinely unmodified ch03_017 piece would
show the identical REFramework warnings. There is no file anywhere for
`_fix_dangling_physics_refs()` to redirect to (its whole safety model
requires `mod_provided_keys` to confirm a real replacement exists), so
this specific report can't be resolved by this project at all, by design
-- redirecting to nothing would mean inventing a file reference out of
thin air, which is exactly the kind of guess this project's fixes have
always refused to make.

Separately checked whether another community tool (`another community fixer`,
reviewed earlier for #9-#12) has an equivalent: it doesn't, and
structurally can't -- `rsz_crc_fix.py`'s own docstring states resource
strings are "never touched" by design, and it has no character-code
substitution feature at all (its own `--substitute-retired` is a
same-shader-family swap, unrelated). It simply doesn't do the kind of
resource-path rewriting that creates or needs to fix this class of
problem, so this isn't a feature gap relative to it.

The widened fix itself is still real and kept -- verified no regression
on SilverWolf/Endfield/DoA -- it now covers the case where a
`crc_patch`-resolved piece has a dangling mesh/jcns/mdf2 reference AND
the mod genuinely ships a same-suffix replacement for that exact slot,
which just wasn't Forte's situation here.

### 16. `find_donor_for_material()`'s "exact name" tier silently downgraded materials to a narrower same-named vanilla sibling (2026-08-08)

Real report, worked through by comparing against another community tool
(`another community fixer`) on real user files: a Nexus user (해골올챙이)
reported that after running mods through this project's force-fix option,
"레다젤트 감마 FM 옷은 모든 물리가 굳었고" (all physics on one piece went
rigid) etc. Those exact mods weren't available to reproduce with, but
investigating a *different* real report the user brought in parallel
(DDDuck's Arkveld/ReyDau/AT-ReyDau "AIO" mods, Arca Live) surfaced a real,
separate, high-blast-radius bug while comparing this project's output
against the other tool's on the SAME files.

The other tool reported 3 of 4 test files "ALREADY-OK - nothing
outdated"; this project flagged every single material in those files
(52/45/42 materials) as stale and rebuilt them, dropping
`MultiBlend_ALBDMap`/`MultiBlend_NRMMap` texture slots and ~15 `Blend_*`
props (a paint-layer customization feature) from nearly every one.

**Root cause**: `slot_merge.py`'s `find_donor_for_material()` tier 1
("own-file exact name") trusted a same-named current-vanilla material as
the structural donor unconditionally, even when its mmtr differed from
the mod's own. Traced directly: Capcom split a `_NoMultiBlend` sibling out
of `MaterialShader/Variation/Base_Equip.mmtr` for these specific armor
pieces' current vanilla files -- keeping the material NAME the same, so
the exact-name tier matched it immediately -- while `Base_Equip.mmtr`
itself is still fully alive game-wide (confirmed via
`WholeGameIndex.find_by_mmtr()`: 310 materials currently use it). This
was true even of a **freshly downloaded, never-before-processed original**
mod file from the author (not just previously-"fixed" copies), ruling out
any prior tool's involvement -- the MultiBlend props are genuine, original
mod-author content.

`_structure_key()`'s own docstring already correctly identifies mmtr as
the thing that determines real structural compatibility, and
`slot_merge.py` already had `_mmtr_variants()`/`_NoMultiBlend`-awareness
for its cross-piece/whole-game fallback tiers -- but the "own-file exact
name" tier ran BEFORE any of that and returned unconditionally on a name
match, never considering whether the name-matched donor's mmtr was
actually the right one to trust structurally.

**Fix**: `find_donor_for_material()` now only takes the immediate
exact-name/exact-mmtr fast path when both agree. When a same-named donor
exists but its mmtr differs, it now first searches for a donor sharing
the mod's own EXACT mmtr (own-file, then cross-piece, then whole-game,
each via a plain `mmtr_path == own_mmtr` filter, not the variant-inclusive
list used by the lower tiers) before falling back to the narrower
same-name donor. This preserves the existing behavior for a genuinely
retired shader (no live match anywhere in the game -> falls through to
the same-name donor exactly as before) while fixing the common case where
the mod's own shader variant is still perfectly valid.

Verified directly: for a freshly downloaded Arkveld/ReyDau/AT-ReyDau
original, materials that had 178 props (needing a real update -- Capcom
added props to `Base_Equip.mmtr` itself since these mods were built) now
correctly rebuild against a same-mmtr donor (191 props, MultiBlend
preserved) instead of the narrower 176-prop `_NoMultiBlend` sibling --
real staleness still gets fixed, but the shader's still-supported
capability no longer gets discarded as a side effect. No regression on
SilverWolf/Endfield/DoA or the Forte pfb suite.

Not yet confirmed whether this is the actual root cause of the original
"물리가 굳었다" report (MultiBlend is a texture paint-layer feature, not an
obvious physics/joint mechanism) -- those specific mod files were never
obtained. But the blast radius here is real and independently significant:
any mod using a shader that later gained a `_NoMultiBlend`-style sibling
for its specific vanilla asset (this pattern is confirmed to already
recur across unrelated shader families per `_mmtr_variants()`'s own
docstring) would have silently lost that capability on every affected
material, for every mod ever processed by this tool before this fix.

### 17. RSZ instance splicing for `preserve_extra`'s substitution path: built, crashed 4 times for 4 different reasons, finally restricted to an evidence-based allowlist (2026-08-08/09)

Real reports: Mangie "Esthe" and "Mask Bikini" bundle their own chest
jiggle-physics RSZ instances that plain `_apply_substitution()` (wholesale
donor-replace) silently dropped, since that path only ever wrote the
donor's own bytes -- reported as "가슴 피직스가 죽어버린다" (chest physics
dies). `_crc_only_fix()`'s `preserve_extra` half already solved the
analogous problem for the CRC-only path (see item on `preserve_extra_pfb_components`
above); the substitution path had no equivalent at all. Built
`_splice_mod_extras()` to fill that gap: append any RSZ instance whose TYPE
the donor doesn't have at all onto the end of the substituted donor's own
instance table.

**This required reverse-engineering undocumented binary structure with no
real spec to check against, and every wrong guess only surfaced as a real
in-game crash, never as a static check failure.** Four consecutive deploys
crashed, each for a genuinely different reason, discovered strictly in this
order:

1. **PFB-level resource manifest** (`ResourceInfo` table, a flat dependency
   list separate from inline RSZ resource-path strings) not updated for a
   newly-referenced resource (Mask Bikini's spliced Chain2 pointed at its own
   `.chain2` file, which the donor's manifest never listed) -- crashed
   outright on an undeclared-but-referenced resource. Fixed with
   `_read_resource_strings()`/`_add_resource_manifest_entries()`.
2. **RSZ instance-index cross-reference fields** (Object-type fields, e.g.
   Chain2's own "EnvWind" field pointing at its ChainWind sibling BY INDEX)
   copied verbatim without remapping to the relocated instance's new index --
   "Heap allocation failed" in both mods. Fixed via a cross-verified
   Object-field registry (`rsz_layout._object_fields_registry()`,
   `tools/rsz_object_fields.json.gz`) built by cross-checking TWO independent
   RSZ dumps (this project's bundled compact registry vs. a freshly-fetched
   REasy dump) and only trusting a field's Object-type classification where
   both agree exactly on `(size, align, is_array)` at the same field index --
   the two dumps disagree on some types' field counts/shapes even at the same
   CRC vintage, so agreement-at-index is the only safe signal.
3. **The RSZ "Object Table"** (a separate array from the instance table,
   right after the 48-byte RSZ header, sized by `objectCount` -- NOT the same
   thing as "instances following the GameObject") never grown to match
   `componentCount` after it was incremented -- identical "Heap allocation
   failed" crash in BOTH mods again, including for extras with zero
   Object-reference fields, proving fix #2 wasn't the cause of this one.
   `componentCount` (PFB `GameObjectInfo`) counts Object Table entries
   belonging to the GameObject, confirmed against a real donor file
   (`componentCount=12` exactly matched `Object Table size(13) - 1`). Fixed
   by growing the Object Table (excluding instances that are themselves an
   Object-type reference TARGET, e.g. ChainWind, which the donor's own object
   table already excludes the same way) and incrementing `componentCount` by
   only the count of entries actually added to THAT table, not the total
   extra-instance count. **A one-line bug was found and fixed during this
   same pass**: the RSZ header's `objectCount` field write used the wrong
   byte offset (`rsz_off+4`, the `version` field) instead of `rsz_off+8` --
   the write silently corrupted `version` instead of growing the Object
   Table at all, discovered immediately by re-testing with direct
   verification (`fits_current_layout`, Object Table bounds check,
   componentCount-matches-added-count check) rather than trusting the code
   read-through.
4. **A genuine access violation** (`Exception occurred: c0000005`, NOT the
   previous "Heap allocation failed" engine assertion -- a different failure
   class), even with #1-#3 all independently verified correct
   (`fits_current_layout()==True`, every Object Table entry in-bounds,
   `componentCount` exactly matching added entries). REFramework's own crash
   log (`reframework_crash.dmp` companion `re2_framework_log.txt` in the game
   install folder, plus `reframework_faulty_files.txt` -- check these before
   asking for a screenshot next time a crash has no dialog) named
   `ace.ClothManagerBase<app.ClothSetting,app.ClothSettingCollection>...doUpdateClothSettingCollection`
   in the stack, but **this could not be trusted at face value**: neither
   `app.ClothSetting` nor `app.ClothSettingCollection` exist as an RSZ
   instance anywhere in either mod's own data, and every single native
   `MonsterHunterWilds.exe` frame in that stack resolved to the identical
   `Ordinal398` symbol -- proof REFramework's stack walker was guessing
   ("TDB" = heuristic nearest-known-VM-method label) rather than reporting a
   real symbolized stack this deep into JIT'd game code. Not reliable
   evidence of which system actually crashed.

**Because the crash log couldn't be trusted, root-caused this the only way
left: real in-game bisection**, not further static analysis. Built one test
variant per mod that spliced ONLY `via.render.ShellFurMesh`/`ShellFurParam`
(fur, purely visual, no physics simulation) and left everything else as
plain forced-substitution, and another that spliced ONLY the
`via.motion.Chain2`/`ChainWind`/`ChildSecondary` group (the actual physics
chain) the same way. Result, confirmed directly in-game:
- Fur-only splice: **crash-free in both mods** (two different pieces, two
  different mods -- Esthe's Helm and Mask Bikini's Arm).
- Chain-only splice: **crashes on game start** (Mask Bikini's Body+Leg).
- Separately, and importantly: **Esthe's chest physics turned out to already
  work with ZERO splicing at all** -- its donor piece already contains its
  own `via.motion.ChainWind`/`Chain2` natively (a pre-existing, unrelated
  vanilla chain), so ordinary forced substitution (this session's other
  fixes: dangling-physics-ref redirection, mmtr donor-priority fix, forced
  Waist substitution) was already sufficient. The splicing feature was never
  actually necessary for Esthe's reported bug at all.

**Given real, reproducible, twice-confirmed evidence that splicing
brand-new physics/chain instances onto a GameObject with zero prior
physics content crashes the game -- via TWO different failure mechanisms
across two attempts, with no further tooling available to inspect why
(no RSZ dumper, no debugger, and the one crash log available proved
unreliable) -- stopped trying to fix it further and instead scoped the
whole feature down to only what's been positively proven safe.**
`_splice_mod_extras()` now filters candidate extras through
`_SPLICE_SAFE_TYPE_NAMES = {"via.render.ShellFurMesh", "via.render.ShellFurParam"}`
-- an ALLOWLIST, not a denylist, on purpose: reasoning by analogy about
which OTHER types might also be safe (e.g. `via.motion.JointConstraints`/
`JointConstraintsLayer`, `ace.cDampingParam` -- all seen as real extras in
these same mods but never isolated in their own bisection test) is exactly
the kind of unverified guess that produced four straight crashes; only add
a type here after it's been isolated and confirmed crash-free in-game the
same way this pair was, never because it "seems similarly harmless." An
extra instance whose type isn't in the allowlist is silently dropped from
the splice (exactly like plain wholesale donor-replace already did before
this feature existed) rather than refusing the whole piece, so a mod with
both fur and chain extras still gets its fur preserved.

**Net outcome for the two real mods that started this investigation**:
Esthe ships fully fixed (working chest physics, needed no splicing after
all). Mask Bikini ships safe and crash-free but WITHOUT its bundled chest
physics -- genuinely not achievable by this tool with what's currently
knowable about the format. If a future session wants to revisit
chain-physics splicing specifically, don't restart from theory: get an
actual RSZ dumper/debugger (the kind REasy Toolkit uses, i.e. live
memory-scanning of the running game) capable of showing what per-GameObject
bookkeeping the engine's cloth/chain manager actually reads, since four
rounds of "fix what the last crash proved was missing" converged on
diminishing, no-longer-diagnosable returns rather than a working feature.
`tools/rsz_object_fields.json.gz` (Object-reference field registry) and the
Object Table growth logic in `_splice_mod_extras()` remain in place and
correct -- they were never the problem in attempt #4, and are exercised
correctly by the fur-only case that IS shipping.

### 18. A 6th attempt (`_transplant_reshaped()`, tier 2 of the crc-only path): the inverse of splicing, structurally sound, and STILL not safe -- a real, undiagnosed boot-time-only defect (2026-08-09)

After #17 shipped, the user pushed to keep thinking rather than accept
Mask Bikini losing its chest physics: "스플라이싱 제대로 완벽하게 구현하는
방법이 뭐가 더 있을지 조금만 더 고민해보고 안되면 포기해야겠다." Re-probing
both mods' pfbs found something #17's investigation never surfaced: across
8 of the 10 armor pieces in both mods (everything except each mod's most
structurally-diverged Waist), the ONLY instance that fails to parse under
the current registry is a single `app.ChainSetting` -- Capcom added a field
(`_WindAssetOverwrite`, a second variable-length string) without bumping
the class's crc, so the mod's 20-byte-old copy gets misread as a 27-byte
current one and rejects the whole file. Every other instance in those 8
pieces round-trips byte-identically already.

This is the exact INVERSE of splicing's direction: instead of grafting mod
content onto donor structure (5 real crashes across #17's attempts), keep
the mod's own file as ground truth -- Object Table, component order,
GameObjectInfo, resource manifest, Chain2/ChainWind/ChildSecondary all
stay byte-identical -- and replace ONLY the reshaped `app.ChainSetting`
instance's field data with the current donor's own values (verified safe
to donor-source: it's engine wind/update-flag plumbing, not mod
customization), plus the same stale-CRC patch tier 1 already does.
Implemented as `_transplant_reshaped()`, wired as tier 2 of the crc-only
path in `plan_pfb()` (tried after tier 1's `_crc_only_fix()` refuses,
before falling through to substitution), reusing `rsz_layout.walk_instances_with_recovery()`'s
new `recovered` return (the set of instance indices whose span came from a
resync, not a clean parse -- exactly the instances needing a donor
transplant) and the splicing saga's `_extract_instance_values()`/
`_write_instance_values()` pair. Verification deliberately does NOT reuse
`fits_current_layout()` (which also demands zero alignment padding) --
these mods' own untouched instances carry real nonzero padding bytes
Capcom's own writer left behind, accepted by the game for months; a
from-scratch strict re-walk to exactly `len(data)` is the actual proof
used instead. 8 of 10 pieces resolved this way, transplant-only, mod
structure 100% preserved, `_apply_substitution()` never touched.

**Confirmed via a genuinely independent third source that the byte-size
math is right, even though the field NAMES probably aren't**: cloned
`alphazolam/RE_RSZ` (a maintained 010 Editor template with its own
`rszmhwilds.json`) and found ITS `app.ChainSetting` entry has a completely
different field layout (`_WindAssetOverwrite` typed as a plain 4-byte
Resource reference, not a string; no `_MeshBoundary` field at all) --
but its declared crc (`89f3eaf6`) doesn't match the live game's actual
instance crc (`7fbd8f3f` on both mods' donor AND mod copies), so it's a
different game version, not directly usable. What IS usable: this
project's own registry parses the LIVE-crc donor's real 27-byte
`app.ChainSetting` instance to exactly 27 bytes with zero overrun/leftover
-- strong evidence the transplant's byte accounting is correct for the
crc that's actually installed, regardless of whether the field names are
exactly right. (Also checked `NSACloud/RE-Chain-Editor`: it edits the
EXTERNAL standalone `.chain2` resource FILE format, a completely separate
binary structure from the inline `via.motion.Chain2` RSZ component
involved here -- not applicable to this bug.)

**Shipped, then failed anyway -- but silently, and only at boot.** Built
delivery zips with `preserve_extra_pfb_components=True` for both mods.
Esthe: chest physics confirmed working in-game. Mask Bikini: chest physics
ALSO confirmed working live. Then: "esthe는 가슴이랑 다리가 사라짐" (Esthe
legs/chest vanish) and separately Mask Bikini went black-screen -- but
specifically **only when booting with that outfit as the saved loadout;
live-equipping the identical content after boot works perfectly every
time.** First assumed this was another instance of the save-state
mechanism from item #1 (a stale record pointing at old broken content,
the "Snow Trigger" pattern) and suggested the documented recovery cycle
(neutral outfit + save, reboot, THEN live-equip target + save). The user
did this exact cycle and it STILL black-screened on the next boot --
correctly pointing out that no legitimate content should ever require a
save dance to load, and that a genuinely fixed file can't need one.
That's the right call: item #1's mechanism is a stale reference to
OLD/broken content; here the save was freshly written from the CURRENT,
verified-correct build and still failed identically at boot every time,
which rules out staleness as the explanation.

**Isolated the true cause via bisection, since REFramework's own crash log
had NOTHING to show this time** (no exception, no dump, `reframework_faulty_files.txt`
unrelated) -- confirming this isn't a crash at all, a silent boot-time
load failure. Rebuilt Mask Bikini with the transplant applied to ONLY the
Body piece (the one piece that actually carries the chest-jiggle
Chain2/ChainWind/ChildSecondary) and every other piece on plain forced
substitution. **Still black-screened at boot.** This proves Body's own
transplant is independently sufficient to trigger it -- not an
interaction between multiple transplanted pieces, and (re-reading the
Esthe incident in this light) very likely the SAME underlying defect hit
Esthe too, not a save-file issue as first assumed; reverting Esthe to
plain substitution (which it never structurally needed in the first
place -- its donor already has native Chain2) coincidentally "fixed" it
by avoiding transplant entirely, not by breaking any stale-save cycle.

**Conclusion: `_transplant_reshaped()` has a real, currently undiagnosed
defect -- content it produces is structurally verified correct by every
static check available (exact byte-count re-walk, cross-checked against
two independent field registries, byte-identical to the mod's own
original structure) and loads correctly via live equip, but something
about how MHWilds constructs a GameObject during the synchronous
boot-time default-loadout path treats it differently and fails silently.**
No crash, no log entry, no faulty-file report -- nothing left to diagnose
further with tools available to this project. Both `_splice_mod_extras()`
(#17) and `_transplant_reshaped()` (#18) are now confirmed, by real
in-game testing, to have a failure mode specifically in
`app.ChainSetting`/chain-physics-adjacent content that neither approach's
static verification catches. **Both remain in the source** (their
non-Chain2 use -- e.g. `_transplant_reshaped()` on a piece whose reshaped
type isn't chain-adjacent -- is unverified either way, not disproven) but
`plan_pfb()`'s tier-2 call and `_splice_mod_extras()`'s call site are
gated behind `preserve_extra_pfb_components`, which stays off by default;
**do not enable it for a real delivery without a fresh in-game boot test
of that exact build**, live-equip alone is not sufficient evidence anymore.

**Independently re-verified against REasy Toolkit itself, 2026-08-09, after
the user pushed back on stopping** ("조금 더 안정적으로 확실하게 이 문제를
해결할 방법이 아예 없는걸까?"): cloned `seifhassine/REasy`'s
`file_handlers/rsz/rsz_file.py` (its core `RszFile` parser, PySide6-free
and usable as a plain library) and drove it directly against the SAME
already-downloaded, live-crc-confirmed `rszmhwilds.json` dump used earlier
in this session. Result: REasy's own independent parser hits the IDENTICAL
failure at the IDENTICAL byte offset trying to parse the mod's stale
`app.ChainSetting` under the current registry (`struct.error: unpack_from
requires a buffer of at least 2130707516 bytes...`) -- proving the parse
failure is a real property of the mod's stale bytes, not a bug in this
project's own registry or parser. More decisively: REasy's parse of the
DONOR's own ChainSetting instance produced field values (`_WindBias=1.0`,
`_CullingLengthBias=1.0`, matching the two `0x3f800000` float patterns
visible in the raw hex) that, when checked against this project's actual
shipped transplant output, are **byte-for-byte identical** --
`ni["data"][11's span]` vs `donor_info["data"][11's span]` compared
directly, exact match, not just structurally equivalent. This closes the
one remaining open question from earlier in this investigation ("is
this maybe just a bug in OUR OWN implementation that a real editor would
avoid?") -- a real, independently-maintained tool confirms the file
content this project produces is exactly correct. The boot-time failure
is conclusively NOT a file-correctness problem; whatever differs between
live-equip and boot-time loading happens somewhere this project has no
way to observe without a live debugger/ObjectExplorer session, not in the
bytes on disk.

Final shipped state for both mods: plain forced substitution only
(`preserve_extra_pfb_components=False`), matching the safest,
longest-verified code path in this project. Esthe: fully fixed, chest
physics intact (never needed the experimental path). Mask Bikini: safe
and stable, without its bundled chest physics -- confirmed not
achievable by either of this project's two independent attempts at
preserving/repairing that specific content, both of which produce
data that's provably correct by every static and live-equip test
available yet fails at boot for reasons this project has no tooling
left to diagnose. If a future session revisits this, the necessary next
step is the ObjectExplorer/EMV-Engine-Lua path outlined in this session's
own suggestion (inspect the live GameObject's actual component tree at
the moment of boot-time construction, compared against live-equip) --
static analysis of the file bytes alone, however careful, has been run
to the end of what it can prove.

**Further pushed on ("이거 외에는 아예 방법이 없는거야?"), and now conclusively
confirmed via a clean, controlled real-mod test -- `_transplant_reshaped()`
(not just this specific content) is the root cause, full stop.** Four more
avenues were tried and eliminated in order, each a genuinely different
hypothesis, none requiring further guessing beyond this point:

1. **GitHub/community research** (`gh`/GitHub search API, since local `gh`
   CLI wasn't installed): found `NSACloud/RE-Chain-Editor` issue #7
   ("Jiggle node Issues in MHWilds"), where the tool's own author suggested
   a real MHWilds jiggle-physics quirk: "The game might be disabling
   certain chain settings IDs, adding a couple blank chain settings before
   anything else may fix it." Implemented this literally against a real
   mod's own external `.chain2` resource file (NOT the inline RSZ
   component) by driving `RE-Chain-Editor`'s own `file_re_chain2.py`
   (`Chain2GroupData.settingID` references `Chain2SettingsData.id`, an
   explicit field, NOT list position -- confirmed via
   `blender_re_chain.py`'s own `chainSettingIDDict[chainSettings.id]`
   lookup pattern -- so renumbering existing real settings +2 and
   prepending 2 blank id=0/1 entries, then letting `Chain2File.write()`
   recalculate every offset itself, is a safe, correct edit). **Also
   failed at boot, identically.** This specific game-engine quirk turned
   out to be a red herring for THIS bug (real, but evidently a different
   phenomenon than what NSACloud was describing).
2. **Loose-file vs `.pak` delivery**: hypothesized a loose-file-loader
   timing/race condition (physics resources not finishing async load
   before the synchronous boot equip-init step reads them). Packed the
   identical fixed bytes into a real `.pak` (`pak_writer.py`'s existing
   `write_pak()` + `pak_reader.py`'s `pak_path_hash64()`, following the
   real `[MHWs]SilverWolf.../silverwolf.pak` mod's own folder/modinfo.ini
   convention). Confirmed via the boot log (`IntegrityCheckBypass:
   Redirecting load of re_chunk_000.pak.sub_000.pak.patch_058.pak to
   custom pak...`) that the pak DID load and override correctly -- so this
   was a valid test, not a null result from a broken pak. **Also failed at
   boot, identically.** Rules out the loading-mechanism hypothesis
   entirely.
3. **Full-severity log re-scan**: re-read `re2_framework_log.txt` at every
   log level (not just `[error]`) around the exact black-screen boot
   timestamp -- zero warnings, zero info messages referencing Chain,
   ChainSetting, or the mod's own paths; the log simply stops mid-stream
   with no signal at all. Confirms there's genuinely nothing left in
   available logs to read.
4. **Independent real-mod cross-check, this time on a THIRD piece**: built
   and boot-tested DOTEI's real "EULA" mod (`[8.EULA] LEG PHYS HEAVY`,
   Nexus, a completely different mod/character/piece than Mask Bikini) --
   confirmed via `plan_pfb()` that its `HELM1` page ALSO now resolves via
   `_transplant_reshaped()` (Capcom's TU5 update staled `app.ChainSetting`
   there too, for the hair-adjust chain, independent of the leg-physics
   pages this test was originally built around). The user's own "physics
   disabled entirely, still black-screens" report at first looked like it
   overturned the whole investigation -- but `HELM1` being enabled the
   whole time (it wasn't recognized as physics-related, since it's a base
   page) meant transplanted content was still present. Built and boot-
   tested a genuine, fully transplant-free control (`preserve_extra_pfb_components=False`
   for the ENTIRE mod, `stats["pfb_crc_only"] == 0` confirmed no
   crc_patch/transplant path was used anywhere) with the identical base
   pages (ARM1/BODY1/HELM1/LEG1/WST1/TEXTHERE FILE) enabled: **boots
   clean, textures correct, no black screen.**

**This is now confirmed across THREE independent pieces in TWO unrelated
real mods** (Mask Bikini's Body, DOTEI EULA's Leg, DOTEI EULA's Helm):
`_transplant_reshaped()`'s output is byte-verified correct by every static
method available (including an independent third-party parser) and always
works via live equip, but is NEVER safe through the boot-time default-
loadout path, while plain wholesale substitution is always safe at boot
on the exact same pieces. This is no longer "unverified, treat with
caution" -- **`_transplant_reshaped()` should be treated as confirmed
broken for real deliveries until whatever boot-time engine mechanism
causes this is actually understood**, not just gated behind
`preserve_extra_pfb_components`. A future session with real live-debugging
access (ObjectExplorer, or a modder who's hit this exact "works live,
never survives boot, no error anywhere" signature) is the only path left;
everything reachable through file analysis, independent tooling, delivery
format, and community-sourced format knowledge has been tried and has
converged on the same wall.

**Postscript, same night: the boot-time failure is non-deterministic, not
a fixed pass/fail per file.** After the wall above, the user pushed one
more round of real testing on DOTEI's EULA (the same `[8.EULA] LEG PHYS
HEAVY` transplant+blank-settings pak from the paragraphs above), enabled
alongside `[8.EULA]99.BODY PHYSICS HEAVY` (a page that, per
`find_pfb_files()`, doesn't even carry its own PFB -- textures/mesh only,
confirmed by there being no Body pfb anywhere in the deployed loose files
either). That exact combination booted clean, repeatedly, across multiple
real cold boots -- the same pak that had reliably black-screened earlier
in this same session with an unrelated page (`BODY PHYSICS HEAVY`, no
mechanical connection to the Leg pfb) toggled off instead. Disabling
`BODY PHYSICS HEAVY` and re-testing the ORIGINAL failing combination
(exact same base pages + the same pak) produced a THIRD distinct outcome
on repeat: no black screen this time, game fully playable, but BOTH the
leg and (previously-perceived-as-working) chest jiggle were simply inert
-- no crash, no visible physics, no error. The user was explicit that
the earlier black-screens were real, not a misread slow transition.

Three outcomes (crash / inert-but-stable / -- never once confirmed
actually working at boot) from byte-identical content across repeated
cold boots, with no file-level or page-selection change that reliably
predicts which one occurs, is conclusive: **this is a genuine race
condition in the game's own boot-time physics-component initialization,
not a deterministic property of any specific file this project produces.**
Immediately retested by applying the identical blank-chain-settings-id
workaround to ALL FIVE of Mask Bikini's own bundled `.chain2` files (not
just Leg -- Arm/Body/Helm/Leg all resolve via `_transplant_reshaped()` for
this mod, confirmed via `plan_pfb()`) layered on top of the full
transplant build (`Mask_Bikini_blanksettings_test.zip`). Failed at boot
again. Given the DOTEI result already proved this exact technique doesn't
reliably prevent the race either way, this was expected to be
inconclusive at best, and was -- consistent with everything else, not new
evidence of anything.

**Final, no-further-questions conclusion**: no file this project can
produce -- however byte-perfect, however many independent tools confirm
it -- can reliably survive MHWilds' own boot-time equipment
initialization once it carries physics content that didn't exist in the
last officially-shipped state of that GameObject. The failure isn't
consistent enough to even reason about from outside the engine (three
different outcomes observed from unchanged bytes). Ship plain forced
substitution only, permanently, for any piece needing genuinely new
physics/chain content added -- treat this as a hard boundary of what this
tool can do, not a pending investigation.

### 19. `.user` files were never scanned at all -- a real "avp" (Additional Visual Parts) wrong-slot-reference bug, and a new `resolve_and_fix_avp_files()` (2026-08-09)

Real report (OVR Rogue "Bifrost", Nexus, a real vanilla-slot armor mod --
no custom-slot substitution involved): wings missing, several materials
rendering white/blank, no crash. Root cause, confirmed byte-level: the
mod's own `041_001_avp.user.3` (`app.user_data.PlayerArmorVisualParam`
and friends -- governs optional decorative sub-parts like wings/capes)
carries an inline resource-path string that self-references a COMPLETELY
DIFFERENT, unrelated armor set (`Armor/Male/036/000/036_000_avp.user`)
instead of its own slot (`Armor/Male/041/001/041_001_avp.user` -- verified
against the CURRENT donor at the same path, which correctly self-
references). Structurally the file is entirely current
(`fits_current_layout()` true, every instance crc matches the live donor)
-- this is NOT a staleness/CRC problem, so `_crc_only_fix()`-style logic
could never catch it; almost certainly a residual left over from however
the mod was originally built (started from set 036's own avp.user as a
template, never updated this one self-referencing string).

**This project had NEVER scanned loose `.user` files for anything at
all** -- `find_pfb_files()` only ever matched `*.pfb.*`. (The pak-bundled
path already treats `.user`/`.scn` identically to `.pfb` since item #8; a
real, pre-existing gap specific to loose files, not a new phenomenon.)
Fixed narrowly with `find_avp_files()` / `_fix_avp_self_reference()` /
`resolve_and_fix_avp_files()` in `pfb_fix.py`, wired into
`process_mod()`: only this specific string pattern (an avp.user self-
reference not matching the file's own set/variant numbers, derived from
its own path) gets corrected, not a general `.user` repair pass -- this
exact bug has a precise, mechanically verifiable correct answer (self-
reference) that needs no donor lookup or structural comparison at all.
Same-byte-length-only substitution, matching the existing in-place
substitution safety margin used everywhere else in this file.

**This fix is confirmed real and correct, but did NOT fully resolve the
report** -- wings are still missing and materials still render wrong
after this fix alone, so a second, deeper issue exists in the same mod
(see below). Both are independently real; fixing one doesn't imply it
was the only problem.

**Investigating the remaining white-material symptom went through two
wrong hypotheses before landing on the likely real one, worth recording
so a future session doesn't repeat the same dead ends:**

1. *Wrong hypothesis: mesh needs more materials than the mdf2 provides.*
   The mod's own mdf2 material COUNT is lower than the CURRENT donor's
   for all 5 pieces (e.g. Arm: mod has 1, donor has 5). This looked like
   the answer, matching a real documented RE Engine rule (see below) --
   but is a red herring here specifically: cloned `NSACloud/RE-Mesh-Editor`
   (a real, maintained Python mesh parser, no bpy dependency for header/
   name-list reading) and drove `file_re_mesh.py`'s `REMesh` class
   directly against both the mod's own `.mesh` and the current donor's
   `.mesh` (donor requires BOTH a main and a "streaming" companion file,
   both fetchable via `game.find_versioned()` with an explicit
   `version_range` -- the default `range(1,500)` is far too small for
   real mesh version numbers like `241111606`, silently returning "not
   found"). Result: the MOD's own mesh internally expects only 1 material
   (`materialCount=1`), matching its own 1-material mdf2 exactly -- the
   deployed mod ships a self-consistent pair. The donor's mesh needing 5
   is irrelevant since the donor mesh is never deployed.
2. *Second-order hypothesis, also ruled out: missing texture page.* The
   mod's main loose page has ZERO `.tex` files -- textures only exist
   inside two separate `.pak`-page variants (`OVR Rogue - Bifrost b`/`r`).
   Confirmed via `Havens-Night/REEngine-Modding-Documentation`'s wiki
   (`Custom-Model-Importing-Guide`, by RE-Mesh-Editor's own author): "In
   MH Wilds and newer (RE9 too), textures can not be loaded as loose files
   and must be put in patch pak files" -- a real, documented engine
   requirement. Asked the user to confirm the `b`/`r` page was enabled
   during testing -- it was, ruling this out too.
3. *Current leading hypothesis, not yet confirmed in-game:* the mod's
   original material's shader (`MaterialShader/Variation/Base_Equip_Fur.mmtr`,
   full MultiBlend-capable) has been **completely retired** -- a whole-
   game scan via `LazyWholeGameIndex.find_by_mmtr()` found ZERO current
   materials anywhere using it (only the `_NoMultiBlend` sibling
   survives). `slot_merge.py`'s mmtr-variant-tolerant matching picks the
   closest available donor (`m_shellfur_UseSC`, `Base_Equip_Fur_NoMultiBlend.mmtr`)
   -- but that donor is semantically a minor "shell-fur technique" utility
   material in the donor's own file, not the PRIMARY full-body material
   the mod's single combined material was designed to be. Every mod
   texture/prop this specific donor lacks gets dropped by design
   (`apply_texture_overrides()`), which may be discarding render-critical
   settings even though the actually-restored textures (BaseDielectricMap
   etc.) look individually correct. Unconfirmed because there's no way to
   verify "this donor is the semantically wrong role" from static files
   alone -- waiting on an updated file from the mod's actual author
   (built with real tooling, not this project's donor-matching heuristic)
   to compare against directly.

**Confirmed-real, reusable documentation from this troubleshooting pass**
(`Havens-Night/REEngine-Modding-Documentation` wiki, "Troubleshooting"
page): "material count and material names need to match on BOTH the mesh
and mdf files... not possible to have less or more material references in
either file" -- the exact rule investigation #1 above is built on, now
externally confirmed rather than just inferred from this project's own
testing. Also: outdated `.PFB`/`.USER` files (not extracted from the
latest patch) cause infinite loading -- the same principle behind this
project's whole CRC-staleness detection approach, independently
corroborated.

### External resources map (compiled 2026-08-09, for future sessions)

A broad research pass (prompted by the user wanting a fuller map of what
exists before continuing to debug blind) turned up the wider RE Engine
modding ecosystem this project has been operating adjacent to without
fully cataloging. Worth checking before re-deriving something from
scratch in a future session:

- **`Havens-Night/REEngine-Modding-Documentation`** (GitHub, actively
  maintained, has an actual wiki -- fetch pages via
  `raw.githubusercontent.com/wiki/Havens-Night/REEngine-Modding-Documentation/<Page>.md`,
  not the repo's own `main` branch) -- general RE Engine modding
  knowledge, troubleshooting, ID lookup tables (including a Monster
  Hunter Wilds item-ID table), a maintained tools list, and a Discord
  server link. The single best "what already exists" index found.
- **`praydog/REFramework`'s own `reversing/` folder** (NOT the main addon
  code) -- the actual pipeline used to generate an authoritative RSZ
  registry from scratch, straight from the tool's own author:
  1. Dump the game's unpacked exe with x64dbg's Scylla.
  2. REFramework's own `DeveloperTools -> ObjectExplorer -> Dump SDK`
     button (already available, no extra install) produces
     `il2cpp_dump.json` -- a full live extraction of every class's
     fields/methods/crc/offsets from the RUNNING game's memory. This is
     the actual ground truth REasy's own dumps (and by extension this
     project's own registries) ultimately trace back to.
  3. `reversing/rsz/emulation-dumper.py` -- uses the Unicorn CPU emulator
     to literally EXECUTE each native (`via.*`) type's real deserializer
     function to infer its field layout (their own docs call this a
     "guess" even in the official pipeline -- worth remembering next time
     this project's own registry turns out wrong for a native type; some
     irreducible uncertainty is inherent to the whole ecosystem, not a
     gap unique to this project).
  4. `reversing/rsz/non-native-dumper.py` -- merges native + non-native
     layouts into the final `rsz<game>.json`.
     Needs Python <= 3.9 specifically (undocumented reason). Not run in
     this project (needs x64dbg/Scylla, external to anything used so
     far) but valuable to know the exact provenance and limitations of
     the registries this project already depends on.
- **`praydog/REFramework`'s own documentation book**
  (`cursey.github.io/reframework-book`, source at
  `github.com/cursey/reframework-book`) -- the TDB (Type Database)
  concept, `ObjectExplorer`/`Chain Viewer` tool docs, and the full Lua/C#
  scripting API reference. `Chain Viewer` specifically visualizes live
  `via.motion.Chain` objects and their collisions -- directly relevant to
  any future physics/chain investigation (see #17-18), never actually
  used this session.
- **`kagenocookie/RE-Engine-Lib`** (.NET) + **`kagenocookie/REE-Content-Editor`**
  (desktop GUI built on it) -- a DIFFERENT, actively developed RSZ/file
  editing stack descended from `RszTool` (see below), explicitly designed
  to "make upgrading data easier after game updates break files with no
  major structural differences." Does NOT currently list Monster Hunter
  Wilds in its supported-games README (RE games, DD2, DMC5, Pragmata
  only) -- worth re-checking in a future session since this ecosystem
  moves fast.
- **`kagenocookie/REE-Lib-Resources`** -- a resource-data repo with a
  dedicated `mhwilds/` folder (updated 2026-08-04, five days before this
  session), containing `il2cpp_cache.json` (~22MB) and
  `file_extensions.json` -- a FOURTH potential independent registry
  source alongside this project's own compact registry, the freshly-
  fetched REasy dump, and `alphazolam/RE_RSZ`'s dump (see #18). Not yet
  cross-checked against the others -- do that before trusting it if used.
- **`czastack/RszTool`** (C#) -- another independent `.user`/`.pfb`/`.scn`
  editor; `RE-Engine-Lib` above is explicitly a fork/expansion of it.
  Not run this session (would need a .NET build), but a real alternate
  cross-check source if Python-based tools ever disagree with each other.
- **`SilverEzredes/MDF-XL`** -- a MHWilds-specific RUNTIME (not file-
  editing) material preset editor/submesh toggler, built on REFramework.
  Doesn't touch file structure at all, so it can't fix a structural
  mismatch, but its submesh/material toggling could be used to LIVE-
  inspect which submesh a "missing" part (e.g. Bifrost's wings) is
  actually trying to use, which this project has no static way to
  determine on its own.
- **`NSACloud/RE-Asset-Library`** -- Blender addon for browsing/
  extracting game files directly (an alternative to RETool/ree-pak-gui
  for the "get the current donor's raw files" step this project's own
  `game_archive.py` already does programmatically -- not a gap, just
  worth knowing the manual-workflow equivalent exists).

**Reusable technique demonstrated this session**: several of these tools
(REasy's `RszFile`, RE-Chain-Editor's `Chain2File`, RE-Mesh-Editor's
`REMesh`) are pure-Python, `bpy`-independent for at least their
read/parse path, and can be driven directly as libraries (`sys.path`
insert + import) without installing Blender or any GUI -- this is how
this session cross-verified its own RSZ transplant logic (#18) and probed
the mesh material-count question (#19) without needing hands-on tool
usage. When a future investigation needs ground truth this project's own
reverse-engineered code doesn't have, check whether the relevant
community tool's parser can be borrowed this same way before building a
new one from scratch.

**Nexus Mods itself is not reachable by automated fetch** -- confirmed
this session (`WebFetch` returns HTTP 403; the in-app Browser pane
navigating there also became unresponsive/crashed the tab). Treat any
Nexus mod page, article, or comment thread as something only the user can
read and relay back -- don't spend a turn retrying different fetch
methods against nexusmods.com.

**A second, independent confirmation of the same "Dump SDK" ground-truth
pipeline** (see the `praydog/REFramework` entry above): `Synthlight/RE-Editor`
(a mature, actively maintained -- updated 2026-08-04, five days before
this session -- `.user`-file GUI editor covering MHWilds among 10 RE
Engine games at "93% write-test pass rate") generates ALL of its game-
specific struct definitions from the exact same
`Enums_Internal.hpp` + `il2cpp_dump.json` pair produced by REFramework's
`ObjectExplorer -> Dump SDK` button. Two unrelated, independently-built
community tools both treating that button's output as their own ultimate
source of truth is strong confirmation: **if a future session needs to
resolve an uncertain field layout with real authority (not another
third-party snapshot that might itself be stale), the answer is always
"click Dump SDK in the user's own currently-running, already-installed
REFramework instance,"** not searching for yet another pre-made registry
online. `Synthlight/RE-Editor` was not run this session (C#, needs a full
Visual Studio build with generated structs from a local dump) but is a
real alternate `.user`-file editor to reach for if REasy/RszTool ever
disagree with each other on a `.user` (not `.pfb`/`.scn`) file
specifically.

**Chinese-language community resources -- a genuinely active, MHWilds-
specific modding scene this project had not looked at until asked to**
(`www.caimogu.cc`, "踩蘑菇社区" -- has a dedicated "怪物猎人荒野MOD圈"
/ "Monster Hunter Wilds MOD Circle" section, distinct from the
similarly-named but different old "怪物猎人世界" / Monster Hunter
*World* section -- easy to confuse, double-check which game a hit is
actually about):
- **"mesh与mdf2不完全讲解"** (`caimogu.cc/post/1931564.html`, "An
  Incomplete Explanation of mesh and mdf2") -- independently confirms, in
  a completely separate write-up from Havens-Night's English wiki, the
  exact same rule: mesh-embedded material names must match the mdf2's
  material set exactly in count AND name, or the game black-screens on
  entry; also documents the mesh's own submesh-naming convention
  (`Group_[state-code]_Sub_[index]_[materialname]`, where state-code
  distinguishes e.g. weapon-sheathed vs. weapon-drawn visibility) and a
  concrete texture-channel reference (BaseDielectricMap/
  NormalRoughnessOcclusionMap/EmissiveMap/AlphaTranslucentOcclusionSSSMap
  channel packing) that matches what this project already reverse-
  engineered independently via `mdf2_slice.py`.
- **"从零开始的手搓物理-Chain2"** (`caimogu.cc/post/1950773.html`,
  "Hand-Crafting Chain2 Physics From Scratch") -- the Blender-side
  authoring workflow for adding NEW chain physics: bones must be named
  `xx_00, xx_01, ..., xx_end` (a *contiguous*, correctly-terminated
  sequence -- a gap in the numbering silently breaks the chain), weight-
  painted to those bones, then "Create Chain From Bone" in RE Chain
  Editor generates the actual chain data from the bone hierarchy. This is
  the AUTHORING side of exactly the feature this project's own #17/#18
  investigation was trying to reconstruct after the fact via raw byte
  editing -- doesn't mention this project's specific boot-vs-live
  symptom, but confirms real modders successfully ship NEW chain physics
  Blender-authored from scratch, which this project's transplant/splice
  approaches (editing existing bytes, never touching bone/skeleton data
  at all) could never do even in principle. If chain-physics preservation
  is ever revisited, authoring via this real Blender pipeline (not byte
  surgery) is the only approach with a track record of actually working.
- **"Mod解包与制作工具资源汇总帖"** (`caimogu.cc/post/1898548.html`) --
  the community's own consolidated tool list; named a `.user`-file GUI
  editor ("MHWS Editor", = `Synthlight/RE-Editor` above) this project's
  English-language research pass hadn't surfaced on its own.
- Circle index page (`caimogu.cc/circle/447.html`) lists further
  MHWilds-specific technical posts, now all read:
  - **"荒野法线贴图默认通道解决办法"** (`post/1912870.html`, normal-map
    channel fix) -- MHWilds-extracted normal maps have red and alpha
    channels swapped relative to the standard convention; fix is
    channel-split, swap red<->alpha (synthesize a pure-white alpha if the
    source has none), recombine. Pure texture-authoring detail, not RSZ/
    PFB-related.
  - **"ReChain碰撞flag解析以及碰撞常见问题"** (`post/1929506.html`,
    ReChain collision-flag analysis) -- CLSP collision flags are a
    bitwise filter: two colliders only interact if their flag values
    share a set bit (e.g. flag 2 (010) and flag 4 (100) never collide;
    flag 6 (110) collides with both). Documents concrete per-bone flag
    values from a real official clip-value table (`spine_0->spine_1: 4`,
    `spine_1->spine_2: 8`, a special spherical-collider value
    `Spine_2: 67108864`, etc.) -- directly relevant to any mod bundling
    its own `.clsp` files (confirmed present in Bifrost's own archive,
    one per piece, never inspected this session). Common pitfalls named:
    incomplete flag setup, bone axis orientation not matching (Z is NOT
    always "up" -- verify via the bone-axis display), and `-1` as a flag
    value causing unintended collisions.
  - **"UV流动部分参数解析"** (`post/1928771.html`, UV-scroll parameters)
    -- `UV_Scroll` is an on/off switch (usually left at 1, deferred to
    the other two); `UV_Scroll_Vectel` (4 floats: h-speed, v-speed, two
    unused-usually-0) sets direction+speed (positive h = rightward,
    positive v = upward); `UV_Scroll_speed` is a global multiplier
    (default 1.0) applied on top: `actual speed = Vectel * speed`.
    `UV_Scroll_Vectel` takes priority if both are set. These exact prop
    names appear in real mod materials this project has already dumped
    (e.g. Bifrost's own material prop list) -- this is the first time
    this project has had their actual semantics documented anywhere.
  - **"荒野防具着色贴图"** (`post/1961567.html`, armor tint/stain map
    authoring) -- **directly relevant to the still-open Bifrost
    investigation**: confirms the `_UseSC` material-name suffix
    (`"Use S(tain) C(olor)"`, presumably) specifically marks a material
    variant that supports the in-game armor-dye/stain system, and
    requires: a `ColorLayer_MaskMap` texture (R channel controls dye
    slot 1 strength, G channel controls dye slot 2, painted as grayscale
    per-channel, never drawn directly in RGB) plus `ColorLayer_R/G/B/A`
    props for the default stain color, and the mesh's own submesh
    material-name reference kept in sync with whatever the mdf2 names
    the material. Cross-checked against this project's own earlier
    material dump of Bifrost's mod material (`ch03_053_0011_arm_UseSC`):
    it DOES already carry a real `ColorLayer_MaskMap` texture path AND
    all four `ColorLayer_R/G/B/A` props -- the mod author correctly
    implemented this system on their end. This reinforces (doesn't yet
    prove) the "wrong donor role" hypothesis from #19: every donor
    material sharing this mod's mmtr family is itself `_UseSC`-suffixed
    (`m_shellfur_UseSC` etc.) -- i.e. every available current donor is
    ALSO a specialized stain-capable variant of some narrower technique
    (shell-fur, plain fur), never the current game's actual PRIMARY
    full-body material -- consistent with (not yet independently
    confirmed as) "this mod's exact original shader role no longer has
    any living counterpart to donor-match against."
  - **"关于贴图易错点、物理Chain2与Clsp的简单操作"** (`post/1951020.html`,
    texture pitfalls + Chain2/Clsp quick operations) -- practical Chain2
    authoring notes: hierarchy is Group > Link > Point (parent settings
    govern children); collision targeting uses a bitwise "Flag A" value
    per link (default `-1` = collide with everything; concrete worked
    examples given, e.g. both-forearms = 512+128 = 640); a specific named
    gotcha -- "if the constraint cone points upward the physics goes
    haywire/spins -- delete the link and regenerate it, don't try to fix
    the existing one in place." **Explicitly checked whether this
    document says anything about PFB/GameObject BOOT-time problems: it
    does not mention any** -- a real Chain2-authoring practitioner's
    troubleshooting notes have no entry for the #17/#18 boot-vs-live
    symptom at all. Weak but real negative evidence that the boot-time
    race condition this project hit is specific to POST-HOC byte editing
    of existing pfb/chain2 data (splice/transplant), not something
    Blender-authored-from-scratch Chain2 mods commonly run into --
    consistent with the "author it properly instead of byte-surgery"
    conclusion already reached in #17/#18's postscript.
  - **"发光参数测试和简单教程"** (`post/1912833.html`, emissive/glow
    parameter testing) -- `Emissive_Power` (main control, ~5-10 typical)
    and `Emissive_Intensity` (fine-tune, usually left at 1) must BOTH be
    non-zero for glow to render at all; in-game "Filters" set to
    official washes out glow, and "Lighting" set to off/low can make an
    emissive texture look bleached. Minor material-tuning reference, not
    tied to any open investigation.

**Other communities checked, found less useful than Caimogu for THIS
project's purposes (mod-creation/reverse-engineering depth, not
installation/consumption):**
- **Korean**: DCInside's "몬스터헌터 와일즈 마이너 갤러리" and
  "몬스터헌터 시리즈 마이너 갤러리", and Arca Live's "몬스터 헌터 채널" --
  real, active MHWilds communities, but sampled threads skew toward mod
  discovery/installation/NSFW-mod discussion, not RSZ/PFB/material
  reverse-engineering. Worth re-checking if a future session specifically
  needs a Korean-language install-troubleshooting angle, not for format
  research.
- **NGA** (`bbs.nga.cn`) -- has an active MHWilds board but no specific
  technical thread surfaced via search; would need direct forum
  navigation (not indexed well by web search) to actually evaluate.
- **Baidu Tieba** -- not evaluated beyond confirming Caimogu is the
  search-engine-preferred result for the same queries.

**A meaningful meta-finding from Caimogu's OWN "from scratch" tutorial**
(`MHWS 从零开始做外观mod教程`, `post/1898851.html`): its author states
plainly that texture conversion works but "**the material (材质) part is
still being researched**" -- full material property implementation
(metallic, roughness, reflectivity) is explicitly unfinished, community-
wide, as of this tutorial. This is genuinely reassuring context for the
still-open Bifrost investigation (#19): the difficulty this project is
having with material/shader donor-matching isn't a sign of missing some
well-known solution -- the most active MHWilds mod-creation community
found this session hasn't fully solved general material authoring either.
Caimogu (`www.caimogu.cc/circle/447.html`) remains the best technical
source found across every language checked; it also runs a live QQ group
(365063009) for real-time community discussion, not something this
project can join but worth knowing exists if a future session wants to
ask a specific unresolved question directly.

### 20. New feature: `mesh_check.py` -- warns on a mesh/mdf2 material mismatch, this project's first time touching `.mesh` at all (2026-08-09)

Direct outcome of the #19 research pass: with the mesh/mdf2 material-
count-and-name-matching rule now independently confirmed by two unrelated
sources (Havens-Night's wiki, Caimogu's "mesh与mdf2不完全讲解"), and this
project having precisely zero prior ability to detect it, built a
DIAGNOSTIC-ONLY check -- `mesh_check.py`'s `read_mesh_material_names()` +
`check_mesh_mdf2_consistency()`, wired into the end of `process_mod()`
(runs against OUTPUT_ROOT, after every other fix already ran) and
surfaced both in the live processing log and as a `gui.py` summary line
matching the existing `materials_left_unresolved` pattern.

**Deliberately diagnostic-only, not a fix**: unlike everything else this
project does, a genuine mesh/mdf2 mismatch has no safe automatic
resolution available -- fixing it would mean editing mesh geometry/
submesh data, a completely different (and, per #17-19's saga, far riskier)
class of file this project has never touched before this addition and
still doesn't write. Warns and names exactly which material names are
missing on which side; never modifies anything.

**Licensing note, explicitly asked of and decided by the user before
writing a line of code**: the only real-world working parser for this
format found anywhere (`NSACloud/RE-Mesh-Editor`) is GPLv3, and this
project needed the format understanding without inheriting that license.
Resolved by clean-room re-implementation: drove RE-Mesh-Editor's own
parser against real files this session (already documented in #19) to
learn the FACTS of the byte layout (field order, sizes, offsets -- not
copyrightable expression, the same category of thing this project's own
PFB/RSZ format knowledge was built from), then wrote fresh,
independently-structured Python matching this project's own existing
style (`struct.unpack_from` at fixed offsets, same shape as `_parse_rsz()`
in `pfb_fix.py`), and verified the result byte-for-byte IDENTICAL to
RE-Mesh-Editor's own output on a real file (Bifrost's own Arm mesh) as
the correctness proof -- comparing independently-produced OUTPUTS, not
comparing or copying CODE. `mesh_check.py`'s own module docstring
records this provenance for the next person who touches this file.

**Format specifics captured** (MHWilds-only -- returns `None`, never
guesses, for anything below RE-Mesh-Editor's own "VERSION_ONI2" cutoff
or an MPLY-format stage mesh): a 176-byte MHWilds-era `FileHeader`
contains `meshGroupOffset` (whose LOD header holds `materialCount` as a
single byte at `+1`), `materialNameRemapOffset` (an array of
`materialCount` `u16` indices), and `nameOffsetsOffset` (an array of
`nameCount` `u64` absolute string offsets, each pointing at a plain
null-terminated ASCII/UTF-8 string -- NOT the UTF-16LE convention this
project's other formats use for resource paths). Material names are
resolved by using the remap indices to look up entries in the combined
name table (which holds bone names too, not just materials -- the remap
only ever indexes the material-relevant subset).

**Verified**: byte-for-byte match against RE-Mesh-Editor's own parser
on Bifrost's real Arm mesh; zero exceptions and 100% successful parse
across every `.mesh` file in every real mod this project's regression
suite covers (Bifrost, Esthe, Mask Bikini, DoA, SilverWolf -- 26 mesh
files total, 0 raised, 0 returned `None`); a synthetic true-positive
test (swapping a different piece's mdf2 into another piece's file slot)
correctly produced exactly 1 mismatch, correctly naming both the missing
and the unexpected-extra material. Zero regressions on the full suite
(`mesh_mdf2_mismatches: 0` for every already-passing mod). Bifrost itself
(the report that prompted this whole investigation) comes back clean --
`0` mismatches -- meaning its own mesh/mdf2 pairs were never the actual
cause of its white-material symptom (already known from #19's direct
testing; this is now confirmed by an independent, generalized check
rather than one-off manual verification, and the tool now has standing
protection against this whole class of bug for every future mod).

## 21. RSZ registry type-precision upgrade (2026-08-09)

After comparing this tool against another community fixer, the
user asked for two improvements: a more precise RSZ field type system
(Resource/UserData/Object/String, not just "is this variable-length"), and
a real field-level migration engine. This entry covers the first half.

**Provenance discovery.** `tools/rsz_fields_mhwilds.json.gz`'s own `_meta`
revealed it was never built by this project -- it was imported wholesale
from the other tool's two-version snapshot format
(`_bake_two_version_snapshot()`, which copies `e["f"]` verbatim with no
re-derivation), labeled `"TU5-ish (borrowed+verified from
another community fixer, cross-checked vs live game 2026-08-08)"`.

**Real bug found in `rsz_layout.py`'s `_bake_raw_dump()`** (used by the
existing "check GitHub for update" feature, unrelated to the imported
registry above): `f["type"] in ("String", "Resource")` treated
fixed-size `Resource` fields (4-byte resource-table index) as if they were
variable-length `String` fields (4-byte length-prefix + inline UTF-16).
Cross-checked against `rszmhwilds_fresh.json` (a live-crc-matching REasy
dump fetched earlier): of ~271k same-shape fields, 826 were confirmed real
Resource-marked-as-String misclassifications (zero in the reverse
direction). Invisible until now because a null/zero Resource value parses
identically either way -- only a genuinely non-zero value would silently
corrupt parsing. Fixed to `f["type"] == "String"`.

**Field-tuple format extended** from 5 to 6 elements: `[name, size, align,
is_array, is_variable]` -> `[..., is_variable, type_string]` (the raw
REasy type name, e.g. "Resource"/"UserData"/"Object"/"String" -- captured
for the future migration engine, not yet consumed elsewhere). All 4 tuple-unpacking
call sites (`rsz_layout.py` x3, `pfb_fix.py`'s `_transplant_reshaped()` x1)
now slice `f[:5]` before unpacking, so old (5-element) and new (6-element)
data interoperate -- needed because `tools/rsz_archive/` still holds
older 5-element snapshots.

**First rebake attempt failed and was reverted.** Fully replacing the
registry with a fresh bake from `rszmhwilds_fresh.json` via the fixed
`_bake_raw_dump()` dropped total entries from 323,073 to 48,448 (its
`complete` field is always `False`/`None`, never a usable "confirmed
fieldless" signal -- unlike the other tool's format, which has an
explicit separate fieldless list). Worse, it broke `via.render.Mesh`
parsing (82 fields in the trusted registry vs 83 in the fresh dump, with a
real size mismatch at one field) -- caught immediately by the established
Esthe/Mask Bikini transplant-resolution regression check, which fell back
from `TRANSPLANT` to plain `substitution` for every piece. Root cause:
native (`via.*`) types are inherently less reliable in ANY RSZ dump --
even REFramework's own official pipeline documents its native-type field
layouts as CPU-emulation "guesses" -- unlike managed (`app.*`) types,
which come from real C#-reflection metadata. Reverted via `git checkout --
tools/rsz_fields_mhwilds.json.gz`; kept the code fixes.

**Second approach: surgical, position-verified patch.** For each type
where the OLD (proven-correct) and fresh-dump entries agree on field
COUNT, compare each field's `(size, align, is_array)` at the same index;
if every field matches, correct that field's `is_variable` from the fresh
dump's real `type == "String"` and append the 6th type-string element. If
ANY field within a type disagrees in shape, leave that entire type's entry
untouched (a shape divergence anywhere means later same-index fields
might not be the same field at all). Result: 818 fields' `is_variable`
corrected, ~900+ types left untouched on shape disagreement (including
`via.render.Mesh`, whose 82-field shape is preserved exactly).

**Second regression, caught before shipping.** Even with the surgical
patch, the Esthe/Mask Bikini transplant check still fell back to plain
substitution. Root cause, found via direct byte-walk debugging: the
transplant path's resync recovery (`walk_instances_with_recovery()`,
documented in #18) depends on `app.ChainSetting` THROWING on these two
mods' old-shape instance, so the walk can resync past it via
`_next_string_offset()`. The mod's real bytes only make sense under the
CURRENT game's `app.ChainSetting` shape by coincidence of the walk
throwing at the right spot -- correcting `_MeshBoundary`/
`_WindAssetOverwrite` to their true fixed-size `Resource` type made
ChainSetting parse WITHOUT throwing (an all-fixed-size shape can't fail a
length-prefix sanity check), but it silently consumed the WRONG byte
count, desyncing every instance after it. A "successful but wrong" parse
is worse than a thrown one here, since the resync path exists specifically
to catch stale/mismatched instances. Excluding just `app.ChainSetting`
from the patch wasn't enough either: `app.CharacterEditRegion`, walked
BEFORE ChainSetting in these mods' files, also had a real `is_variable`
correction, which shifted `pos` at the moment ChainSetting throws --
moving where the resync search starts, and desyncing the walk at a
completely unrelated later instance (`via.character.CollisionShapePreset`).

**Final fix: exclude every type these two mods actually touch.** Rather
than hand-picking which upstream types are "safe" to correct (fragile, and
only provable per-mod), the patch now excludes ALL 30 distinct type_ids
referenced anywhere in Esthe's and Mask Bikini's own pfb files (enumerated
directly from their real instance tables) from the `is_variable`
correction entirely -- their registry entries are byte-identical to the
pre-patch baseline. Verified: Esthe and Mask Bikini both return to
`TRANSPLANT` for Arm/Body/Helm/Leg and forced `substitution` for Waist,
matching the original verified baseline exactly; the standard regression
suite (SilverWolf/Endfield_LiJiyan/DoA_Raise_the_Sail) and the Bifrost
avp-fix/mesh-check both produce byte-identical stats to before this patch,
zero errors. General correctness benefit: ~47,600 other type entries
gained their real type string, 818 fields elsewhere in the registry had a
genuine Resource/UserData-as-String misclassification corrected --
available to the future field-level migration engine and to any future
mod whose crc-only/transplant resolution depends on accurate variable-length
detection, without touching anything this project has actually verified
in-game.

Not yet started: the field-level migration engine itself (the other half
of "둘다 하자" -- do both).

## 22. Suffix-only field migration for `_transplant_reshaped()` (2026-08-09)

The other half of "둘다 하자": rather than a generic schema-diffing engine
(rejected as scope -- would require knowing a mod's exact OLD field shape,
which this project doesn't have for instances that predate even the
archived TU4 snapshot, e.g. ChainSetting; guessing it is the same class of
speculative RSZ engineering that's crashed this project 5 times), scoped
down to the narrowest defensible version: `rsz_layout.try_suffix_field_migration()`
tries dropping the CURRENT registry shape's trailing fields (1..n-1 of
them) against a reshaped instance's own bytes, and accepts a truncation
ONLY if it's the single unique depth whose parse lands exactly on the
instance's byte boundary. `_transplant_reshaped()` now tries this first
for each reshaped instance -- on a unique fit, the mod's own values are
kept for every field that still exists, and only the genuinely-new
trailing field(s) come from the donor; on no fit or multiple fits, it
falls back unchanged to the original all-donor-values behavior.

Verified safe: a synthetic unit test confirms a true tail-append (2 old
fields, 1 new one) is uniquely recovered, and a garbage-length case
correctly returns `None`. Full regression suite (SilverWolf/Endfield/DoA)
and the Esthe/Mask Bikini `TRANSPLANT` resolution check both came back
byte-identical to before this change -- zero regressions.

**Honest limitation, found by testing against the only real case we
have**: exhaustively enumerating every field-subset (not just suffixes)
against the real Esthe ChainSetting instance's 19 bytes found 18
DIFFERENT subsets that all fit exactly (dropping various combinations of
`_MeshBoundary`/`_WindAssetOverwrite`/`_WindAssetOverwrite2`/etc., never
a suffix-only combination). This means the real, confirmed mismatch is
NOT a trailing-fields-appended case at all -- Capcom's actual change here
landed in the middle of the field list, not the tail -- so the "new
fields only ever get appended at the end" hypothesis this feature is
built on genuinely doesn't apply to this case, and it correctly declines
to migrate (falls back to the old, already-verified-safe all-donor
transplant) rather than guess among 18 ambiguous candidates. The feature
ships as safe, tested infrastructure for a FUTURE mod whose reshaped type
really did just grow a field at the end -- it provides no improvement for
ChainSetting specifically. Recovering ChainSetting's own wind-bias
customization would need a different, more targeted approach (e.g. a
hand-verified field whitelist for that one class) -- not attempted here,
flagged as a possible future step if a user ever reports losing
customization there.

## 23. gpbf (GPU byte-address-buffer) slots weren't preserved from the mod (2026-08-09)

Real bug report (Nexus, "TiNE's Qipao Ver.R Remastered", independently
confirmed by two people: a comment from `tsuji2` -- "the design has
changed, but it's just the color that's messed up" -- and the user's own
in-game screenshot showing the equipped piece rendering as bare skin with
almost no dress visible, both against the SAME mod). Root-caused by
directly parsing the mod's own material (via `mdf2_slice.extract_material()`)
and diffing every field of `auto_fix.apply_texture_overrides()`'s output
against it: `shading_type`, `alpha_flags_raw`, `mmtr_path`, textures, and
props all matched -- but `gpbf_entries` did not. That function only ever
explicitly overrode `name`/`shading_type`/`alpha_flags_raw`/`textures`/
`props` back to the mod's own values on top of `copy.deepcopy(donor_mat)`;
`gpbf_entries` was never in that list, so it silently stayed as the
DONOR's.

For this material (`Qipao_UseSC`, shader `Base_Equip_Fur.mmtr`, matched
whole-game to donor `ch02_053_0014_fur_UseSC` since the shader had zero
same-file/same-set candidates), the mod's own `MultiBlend_BAB` gpbf slot
deliberately points at `systems/rendering/Empty.gpbf` (consistent with
its `MultiBlend_ALBDMap`/`MultiBlend_NRMMap` texture slots also being
NullGray/NullNormal placeholders -- the author has multi-blend off). The
donor's `MultiBlend_BAB` instead points at
`Art/Model/Character/ch03/053/001/4/textures/ch03_053_0014_Mblend.gpbf` --
a real per-vertex/per-pixel blend-weight buffer sized and laid out for a
COMPLETELY unrelated character's mesh/UV topology. The engine doesn't
crash or warn (the buffer path is valid, just semantically wrong) -- it
renders using garbage blend weights for this mesh, producing exactly the
reported symptom: correct silhouette/design, wrong-looking color/blending.
Verified directly: extracting the mod's own material and the tool's
pre-fix output and diffing every field found this as the ONLY difference;
textures, props, and everything else were already correctly preserved
(confirmed no length-mismatch silent-discard in `apply_texture_overrides()`'s
existing prop-override logic either -- that hypothesis was checked and
ruled out first).

**Fix**: `gpbf_entries` now gets the same name-matched override treatment
already used for textures/props. Format: a flat list of `gpbf_split[0]`
`(slot_name, h1, h2)` entries followed by `gpbf_split[1]` `(path, 0, 1)`
entries, paired by matching INDEX (i-th slot name <-> i-th path) --
confirmed directly against this material's real data (both counts equal,
4 and 4). For each donor slot name that also exists in the mod's own gpbf
slots, the donor's corresponding path entry is replaced with the mod's
own path; skipped entirely (falls back to old donor-wholesale behavior)
if the mod's own name/path counts don't match 1:1, matching this
project's established "don't guess when ambiguous" posture.

**Scope**: this is NOT specific to this one mod or shader -- `has_gpbf`
applies whenever `19 <= numVersion < 100000`, true for most current mdf2
files, and the bug fires any time `apply_texture_overrides()` runs a
cross-file donor match (whole-game or cross-piece) on a gpbf-bearing
material with a non-empty gpbf slot the mod customized. Same-file/
same-set matches were never affected structurally (donor and mod usually
share gpbf content in that case) but could still have silently differed
if a mod author changed a gpbf reference intentionally.

Verified: full regression suite (SilverWolf/Endfield/DoA) byte-identical
to before this fix (zero regressions), and a direct re-parse of the fixed
`Qipao_UseSC` material's `gpbf_entries` now matches the mod's own
original data exactly. Not yet re-verified in-game by the reporting users
(both were told to re-run the tool and re-check).

## 24. Real-world confirmation of the `Base_Equip_Fur.mmtr` hypothesis, and a directional staleness-check fix it exposed (2026-08-09)

The user obtained a fresh, author-updated copy of "OVR Rogue - Bifrost"
(the mod behind item #19's white-material investigation) directly from
its own creator. Comparing every material's `mmtr_path` between the old
(broken, as originally reported) and new (author-fixed) files:
**every single one of the 5 affected materials (Arm/Body/Helm/Leg/Waist)
was switched from `Base_Equip_Fur.mmtr` to plain `Base_Equip.mmtr`** --
the author didn't patch data under the old shader, they rebuilt the
material under a different one (25 tex slots/191 props vs the Fur
variant's 18/120 -- a genuinely different schema, real re-authoring work,
not a metadata edit). This is real-world, independent confirmation of
#19's leading (until now unconfirmed) hypothesis: `Base_Equip_Fur.mmtr`
is fragile/near-retired in the current game build (only 2 real materials
game-wide still use it) and donor-substituting content built for it
produces a broken-but-non-crashing result. Same shader, same failure
class as the TiNE Qipao gpbf case above -- two independent real mods now
point at this exact shader family being the common thread. Not something
this project's donor-matching architecture can fix automatically (it
requires re-authoring under a different schema, a judgment call about
which old texture maps to which new slot), but useful, actionable
information for anyone maintaining an affected mod.

**Running this new, already-current file through the tool exposed a
real, separate bug**: it still rebuilt all 5 materials, dropping their
(genuine, author-authored, current) `MultiBlend_ALBDMap`/`MultiBlend_NRMMap`
texture slots and 14 `Blend_*` props -- the exact same SYMPTOM as #16's
bug, but a different root cause. #16 fixed WHICH donor gets selected
(prefer an exact-mmtr donor over a same-named-but-different-mmtr one).
This is downstream of that: `_structure_key(mod) != _structure_key(donor)`
(prop count / texture-type set / gpbf split / mmtr, blunt inequality)
governed whether a material was "stale" (worth rebuilding) at all --
treating ANY difference as "the donor is more current", including the
direction where the donor has FEWER fields than the mod already has.
For this file, only 2 materials in the whole game share `Base_Equip.mmtr`
exactly, and neither is a superset of the other, so whichever gets
picked as a donor always looks "different" under a blunt comparison --
silently downgrading an already-correct, freshly-authored file.

**Fix**: replaced `_structure_key()`/`!=` with `_material_needs_fix()`,
which only returns True when the donor has a texture slot, prop name, or
gpbf slot the mod's own material doesn't already have -- i.e. only when
there's something to actually gain. A first version of this fix kept an
unconditional "different mmtr always means stale" shortcut (reasoning
that shader identity must match to trust the donor at all) -- but that
broke the SAME real case one layer up: `find_donor_for_material()`'s
own-file tier is itself mmtr-VARIANT-tolerant (accepts a `_NoMultiBlend`
sibling per #16), so the actual donor chosen here had mmtr
`Base_Equip_NoMultiBlend.mmtr`, genuinely different from the mod's
`Base_Equip.mmtr`, while still being a pure field subset -- the mmtr
shortcut treated that mismatch as "needs fixing" and reproduced the
identical bug. Removed the mmtr special case entirely: a genuine
shader-FAMILY change (like this same mod's own real Fur->non-Fur
switch) has almost no field-name overlap between schemas, so the subset
check catches it without help.

Verified: the new Bifrost file's materials now correctly report
`already matches the current game version's structure -- left untouched`
(0 texture restorations, 0 MultiBlend drops) instead of being rebuilt.
The OLD (genuinely broken, `Base_Equip_Fur.mmtr`) Bifrost file still
correctly gets rebuilt (real staleness still detected). Full regression
suite (SilverWolf/Endfield/DoA) plus TiNE Qipao and Arsinia Bunnysuit
(both from this session's earlier analysis) all byte-identical to their
prior baselines -- zero regressions. Fixed in both `auto_fix.py`
(loose-file materials) and `pak_mod_fix.py` (materials inside a mod's own
`.pak`) -- same bug, same fix, both call sites.

## 25. Shipped: automated shader migration for `Base_Equip_Fur.mmtr`, in-game verified (2026-08-09)

Turned #24's confirmation into an actual opt-in feature. `slot_merge.py`
now has `SHADER_MIGRATION_MAP` (currently just
`{"Base_Equip_Fur.mmtr": "Base_Equip.mmtr"}`, deliberately a hardcoded,
individually-verified map, not a general "find a similarly-named shader"
heuristic) and `_find_shader_migration_donor()`, which searches
whole-game for an EXACT match on the target mmtr first (no
`_NoMultiBlend`-variant tolerance -- the same-path vanilla donor for a
migrated material is often only the narrower sibling, which produced a
smaller field set than the real author's own fix in testing). Wired
through `find_donor_for_material(..., shader_migration_map=...)`, tried
BEFORE the material's own mmtr tiers (a known-retired shader's own tiers
already "succeed" today, just badly -- that's the whole bug), falling
through to normal resolution if the migration search itself finds
nothing. New `experimental_shader_migration` parameter threaded through
`process_mod()`/`plan_mod()`/`_resolve_loose_files()`/`resolve_pak_files()`,
off by default, exposed in the GUI as a third experimental checkbox
alongside force-fix/preserve-extra.

**Validated three ways before and after shipping:**
1. Field-level: an in-memory transform of the OLD (broken) Bifrost Arm
   material matched the REAL author-provided new material's texture-slot
   set and prop-name set 100% (25/25, 191/191); of 32 differing prop
   VALUES, every single one traced to either (a) a field the old material
   never had at all (donor default used, no way to know the author's
   later choice) or (b) the author's own deliberate recolor/retune of a
   field the old material DID have (confirmed by checking the OLD
   material's own value directly) -- i.e. the mechanical transform never
   invented or corrupted anything; it only couldn't replicate the
   author's independent creative work.
2. **Real in-game test, the decisive one**: built a full deployable
   Bifrost archive (all 5 affected materials migrated, everything else
   byte-identical to the original broken mod) and the user confirmed live
   in MHWilds -- wings intact, materials rendering correctly, matching the
   reference appearance. This is the strongest verification this project
   can produce for a content-level fix.
3. Ran the shipped feature (not the earlier hand-rolled experiment) against
   all 5 Bifrost materials, the already-current new Bifrost file (correctly
   left untouched -- its materials aren't `Base_Equip_Fur.mmtr` so the
   migration map never triggers), TiNE Qipao (all `Base_Equip_Fur.mmtr`
   materials migrate cleanly, 0 errors), and the standard regression suite
   with the flag OFF (byte-identical to baseline -- confirmed opt-in,
   zero effect when not requested).

**Important asymmetry, told to the user directly**: Bifrost's result is
in-game verified. TiNE Qipao's is NOT -- its mod author is no longer
reachable, so there is no way to confirm the migrated file actually
renders correctly in that specific mod's case, only that it produces the
same class of structurally-sound, field-preserving output the Bifrost
case proved out. Ship it as available but explicitly label results from
this option as unverified per-mod until someone confirms in-game.

## 26. Shader migration confirmed to CRASH a real mod, plus overwhelming validation across a whole modding community (2026-08-09)

**The crash.** The experimental TiNE Qipao build from #25 was tested
in-game and crashed the game immediately on equipping the outfit -- not
the earlier cosmetic bug, an actual hard crash. Isolated cleanly: the
prior gpbf-only build (no shader migration) did NOT crash under the exact
same sub-option combination (Body default etc.) -- shader migration
itself is the trigger, confirmed by direct A/B with everything else held
constant.

**Ruled out the obvious suspects.** The donor Qipao's materials migrated
against (`m_0012_UseSC` from `ch02/001/001/2/ch02_001_0012.mdf2.45`) is
the EXACT SAME donor 3 of Bifrost's 5 real, in-game-verified-working
materials used -- so the donor/its texture values aren't inherently
unsafe. Both Bifrost and Qipao ship zero `.pfb` files of their own (both
reuse an existing vanilla mesh/pfb unchanged), so "custom mesh vs texture
reskin" isn't the differentiator either. `mesh_mdf2_mismatches: 0` for
the migrated build, so mesh/mdf2 material-count-and-name consistency
holds too.

**User's own catch: TiNE's Qipao is NOT part of the Chinese modding
community whose 17 mods (item #24/#25's `SHADER_MIGRATION_MAP` source)
all independently converged on `Base_Equip_Fur.mmtr` -> `Base_Equip.mmtr`.**
Different author, near-certainly a different build pipeline/toolchain.
Ran the same field-level validation used for Bifrost against the other 16
Chinese-community mods' real author-provided fixes (source files obtained
directly from the modder, `C:\Users\User\Desktop\Chinese\source\`):
**72 materials across 16 mods, 100% texture-slot-set match and 100%
prop-name-set match against the real fix, every single one** -- combined
with Bifrost's own in-game confirmation, that's 17/17 real mods from this
specific community matching perfectly. Leading (unconfirmed) hypothesis
for why Qipao specifically differs: it reuses the vanilla "Chain" armor's
existing mesh unchanged, and the migration's new `Detail_*` texture
layer may need a secondary UV channel that mesh doesn't have -- but this
is speculation, not verified; the real lesson is that structural
correctness (proven exhaustively) does NOT guarantee in-game safety for a
mod outside the specific pipeline this was validated against, echoing the
Mask Bikini/`_transplant_reshaped()` lesson from #18 (static analysis has
a hard ceiling; some failures only show up live).

**Decision, discussed directly with the user**: do NOT make
`experimental_shader_migration` default-on. It stays exactly what it's
named -- an opt-in experimental checkbox, same posture as
`preserve_extra_pfb_components`/`force_unresolved_pfbs`, now with a
CONFIRMED real crash on its record (not just a theoretical risk like the
other two currently carry). Safe-to-recommend scope, as of this entry: the
17 Chinese-community mods with independently-verified-matching real
fixes. Outside that specific pool (Qipao, or any unvalidated mod), this
option is a known crash risk, not a safe default assumption.

**UI**: the three experimental checkboxes were an unlabeled row that kept
growing (this is the 3rd). Regrouped into a `ttk.LabelFrame` ("⚠
Experimental options") with a shared warning line underneath
("verify in-game, some options confirmed to crash on certain mods") --
each checkbox's own label dropped the now-redundant "Experimental:"
prefix (shorter, and the group heading already says it once). Also added
a per-material `[warn]` log line specifically for shader migration
(referencing this real crash) whenever it actually fires, matching this
project's established pattern of naming the specific risk in the log at
the moment a risky path is taken (see `_transplant_reshaped()`'s own
"experimental option, verify in-game" line) -- fixed in both
`auto_fix.py` (loose files) and `pak_mod_fix.py` (materials inside a
mod's own `.pak`).

## 27. GUI visual redesign: "Night Ops" theme (2026-08-09)

Real Nexus comment ("slopcoded apps that are actually useful is one thing
but slop art is another") prompted a UI pass. Built three full mockup
directions as an HTML artifact (warm-light "Field Log", dark-ember "Night
Ops", cool-slate "Slate Console" -- same layout/copy in all three, only
palette/type differed) and let the user pick before touching real code --
**Night Ops** (near-black warm background, ember/amber accent) won.

Implementation notes:
- `main()` switched from `style.theme_use("vista")` to a new
  `_apply_theme()` that forces the cross-platform `"clam"` base theme.
  `"vista"` looks native but silently ignores most `style.configure()`
  color overrides (it delegates rendering to the OS theme engine) -- there
  is no way to get a genuinely dark ttk app on Windows while staying on
  `"vista"`. `"clam"` fully honors color configuration.
- `THEME` (module-level dict) is the single source of truth for the
  palette; every widget pulls from it rather than hardcoding hex values a
  second time.
- tkinter has two widget families that need separate handling: `ttk.*`
  widgets go through `ttk.Style` (`_apply_theme()`), but plain `tk.*`
  widgets (`Listbox`, `ScrolledText`/`Text`, `Menu`, the primary `Button`)
  take color kwargs directly and don't listen to `ttk.Style` at all --
  each one is themed individually at construction.
- New: log lines now color-code by the `[fixed]`/`[warn]`/`[error]`/
  `[info]` markers this project's `log()` callers already use consistently
  everywhere (`pfb_fix.py`, `auto_fix.py`, etc.) -- `_log_tag_for()` maps a
  raw line to a `Text` tag, applied in `_poll_queues()`. Purely a display
  concern; never changes what gets logged or filters anything.
- **Known, accepted limitation**: `tkinter.messagebox` dialogs
  (confirmations, errors -- used throughout for the diagnosis/save-location
  flow) are native OS dialogs and cannot be recolored by any supported
  means; reimplementing all of them as custom `Toplevel`s just to theme
  them was judged out of scope for a cosmetic pass. Same story for the
  native Windows title bar itself (would need `ctypes` DWM calls, extra
  fragility for a nice-to-have). Everything else -- main window, all its
  widgets, the RSZ Snapshot dev dialog -- is themed.
- Verified via a headless smoke instantiation (`_apply_theme()` + `App()`
  + `root.update()`, then simulated log lines through the real
  `_poll_queues()` drain path) rather than a live manual launch --
  confirmed no exceptions, correct colors on `start_btn`/`log_text`
  tags/`root`/`mod_listbox`, and that language-switching
  (`_retranslate()`) still works with the new `options_frame` widget.

**Follow-up, caught by the user's own first real launch (headless
instantiation can't render pixels, so this was never going to surface
until someone actually looked at it)**: the native root-level menu bar
(`root.config(menu=menubar)`, holding the one "Settings > Developer
Options > RSZ Snapshot..." entry) rendered as a stark white strip across
the top of the otherwise-dark window -- confirming the "native OS chrome
ignores color kwargs" limitation applies to the top-level menu bar
specifically (not just `messagebox`/title bar as originally scoped).
Fixed by dropping `root.config(menu=...)` entirely and rebuilding the
same two-level structure as a `ttk.Menubutton` + attached `tk.Menu`
dropdown instead: a `Menubutton`'s popup is a genuinely separate floating
window, not part of the root window's OS-drawn frame, so it DOES honor
`tk.Menu` color kwargs on Windows (already set, just never got a chance
to render right since the old attachment point couldn't use them). Same
menu content/behavior, fully themed now, verified via the same headless
smoke-instantiation approach.

## 28. "Check GitHub for latest data" could have silently undone today's own registry precision work -- fixed to merge, not overwrite (2026-08-09)

User looked at the (now-themed) RSZ Snapshot dialog and asked directly
whether its "Check GitHub for latest data" button was actually safe.
Traced it: that button calls `fetch_latest_dump()` (downloads a fresh raw
REasy dump) -> `install_snapshot(dump_path, as_role="current")` ->
`detect_and_convert()` -> `_bake_raw_dump()`, a straight wholesale rebake
with ZERO awareness of anything already installed. This is the EXACT
mechanism items #21-23 (earlier the same day) proved dangerous: a
wholesale rebake from a raw dump collapsed total entries 323,073 ->
48,448 (raw dumps have no reliable "confirmed fieldless" marker) and
broke `via.render.Mesh`'s field count (native `via.*` types are
inherently less reliable in any raw dump). That whole investigation ended
in a one-off manual script, never fed back into the actual `install_snapshot()`
code path -- meaning this GUI button, sitting right there the whole time,
could silently undo all of that work and reintroduce the exact regression
the moment anyone clicked it (auto-archiving the previous "current" first,
so not unrecoverable, but silently ACTIVE until someone noticed and
manually reverted).

**Fix, per the user's own suggested direction ("다운로드하면 덮어씌워지는게
아니라 분석해서 기존 레지스트리를 보강하는 방식으로는 안되나" -- exactly
right)**: generalized the earlier one-off manual patch script into the
actual code path. `_bake_raw_dump()` now takes an optional `merge_with`
(the current registry's own entries) and, when given, does a SAFE MERGE
instead of a wholesale rebake: a type already in `merge_with` gets its
`is_variable`/type-string corrected ONLY if the fresh dump agrees with
the trusted entry on every field's `(size, align, is_array)` at the same
position -- any shape disagreement anywhere leaves that whole type
completely untouched; a type the fresh dump doesn't mention (or has no
usable field data for) is likewise untouched; a type genuinely new to
`merge_with` gets added wholesale (nothing existing to protect there).
`install_snapshot()` now automatically loads the current registry as
`merge_with` whenever `as_role == "current"` and one already exists --
callers (the GUI, an import) don't need to know or opt into this, it's
just how installing "current" from a raw dump works now.

**One more real gap this surfaced**: the earlier manual patch's exclusion
of the 30 type_ids touched by the ONLY two mods this project's
`app.ChainSetting` transplant path has ever been verified against (their
resync-recovery depends on those specific types staying byte-identical to
what was tested, even where a plain shape-agreement check would otherwise
call correcting them safe) was never captured as a reusable constant --
it lived only in that session's scratchpad file. Promoted it to
`_TRANSPLANT_VERIFIED_TYPE_IDS`, a real module-level constant in
`rsz_layout.py`, and wired it into the merge loop so this exact protection
survives every future registry refresh, not just the one script run that
originally established it.

Verified against real data: merging the same fresh dump used earlier
that day against the (already-patched) current registry reproduces
`corrected: 0` (nothing left to fix, since it's already fixed) with
`via.render.Mesh` and `app.ChainSetting` both byte-identical; merging
the SAME fresh dump against the pre-patch git baseline instead reproduces
`corrected: 47630` -- an EXACT match to that morning's manual patch run
-- with `app.ChainSetting` still fully protected either way. Full
regression suite and the Esthe/Mask Bikini TRANSPLANT resolution check
both unaffected (this only touches the snapshot-install pipeline, not the
currently-active registry file).

## 29. Shader migration texture bleed: a new "Mask" texture slot must never inherit the donor's own value verbatim (2026-08-09)

Second real bug found in the shader migration feature (after the TiNE
Qipao crash, #26), this time on Bifrost -- the ONE mod this feature had
actually been confirmed working in-game. User reported the character's
own hair/detail bleeding through the Helm piece where it shouldn't be,
compared the exact same rebuild against two OTHER builds of the SAME mod
that looked clean, and insisted on tracing the real cause rather than
accepting "maybe it's stale save data" (correctly -- see
[[no_save_state_excuse]] in memory, the user shut this down twice and it
should never be offered again for this project).

**Root cause, found by exhaustively diffing the Helm material's every
texture/prop under two different real donors**: `DetailMaskMap` -- a
texture slot the mod's OLD material never had at all, so it's entirely
new content from whichever donor `_find_shader_migration_donor()` picks.
The FIRST hand-built experiment (this session's very first Bifrost
validation, #25) happened to use a donor whose `DetailMaskMap` was
already the engine's own inert "nothing here" placeholder
(`NullBlack_Alpha_MSK4.tex`) -- safe purely by luck. The actual SHIPPED
feature's smarter per-material donor selection picked a DIFFERENT, more
structurally-appropriate donor (`m_0012_UseSC`) for the Helm/Arm/Waist
pieces -- but that donor's own `DetailMaskMap` is a REAL, non-null mask
belonging to an entirely unrelated character. A mask texture's "show
detail here" regions are UV-coordinate-specific to whatever mesh it was
authored for; applied to Bifrost's own completely different UV layout,
that unrelated character's detail pattern bleeds through at essentially
arbitrary spots on the mesh -- visible near the head/hair on the Helm,
apparently landing somewhere inconspicuous on the Arm (same donor, same
mask, different mesh UVs -- confirmed the Arm piece got the identical
fix applied even though it never visibly showed the bug).

**Why this wasn't caught by the extensive earlier field-level validation
(#25's 100%-match-across-17-mods check)**: that check only verified our
mechanical transform matches what a REAL AUTHOR'S OWN rebuild produced --
which it does, exactly. The bug isn't a mismatch from the author's
intent; it's that trusting an arbitrary structural donor's value for a
brand-new "Mask"-type slot is unsafe IN GENERAL, regardless of whether
the result happens to match what got shipped as an author's own real fix
elsewhere. Blind luck (the first-tested donor happening to be inert)
made this look safe before a different, equally-valid donor exposed it.

**Fix**: `apply_texture_overrides()` now treats any texture slot whose
name contains `"mask"` specially IF it's genuinely new to the mod's own
material (never blind for slots the mod already had -- those still
correctly keep the mod's own value, name-matched, exactly as before) --
if the donor's value for that slot isn't already a recognized inert
placeholder (`_looks_like_null_texture()`: filename starts with `"Null"`,
matching the `NullGray`/`NullNormal`/`NullBlack_Alpha_MSK4`/`NullWhite`/
`NullATOS`/`NullNormalRoughnessOcclusion`/etc. convention already used
pervasively across this game's own materials wherever an optional layer
is genuinely off), it's forced to `NullBlack_Alpha_MSK4.tex` instead of
trusting the donor's own UV-mismatched value. The mod never used this
feature at all, so there's no "correct" mask value to guess at -- forcing
it off is the only choice that can't be wrong.

Verified: all 5 of Bifrost's migrated materials now get `DetailMaskMap`
forced to the inert default (confirmed via direct log output), full
regression suite unaffected (this only fires for a texture slot that's
both brand-new to the mod AND name-matches "mask" AND isn't already an
inert placeholder -- none of the standard regression mods' materials hit
this path at all). Not yet re-confirmed in-game by the user -- a new
build (`OVR Rogue - Bifrost (fixed, shader-migration, mask-safe).zip`)
was sent for that.

**Postscript: the mask fix was correct but was NOT the hair bug's cause
-- see #30, which found the real one.** (The mask fix stays: donor-value
bleed through a UV-specific mask on a brand-new slot is real regardless,
it just wasn't what this particular symptom was.)

## 30. avp self-reference "fix" (#19) REVERSED -- cross-slot avp references are deliberate, and rewriting them broke hair-hide (2026-08-09)

The #29 mask fix did not resolve the reported hair-poking-through-helm
symptom. The user then supplied the decisive observation: the very FIRST
hand-built Bifrost file (this session's original shader-migration
experiment) never had the bug, while every tool-built version did --
and the author's own updated release doesn't have it either.

Diffed all four variants' `041_001_avp.user.3`:
- OLD original mod: references `.../Armor/Male/036/000/036_000_avp.user`
- AUTHOR's own updated release (works): SAME 036/000 reference, kept
- Hand-built first experiment (works): SAME 036/000 reference (that build
  only swapped 5 mdf2 files, never ran `process_mod()`, so the avp fix
  never touched it)
- Every tool-built version (hair pokes through): reference rewritten to
  `041/001` by #19's `_fix_avp_self_reference()`

**The #19 hypothesis ("templating leftover pointing at the wrong slot")
was wrong.** The mod's helm BORROWS armor set 036's mesh -- its material
is literally named `ch03_036_0003_helm_UseSC` -- and the avp referencing
036's avp is how the borrowed helm receives 036's correct hair-hide
parameters (`PlayerArmorVisualParam` governs per-piece hair-hide flags).
The author's own update RETAINING the "wrong"-looking reference is the
decisive evidence it's deliberate. Rewriting it to the mod's own slot
(041) pulled vanilla 041's visual params instead, whose hair-hide flags
don't match the borrowed 036 helm shape -- base hair pokes through. And
the #19 fix never actually fixed anything real anywhere: the white-
texture symptom it was chasing turned out to be the retired-shader issue
(#24/#25), entirely unrelated.

**Fix: reversal.** `_fix_avp_self_reference()` is now
`_report_avp_cross_slot_reference()` -- logs an `[info]` line when a
cross-slot reference exists (still useful debugging information) but
NEVER modifies the file. `resolve_and_fix_avp_files()` kept its name
(call-site stability) but is diagnostic-only and always returns
`{"fixed": 0}`. There is no way to distinguish "deliberate cross-slot
borrow" from "genuine templating mistake" from file structure alone, and
the only real-world case ever observed is the deliberate kind -- so
never rewrite.

Broader lesson, same shape as #26's: a mechanically-verifiable
"inconsistency" (mod file differs from the vanilla-donor convention) is
not the same thing as a defect. Both #19 (avp) and the original blunt
staleness check (#24) failed by treating "differs from vanilla donor" as
"wrong". Vanilla conventions describe vanilla content; mods break them
on purpose.

Verified: rebuilt Bifrost through the full current pipeline
(`OVR Rogue - Bifrost (fixed v3, avp-untouched).zip`) -- avp keeps the
author's 036/000 reference byte-identical, shader migration + #29 mask
fix still apply to all 5 materials, full regression suite byte-identical
(none of those mods have avp files at all). **CONFIRMED in-game by the
user ("아주 잘 작동해"): hair renders correctly under the helm, the full
fix chain (shader migration + mask neutralization + avp left untouched)
is now end-to-end verified on this mod.** This closes the Bifrost saga:
the original white-texture/missing-wings report needed the retired-shader
migration (#24/#25), the helm hair bleed needed BOTH #29's mask fix AND
this reversal -- and the avp rewrite (#19) turned out to be a bug this
project itself introduced along the way, not part of any fix.

## 31. DOA "Rachel" CRASH: variant-tolerant donor tier silently downgraded a living shader -- exact-mmtr tiers now run first across all scopes (2026-08-09)

Real report with a perfect three-way test set (user supplied broken
original + our tool's output + the author's own working update): our
output crashed the game on equip. Three-way diff isolated it immediately:
every affected material uses `Base_Equip.mmtr` (fully alive, 310 users
game-wide), the author's working fix KEEPS that shader and just refreshes
the prop set (25 tex/187 props -> 25/191), while our output had
DOWNGRADED the material's shader itself to `Base_Equip_NoMultiBlend.mmtr`
(23 tex/176 props) -- and inconsistently: in the same 0015 file, 'cage'
happened to find an exact-mmtr donor (correct 25/191 result) while its
two sibling materials got the downgrade.

**Root cause -- the no-exact-name blind spot of #16's fix.** #16 only
covered the case where a SAME-NAMED vanilla donor exists with a different
mmtr; Rachel's materials have no same-named vanilla counterpart at all,
so donor resolution went straight to the own-file VARIANT-tolerant mmtr
tier -- and this slot's current vanilla file only carries the narrower
`_NoMultiBlend` sibling, which `apply_texture_overrides()` then (by
design -- mmtr comes from the donor) wrote in as the material's new
shader, stripping its MultiBlend slots/props.

**Fix**: `find_donor_for_material()` now runs EXACT-mmtr tiers across
all three scopes (own-file -> cross-piece -> whole-game) BEFORE any
variant-tolerant tier. A wider-scope donor with the right shader beats a
nearby donor with the wrong one; variant tolerance remains strictly a
last resort for a shader with genuinely zero live users anywhere (its
original retired/split-shader purpose).

Ripple effects, all inspected rather than assumed: SilverWolf and
DoA_Raise_the_Sail's regression stats shifted slightly (29->24 and
206->208 textures_restored) -- traced each donor change and they were the
SAME latent downgrade bug being fixed in those mods too (e.g.
SilverWolf's 'sw' materials had been silently matching NoMultiBlend
variants all along); zero errors, zero unresolved. The author's new
Bifrost now comes back fully `already_current=7, fixed=0` (previously
one material was still being pointlessly rebuilt). Rachel's rebuild now
matches the author's own fix shape exactly (every material Base_Equip
25/191, `DOA - Rachel (fixed v2).zip`) -- **CONFIRMED working in-game by
the user.**

Running tally of the "differs from vanilla convention is not a defect"
lesson (#24 staleness direction, #30 avp, now #31 shader variants): all
three of this project's self-inflicted bugs this session came from
trusting the nearest vanilla structure over the mod's own still-valid
choices.

## 32. TiNE Qipao crash RESOLVED -- it was #29's mask bleed all along (2026-08-09)

Bisection converged fast: a Body-only-migrated build (everything else on
the known-good gpbf-only base) still crashed -- but that build predated
the #29 mask fix. Rebuilding the SAME Body-only bisect through the
CURRENT pipeline (DetailMaskMap neutralized on all 4 Fur materials)
**eliminated the crash entirely, confirmed in-game by the user** -- the
outfit now renders correctly, matching the mod's reference screenshots.

So the #26 crash and the #29 Bifrost hair-bleed were the SAME underlying
bug -- a migrated material inheriting the donor's own non-null
`DetailMaskMap` -- with wildly different symptoms per mod: a cosmetic
texture bleed on Bifrost, an immediate hard crash on equip for Qipao.
(Why the same bad data crashes one mod and only discolors another is an
engine-internals question this project can't answer from files alone;
what matters is that the single fix provably resolves both.) #26's
"different pipeline/community" hypothesis for the crash is thereby
retired -- the pipeline difference was real but irrelevant; the crash
trigger was ours. The shader migration feature's risk posture can be
softened accordingly: its one known crash is now explained AND fixed,
though it stays opt-in (the #26-era warning text still overstates the
danger slightly -- acceptable; overwarning is the safe direction).

Full-mod final build (`TiNE's Qipao Ver.R Remastered (fixed final).zip`,
79 materials migrated across all sub-options, 79 masks neutralized, zero
errors) -- **CONFIRMED fully working in-game by the user ("완벽하게
작동해")**. Both mods that ever exercised the shader-migration path
(Bifrost, Qipao) are now end-to-end verified on the current pipeline.

## 33. Armor slot RETARGETING: two manual moves fully verified in-game (2026-08-09)

New capability territory, prompted by a community reference document the
user supplied (`MHWs 방어구ID 한글ver (개인모드팩용).xlsx`, original by
Quaysar/RayVVV, Korean translation by 몬붕이): a per-slot × per-variant ×
per-piece matrix of which physics components exist on every ch03 armor
slot -- `clsp` (via.character.CollisionShapePreset), `chain` (chain
physics), `gpuc` (GPU cloth, noted as UNEDITABLE by any current tool --
avoid replacing gpuc-bearing pieces), plus slinger presence. This is
effectively a mod-slot COMPATIBILITY table: a mod built for slot A can
move to slot B when B's variant has a matching per-piece physics profile.

**Two real moves performed and both CONFIRMED working in-game:**
1. OVR Rogue Bifrost: 041/001 (블랑고) -> 051/001 (아티어)
2. TFD Bunny (Ultimate): 051/001 (아티어) -> 012/001 (라바라) -- resolving
   the slot collision the first move created.

**The verified recipe** (both mods were the loose-file Chinese-community
pipeline: mesh+mdf2+chain2/clsp/jcns/sfur+HairAdjustList+avp, no pfb):
1. Pick a target slot whose variant physics profile matches the source's
   (both cases: all five pieces `clsp chain`, slinger present).
2. Verify the target's vanilla files all exist in the live game (every
   piece's mdf2/mesh, the avp, all six pfbs, HairAdjustList) -- via
   `find_versioned_path()`.
3. Relocate by PATH-PART renaming only: directory part `<src_set>` ->
   `<dst_set>` (exact-part match, never substring), filename prefixes
   `ch03_<src>_` -> `ch03_<dst>_`, and `<src>_<var>_avp` ->
   `<dst>_<var>_avp`. (First attempt used string-level substring replace
   on the whole relative path and silently failed to rename the DIRECTORY
   components -- part-level replacement is the correct primitive.)
4. Touch NOTHING inside any file. Internal cross-slot references are
   deliberate and slot-independent: Bifrost's avp references 036's avp
   (borrowed-helm hair-hide, #30), Bunny's references 023's -- both stay
   valid wherever the files live. mdf2 texture paths referencing the OLD
   slot's vanilla textures also stay valid (vanilla files exist
   regardless of which slot the mod occupies).
5. Version-suffix mismatches that MIRROR the source slot's own
   relationship are fine: both mods ship `chain2.14` while vanilla (both
   source and target slots) is `.13` -- that exact mismatch was already
   the shipped, in-game-working state at the source slot. sfur files with
   no vanilla counterpart at the target also mirror the source (041 had
   none either).
6. The mod's own texture `.pak` sub-folders are slot-independent (hashed
   custom paths) -- copy through untouched.

**Feature decision (user + assistant aligned)**: this should become a
built-in MHWmodfixer feature rather than a separate tool -- ~90% of the
needed infrastructure (pak index, version lookup, path handling, parsers)
already exists here, and the xlsx table can be baked into a bundled data
file to power a compatibility-checked target-slot picker. Not yet built
-- the two manual moves above are the validation groundwork.

## 34. Shipped: "적용 방어구 변경" (Change Target Armor) -- the #33 recipe as a real feature (2026-08-09)

Turned #33's two hand-verified moves into an actual opt-in tool feature.
Three new pieces:

- **`tools/bake_armor_slots.py`** -- one-time baker, converts the
  community xlsx into `tools/armor_slots_ch03.json.gz` (180 slot-variants,
  123 with a usable per-piece physics profile; the sheet's personal
  mod-pack annotation columns are dropped, only objective data is kept).
  A slot with no parseable per-piece data (accessory rows the sheet only
  annotated `chain O`/`chain X`) gets `pieces: null` and is EXCLUDED from
  automatic matching entirely -- never guessed at.
- **`slot_retarget.py`** -- the actual logic, a direct code translation of
  #33's verified recipe: `detect_mod_slot()` (regex over the mod's own
  paths/filenames for `ch03/<set>/<variant>/`), `find_compatible_targets()`
  (ranks every table slot by physics-profile match: `exact` / `partial`
  [some target piece lacks `chain`] / `gpuc` [target piece has uneditable
  GPU cloth -- always ranked worst, per the sheet's own explicit warning]),
  `verify_target_vanilla()` (live-game completeness check per candidate --
  every piece's mdf2/mesh/pfb + the avp), and `retarget_tree()`
  (PART-level path/filename renaming only, `ch03_<src>_` -> `ch03_<dst>_`
  and `<src>_<var>_avp` -> `<dst>_<var>_avp`, followed by a hard safety
  scan that raises if ANY source-slot trace survives in the output tree
  -- file CONTENT is never touched, matching #33's established recipe
  exactly).
- **GUI wiring** -- a `btn_retarget` button next to Settings in the main
  window's top row (plus a ⓘ hover tooltip explaining the feature, via a
  new small `_Tooltip` helper class), opening a **separate `Toplevel`
  dialog** (`_open_retarget_dialog`), not a tab next to the repair flow.
  User's own explicit call ("탭으로 분리하는거보다 따로 빼는게 일단은
  안전해") -- the two features have unrelated workflows (batch-repair-many
  vs pick-one-and-choose-a-target) and a tab risked visual confusion with
  the main repair flow; a separate window is the safer, smaller-footprint
  change. The dialog: file picker -> background-thread detection (same
  `threading.Thread` + `win.after(0, ...)` cross-thread pattern already
  used by the RSZ Snapshot dialog's GitHub-fetch) -> a `ttk.Treeview`
  compatibility table (new to this codebase -- `_apply_theme()` gained
  Treeview/Treeview.Heading style rules, color-tagged rows by grade:
  green=exact, amber=partial, red=gpuc) -> live-verify the SELECTED target
  only (not all 85+ candidates up front, for responsiveness) -> save.

**Naming, decided directly with the user.** First considered a tab-bar
design (see the artifact mockups from this session) with a raw "슬롯"
label -- the user asked for something non-modders would understand:
"기능 명칭을 더 직관적으로 바꿔야겠어." Settled on **"적용 방어구
변경"/"Change Target Armor"** (describes the action in plain terms, no
"slot" jargon) with a ⓘ tooltip carrying the fuller explanation, so the
button label itself stays short.

**Gender labeling, a real correctness fix caught before shipping.** The
sheet's 번호2 (variant) column -- e.g. `000`/`001` -- looked like it might
mean character gender directly, per the user: "번호2 컬럼에 000은 남성
001은 여성이거든... 그냥 000 001로 표기해버리면 성별이 헷갈리니까."
Checked this against the live game first rather than assuming the pattern
holds: **both a `Armor/Male/<set>/<variant>/` and
`Armor/Female/<set>/<variant>/` avp exist for every set/variant number**
(both genders' character models ship separate art for every armor,
independent of the variant number) -- so 번호2 is NOT the game's own
male/female axis, and blindly labeling every variant ending in `0` as
"male" would be wrong for the many single-variant accessory rows (e.g.
`089/000` "깃 한 가닥 목걸이", a necklace -- not gendered at all). The
real pattern, confirmed across every example checked (`041 000/001`,
`030 600/601`, `017 300/301`, etc.): within the SAME armor set, a variant
ending in `0` paired with a sibling ending in `1` (same leading digits)
is that armor's male cut / female cut respectively. `bake_armor_slots.py`'s
`_assign_genders()` implements exactly this -- pairs siblings within a
set, labels both sides, and leaves any variant with no such sibling
(every real accessory checked) unlabeled. `slot_retarget.gender_label()`
renders it as 남성/여성 (ko) or Male/Female (en) wherever a slot is shown
in the UI -- raw `000`/`001` numbers are never surfaced to the user
directly, exactly the ask.

**Verified end-to-end, not just at the module level.** Headless GUI
smoke tests (a real `TkinterDnD.Tk()` root + `root.mainloop()`, since the
cross-thread `Toplevel.after()` callback this dialog uses needs an
actual running Tcl mainloop -- manual `update()` pumping alone raises
`RuntimeError: main thread is not in main loop`) drove the REAL dialog
code path: clicked "Choose...", waited for the background detection
thread, confirmed the Treeview populated with 85 correctly-labeled
candidates for TFD Bunny's `012/001` slot, then selected a target and
clicked "Generate Relocated File" -- the resulting file was diffed
byte-for-byte against an equivalent core-only `retarget_archive()` call
and matched exactly. Also re-ran the standard SilverWolf/DoA regression
suite (unaffected -- this feature is a wholly separate module, doesn't
touch `auto_fix.py`/`slot_merge.py`/`pfb_fix.py` at all) plus both #33's
original hand-verified Bifrost/Bunny relocations through the new
`retarget_archive()` function and confirmed byte-identical output to
those in-game-confirmed-working files. Not yet a fresh in-game test of
the SHIPPED feature specifically (the underlying recipe already has two
independent in-game confirmations from #33) -- if a future session ships
a NEW relocation via this GUI, treat the first one as worth a quick
in-game check same as any other new capability.

## 35. Retargeting extended to multi-slot mods (per-slot decisions), plus a real ch02/male gap and a real async-exception bug (2026-08-09)

Right after #34 shipped, the user asked directly whether mods with lots of
FOMOD suboptions (DOTEI's EULA was the concrete example) work with this
feature. Tested DOTEI's real mod (`C:\Users\User\Desktop\dotei\`) and
TiNE's Qipao against `detect_mod_slot()` -- both come back as the
"ambiguous, refuse" case #34 shipped: DOTEI genuinely spans 5 different
armor slots (a dominant one, `043/600`, plus 4 slots' worth of custom
textures the author stashed in unrelated slots' folders via a "TEXTHERE
FILE" FOMOD page), and Qipao ships two FULL slots' worth of piece files
(`006/000` and `006/001`) in the same "Body" page. Refusing outright was
too blunt -- the user's call: **"부수적인 옵션들도 다시 선택하거나 하는
옵션으로 완전히 전부다 이동할 수 있게 하는게 맞아"** (let the incidental
ones be reassigned too, via their own choice, so EVERYTHING can move) --
not "leave incidental files where they are" (which the user explicitly
rejected first: "그러면 안되거든", correctly noting that a piece file
left in place is really a piece STAYING active at its old slot, not
neutral, unlike a texture that's just referenced by absolute path).

**New multi-slot API in `slot_retarget.py`**: `detect_mod_slots()` (plural,
never refuses) returns one `ModSlotGroup` per distinct slot found PLUS the
list of files matching no slot pattern at all (always pass-through,
untouched, regardless of any group's assignment). `retarget_tree_multi()`/
`retarget_archive_multi()` take `{group.key: (dst_set, dst_variant) | None}`
-- `None` is an explicit, deliberate "leave this slot's own files exactly
where they are," not a default. Every detected group MUST have an entry
or `retarget_archive_multi()` refuses -- a GUI can never silently ship a
half-decided mod. Each reassigned group is built in its own isolated
staging directory before merging into the final output, so one group's
freshly-relocated files can't spuriously trip (or hide from) another
group's own leftover-trace safety scan.

**Real bug found via this exact multi-slot testing, not theoretical**:
the first version only matched `ch03` (female) paths -- DOTEI's real
files revealed the game ships PARALLEL `ch02` (male hunter) content at
the *identical* slot numbers for every armor (confirmed live: every
tested set/variant has both a `ch02` and `ch03` folder, and both a
`Armor/Male/.../avp` and `Armor/Female/.../avp`). Moving only the `ch03`
half of an armor while leaving `ch02` at the old slot number would have
been a real, silent half-move -- a male-hunter player's outfit stays
behind. Fixed: `_MODEL_SLOT_RE`/`_PIECE_FILE_RE_TMPL` now match `ch0[23]`
so both genders' files land in the SAME group and move together;
`retarget_tree()`'s filename-prefix substitution now captures and
preserves which of `ch02`/`ch03` a file already was (never coerces one
into the other), and `verify_target_vanilla()` checks BOTH the male and
female avp at the target. Note this "ch02 vs ch03" axis (which
PLAYABLE-CHARACTER gender an armor copy is for) is completely orthogonal
to #34's "번호2 variant" gender labeling (which CUT/style of the SAME
armor, within one gender) -- confirmed both axes are real and
independent, not two names for the same thing.

**Real async-exception bug found and fixed, pre-existing since #28 and
shipped in commit `126edcc`, not new to this session's rewrite**: every
`except Exception as exc: win.after(0, lambda: ...t(..., e=exc)...)`
pattern in this file raises `NameError: cannot access free variable
'exc'` the moment the deferred lambda actually runs -- Python unbinds an
`except ... as name:` variable the instant that except BLOCK exits, but
the lambda only captures the NAME by closure, and `win.after(0, ...)`
runs it on a later mainloop tick, after the block (and the binding) is
long gone. Caught by a real headless GUI test hitting a real error path
(feeding a bad archive), not by inspection. Fixed at all 3 async call
sites (RSZ Snapshot's GitHub-fetch worker, and both of this feature's
workers) by formatting the message string with `t(...)` INSIDE the except
block (while `exc` is still bound) and closing over that plain string
instead. The synchronous call site (snapshot import, not deferred through
`win.after`) never had this bug and was left alone.

**GUI redesigned around a two-tier Treeview**: a "감지된 방어구 슬롯"
list (one row per group, with a live status column: "결정 필요" /
"그대로 유지" / "→ move to X") plus a "변경 가능한 방어구" compatibility
list scoped to whichever slot is currently selected, with "이 슬롯에
적용"/"이 슬롯은 그대로 두기" buttons recording a decision per slot.
Generate stays disabled until every row's status is resolved.

**Verified end-to-end against DOTEI's actual mod, through the real GUI
code path** (zipped the real folder, drove the dialog via a Tcl
mainloop-based test exactly like #34's, picking the dominant slot's top
candidate and explicitly leaving all 6 incidental slots unchanged):
output file's main slot fully relocated (zero leftover trace, now
absorbing `ch02` files too -- 27 -> 32 files vs the pre-ch02-fix run),
all 6 incidental slots' files verified byte-identical at their ORIGINAL
path. Also core-tested reassigning Qipao's BOTH detected slots to two
DIFFERENT real targets simultaneously (not just "one moved, rest left") --
both relocated correctly, zero cross-contamination, zero leftover traces
of either original slot number. Standard regression suite unaffected
(this module still never touches `auto_fix.py`/`slot_merge.py`/
`pfb_fix.py`).

## 36. Mask Bikini's chest physics saga (#17/#18) resolved -- by the author, not by this project (2026-08-09)

The mod's own author (Mangie) shipped a new source file
(`C:\Users\User\Desktop\mangie\source\[MHWilds] Mask Bikini.zip`) that
now bundles real `.pfb` files at the correct vanilla paths (it previously
didn't -- only loose `mh03`-substituted mdf2/chain2/clsp). Checked every
piece's own bytes directly against the CURRENT registry/donor, independent
of any of this project's repair logic:

- `rsz_layout.fits_current_layout()` returns **True** for all 5 pieces
  (Arm/Body/Helm/Leg/Waist) -- each parses to an exact byte count under
  the live game's own field layout, zero alignment-padding issues.
- **Zero CRC mismatches** between the mod's own instances and the current
  donor's, for every shared type across all 5 pieces.
- Body/Leg carry the exact 3 real chest/leg-physics instances this
  project spent items #17/#18 trying (and ultimately failing, due to an
  unfixable boot-time race condition) to preserve: `via.motion.Chain2`,
  `via.motion.ChainWind`, `via.motion.ChildSecondary` -- now present
  NATIVELY in a properly-shaped file, not spliced in after the fact.

Running the current pipeline against this file confirms it needs **zero
pfb repair of any kind** -- `pfb_fixed: 0, pfb_crc_only: 0, pfb_unresolved: 0`
across all 5 pieces, and a direct byte-for-byte input-vs-output diff
confirms every `.pfb` passes through this project's tooling completely
untouched (correctly recognized as already-current, extras and all).
Only the loose mdf2 materials needed the usual donor-matching (some
`mask_UseSC`/`skin` materials had multiple same-mmtr candidates, resolved
via the existing tie-breaking logic in `_pick_best()`).

**The actual lesson, worth stating plainly**: #18's conclusion --
"no file this project can produce, however byte-perfect, can reliably
survive MHWilds' own boot-time equipment initialization once it carries
NEW physics content that didn't exist in the last officially-shipped
state of that GameObject" -- was specifically about content assembled
via POST-HOC byte editing (splice/transplant onto an existing pfb this
project didn't originally author). It was never a claim that chest
physics on this armor is impossible in general. The Caimogu community
tutorial referenced in #19's research section ("从零开始的手搓物理-Chain2")
already said as much: real chain physics needs to be authored through
the actual Blender + RE-Chain-Editor pipeline (bones named `xx_00...xx_end`,
weight-painted, then "Create Chain From Bone"), not reconstructed from
raw bytes after the fact -- and that's evidently what changed between the
old and new Mask Bikini source. Delivered as
`[MHWilds] Mask Bikini (fixed, chest physics intact).zip` in
`C:\Users\User\Desktop\CC download\` -- awaiting in-game confirmation,
but for the first time on this mod, both the boot-time-race concern (no
byte surgery involved at all -- the file is untouched) and the physics
preservation are simultaneously satisfied.

## 37. `fluffy_repackage.py` generalized to multi-page mods with loose leftovers, Mangie-aware exact reordering, and a real "produces no output" gap fixed (2026-08-09)

Prompted by testing Mask Bikini's own Fluffy install: "야 너 플러피 fomod 설정으로 안만들었지?" -- checked, and this project's own output correctly preserved the mod's existing page structure byte-for-byte (`fluffy_repackage.py`'s original rule already refuses to touch a mod with >1 modinfo.ini folder). But the user then explained the REAL problem is upstream, in the author's own release: Mangie's raw "Mask Bikini" archive has 2 working pages (Main, Open Mask) but 3 more pieces (Alma.pak, Gemma.pak, Textures.pak -- one of them README-marked REQUIRED) sitting as loose top-level files with no page at all, so Fluffy's page-selector never offers them. **"그러면 안되거든 ... 재정렬/재빌딩해주는 작업이 필요해"** -- this needs fixing, automatically, not as a manual toggle ("별다른 자질구레한 수동 선택 옵션 추가보다 자동으로 판독해서 대응해주는게 유저한텐 좋지").

**Why this specific gap exists**: `needs_repackaging()`'s original rule was `len(folders) != 1: return False` -- built and tested only against the ORIGINAL single-folder-plus-extras shape (Banshee/MooMoo's raw releases). Mask Bikini has 2 folders already, so it was being treated as "already fine," even though it plainly wasn't. The user's own read on WHY this keeps happening specifically to Mangie's releases: **"망기는 MO2를 써서 플러피에서 겪는 저런 문제에 대해서 별로 신경을 안쓰는거 같다는 느낌"** -- MO2 has no concept of Fluffy's page-selector at all, so an author who only ever tests via MO2 would never notice this gap in their own releases.

**Fixed with two coordinated changes:**
1. `needs_repackaging()`/`repackage_for_fluffy()` now trigger on ANY number of existing modinfo.ini folders (not just exactly one), as long as loose un-paged extras remain. The two shapes are handled differently: the ORIGINAL single-folder case is completely unchanged (verified byte-for-byte against the untouched code path); the new multi-folder case never touches the EXISTING folders unless the author is specifically recognized as Mangie (see below) -- for an unknown author, only the loose extras get wrapped into new trailing pages, continuing whatever numeric prefix style ("01."/"02.") already exists, since this project has no real evidence about what page ORDER an unknown author's mod actually wants.
2. `_is_mangie_mod()` checks `author`/`category` in an existing page's own modinfo.ini (`MangieW` / `Mangie's Modding` in every real example seen). When true, applies a smarter, EXACT reproduction of a real community fix the user supplied as a reference (`C:\Users\User\Desktop\mangie\Mangie Mask Bikini.zip`, an older content version but with hand-corrected Fluffy structure): renumber every page from 0, with a "Textures" extra inserted right after the main page (matching the mod's own README, which always marks Textures required alongside the main file) and ahead of cosmetic option pages -- verified to reproduce that reference's exact page order (`0. Main File / 1. Textures / 2. Open Mask / 3. Alma / 4. Gemma`) when run against the mod author's actual current (physics-fixed, #36) source.

**Real, separate bug this surfaced and fixed**: `gui.py`'s `_run_one()` had an early-exit gate -- `if not needs_fix and not unresolved_plans: return "already_current"`, with literally NO output file ever written -- that ran BEFORE `repackage_for_fluffy()` was ever reached. A mod whose CONTENT is already fully current (Mask Bikini's own case, per #36 -- `pfb_fixed=0` across the board) but whose Fluffy STRUCTURE still needs fixing would previously report "already up to date, nothing to fix" and produce nothing at all, even though repackaging alone was exactly what was needed. The user surfaced this directly: some Fluffy users just take an author's latest file and manually repackage it themselves for structure only, without needing any content repair, and the tool should support that use case too, not just "does content need fixing." Fixed by checking `fluffy_repackage.needs_repackaging(mod_root)` alongside `needs_fix` at the gate: when content needs nothing but the structure does, skip straight to a plain copy + `repackage_for_fluffy()` (no need to run the full, here no-op, repair pipeline) and still produce output, logged distinctly ("content is already up to date -- only the Fluffy page structure needed fixing"). The genuine "nothing to do at all" case (neither content nor structure needs anything -- confirmed against the author's own already-fixed new Bifrost) still correctly produces zero output, unchanged.

Verified: the single-folder MooMoo/Banshee-style regression path is provably untouched (same code, unreached by the new branch since `len(folders) > 1` routes elsewhere); Mask Bikini's real archive reproduces the reference's exact page order end-to-end through the REAL `gui.py::_run_one()` code path (not a reimplementation), including the new "content current, structure only" branch actually firing and producing a correctly zipped, correctly Fluffy-paged, content-fixed-and-chest-physics-intact output; the standard `pfb_unresolved`-present case (SilverWolf) and the standard true-no-op case (author's new Bifrost, zero files produced) both still behave exactly as before. Delivered as
`[MHWilds] Mask Bikini (fixed, Fluffy-ready).zip` in `C:\Users\User\Desktop\CC download\`.

## 38. Armor names in "적용 방어구 변경" now show in English too, when the UI language isn't Korean (2026-08-09)

The retarget dialog only ever showed armor names in Korean (straight from the source spreadsheet), regardless of the app's own selected UI language -- confirmed by a real screenshot, English UI, Korean armor names in the table. User's own framing for the fix: only bother with real translations where a source actually exists to verify against, and en-only is fine for ja/zh_tw/zh_cn (no need to hunt down 3 more translations for names this project can barely verify once).

**Source used, NOT guessed from memory**: the user's own installed REFramework Lua mod ("FemaleBodySliders", already present in their game folder from the unrelated `AltArkveldAArmor` investigation earlier this session) maintains a real (set,variant)-keyed English armor-piece-name table for its own UI (`reframework/autorun/FemaleBodySliders/ExtraLayeredArmorDictionary.lua`). Parsed it programmatically (170 (set,variant) entries across 78 sets), matched against this project's own (set,variant) keys, and cross-checked a handful of stale/garbled entries (internal dev names like "Rey Sand..."/"Udra Mire..."/"Dahaad Shard..." instead of the shipped names) against game8.co's confirmed MHWilds armor-set roster before trusting them.

**77 of 104 Korean names resolved this way; the remaining 27 (mostly unique/DLC accessory items with no monster-name convention to cross-check against) are deliberately left untranslated** -- same "don't guess when the evidence runs out" discipline as everywhere else in this project; those keep showing Korean in every UI language rather than risk shipping a wrong name.

Implementation: `tools/bake_armor_slots.py` gained a `NAME_EN_OVERRIDES` dict (Korean name -> English), baked into each slot entry as `name_en` (null when unresolved). `slot_retarget.py` gained `armor_name(name_ko, name_en, lang)` (mirrors the existing `gender_label()` pattern) -- Korean UI always shows Korean; any other UI language shows the English name when available, Korean otherwise. `ModSlotInfo`/`ModSlotGroup`/`TargetCandidate` all gained a `name_en` field threaded through from the table. `gui.py`'s retarget dialog now calls `armor_name()` at all three display points (detected-slot rows, compatible-target rows, and the assigned-target status text).

Verified via the real GUI dialog with `i18n.set_language("en")`: detected slot and compatibility-list rows now show "Doshaguma", "Lala Barina", "Congalala", "Uth Duna", "Rey Dau", etc. in English; a Korean-UI run still shows Korean (regression check); an entry with no confident translation still falls back to Korean even under English UI (confirmed directly, not just by code inspection).

**Follow-up pass, same day**: the user confirmed one name directly from the
game (`병사의 갑주(디럭스)` = "Feudal Soldier", a Deluxe Edition bonus set
the Lua source didn't cover). Also cross-checked the remaining unresolved
names against `mhwilds.kiranico.com`'s armor-series list, fetched in BOTH
Korean (`/ko/data/armor-series`) and English (`/data/armor-series`) --
both pages list every series in identical underlying order, so aligning
them position-by-position gives a direct, non-guessed pairing (held
correct across 90+ consecutive positions with zero mismatches before
diverging into content outside this project's own ch03 scope). This
**corrected several of the FIRST pass's own over-specified guesses** --
Kiranico's real armor-menu names are shorter than the full monster name
for several sets (`고어`/"Gore Magala" -> "Gore", `블랑고`/"Blangonga" ->
"Blango", `콩가`/"Congalala" -> "Conga", `다하딜라`/"Jin Dahaad" ->
"Dahaad", `호뢰악룡`/"Guardian Fulgur Anjanath" -> "Guardian Fulgur",
`호흉조룡`/"Guardian Ebony Odogaron" -> "Guardian Ebony") -- worth
remembering: a correct-*sounding* guess (the full canonical monster name)
can still be wrong for the specific in-game armor-menu label; always
prefer a real second source over a plausible extension of the first.
Also resolved 9 previously-unmatched names this way (`네라치카`=Comaqchi,
`브라치카`=Bulaqchi, `스자의 허리띠`=Suja's Belt, `용왕의 척안`=Dragonking's
Third Eye, `대식가의 귀걸이`=Gourmand's Earring, `헌신의 피어스`=Earrings of
Dedication, `탈리오스`=Talioth, plus `고우키`=Akuma [MH's Street Fighter
collab set -- confirmed directly by the user] and `노블레스`=Noblesse [a
plain loanword, no external check needed]). Coverage: 86/104 Korean names
now have a confident English pairing; the remaining 18 (mostly unique/DLC
accessory items -- eyewear styles, wigs, earrings -- Kiranico's
armor-series page doesn't cover non-series accessories at all) are still
deliberately left in Korean.

## 39. Real multi-language armor names -- sourced directly from the game's own localization file, not a wiki (2026-08-09)

The user's own question after all the manual name-hunting above: "게임 설치폴더 내에 번역 스트링 파일 같은거 없을까?" (isn't there a translation string file in the game's own install folder?) -- and yes, there is. RE Engine games ship their UI text as "GMSG" `.msg` files; armor set names specifically live at
`natives/stm/gamedesign/text/excel_equip/armorseries.msg.23`, confirmed present and readable via this project's own `game_archive.py` (1.9MB). Found the exact path via `LartTyler/mhdb-wilds-data`'s `config.toml` (a real community MHWilds-DB extraction pipeline, not guessed) -- `input_prefix = "STM/GameDesign/Text"` + `Excel_Equip/Armor.msg.23` / `ArmorSeries.msg.23` among its target list.

**New `tools/msg_reader.py`** -- a from-scratch, read-only GMSG parser. Same provenance model as `mesh_check.py` (see that file's own docstring for the precedent): learned the real format (header layout, an XOR-chain string-pool decryption scheme, the entry/language-table walk) by reading REasy's own `MsgHandler` (`seifhassine/REasy`, `file_handlers/msg/msg_handler.py`, LGPLv3) as a reference, then wrote fresh, independently structured code with none of REasy's Qt/`BaseFileHandler` dependencies (this project only ever needs the read path, never write). Verified correct by cross-checking its output against Kiranico's own already-confirmed Korean/English pairs -- exact match on every entry checked.

**This is strictly better than every earlier approach in #37/#38** -- no guessing, no wiki cross-referencing, no risk of a stale/wrong community source: it's the exact text string the game itself displays, and critically, it carries EVERY language the game ships (`via.Language` codes 0=Japanese, 1=English, 11=Korean, 12=TraditionalChinese, 13=SimplifiedChinese, plus more this project doesn't need), not just an English fallback. This retires the earlier "en-only for non-Korean UI, not worth chasing ja/zh separately" compromise from #38 -- the data was sitting right there once the right file was found.

**One real format wrinkle, found and handled, not glossed over**: a monster with no low-rank armor tier at all (confirmed: several elder-dragon/late-game monsters -- Arkveld, Gore Magala, Rathalos, Blango, etc.) has ONLY tier-suffixed entries in the file (`이름α`/`이름β`/`이름γ`, Korean suffix appended directly with no space; the corresponding English/ja/zh values carry the suffix space-separated, `"Name α"` -- confirmed by direct inspection of the parsed bytes, not assumed) and never a bare `이름` entry, while this project's own sheet names a whole SERIES with one flat name regardless of rank. Handled by falling back to the α-tier entry (stripping the suffix back off both sides) whenever no bare entry exists -- jumped `bake_armor_slots.py`'s live-game-matched count from 69/104 to 156/104-worth-of-slot-variants on the first attempt at this fix.

**A handful of the sheet's own Korean text differs cosmetically from the game's real spelling for the identical set** (missing/extra space, a compound word the sheet appends that the game's own name doesn't carry, a single-syllable variant) -- found via fuzzy substring matching against the real game data once the α-tier fix still left a few unexpectedly unresolved, not guessed: `수호룡세크레트`→`수호룡 세크레트`, `실드후드`→`실드`, `블로썸`→`블로섬`, `길드 크로스`→`길드크로스`. A small `KO_NAME_ALIASES` table in `bake_armor_slots.py` bridges these so they still resolve to real game-sourced translations in all 4 languages instead of falling back to English-only or nothing.

**Final coverage: 99/104 unique Korean names have game-sourced translations** in en/ja/zh_tw/zh_cn all at once (up from #38's 86 English-only names). The user directly questioned the first pass's "5 items ArmorSeries.msg doesn't cover" conclusion ("게임 내 데이터에 없을 리가 없는데") -- correctly: those 5 (검객의 척안(디럭스), 도깨비뿔 가발(DLC), 용인족 귀(DLC), 블루밍서클릿) WERE in `ArmorSeries.msg` all along, just under yet more of the same class of cosmetic spelling difference already seen twice this session (`검객 척안` vs the sheet's `검객의 척안(디럭스)` -- drops "의"/adds a "(디럭스)" qualifier the game's own name never had; `도깨비뿔 가발` vs `...(DLC)`; `용인족의 귀` vs `용인족 귀(DLC)`; `블루밍 서클릿` vs `블루밍서클릿`, another missing space). Four more `KO_NAME_ALIASES` entries resolved all of them with real per-language text. **`Accessory.msg` was a red herring** -- checked it directly and it turned out to hold decoration/skill-gem ("장식품") names, not cosmetic layered-armor accessories at all; never needed. The only 5 still unresolved are `내복?` and the 4 debug/placeholder entries the source spreadsheet itself never identified (`Debug body ?`, `fbxskel`, `内衣打底?`, `基础身体`) -- these may genuinely have no player-facing display text in the game at all, consistent with the sheet's own "?" markers.

**Architecture change**: `bake_armor_slots.py`'s hand-maintained `NAME_EN_OVERRIDES` dict (built by hand across #37/#38, English-only) is retired for anything the game data covers -- replaced by `_load_armor_series_names()` reading live from the currently configured game install at BAKE time (not runtime; the app itself never needs game access just to show a name, only to verify a retarget target actually exists). A small `ACCESSORY_NAME_OVERRIDES` dict (English-only, manually confirmed) remains for the handful of items outside the msg file's coverage. Each slot entry's schema changed from a single `name_en: str|None` to `names: dict` (`{"en"/"ja"/"zh_tw"/"zh_cn": str}`, only keys with a real value present) -- `slot_retarget.py`'s `armor_name()` and all three dataclasses (`ModSlotInfo`/`ModSlotGroup`/`TargetCandidate`) updated to match. Verified end-to-end through the real GUI dialog with `i18n.set_language("ja")` -- armor names render in real Japanese (e.g. `ラバラ` for Lala Barina, `ドシャグマ` for Doshaguma), not just English.

**Two real, separate follow-up bugs found by the user immediately after, both fixed same day:**

1. **The main window's "적용 방어구 변경" button itself never retranslated.** `_retranslate()` (called on every language switch) simply never listed `self.btn_retarget` -- confirmed via a screenshot: every other main-window label switched to Traditional Chinese, this one button stayed in English. One-line fix: added `self.btn_retarget.configure(text=t("btn_retarget"))` to `_retranslate()`.

2. **The retarget dialog itself never refreshed if the user changed language WHILE it was already open** -- confirmed directly by the user: "메인 화면에서 언어변경을 해도 방어구 변경 창을 닫고 다시 켜지 않으면 언어 변경한 게 반영이 안되네." Root cause: `_open_retarget_dialog()`'s widgets are all built once, from local closures, entirely outside `_retranslate()`'s reach -- there was no mechanism connecting the two at all. Fixed with a light hook pattern: `App.__init__` gets a new `self._retarget_refresh_fn = None`; `_open_retarget_dialog()` defines a `refresh_texts()` closure (re-applies every static label/column-heading/button text via `t()`, and re-renders the slot/candidate Treeview rows from the SAME already-stored `state["groups"]`/`state["candidates_by_key"]` data -- no re-detection needed, just re-formatting in the new language) and registers it as `self._retarget_refresh_fn` while open; `_retranslate()` calls it if set; both the Close button and the window's own [X] (`win.protocol("WM_DELETE_WINDOW", ...)`) clear the hook back to `None` on close, so a closed dialog's stale closure can never fire after the fact.

   **Investigating this surfaced a THIRD, quieter issue**, caught only by testing the live-switch end-to-end rather than trusting the refresh mechanism's code to be correct by inspection: after the hook fix, armor NAMES updated correctly (they're sourced from the just-added `names` dict, covering all 4 languages per #39) but the dialog's OWN UI chrome -- window title, column headers, button labels -- stayed in English regardless of target language. Root cause was NOT the refresh mechanism (which worked correctly throughout) but that literally every i18n key this session added for the retarget dialog (`dlg_retarget_title`, `col_*`, `btn_apply_to_slot`, `msg_retarget_*`, etc. -- ~35 keys) was only ever given `ko`/`en` values, silently falling back to English for ja/zh_tw/zh_cn exactly as `t()` is designed to -- inconsistent with the rest of this app's own established convention (nearly every OTHER i18n key already carries full 5-language coverage). Also caught the pre-existing shared `btn_close` key (used by the RSZ Snapshot dialog too, predates this session) in the same ko/en-only state. Filled in real ja/zh_tw/zh_cn text for all of them, matching the app's existing tone. Re-verified live: switching to Japanese mid-session with the dialog open now correctly updates the window title, column headers, row status text, grade labels, and the Close button, not just the armor names.

**Same-day follow-up: the user immediately found the identical bug in the OTHER dialog** (RSZ Snapshot Manager, Settings > Developer Options) -- "이 창도 언어변경이 실시간 적용이 안된다야." Same root cause, same fix: `_open_snapshot_dialog()` is also a standalone Toplevel built once, with no connection to `_retranslate()`. Applied the identical pattern -- `self._snapshot_refresh_fn`, a `refresh_texts()` closure (conveniently thin here, since the dialog's existing `refresh()` function already re-renders the whole info panel from fresh `t()` calls every time it's invoked for its original purpose of showing post-install results -- calling it again after a language switch was sufficient for that part; only the window title and the 3 buttons needed their own explicit `.configure(text=...)` calls), registered on open and cleared via both the Close button and `WM_DELETE_WINDOW`.

**A full audit this prompted** (checking every i18n key for complete 5-language coverage, not just the ones visibly broken) found the ENTIRE RSZ Snapshot dialog's key set (`dlg_snapshot_title`, `snap_*`, `btn_import_snapshot`, `btn_check_github`, `ask_confirm_download`, `ask_snapshot_role`, `msg_snapshot_*`, `err_*download*`, `filetype_snapshot`, `dlg_choose_snapshot`, `progress_phase_downloading_rsz` -- ~18 keys) was ALSO ko/en-only, unrelated to today's retarget-dialog work and predating this session entirely -- this whole developer-tools area had simply never gotten full translations. Also found `menu_settings`/`menu_dev_options`/`menu_rsz_snapshot` (the Settings dropdown itself) and `msg_partial_materials_hint` in the same state, plus a real self-inflicted regression: `tip_retarget`'s ja/zh_tw/zh_cn text existed at some earlier point but got silently dropped when the tooltip copy was rewritten to describe multi-slot support (#37) without carrying the other languages forward. Filled in all of it -- the project-wide `i18n._STRINGS` audit now reports zero keys with incomplete language coverage (110/110 keys, all 5 languages each). Lesson for next time: when editing an EXISTING i18n key's `ko`/`en` text, always check whether it already had `ja`/`zh_tw`/`zh_cn` siblings before overwriting the whole dict literal, and when adding a NEW key, add all 5 immediately rather than deferring non-Korean languages "for later" -- both of today's bugs trace back to that deferral, twice.

## 40. A real "mod died" support case (Arsinia "Ryan Reos Bunnysuit", Nexus 2793): a new transmog pattern, a native-type registry gap, and item #18's `app.ChainSetting` boot-time bug recurring in a totally unrelated mod (2026-08-10)

A user asked whether a specific reported-dead mod could be fixed. Investigated end to end rather than answering from the mod page description alone, and it's worth recording both the new pattern found and the outcome, since the honest answer turned out to be "partially, and the interesting part isn't safe to ship."

**Wrong premise caught before any code was touched.** The mod's description mentions "Modular Armor Framework" (MAF, a separate community REFramework Lua addon) and lets the user pick one of five transmog targets (Hope/Guild Knight/Innerwear1/Clerk/G-Earring FOMOD pages) to replace with the bunny outfit. The initial assumption was that MAF handles the target-slot choice at runtime (so this project's own tooling could never touch that part) and that our own slot-retargeting feature (#34) might be repurposed to "bake in" one fixed target instead. Both halves were wrong, found by actually opening the archive rather than trusting the description:
- MAF's own JSON definition (`reframework/data/ModularArmorFramework/Definitions/ArsiniaRRBunnysuit.json`) only toggles **submesh visibility** (jacket on/off, sleeves, pasties, gloves) live in-game -- nothing to do with which vanilla slot gets replaced.
- The Hope/Guild Knight/Innerwear1/Clerk/G-Earring choice is **already fully static**: each "Transmog X" FOMOD page ships a hand-edited copy of that REAL vanilla slot's own `.pfb` (e.g. `Armor/Female/001/001/Body/ch03_001_0012.pfb.18`, byte-identical structure to vanilla except its resource-path strings), with the mesh/mdf2/chain2 references redirected to point at the mod's own custom, non-numeric path (`Art/Model/Character/ch03/Arsinia/RRBunny/ch03_RRBunny_0002.*`) instead of vanilla content. Confirmed directly by extracting and reading the pfb's own UTF-16LE strings. Picking a page already IS "baking in" a fixed target -- there's nothing for our retargeting feature to add here.

**This is a genuinely new customization pattern for this project to have on record**: previous custom-slot handling (`donor.py`'s `candidate_donor_paths()`, `pfb_fix.py`'s `_apply_substitution()`) is built entirely around a 4-character fake-character-code swap (`mh03` standing in for `ch03`, matched by `_CODE_RE = [a-z]{2}\d{2}`). This mod's redirect is a completely different shape -- an arbitrary custom path segment (`Arsinia/RRBunny`), not a 4-char code -- so none of that existing substitution machinery recognizes or touches it at all.

**A theoretical worry raised before testing turned out to be unfounded once actually tested.** The concern was that if one of these Transmog pfbs ever needed a plain wholesale donor-replace, the custom redirect would be silently overwritten back to vanilla, quietly killing the transmog with no error. Running the mod through `auto_fix.py` for real showed this does NOT happen: every one of the 25 Transmog-page pfb files came back `[warn] ... found donor ... but its content doesn't reconcile with the mod's own -- leaving untouched (possible real customization)` -- `_find_substitution()`'s existing string-diff safety threshold already refuses to touch a file this divergent from its donor, exactly the same refusal behavior it was built for. The base RRBunny mesh/material files (11 files, at the custom `Arsinia/RRBunny` path) resolved completely normally via ordinary whole-game mmtr donor matching -- path convention doesn't affect material donor-matching at all, only pfb resource-string substitution.

**Root cause of "died": a real vanilla structural change the registry only partly covers.** `rsz_layout.fits_current_layout()` returned `False` even on a freshly-pulled CURRENT donor (not just the mod's own bytes) for the Hope and Innerwear1 slots -- a strong signal, since a live donor failing our own check normally means a registry gap, not real file corruption. Manually walking the donor's instances (`_parse_instance` position tracking) found the exact break point: `via.dynamics.GpuCloth` (Hope) and `via.motion.ChildSecondary` (Innerwear1) parse with a soft alignment mismatch (`ok=False`), which cascades into the NEXT instance overrunning the data block entirely. Both are NATIVE (`via.*`) types -- consistent with this project's established, repeatedly-confirmed caveat (#17/#21/#28) that native-type field layouts are CPU-emulation guesses in every available community dump, never derived from real reflection metadata the way managed (`app.*`) types are. Checking the other three target slots directly: **Guild Knight and Clerk parse perfectly clean under the current registry; only Hope and Innerwear1 hit the native-type gap.** This is a genuinely per-armor-set, per-native-type gap, not a wholesale registry failure -- worth remembering next time a whole-mod "doesn't fit" result looks like total registry failure; check each affected slot individually.

**Fetched a fresh dump and merged it in (`rsz_layout.fetch_latest_dump()` + `install_snapshot(as_role="current", rotate=True)`, the exact pipeline #9/#28 built) -- didn't resolve the two native-type gaps.** Merge stats: `corrected=4, shape_mismatches=45, added=0`. The freshest available community dump still doesn't nail `GpuCloth`'s/`ChildSecondary`'s exact layout well enough to parse cleanly -- further confirmation that native-type uncertainty is a property of the whole community-dump ecosystem (per #21's REFramework-pipeline research), not something a newer fetch reliably fixes. (Also re-confirmed, this time by direct dict-key inspection rather than assumption: the registry schema uses `"n"`/`"f"`, not `"name"`/`"fields"` -- an ad-hoc inspection script using the wrong key names looked like a real "12 types missing from the registry entirely" finding at first and was NOT -- always confirm against the actual schema, e.g. `_bake_raw_dump()`'s own output shape, before trusting a quick one-off inspection script's verdict.)

**With `preserve_extra_pfb_components` (the existing experimental checkbox) enabled, most of the Transmog pfbs DO resolve -- via `_transplant_reshaped()`, tier 2 of the crc-only path.** 13 of the ~25 pfbs across all five pages came back `[transplanted]`. But checking exactly which instance was being reshaped/transplanted, via `walk_instances_with_recovery()`'s `recovered` set, on three different pieces across three different pages (Clerk/Body, Guild Knight/Body, Hope/Arm): **every single one is `app.ChainSetting`** -- the EXACT type item #18 spent an entire investigation confirming has a real, non-deterministic, boot-time-only failure mode (three distinct outcomes -- crash, silently inert, or occasionally fine -- observed from byte-identical rebuilds across repeated cold boots, on two completely unrelated mods, Mask Bikini and DOTEI EULA). This is not a new bug to chase; it's **confirmation that #18's finding generalizes far beyond the two mods it was originally found on** -- any mod whose bundled pfb needs a `ChainSetting` transplant to resolve hits the identical wall, regardless of author or content. Per #18's own conclusion ("do not enable it for a real delivery without a fresh in-game boot test of that exact build" -- and by this point, three separate boot tests already failed unpredictably), this is not safe to ship for this user's request either, even though the tool technically produces output.

**Answer given to the user, and the general lesson**: this mod cannot currently be fully, safely repaired by this project. The base RRBunny material/texture content can be (and was, cleanly). The Transmog pfb pages' redirect structure is now stale relative to the current game (Capcom added new cloth/fur-physics native components -- `GpuCloth`, `ShellFurParam`/`ShellFurMesh`, `ClothSetting`/`ClothSettingCollection`, `ChainSettingCollection`, `ace.cDampingParam`, `via.dynamics.cloth.CurveWind`, `app.CLSPVirtualGround`, `app.CollisionShapePresetController` -- all found freshly present in ordinary vanilla armor pfbs this session, none in the older mod copy), and the one mechanism that structurally reconciles the divergence (`ChainSetting` transplant) is the specific, already-confirmed-unsafe-at-boot mechanism from #18. No workaround was found or attempted beyond what #18 already ruled out -- re-litigating that conclusion wasn't productive; recognizing the SAME confirmed failure mode recurring was the useful outcome here. If a future session hits another mod whose only blocker is a `ChainSetting` transplant, this is now confirmed (not just suspected) to be a systemic, not mod-specific, dead end with today's tooling.

### 41. Fresh-machine build broke on `backports.zstd` -- PyInstaller's `collect_all` never found its compiled `.pyd` at all (2026-08-10)

Cloning this repo onto a brand-new machine (Python 3.13, freshly `pip install -r requirements.txt`) and building via `MHWmodfixer.spec` produced an exe that crashed on launch, immediately, with `Unhandled exception in script: cannot import name 'zstd' from 'backports'`. Not a code bug in this project -- an environment/packaging gap that only surfaces on a fresh machine, never on the original dev box where the exe was presumably already built once with an older py7zr/backports.zstd pairing.

**Root cause**: py7zr now imports `backports.zstd` (a PEP 420 namespace package providing a compiled `_zstd.cp313-win_amd64.pyd` extension, with a pure-Python `_zstd.py` fallback stub that only works if a SEPARATE, never-actually-shipped `_zstd_cffi` cffi module exists). `collect_all('backports.zstd')` -- the same pattern already used for `tkinterdnd2` in this spec -- silently failed to discover the `.pyd` at all for this package (namespace packages confuse PyInstaller's `collect_dynamic_libs`), so only the `.py` source stub got bundled. That stub unconditionally does `from backports.zstd._cffi import (...)`, which itself needs `backports.zstd._zstd_cffi` -- a module that was never built by this package's own install (the real backend is the `.pyd`, not cffi) and doesn't exist anywhere on disk. Two-stage failure, fixed one layer at a time: first `collect_all` was added (fixed "no module named zstd" but exposed "no module named `_zstd_cffi`"), then `excludes=['backports.zstd._zstd', 'backports.zstd._cffi']` was added to Analysis so the broken pure-Python fallback chain never gets bundled/graphed at all, then the REAL `.pyd` had to be added to `binaries` by hand (`glob.glob` over `backports.zstd.__file__`'s own directory) since `collect_all`'s automatic binary discovery genuinely never found it on this namespace package.

**Fix, in `MHWmodfixer.spec`**: `collect_all('backports.zstd')` (kept, still needed for its `.py`/data files), `excludes=['backports.zstd._zstd', 'backports.zstd._cffi']` in `Analysis(...)` (stops the broken fallback stub from being graphed), and an explicit `binaries += [(p, 'backports/zstd') for p in glob.glob(...)]` sourced directly from the installed package's own directory (`os.path.dirname(backports.zstd.__file__)`) to guarantee the real compiled extension ships regardless of `collect_all`'s namespace-package blind spot.

Verified: rebuilt exe launches cleanly (window title renders correctly, "Night Ops" theme intact), closed cleanly, no exception. Not yet re-verified whether this was already silently broken in the shipped v0.5 release itself (built on the original dev machine, which may have an older/different `backports.zstd`/py7zr pairing that never hit this) -- if a future session sees this exact crash reported by an end user (not just a from-source builder), the same fix applies, and it's worth checking whether `pip show py7zr`'s pinned version changed recently enough to explain why the dev machine never saw it.

### 42. Weapon-slot retargeting: the #40 groundwork turned into a real feature -- code/GUI built ahead of the game reinstall, still unverified against a real mod or live game (2026-08-10, continued on a new machine)

The "start weapon-slot groundwork" work from #40's commit (`tools/bake_weapon_slots.py` + `tools/weapon_slots.json.gz`, 622 weapon models across all 14 types, baked on a DIFFERENT machine that had the game installed) got interrupted by a computer switch -- this session picked it up on a fresh machine that didn't have Monster Hunter Wilds installed at all (confirmed via `git log`/`git branch -a`/`git stash list` showing nothing else in flight, and the local Claude Code session-transcript folder having no record of the prior session at all -- it ran on a different machine/account, consistent with this whole project's history of switching between a home PC and a work PC). The user chose to reinstall the game on this machine to finish the feature properly rather than leave it stalled; while that install ran in the background, the parts that don't need live game access got built.

**New `weapon_retarget.py`**, a structural mirror of `slot_retarget.py` (armor), adapted for two real differences from armor:
- **No "pieces" concept.** A weapon model is one mesh + one mdf2 + (usually) one equip pfb, not up to 6 separate piece files like armor -- `ModWeaponInfo`/`detect_mod_weapon()` are correspondingly simpler than `ModSlotInfo`/`detect_mod_slot()` (a single `(type_code, sid, iid)` triple, not a piece-number set).
- **Compatibility logic is actually simpler than armor's**, per `bake_weapon_slots.py`'s own reasoning already on record: a mod shipping only mesh+mdf2 (the common reskin case, no bundled pfb) is safe to retarget to ANY same-type target regardless of physics profile, since the target's own vanilla pfb is never touched either way. Only a mod that bundles its OWN pfb needs a physics-superset check -- and unlike armor's `partial`/`gpuc` grades (which are still usable, just less ideal), a weapon target that fails this check is graded `refused` outright and blocked from being applied in the GUI, not just discouraged: there is no safe reconciliation path for a mismatched bundled weapon pfb, since that would need the same `app.ChainSetting` transplant mechanism #18 already confirmed unsafe at boot.
- The weapon TYPE (it-code) is a hard, non-negotiable boundary -- never offered as a candidate outside the source's own type, mirroring how armor never crosses `ch03` but CAN cross set/variant.

**Verified without the game** (everything `find_compatible_weapon_targets()`/`detect_mod_weapon()`/`retarget_tree()` can be tested on, since they only touch the already-baked `weapon_slots.json.gz` and synthetic file trees, never live game files): a fake reskin source (no pfb) returns 100% `exact` across all 44 other `it00` models; a fake source WITH a 5-component physics profile (ChainSetting/Chain2/ChainWind/ShellFurMesh/ShellFurParam, a real `it00/00/0001` entry) correctly grades targets missing the fur components as `refused` with the right missing-physics list (5 exact / 39 refused out of 44); zero cross-type leakage in either case. `detect_mod_weapon()` correctly returns a list (not a single result) for a synthetic 2-weapon mod, and an empty list for a mod matching nothing. `retarget_tree()` on a synthetic reskin mod (`it0000_0006_0.mdf2`/`.mesh` under the confirmed game path convention) relocated both files to the target id with byte-identical content, confirmed directly.

**What's explicitly NOT verified yet, unlike the armor version at the same stage**: armor's `slot_retarget.py` was written only AFTER directly inspecting real Chinese-community-pipeline mod archives (per #33/#34) to confirm mods actually mirror the game's own path convention. No real weapon mod archive has been obtained or inspected yet for this feature -- `detect_mod_weapon()`'s regexes are built purely from `bake_weapon_slots.py`'s own confirmed GAME-side convention, extrapolated to what a mod's own file layout probably looks like. This module's own docstring flags this explicitly. **Do not treat this as validated the way armor retargeting is** -- get a real weapon mod (ideally one with a bundled pfb, to exercise the `refused` path for real) and run it through `detect_mod_weapon()` before trusting output from this feature.

**GUI**: new `btn_weapon_retarget` ("적용 무기 변경"/"Change Target Weapon") next to the existing armor button, opening `_open_weapon_retarget_dialog()` -- deliberately simpler than the armor dialog (no per-slot Treeview/assignment dance, since a weapon mod targets exactly one model): pick file -> background-thread detect -> a single compatibility Treeview (green=exact, red=refused, refused rows blocked from `do_generate()` with an explanatory error rather than silently allowed) -> live-verify the selected target only -> save. Same `_retarget_refresh_fn`-style hook pattern (`_weapon_retarget_refresh_fn`) wired into `App._retranslate()` for live language switching while the dialog is open, learned directly from the two real bugs #39 found in the armor dialog and the RSZ Snapshot dialog (missing button retranslation, no live refresh at all) -- built correctly the first time here instead of repeating that discovery.

Added 18 new i18n keys, all 5 languages filled in immediately (not deferred) per #39's own explicit lesson about exactly this mistake; a full-audit script (`for key in i18n._STRINGS: check all 5 langs present`) confirms 128/128 keys with zero gaps, project-wide.

**Verified via headless GUI smoke test** (the established `_apply_theme()` + `App()` + `root.update()` pattern from #27, extended here to actually open/close the new dialog and switch language both with the dialog open and after closing it): App instantiates cleanly, the dialog opens and closes without exception, and -- a real bug the FIRST test run caught before it ever reached a real user -- closing the dialog via a raw `Toplevel.destroy()` instead of going through its own `WM_DELETE_WINDOW` handler leaves `_weapon_retarget_refresh_fn` stale (never cleared), which the test surfaced immediately by asserting the hook is `None` after a proper close and initially failing until the test itself was fixed to close via the real handler -- not a product bug, but a reminder that even a "just testing" shortcut can silently exercise the wrong code path.

**Still to do once the game finishes installing** (tracked here so a future session doesn't have to rediscover the plan): (1) obtain a real weapon mod (reskin-only first, then one with a bundled pfb) and run it through `detect_mod_weapon()` to confirm the path-convention assumption actually holds, fixing the regexes if it doesn't; (2) run `verify_target_vanilla()` against the live game for real; (3) do an actual `retarget_archive()` end-to-end relocation and deploy it in-game, mirroring #33's manual verification process before trusting this the way armor retargeting is trusted; (4) weapon name resolution is still explicitly deferred (`weapon_label()` just returns the raw id) -- `weaponseries.msg` only covers 47 series for 622 individual models, so the same per-model-name-resolution problem #39 solved for armor via `ArmorSeries.msg` doesn't have an obvious equivalent yet for weapons; investigate whether a different live-game data source resolves individual tiers before attempting this.

**Update, same day: game installed, 4 real weapon mods obtained, items (1)-(2) done and a real compatibility-logic bug found and fixed.** The user reinstalled MHWilds on this machine (`C:\Program Files (x86)\Steam\steamapps\common\MonsterHunterWilds`) and supplied 4 real Nexus weapon mods to test against (Ebony And Ivory Dual Pistol, Hirabami Great Sword, Tailless Miyabi's Katana, Uth Duna Sword And Shield).

- **Path-convention assumption CONFIRMED**: all 4 real mods use the exact game-side directory convention `bake_weapon_slots.py` established (`natives/stm/Art/Model/Item/it<NN>/<sid>/<iid>/...`) -- case varies between mods (`STM` vs `stm`, already handled by `re.IGNORECASE`), but the structure itself matches exactly. `detect_mod_weapon()` correctly identified all 4 (it02/00/0013, it00/00/0007, it03/00/0007, it01/00/0003) with zero changes needed to the regexes.
- **A real gap `bake_weapon_slots.py`'s own reasoning didn't anticipate, found by actually inspecting these mods**: 3 of the 4 real mods bundle a loose `.chain2` file with NO pfb of their own -- a real, common shape the original "only a bundled PFB needs the physics check" assumption missed entirely (it implicitly assumed "no pfb" meant "no physics content at all"). Fixed: `ModWeaponInfo` gained `has_physics_files` (set when a mod ships `.chain2`/`.jcns`/`.clsp`/`.sfur` without a pfb), and `find_compatible_weapon_targets()` now has three grades instead of two -- a bundled-physics-file-no-pfb mod grades `partial` (not `refused`) against a target lacking the near-universal chain baseline, since the bundled file just goes unreferenced (silent feature loss) rather than risking a crash the way a mismatched bundled PFB would. GUI/i18n updated to match (`grade_weapon_partial`, `note_weapon_partial_physics`, amber-colored row, still selectable/generatable -- only `refused` blocks generation).
- **Dual Blades (it02) reskin has NO physics files at all** (`Ebony And Ivory Dual Pistol` -- despite the flavor name, it's a Dual Blades reskin: two numbered model variants `_0`/`_1` sharing one iid, both correctly grouped under the same `detect_mod_weapon()` key) -- confirms the plain "exact everywhere" case is real too, not just theoretical.
- **Full `retarget_archive()` end-to-end test, real mod, live game**: Hirabami Great Sword (it00/00/0007, ships chain2+mdf2+mesh, no pfb) relocated to it00/00/0000 -- output zip verified to contain correctly renamed `it0000_0000_0.{mdf2,mesh,chain2}` files, byte-for-byte content otherwise untouched. `verify_target_vanilla()` against the live game confirms the target has real mdf2/mesh/pfb files -- `ok=True, missing=[]`. Saved as `Test\_retargeted_test.zip` for the user to optionally deploy and confirm in-game (item (3) from the original plan) -- not yet actually equipped/tested live in MHWilds itself, the one remaining unverified step.
- Committed as a follow-up to the groundwork commit above; CLAUDE.md and code updated together.

**Still outstanding**: (a) actual in-game equip test of `_retargeted_test.zip` (or a fresh one) -- the one thing only playing the game can confirm; (b) a real mod that bundles its OWN pfb has not been tested yet (none of the 4 supplied mods have one), so the `refused`-grade path is only unit-tested against synthetic data, not a real mod; (c) weapon name resolution remains deferred, unchanged from the original plan.

**Update, next session, item (b) done: a real bundled-pfb mod confirms the `refused`-grade logic, and two real bugs in `retarget_tree()`'s filename rename found and fixed along the way.** Used `C:\Users\User\Desktop\Weapon\Reydau Greatsword - Reybane Azariel-1157-2-0-1772640524.rar`'s "[1] Effect lvl 1_use only one" page -- a real mod bundling its own equip pfb (confirmed earlier, item #42's own architecture section, to carry `app.ChainSetting`/`Chain2`/`ChainWind`/`ShellFurMesh`/`ShellFurParam`).

- `detect_mod_weapon()` correctly identified it (`type_code='00', sid='10', iid='0002', has_pfb=True`) with zero changes needed.
- `find_compatible_weapon_targets()` graded it **39 refused / 5 exact out of 44** -- exactly matching the earlier SYNTHETIC unit test's predicted numbers from the same section above, now confirmed against a real mod's real bundled pfb bytes, not synthetic data.
- `verify_target_vanilla()` against the live game confirmed one of the 5 `exact` targets (`it00/00/0001`) is real and complete.
- **First real `retarget_archive()` run on this mod surfaced a genuine gap**: the mod's bundled sound bank (`natives/STM/sound/wwise/it0010_0002_m.sbnk.1.x64`) kept its OLD id in the filename after relocation -- `retarget_tree()`'s file-rename regex was hardcoded to only match filenames ending in the mesh/mdf2/pfb-style `..._0` suffix; this sound bank's own naming convention is `..._m` instead, so the pattern silently never matched it at all (and the safety leftover-scan didn't catch it either, since ITS OWN pattern also required a separator between the type code and sid that a bare concatenated filename like `it0010_0002` doesn't have). Confirmed this same root cause would also silently miss a Dual Blades mod's `_1`-suffixed second-pistol file (real, per the `Ebony And Ivory Dual Pistol` case above) -- not just a sound-file-specific issue.
- **Fix**: widened `file_re` from `it{code}{sid}_{iid}_0` (hardcoded trailing `_0`) to just `it{code}{sid}_{iid}` (the id prefix, whatever comes after), and widened the leftover safety-scan's pattern to make the type-code/sid separator optional too, so a future unanticipated filename shape gets caught by the safety net instead of silently passing through unrenamed.
- **A second bug, self-inflicted by the first fix, caught immediately by re-testing rather than trusting the diff by eye**: the replacement string on the very next line still had the OLD hardcoded `"...{dst_iid}_0"` tail, so every renamed file ended up with a DOUBLE suffix (`it0000_0001_0_0.pfb.18`, `it0000_0001_0_m.sbnk...`) -- the pattern got fixed but the replacement didn't. Caught by actually re-running the real `retarget_archive()` function again (not just reasoning about the diff) and comparing byte-for-byte against a hand-traced expected result, per this whole project's own established "verify empirically, don't trust a fix by inspection" discipline. Fixed by dropping the same hardcoded `_0` from the replacement string too.
- **Re-verified after both fixes**: the bundled-pfb "Effect" mod's pfb (`it0000_0001_0.pfb.18`) and sound bank (`it0000_0001_m.sbnk.1.x64`) both rename correctly now, and a regression check against the plain reskin case (the same mod's own base "[2] Rey Dau_GREATSWORD" page, mesh+mdf2 only) confirms no regression there either.
- Saved as `ReyDau_Effect_retargeted_test.zip` in `C:\Users\User\Desktop\CC download\` -- not yet deployed/equipped in-game (still item (a) from the original outstanding list).

Item (c), weapon name resolution, remains deferred and is the next thing to pick up.

**Update, same session: item (c) done -- real per-model weapon names, sourced directly from game data, mirroring #39's armor approach.** Two real obstacles made this harder than armor's version, both resolved with evidence, not guesses:

1. **No per-type msg file name reliably matches its real English weapon type.** Found all 14 `excel_equip/<name>.msg.23` files (`longsword`, `shortsword`, `twinsword`, `tachi`, `hammer`, `whistle`, `lance`, `gunlance`, `slashaxe`, `chargeaxe`, `rod`, `bow`, `lightbowgun`, `heavybowgun`) via a community datamining pipeline's `config.toml` (`LartTyler/mhdb-wilds-data`) rather than blind guessing (~60+ guesses had already failed for a "greatsword"/"dualblade"-style literal name). **`longsword.msg` is actually Great Sword and `tachi.msg` is actually Long Sword** -- caught by reading each file's own flavor text (`longsword.msg`: "A great sword...its large blade can clear the area in one sweep"; `tachi.msg`: "...imbued with spirit to aid its mighty swings", referencing Long Sword's real Spirit Gauge mechanic) rather than trusting the filename. A first pass got this backwards by assuming filename=type; caught and corrected before it shipped.

2. **The it-code (00-13) <-> weapon-type mapping needed independent, direct verification, not inference.** `app.Weapon`'s own `_WpType` field turned out to just equal the it-code number itself (no help). What actually worked: real Nexus mod archives whose folder/file names carry the type abbreviation in parens -- "MHWI Fatalis Weapon Collection" and "MHWI Ruiner Nergigante Weapon Collection" (the user fetched these specifically for this purpose) name every piece like `Fatalis Depth (LBG)` or `Ruinous Perdition (LAN)`, letting `detect_mod_weapon()`/direct pak-hash-probing read off the real it-code directly. 13 of 14 types confirmed this way in one pass (it00=GreatSword, it01=Sword&Shield, it02=DualBlades, it03=LongSword, it04=Hammer, it05=HuntingHorn, it06=Lance, it07=GunLance, it08=SwitchAxe, it09=ChargeBlade, it10=InsectGlaive, it11=Bow, it13=LightBowgun) -- the 14th (it12=HeavyBowgun) follows by clean elimination, not a guess, since exactly one type and one code were left over.

**The actual per-model name link**, found by locating (not guessing) `natives/stm/GameDesign/Common/Weapon/<TypeFile>.user.3` (same `<TypeFile>` naming as the msg files) via the same community config.toml, prefix `STM/GameDesign` for `.user` files vs `STM/GameDesign/Text` for `.msg` files -- a real, easy-to-miss distinction the config.toml made explicit and that blind path-guessing had been getting wrong. Its `app.user_data.WeaponData.cData` RSZ instances have `_Index` (0-indexed, = msg suffix minus 1) and `_ModelId`. **`_ModelId` decodes to `(subid, iid)` via `subid = model_id // 1000, iid = model_id % 1000`** -- verified against 3 independent types (the "LongSword"-named-file/Great Sword, Hammer, Lance) before trusting it everywhere. Multiple msg indices legitimately share one `_ModelId` (rarity tiers I-V of the same tree usually reuse one visual model, confirmed real: `LongSword_1` through `_5` -- Hope Blade I-V -- all share `_ModelId=4`) -- resolved by keeping the LOWEST index (the tier-I / "base" name) as each model's representative label.

**Shipped**: `tools/bake_weapon_names.py` (new) resolves names for all 14 types and merges them directly into the existing `tools/weapon_slots.json.gz` (adds a `"name"` field per entry, alongside the already-baked `materials`/`physics`/`has_pfb` data) rather than a separate file. Result: **403 unique models named across all 14 types, 348 of which matched a real entry already confirmed to exist** in this project's own game-file scan (the other ~55 resolved names are for content this specific game install doesn't have, e.g. unowned DLC/collab weapons whose large `_ModelId` values like `100000`+ never showed up in the earlier brute-force existence scan for exactly that reason). `weapon_retarget.py`'s `weapon_label()` now returns the real name when available (e.g. `it00/00/0007` -> "Cheda Blade I"), falling back to the raw id for the remaining ~45% of real models this data reading couldn't confidently resolve (mostly non-representative extra-variant entries, e.g. a Dual Blades mod's second `_1`-numbered pistol file, which the WeaponData table doesn't carry its own separate name for) -- same "never invent a name, show the id instead" discipline this project applies everywhere else. Verified: `weapon_label()` returns real names for known real examples, raw id for out-of-range/nonexistent keys; `gui.py` imports cleanly with the new wiring (already plumbed into both Treeview population call sites from #42's original GUI work, no changes needed there).

**Same-day follow-up: extended to all 5 UI languages, not just English.** User's own catch -- armor names (#39) cover ko/en/ja/zh_tw/zh_cn, weapon names had only shipped English. Unlike armor (whose Korean name comes from an external spreadsheet, with only en/ja/zh_tw/zh_cn resolved from the game's own `ArmorSeries.msg`), weapons have **no external spreadsheet at all** -- every language, Korean included, was already sitting in the same per-type msg files, just not extracted yet. `bake_weapon_names.py`'s `_load_msg_names()` now pulls all 5 languages via the same `via.Language` code map `bake_armor_slots.py` already uses (`ko=11, en=1, ja=0, zh_tw=12, zh_cn=13`), storing a `names: {lang: text}` dict per weapon entry (replacing the earlier English-only `name` string field -- the baker pops the stale key when re-baking). `weapon_label(key, lang="ko")` gained the `lang` parameter, looking up the requested language and falling back to English then the raw id -- structurally simpler than armor's `armor_name()`, since there's no "always show Korean regardless of UI language" special case to carry (that only existed for armor because Korean there is spreadsheet-sourced, not game-sourced). Both `gui.py` Treeview-population call sites updated to pass `i18n.get_language()`, matching the exact pattern `armor_name()`'s call sites already use. Verified: `it06/00/0004` resolves to `{"ko": "호프랜스Ⅰ", "en": "Hope Lance I", "ja": "ホープランスⅠ", "zh_tw": "希望長槍Ⅰ", "zh_cn": "希望长枪Ⅰ"}` -- all 5 coherent and mutually consistent; `gui.py` still imports cleanly.

**Same-day follow-up: coverage investigation (why isn't it 100%?), leading to a real accuracy fix.** User pushed on why coverage wasn't complete rather than accepting the first result. Broke it down by subid and found a real, structural split: **subid=00 (the main tree) was 86% named; subid=01/03/99 were 0%; subid=10 was ~15%.** Investigated each:
- **subid=01/03/99: confirmed genuinely absent, not a bug.** Checked multiple types' `WeaponData.cData` tables directly (Hammer, ShortSword, Bow, the misleadingly-named "LongSword" file) -- zero rows anywhere reference a `_ModelId` in the 1000-1999 (subid=01) range. Tried a "maybe subid=01 reuses subid=00's name (a higher-tier reskin of the same tree)" hypothesis by comparing `_Name` GUIDs -- moot, since there's no subid=01 row to even compare. Searched the ENTIRE `reframework/data/` folder (every mod's own bundled data, at the user's request) for a possible alternate weapon-name catalog -- found only small settings/locale files for each mod's own UI, confirming these community mods resolve names LIVE from game memory via REFramework's Lua API at runtime, not from any bundled static file this project could read instead.
- **subid=10 (Artian weapons): mostly a genuine "no fixed name" case, not missing data.** Cross-referenced with `reframework/autorun/artian_editor.lua` (a real, already-installed Artian-crafting mod) -- Artian weapons' display names are composed dynamically at craft time from element/material choices via `Core.GetLocalizedText(data._Name)` + appended bonus-name suffixes, not read from one static per-model row the way a regular forged weapon's name is. The handful of subid=10 entries that DO resolve (~15%) are real named quest-reward/unique weapons sharing that subid slot, not Artian bases.
- **Real fix found while reading `artian_editor.lua` for this investigation**: it calls `Core.GetLocalizedText(data._Name)` where `_Name` is the SAME Guid-typed field this project's own `WeaponData.cData` struct already has -- a DIRECT link to a msg entry, via that entry's own 16-byte UUID (present in every GMSG file, right at the start of each entry's record). `tools/msg_reader.py` had been silently discarding this UUID the entire time (`cur_off = eoff + 16  # skip 16-byte uuid`) in favor of matching by position (`_Index + 1 == msg suffix number`) -- a much weaker heuristic that silently mismatches whenever an entry's numbering doesn't line up 1:1 with its data row. Fixed: `msg_reader.py` now exposes each entry's `"uuid"` (hex string); `bake_weapon_names.py` rewritten to match `WeaponData.cData`'s raw `_Name` bytes (read directly at the known fixed offset, instance start + 72, 8-byte aligned) against msg entries' UUIDs directly, instead of the index heuristic. Verified on Hammer alone: 84 of 85 rows now resolve via direct UUID match (the positional method's accuracy on the SAME data was never directly measured, since it silently returned wrong-but-plausible-looking names rather than failing loudly). **Result project-wide: subid=00 coverage jumped from 86% to 95%** (352/370); subid=01/03/99/10 unaffected, as expected, since they were never a matching-accuracy problem to begin with -- there's simply no row to match against.
- **The remaining gap (subid=01/03/99 entirely, most of subid=10) needs live game-memory access to close** -- e.g. a REFramework Lua script calling the same name-resolution functions these other mods already use, run inside the actual running game, which this project's static-file-only approach cannot do on its own. Not attempted this session (no Lua script was written or run) -- flagged as the concrete next step if a future session wants full coverage, using `artian_editor.lua`/`link_equipment_and_layered_sets.lua` as real, working reference code for the exact API calls needed.

**Follow-up session: the live-game-memory approach was built, run, and closes the gap -- with one real correction to the #42 subid=10 hypothesis.** A standalone REFramework Lua diagnostic (`mhwmodfixer_weapon_name_dump.lua`, dropped in `reframework/autorun`, NOT part of this repo -- one-shot tool, deleted after use) was written to read weapon names live. First attempt used `sdk.create_resource()` to load `Common/Weapon/<Type>.user.3` fresh -- failed uniformly across all 14 types (wrong path/resource-type guesses, several prefix/suffix/type-name combinations tried, all failed). Second attempt, found by reading `artian_editor.lua` more closely: the game already keeps every `WeaponData.cData` row loaded LIVE in `sdk.get_managed_singleton("app.VariousDataManager")._Setting._EquipDatas._Weapon<Key>._Values` (one array field per type, key names byte-for-byte matching this project's own `TYPE_FILES` PascalCase values, per `artian_editor.lua`'s own `keys` list) -- no resource loading, no path guessing, just read already-loaded data. Worked immediately: **all 14 types, zero errors, 928+130+144 = 1202 total rows** (before dedup by representative tier).

**Real correction to #42's subid=10 hypothesis**: subid=10 is NOT "mostly Artian, dynamically named" -- the live dump returned real static names for every subid=10 row across all 14 types (e.g. it00/10/0004 = "Buster Sword I/II/III", it00/10/0002 = "Bone Blade I-IV" + "Bone Slasher"). These are just ordinary named weapon trees sharing that subid slot, same as subid=00. The earlier ~15%-resolved figure was a real matching-accuracy gap (pre-UUID-fix), not evidence of dynamic naming -- the UUID fix already documented above should have been re-tested against subid=10 specifically before concluding "no fixed name," and wasn't.

**A genuine third subid band discovered, not previously known to exist at all**: subid=100 (`_ModelId` 100000+, decodes the same way: `subid = model_id // 1000 = 100`). Confirmed real via the live dump (144 rows across all types) -- contains real Artian base tiers I/II (e.g. "Artian Blade I/II") AND real unique/quest-reward final weapon names (e.g. "Whitefire Rathguard," "Grimslayer Urgeom," "Fulgurcleaver Guardiana," "Varianza"). The live dump's own sid values across all 14 types are confirmed to be **exactly `{00, 10, 100}`, nothing else** -- subid=01/03/99 come back with zero rows in the live data too, a second, independent confirmation (not just a repeat) of the earlier static-file finding that those genuinely don't exist anywhere.

**Merged via a new `resolve_names_from_live_dump()` in `bake_weapon_names.py`** (`python tools/bake_weapon_names.py --live-dump <path>`, alongside the original static-file `resolve_names()` -- both kept, selected by an optional `--live-dump` flag), same lowest-index-per-model_id representative-name logic as the static path. Result: 435 unique models named (deduped), 380 matched a real existing `weapon_slots.json.gz` entry -- **identical count to the pre-live-dump baseline** (352/370 for subid=00, 28/191 for subid=10), which is a reassuring cross-validation (two independent methods, static-file UUID-matching and live-singleton reading, agree exactly on the overlapping range) rather than a new improvement in itself.

**Tried to extend `bake_weapon_slots.py`'s own physics/materials scan to also cover subid=100 (for the retargeting feature, not just names) -- found a real, currently unsolved gap.** `SUBID_PROBE_RANGE` only ever probed `00`-`99` (`range(0, 100)`); the earlier `ITEMID_PROBE_EXTRA = [100000, ...]` guess had the WRONG axis entirely (it tried `100000` as an ITEMID under subids `00`-`99`, but `100000` actually decodes to `(sid=100, iid=0000)` -- a different axis, never reachable that way). Added `SUBID_PROBE_EXTRA = [100]` on the correct axis and re-ran the baker -- **found ZERO mesh files anywhere under `art/model/item/<code>/100/<iid>/` for ANY of the 14 types**, confirmed via direct existence checks against the live game's own paks, not just this baker's probe range. Also checked whether `_CustomModelId` (the RSZ field immediately after `_ModelId`) points at a different physical model for these rows -- it's `0` for every subid=100 row checked, ruling that out too. **Left as a genuine unsolved limitation, not guessed at**: these subid=100 weapons are real and presumably equippable in-game (they have real names, a real data-table presence), but this project doesn't know where their mesh/mdf2/pfb assets actually live -- either a different file-path convention entirely (not derivable from `_ModelId` the way subid=00/10 are), or they share existing geometry through some mechanism not yet found. `scan_weapon()` returns an empty dict for any subid=100 entry until this is cracked; `weapon_slots.json.gz` stays at 622 entries (unchanged) since the widened probe found nothing new to add. If a future session wants to close this, the REFramework Lua path is the obvious next tool -- e.g. reading a live `WeaponData.cData` row's other fields for a resource/path reference this static approach hasn't checked yet, or using `ObjectExplorer` to inspect an actually-equipped subid=100 weapon's real GameObject/resource tree.

### Policy: no new tagged release/GitHub Release until SignPath signing is live (decided 2026-08-10)

Checked the live Nexus listing (`nexusmods.com/monsterhunterwilds/mods/4695`) while investigating why the user's SignPath application email hadn't gotten a reply yet -- the mod is the #1 entry in the game hub's own "Trending Mods" section (67 endorsements), which is a strong signal a Nexus staffer reviewing the SignPath-unrelated but AV-adjacent situation would see it fast. Separately confirmed the CURRENT live v0.5 listing still shows a red "Some suspicious files" virus-scan badge on the Nexus page itself -- the exact AV false-positive problem this whole SignPath effort exists to fix, still visibly unresolved to any visitor today.

**Explicit decision, stated directly by the user: do NOT cut a new version-numbered release (tag push, e.g. `v0.6`) until SignPath Foundation code signing is actually live and wired into `build.yml`.** All of today's real fixes (backports.zstd packaging bug, weapon-slot retargeting feature, MHWmodfixer.spec bundling fix) are on `main` and pushed to GitHub, but deliberately NOT tagged/released yet -- `main` being ahead of the latest release (`v0.5`) is the correct, intended state right now, not an oversight. A future session should NOT create a new tag/GitHub Release on its own initiative for this reason alone; wait for either (a) explicit user instruction, or (b) the SignPath application being approved, whichever the user raises first.

**Known tension with this policy, surfaced 2026-08-10, not yet resolved either way:** the live Nexus listing's "Some suspicious files" virus-scan badge (see the SignPath-application entry above) is most likely NOT a stale/unrelated flag -- the v0.5 asset currently uploaded to Nexus was almost certainly built with the self-compiled-PyInstaller-bootloader version that CLAUDE.md's own AV-false-positive section confirmed got WORSE VirusTotal results (5/66, including an explicit WithSecure "Trojan" verdict) before being reverted in source the next day. That revert was never re-uploaded to Nexus under the existing v0.5 tag/page. So: the release-hold policy above is correct for NEW version numbers, but it does NOT preclude re-uploading a corrected BUILD of the already-published v0.5 to Nexus (same version number, no new git tag needed) if the user wants to clear the Nexus badge sooner than waiting on SignPath approval. This was raised as a suggestion, not decided -- confirm with the user before doing this proactively; don't treat "hold new releases" as also meaning "never touch the existing v0.5 Nexus upload."

### 43. `tools/UnRAR.exe` dropped entirely -- Windows's own built-in `tar.exe` handles RAR extraction instead (2026-08-10)

Prompted by the user asking to preemptively look into replacing UnRAR.exe (RARLAB freeware, not open source) before SignPath's "no proprietary components" review possibly flags it -- rather than settling for "no pure-Python RAR5 decoder exists" (true, confirmed via research) or the LGPL `unar` tool (also genuinely open source and RAR5-capable, but no current prebuilt Windows binary is easy to obtain), found something strictly better: **Windows 10 (1803+)/11 ships `tar.exe` at `%windir%\System32\tar.exe`, which is bsdtar/libarchive under the hood (BSD-licensed) and has working RAR5 read support already compiled in.** Confirmed directly against 2 real RAR archives found on this machine (not synthetic test data) -- one expanded from 10,418 compressed bytes to 658,511 bytes across 4 files (~63x), proving genuine decompression happened, not just a pass-through of already-stored entries.

**Why this beats every other option considered**: it needs NO bundled binary at all -- not RARLAB's proprietary UnRAR.exe, not even a from-source-built open-source alternative. Every Windows 10/11 machine already has it. This makes the SignPath "no non-OSS component" question moot for RAR support entirely, rather than just swapping which binary gets bundled.

**Changed**: `archive_extract.py`'s `.rar` branch now shells out to `tar.exe -xf <archive> -C <dest>` directly via `subprocess`, replacing the `rarfile` + bundled-`UnRAR.exe` approach. `rarfile` was confirmed used nowhere else in the codebase (grepped first) before removing it from `requirements.txt`; `tools/UnRAR.exe` deleted from the repo; `MHWmodfixer.spec`'s `datas` no longer bundles it. README.md/README.ko.md's "Rebuilding the exe" and "File layout" sections updated to match (removed the `--add-data "tools/UnRAR.exe;tools"` PyInstaller flag, updated the prose description of `.rar` handling in both languages).

Verified: the real `extract_archive()` function (not a standalone prototype) re-tested against both real `.rar` files post-change, byte-identical output to the direct-`tar.exe` prototype test. Error handling checked separately (missing tar.exe / extraction failure both raise clear exceptions). **Not yet re-verified**: whether `tar.exe` correctly handles special/Unicode characters INSIDE a rar archive's own entry names (a real historical libarchive/bsdtar bug class on Windows, confirmed to exist via research, but not reproducible with the 2 real test files on hand, which had plain ASCII entry names) -- worth stress-testing with a mod archive that has non-ASCII or apostrophe-bearing filenames inside the rar itself before fully trusting this on a wide variety of real-world mods. Exe not yet rebuilt with this change as of this entry (queued next).

**Update, same day: exe rebuilt with this change (on top of the stock-bootloader revert above), VirusTotal-checked -- 0/63, completely clean.** Rebuilt via the normal `python -m PyInstaller MHWmodfixer.spec --noconfirm` (confirmed `tools/UnRAR.exe` absent from `dist/MHWmodfixer/_internal/tools/`), smoke-tested (launches, correct window title, closes cleanly), packaged and uploaded to VirusTotal by the user: **`f38c6b1ecb491325e58cd772f75be11ea217809e3e5638a009e0bde6c4b1cdf6`, "No security vendors flagged this file as malicious," 0/63** -- every vendor that had flagged the self-compiled-bootloader v0.5 build (Avast, AVG, Avira, Cynet, WithSecure) now reads Undetected. Matches the confirmed-clean v0.3/v0.4 baseline exactly. Two things changed at once here (bootloader reverted to stock + UnRAR.exe removed), so this can't cleanly isolate how much the UnRAR removal itself contributed versus the already-expected bootloader-revert benefit -- but the combination is confirmed clean, and one fewer bundled third-party binary can only help, never hurt, the "unusual bundled executable" class of heuristic. Per the standing no-new-release policy above, this build is NOT tagged/released yet -- recorded here as evidence for whenever a release does go out.

### 44. Standalone-.pak weapon mod support, slot-occupancy warnings, weapon multi-slot retargeting, and the start of real Artian-tier name mapping (2026-08-10, continued session)

A real user session testing the weapon retargeting feature (#42) against actual downloaded mods surfaced several real gaps in rapid succession, each fixed and verified against the specific real mod that broke it.

**Standalone-.pak weapon mods** (`weapon_retarget.py`): the very first real mod tried ("Dreaming Dalamadur") came back completely undetected -- turned out to be packaged as its own `.pak` file (no loose paths at all), which `detect_mod_weapon()`'s regex-based scan can never find anything in (a pak's entries carry only a hash64, no path string -- same "no plaintext directory listing" fact this project already knew about the GAME's own paks). Fixed by mirroring `pak_mod_fix.py`'s own established technique (`read_by_hash()`'s docstring: "if a mod's entry hash exactly matches one of the game's own current entries, that IS the vanilla donor") -- except here the goal is identifying WHICH slot, not just getting donor bytes: `detect_mod_weapon_pak()` computes every known `weapon_slots.json.gz` slot's canonical path (at every plausible version suffix) and checks membership in the mod's own pak hash set. Verified directly: "Dreaming Dalamadur"'s pak has 6 entries, exactly 2 hash-match a known vanilla path (mdf2+mesh for `it00/01/0004`), the other 4 are the mod's own custom-named textures (never hash-match anything, by design). `retarget_pak()` rebuilds the pak by rehashing only the identified entries to the target slot's equivalent path/version, passing every other entry through with its ORIGINAL hash unchanged (a texture's own path was never derived from the weapon's slot number, so it doesn't need to move).

**Real bug found via this same pak work: infinite copy loop.** `retarget_archive()`'s new pak branch did `for p in mod_root.rglob("*"): ... shutil.copyfile(...)` to copy the mod's other files into `out_root` -- but `out_root` lives INSIDE `mod_root` (both under the same `work` tempdir), so the live `rglob()` kept re-discovering its own freshly-copied output as new source files, recursing forever (caught directly: a real run was still copying the same 3 files in a loop after 180+ seconds, only surfaced by instrumenting with real timestamped file-flushed logging after several rounds of misleading "it's just slow" theories -- background-shell job tracking via `&` inside a single Bash call also turned out to be unreliable in this environment, losing/orphaning processes between tool calls; a plain synchronous call that the harness auto-backgrounds on timeout was the only trustworthy signal). Fixed by materializing the file list (`list(mod_root.rglob("*"))`) before the copy loop starts -- `retarget_tree()` (loose-file path) never had this bug since it already iterates a pre-captured `source.files` list from detection, not a live scan.

**Real bug: `t()` i18n crash silently froze the dialog.** `t("msg_weapon_retarget_detected", key=info.key, ...)` crashed every time with `TypeError: t() got multiple values for argument 'key'` -- the message's own `key=` kwarg collided with `t(key: str, **kwargs)`'s own first positional parameter name. Because the exe is `--windowed` (no console), the exception had nowhere to print and the dialog just silently stayed on "분석 중..." forever, looking exactly like a performance hang -- diagnosed by temporarily adding file-based debug logging (`_dbg()` writing to a fixed temp path with explicit `flush()`+`os.fsync()`) into both the background worker and the `win.after()` callback, which is what finally caught the real traceback. Fixed by renaming the kwarg to `wkey` (both call sites -- initial render and the language-switch `refresh_texts()` copy). Worth remembering generally: an unexplained "just hangs, no visible error" symptom in this project's `--windowed` build is a strong signal to add throwaway file-logging with explicit flush/fsync before spending more time hypothesizing about performance.

**Slot-occupancy detection (both armor and weapon retargeting dialogs), decided directly with the user:** the user wanted the retarget dialogs to warn when a candidate TARGET slot is already occupied by another currently-active mod. Two techniques layered together, in the order the user actually converged on after some back-and-forth:
1. Considered parsing Fluffy Mod Manager's own `installed.ini` (its per-game "currently deployed" manifest, found at `<fluffy_root>/Games/MonsterHunterWilds/installed.ini` -- one `[Section]` per installed/enabled mod page, each listing every `natives/`-relative file it deploys via repeated `file=` lines) as the PRIMARY detection mechanism.
2. **User's own correction: "플러피를 읽는거보다... native를 직접 읽는게 훨씬 낫겠다... mo2 사용하는 사람들도 있으니까"** -- switched the PRIMARY mechanism to `game_archive.find_loose_files()` (a plain filesystem glob against `<game_dir>/natives/...`, no Fluffy-specific parsing at all, tool-agnostic for any mod manager that does real loose-file deployment). `installed.ini` parsing (`fluffy_installed.py`) was kept as a SECONDARY, optional enhancement: when a slot IS found occupied via the native check, `installed.ini` (if a Fluffy path is configured) additionally names WHICH mod -- falling back to a generic "already used by another mod" warning (no filename shown) when Fluffy isn't configured or doesn't know that specific file, per the user's own explicit call: "플러피 안깔고 하는 사람들은... 그냥 다른 모드가 사용중만 나오게 해야해."
3. **MO2 support was explicitly ruled out, not just deferred**: MO2 uses a virtual file system (USVFS) and never actually writes into the real game directory at all, so no filesystem-based check (native OR any hypothetical MO2-specific one considered) can see it. User's own call: "Mo2는 버려."
4. `auto_detect_fluffy_dir()` (`auto_fix.py`): Fluffy is a portable app with zero OS footprint (checked directly: no HKCU/HKLM Uninstall registry entry, no AppData folder, no Desktop/Start Menu `.lnk` -- all confirmed empty on a machine that DOES have it installed), so the only real auto-detection signal is "is `Modmanager.exe` currently running" (via a `Get-Process` PowerShell one-liner, `CREATE_NO_WINDOW` flagged so it doesn't pop a console in the `--windowed` build). Falls back to a hardcoded personal-machine default, then plain manual entry -- matching the user's own stated tolerance ("자동탐지가 어렵거나... 사용자한테 직접 입력하게끔 하는 것도 괜찮은 방법이야").
5. UX: warn-only, never block selection (user's explicit call: "선택은 가능하게 하고 경고 팝업은 띄워주면 좋겠네") -- an inline note in the candidate list's "비고" column always, PLUS a confirmation popup (`_confirm_occupied()`) specifically at Generate time for whichever slot(s) ended up assigned to an occupied target.

**Weapon multi-slot retargeting** (mirroring armor's own #35): the SAME real-mod testing surfaced a mod ("ReyDau_Fixed.zip") bundling loose files for TWO distinct weapon models at once (`it04/00/0012` and `it04/10/0002` -- confirmed later in the same session to be two different Artian-tier appearance stages the mod author accidentally targeted together instead of just one, see below) -- the single-target-only dialog flatly refused it ("Couldn't detect exactly one weapon model"). Ported armor's exact `detect_mod_slots()`/`retarget_tree_multi()`/`retarget_archive_multi()`/two-tier-Treeview-dialog architecture to weapons (`detect_mod_weapons()` plural, same functions pluralized, `_open_weapon_retarget_dialog()` rebuilt to match `_open_retarget_dialog()`'s structure) -- verified end-to-end via a real headless Tk mainloop-driven GUI test (not just the underlying functions) against the real mod, including assigning both detected models to two DIFFERENT targets and confirming the Generate button correctly enables only once every detected model has a decision.

**Regression this same porting effort caused, caught by the user retesting immediately**: the new plural `detect_mod_weapons()` was loose-file-only at first (no pak fallback), which meant `do_pick()` calling it instead of the old singular function silently broke every previously-working standalone-.pak mod ("Dreaming Dalamadur" specifically). Fixed by adding the same pak-hash-matching fallback to the plural function (each pak resolving to exactly one triple becomes its own one-pak group) and extending `retarget_tree_multi()` to branch on `group.pak_path is not None` (rebuilds that group's own pak via `retarget_pak()` directly instead of the loose-file staging path) -- re-verified both the pak-mod case and the loose multi-mod case together afterward, no further regression.

**Artian weapon tier naming -- real structure found, but only safely mappable per-confirmation, not generally.** Investigating why some detected weapon slots still show raw ids led to a genuine side-quest: Monster Hunter Wilds' Artian weapons have (per real community documentation, Namuwiki, cross-checked against this project's own live game data) 3 crafting tiers that are NOT sequential upgrades of one weapon but separate items ("6/7/8레어 아티어 무기는... 맘 타로트 무기처럼 각각 별개의 무기로 취급"), plus a 4th Gogmazios-upgrade final tier with a genuinely new appearance. Confirmed directly in the live weapon-name dump: every `subid=100` model_id group (already known real-Artian-only territory) follows an exact naming pattern -- a name ending in "Ⅰ" = tier 1, "Ⅱ" = tier 2, and a bare unique flavor name (no numeral) = tier 3 (e.g. it04's `100002`: "아티어해머Ⅰ" / "Ⅱ" / **"모토반켈"**) -- except the "Fulgur"-branded branch specifically, which consistently skips tier II (2-tier only, confirmed across every weapon type checked). Separately confirmed the 4th Gogmazios-final tier lives as a completely SEPARATE model hidden in plain subid=00 (e.g. it04's own Gogma-final, "금계의 데스반켈"/Bound Admonition's Deathvankel, sits at `it04/00/0018` -- indistinguishable from an ordinary named weapon by id alone, only findable by its name text matching this pattern).

**Tried and failed to find a general structural link** between a tier-3-unique model (subid=00, e.g. `it04/00/0012`) and its matching tiers-1&2-shared model (subid=10, e.g. `it04/10/0002`), which would have let this be solved with a general rule instead of per-mod confirmation:
- Both share the identical generic placeholder material name `"lambert2"` (a real, checkable signal, but far too broad on its own -- 78 entries project-wide share it, spanning multiple unrelated categories including the already-known-empty subid=01/03/99).
- Hypothesized the `_Hammer`-style per-type RSZ cross-reference field (the same field `artian_editor.lua`'s own code comments reveal `cEquipWork.FreeVal1` is sourced from) might link the two rows directly -- checked by reading the raw field value from both rows directly: it's just each row's own roughly-sequential array-position id, NOT a shared identifier between the subid=00 and subid=10 rows. No link.
- Checked whether `subid=100` group COUNT (the number of distinct Artian "families" a weapon type has, e.g. Dosha/Albirath/Fulgur/plain-Artian) matches the COUNT of unnamed-`lambert2` subid=00 entries for that same type, across all 14 types -- only matched for it04 (3=3), every other type had noticeably more subid=100 groups (3-5) than subid=00 candidates (mostly just 1, `it13` had 0) -- concluded this was a coincidence for it04, not a real rule.

**Resolution, per the user's own direction**: this can only be solved by the user testing real single-target Artian-skin mods in-game one at a time and reporting which exact slot each corresponds to (tracked ongoing in auto-memory, `weapon_artian_tier_mapping.md`, for continuity across future sessions). A small `CONFIRMED_MANUAL_NAMES` dict in `tools/bake_weapon_names.py`, applied as a final override pass after every automatic name merge, holds each confirmed mapping -- **2 confirmed so far**: `it04/00/0012` = "모토반켈" (verified via a real "Rocket Hammer_DIAGNOSTIC_singlesource" mod that targets ONLY that slot and renders as the Hammer's tier-3 Artian look) and `it00/00/0002` = "발리안차"/Varianza (verified via "Wyvern Impact2.2", the Great Sword's plain "Artian Blade" branch tier 3, confirmed the correct branch by its own `lambert2` material matching the pattern). `it04/10/0002` (the tiers-1&2-SHARED model) also got a manually-composed label ("아티어해머 (Ⅰ/Ⅱ 공용)") -- explicitly NOT official game text (the game never displays one combined name for a model two different named tiers share), built from the real localized tier-1/2 stem + an explicit "shared" qualifier so it's never mistaken for an authoritative in-game string. No general rule was applied to any OTHER weapon type's still-unnamed slots -- confirmed candidates only, matching this project's consistent "don't guess a name" discipline. Once a `CONFIRMED_MANUAL_NAMES` entry exists, it automatically becomes name-eligible for `find_compatible_weapon_targets()`'s existing `if not cand.get("names"): continue` filter too (verified directly) -- no separate code path needed to also offer it as a retarget target.

**Also fixed while merging subid=100 (Artian) names**: two real bugs in `bake_weapon_names.py`'s own merge logic, found by re-testing after every claimed fix rather than trusting the printed summary line:
1. Re-running `bake_weapon_slots.py` (to test the earlier subid=100 mesh-probe extension, itself unsuccessful and left unsolved) silently wipes ALL previously-merged names, since it rebuilds `entries` from scratch with no `names` field at all -- already documented as a warning in that script's own docstring; recorded here again because it directly caused a "why did the names disappear" confusion this same session.
2. The merge loop only ever ADDS/OVERWRITES names for keys present in the CURRENT resolve -- a key that resolved once (e.g. one of the 14 "#Rejected#" placeholder entries, before the filter existed) but no longer does on a later run keeps its STALE old value forever, since nothing ever clears it. Fixed by clearing every entry's `names`/`name` field at the start of every merge, before re-adding from the current resolve -- confirmed this was the actual reason the "Rejected" entries survived two supposedly-clean re-bakes.
3. subid=100 (Artian) entries have no discoverable mesh file at all (per the earlier unsolved gap), so `bake_weapon_slots.py`'s existence-scan never creates a table entry for them -- meaning their names, despite resolving correctly from the live dump, were silently discarded by the merge loop's `if key in payload["entries"]` guard. Fixed: the merge loop now adds a NAME-ONLY entry (`{"names": ...}`, no `has_mdf2`/materials/physics) for any resolved subid=100 key missing from the table -- `find_compatible_weapon_targets()`'s existing `has_mdf2` guard already correctly excludes these from ever being offered as a retarget TARGET (there's no way to verify/build a donor for a slot whose files can't be found), this purely lets `weapon_label()` show a real name instead of a raw id wherever one of these keys is ever displayed. 52 such entries added (674 total weapon_slots.json.gz entries, up from 622).

### 45. subid=01/03 weapon names filled from a cross-verified third-party database -- zh_cn only, and why (2026-08-11)

subid=01/03 have zero rows in `WeaponData.cData` at all (confirmed twice already, #42/#44) -- no official per-language text exists ANYWHERE in this game's own data for these slots, live or static. The only source found that names them at all is a Simplified-Chinese weapon-ID database bundled inside a third-party Chinese community MHWilds mod-manager tool (per this project's standing no-competitor-mention policy, not named or linked here or anywhere in git history -- extracted 2026-08-11 purely for private cross-verification, matching how this project has always treated other community tools' data: as unverified input to check against real game data, never redistributed).

**Extraction**: the tool is a .NET/Costura-bundled exe; `dnfile` (pure-Python .NET metadata parser, no `dotnet` SDK needed) pulled an embedded `costura.*.dll.compressed` resource (raw DEFLATE, no length prefix -- `zlib.decompressobj(-15)` on the resource bytes directly), which itself embeds a `.resources`-format blob (`ModBox.MH.MHWS.R.resources`) containing a plain UTF-8 CSV (`mhws_weapon`, `TYPE,sid_iid,name1/name2/...`).

**Verification before trusting**: cross-checked all 470 of its rows against this project's own already-resolved weapon names (sourced independently from live game data, not this CSV) -- **subid=00 matched 340/340 (100%)**, but **subid=10 matched only 1/23** (the other 22 are flatly different weapons by name, e.g. `it11/10/0001`: this project's own live-data name is "龙穿弓" [Dragon-Piercing Bow], the CSV says "护辟虐弓" [Protect-Tyrant Bow] -- unrelated weapons, not a translation variance). This means subid=10 has a genuine index-misalignment between the two sources (which one -- or whether both are internally consistent but numbered differently -- is unresolved) -- **subid=10 rows from this source are never used**, only subid=00/01/03. The CSV's own "TypeFile_NN"-pattern placeholder rows (e.g. `LongSword_97`) turned out to be the exact same `#Rejected#` dev-leftover entries this project's own `_is_placeholder_name()` already filters (independent confirmation both sources describe the same real underlying game data for subid=00) -- excluded from the merge the same way.

**Result**: 64 new zh_cn-only names added for subid=01/03 (78 candidate rows minus 14 that were the placeholder pattern). Bundled as `tools/community_mhws_weapon_zh_cn.csv`, loaded by a new `load_community_zh_cn_names()` in `bake_weapon_names.py`, applied as a third merge pass (after the live-dump resolve and `CONFIRMED_MANUAL_NAMES`) that only ever fills a key with NO existing name -- never overwrites. `weapon_retarget.weapon_label()`'s fallback chain extended from `lang -> en -> raw id` to `lang -> en -> zh_cn -> raw id`, since a real Chinese name is still strictly more informative than a raw id even in a non-Chinese UI.

**Multi-language expansion asked for, not yet done**: the user wants EN/KO/JA/zh_tw names for these same subid=01/03 slots too, not just zh_cn. Since there's no official per-language text for these slots anywhere in the game's own data (unlike subid=00, whose real msg-file text already covers all 5 languages), producing those would mean either machine-translating the zh_cn text (real accuracy risk -- this project has repeatedly found a literal translation of Capcom's own naming diverges from the real official localized name, e.g. "波涛刀" is officially "Uth Khlunda" in English, not a literal rendering) or finding further independent community sources per language (the same kind of cross-referencing #38/#39 did for armor names via Kiranico). Flagged for a future session -- not started yet.

### 46. Shader migration's brand-new-slot donor bleed widened past "mask"-named slots -- Detail_ALBD_*/Detail_NRRH_* channels hit the same defect (2026-08-13)

Real report on Mangie "Fluffy Bunny" (Nexus): with `force_unresolved_pfbs` on (needed to fix a genuinely-stale Waist piece) and `experimental_shader_migration` OFF, the game boots fine but the Arm piece's fur coat renders black. With `experimental_shader_migration` also ON, the fur color renders correctly (shader migration doing its job) -- but the game black-screens on reconnect after equipping it. A same-force-unresolved, shader-migration-on/off A/B pinned the boot-time regression specifically to shader migration, not the Waist force-fix (the user's own controlled test, not assumed).

Diffed the Arm piece's `fur_UseSC` material (`Base_Equip_Fur.mmtr` -> `Base_Equip.mmtr`) between a no-shader-migration and a shader-migration build directly (`mdf2.Mdf2File`/`mdf2_slice.extract_material`, not just the log). `DetailMaskMap` itself was already correctly neutralized by #29's fix (forced to `NullBlack_Alpha_MSK4.tex`), but the individual `Detail_ALBD_G`/`Detail_NRRH_G` and `Detail_ALBD_A`/`Detail_NRRH_A` slots -- also brand-new to the mod's own material, also never checked by #29's `"mask" in t["type"].lower()` condition since their names don't contain "mask" -- still carried the picked donor's real, non-null content verbatim (a leather/chainmail detail decal belonging to a completely unrelated character, sized and UV-mapped for that donor's own mesh). Whether this specific bleed is what caused THIS mod's black screen is unconfirmed (materials alone are an unusual root cause for a boot-time hang by this project's own established pattern, e.g. #18's pfb/RSZ-only findings) -- but #26/#32 already proved a materially-identical "brand-new slot borrows a UV-mismatched real donor value" bug caused an outright CRASH on TiNE's Qipao, so a material-level cause for a boot-time failure is not unprecedented for this exact defect class, and it's worth closing either way regardless of whether it's the full explanation.

**Fix**: generalized `apply_texture_overrides()`'s neutralization condition from `"mask" in t["type"].lower()` to fire for ANY texture slot that's genuinely new to the mod's own material and whose donor value isn't already a recognized `Null*` placeholder, then picks a per-kind neutral default instead of a single mask-only one: `"mask" in type` -> `NullBlack_Alpha_MSK4.tex` (unchanged), `Detail_ALBD*` -> `NullGray.tex`, `Detail_NRRH*` -> `NullNormalRoughnessOcclusion.tex` -- both new defaults taken directly from what this SAME file already uses for its own genuinely-unused Detail channels (Detail_ALBD_R/NRRH_R on the same material), not guessed. Any other still-unclassified brand-new slot type falls through as a no-op (`safe_default = None`), identical to pre-fix behavior -- this only changes outcomes for the mask/Detail_ALBD/Detail_NRRH families, nothing else.

Verified: re-running Fluffy Bunny's Arm piece through the fixed code shows all 8 Detail_ALBD_*/Detail_NRRH_* slots (R/G/B/A) now correctly neutralized alongside DetailMaskMap; standard regression suite (SilverWolf fixed=1/textures_restored=24, DoA fixed=4/textures_restored=208) byte-for-byte matches the documented baseline -- zero regression, since the branch is a no-op for every slot type outside the three now-covered families. Delivered as `Fluffy Bunny (fixed, shader-migration detail-fix).zip` in `C:\Users\User\Desktop\CC download\` (force_unresolved on, preserve_extra off, shader_migration on). **CONFIRMED in-game by the user ("완벽하게 수정되었다") -- the black screen on reconnect is resolved.** This closes the loop on shader migration's remaining known crash-adjacent risk: every real instance of the "brand-new slot inherits an unrelated donor's real value" defect class found so far (TiNE Qipao's crash #26/#32, Bifrost's hair bleed #29, and now Fluffy Bunny's boot-time black screen) traces to the same root cause and the same fix shape.

**Delivery note (2026-08-13, real mistake caught by the user)**: the FIRST delivered zip for this mod was built by manually driving `process_mod()`/`repackage_for_fluffy()` outside the real `gui.py::_run_one()` flow, and `mod_root` was scoped to just the inner `"[MM] Fluffy Bunny"` folder -- silently excluding the 3 loose sibling pak pages (`Alma.pak`/`Gemma.pak`/`Textures.pak`) that live one level up from it, per this project's own documented Mangie-mod shape (item #37). The user caught it immediately ("저거 망기모드인데 또 플러피 구조 다 깨진 파일로 만들어줬잖아"). Rebuilt with `mod_root` correctly scoped to the TOP-LEVEL extraction directory (containing both the modinfo.ini folder and the loose pak siblings) -- output zip grew from 4.5MB to the correct ~45MB with all 4 Fluffy pages (Main/Alma/Gemma/Textures) present, confirmed by listing the zip's contents before redelivering, not just trusting the build succeeded. Lesson recorded in auto-memory (`mangie_mod_root_scope.md`): any manual (non-GUI) repro script for a mod archive must first check the extraction directory's top level for loose siblings before picking `mod_root`, not just wherever `modinfo.ini`/`natives/` happen to live.

Shipped in the real v0.5 release build the same day, alongside the weapon-retargeting feature (#42/#44) and slot-occupancy warnings (#44) that had been sitting on `main` unreleased since v0.5's last asset refresh -- `gh release edit v0.5` (notes appended, not replaced) + `gh release upload v0.5 <zip> --clobber` (same tag, no new version number, per the standing release-hold policy's explicit-user-instruction exception).
