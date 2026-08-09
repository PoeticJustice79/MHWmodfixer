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

After comparing this tool against the other another community fixer, the
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
