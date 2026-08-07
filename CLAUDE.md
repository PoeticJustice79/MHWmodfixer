# MHWmodfixer by Littlefish — project notes for Claude Code

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
CURRENTLY installed game). (Idea prompted by reviewing a other
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

See README.md's "exe 다시 빌드하기" section for the exact PyInstaller
command (must list every module that's only ever imported lazily inside a
function as `--hidden-import`, or PyInstaller's static analysis misses
it — `pak_mod_fix`, `whole_game_index`, `fluffy_repackage`, `pfb_fix` all
need this). Close any running `MHWmodfixer.exe` first — PyInstaller can't
overwrite a locked exe (the GUI now refuses a second simultaneous launch
via a Windows named mutex, but an already-running instance from a prior
session will still lock the file).
