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
