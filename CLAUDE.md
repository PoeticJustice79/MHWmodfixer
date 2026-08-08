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
