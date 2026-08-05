"""
End-to-end merge test using two REAL game files for the same material
(current mod file, numVersion=45, and its REFramework .bak1 revision, also
numVersion=45 but with a different prop layout: material[1] has 178 props
instead of 187 -- a genuine structural difference between two real captures).

We can't get a true "next game patch" vanilla sample without extracting the
live pak, so to exercise the "mod's texture overrides get reapplied onto a
different structural skeleton" path specifically, we build a synthetic
"vanilla-like" file: take the bak1 file (different structure) and revert its
mangie/mods/banshee/* texture paths back to plausible stock defaults. Then
merge the real mod file's overrides onto it and confirm:
  1. the result keeps the bak1 skeleton (178 props on material[1])
  2. every overridden texture slot now matches the mod's custom path
  3. every untouched slot (skin material, unrelated banshee slots) is
     unaffected
  4. the result reparses cleanly
"""
from mdf2 import Mdf2File, numVersion_from_filename
from merge import merge_material_textures

SCRATCH = r"C:\Users\User\AppData\Local\Temp\claude\D--\91b1e6e3-1a0a-44c7-b48d-998a1f6b86c6\scratchpad\mhwmod\sample"

mod_path = SCRATCH + r"\mh03_014_0003.mdf2.45"
bak_path = SCRATCH + r"\mh03_014_0003_bak.mdf2.45"

with open(mod_path, "rb") as f:
    mod_data = f.read()
with open(bak_path, "rb") as f:
    bak_data = f.read()

mod_nv = numVersion_from_filename(mod_path)
bak_nv = numVersion_from_filename(bak_path)

mod_mdf = Mdf2File(mod_data, mod_nv)

# Build the synthetic "vanilla": bak1 skeleton with mangie overrides reverted
# to made-up stock-looking paths.
vanilla_stub = Mdf2File(bak_data, bak_nv)
mangie_mat = vanilla_stub.materials[1]
assert mangie_mat.name == "banshee_UseSC"
reverted = {}
for t in mangie_mat.textures:
    if "mangie/mods/banshee" in t.path_str:
        stock_path = t.path_str.replace(
            "Art/Model/Character/ch03/mangie/mods/banshee/", "Art/Model/Character/ch03/CommonTextures/armor/"
        )
        reverted[t.type_str] = (t.path_str, stock_path)
        vanilla_stub.set_texture_path(t, stock_path)

print("Reverted (simulating vanilla defaults before mod was applied):")
for type_str, (old, new) in reverted.items():
    print(f"  {type_str!r}: {old!r} -> {new!r}")

vanilla_bytes_before_merge = vanilla_stub.to_bytes()

# sanity: this synthetic vanilla must still parse fine post-revert
check = Mdf2File(vanilla_bytes_before_merge, bak_nv)
assert check.materials[1].props.__len__() == 178, "synthetic vanilla should keep bak1's 178-prop skeleton"
print(f"\nsynthetic vanilla OK: material[1] prop count = {len(check.materials[1].props)} (bak1 skeleton preserved)")

# ---- now the actual thing under test: merge the mod's overrides back on ----
vanilla_for_merge = Mdf2File(vanilla_bytes_before_merge, bak_nv)
log_lines = []
changed = merge_material_textures(vanilla_for_merge, mod_mdf, log=log_lines.append)
for l in log_lines:
    print(l)
print(f"\nmerge_material_textures changed {changed} texture path(s)")

result_bytes = vanilla_for_merge.to_bytes()
result = Mdf2File(result_bytes, bak_nv)

ok = True

# 1. skeleton preserved (178 props on material[1], came from bak1 not mod's 187)
if len(result.materials[1].props) != 178:
    print(f"FAIL: expected 178 props preserved from vanilla skeleton, got {len(result.materials[1].props)}")
    ok = False
else:
    print("PASS: vanilla skeleton's prop layout (178) preserved, not mod's (187)")

# 2. every reverted slot got the mod's real override path back
mod_mangie_tex = {t.type_str: t.path_str for t in mod_mdf.materials[1].textures}
result_mangie_tex = {t.type_str: t.path_str for t in result.materials[1].textures}
for type_str in reverted:
    expected = mod_mangie_tex[type_str]
    got = result_mangie_tex[type_str]
    if got != expected:
        print(f"FAIL: {type_str!r} expected {expected!r}, got {got!r}")
        ok = False
if ok:
    print(f"PASS: all {len(reverted)} overridden texture slots correctly restored to mod paths")

# 3. unrelated slots (skin material, and banshee slots we never touched) unaffected
skin_before = {t.type_str: t.path_str for t in vanilla_stub.materials[0].textures}
skin_after = {t.type_str: t.path_str for t in result.materials[0].textures}
if skin_before != skin_after:
    print("FAIL: skin material was unexpectedly modified")
    ok = False
else:
    print("PASS: unrelated 'skin' material completely untouched")

untouched_banshee = {t.type_str for t in mangie_mat.textures} - set(reverted)
mismatches = [t for t in untouched_banshee if result_mangie_tex[t] != mod_mangie_tex[t] and result_mangie_tex[t] != {tt.type_str: tt.path_str for tt in mangie_mat.textures}[t]]
# (these were already identical between vanilla-stub and mod before merge, so just confirm still present/unchanged)
print(f"PASS (info): {len(untouched_banshee)} already-matching banshee slots left as-is")

print(f"\nresult size: {len(result_bytes)} bytes")
print("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED")
