import sys
from mdf2 import Mdf2File, numVersion_from_filename

path = sys.argv[1]
with open(path, "rb") as f:
    data = f.read()
nv = numVersion_from_filename(path)

m = Mdf2File(data, nv)
mat = m.materials[1]  # 'banshee_UseSC', the interesting one with overrides
print("BEFORE:")
for t in mat.textures:
    print(f"  {t.type_str!r} -> {t.path_str!r}")

# Make one path much longer, one much shorter, one same length, across two materials.
edits = [
    (mat.textures[2], "Art/Model/Character/ch03/mangie/mods/banshee/REPLACED_much_longer_path_banshee_d_new.tex"),
    (mat.textures[3], "x.tex"),
    (mat.textures[4], "Art/Model/Character/ch03/mangie/mods/banshee/banshee_x2.tex"),  # same-ish length
]
for tex, new_path in edits:
    old = tex.path_str
    m.set_texture_path(tex, new_path)
    print(f"edited {tex.type_str!r}: {old!r} -> {new_path!r}")

# also edit a texture belonging to the OTHER material to make sure cross-material
# offset fixups behave
mat0 = m.materials[0]
m.set_texture_path(mat0.textures[1], "Art/Model/Character/ch03/CommonTextures/skin/REPLACED_test.tex")

out = m.to_bytes()
print(f"\noriginal size: {len(data)} -> new size: {len(out)}")

# Now re-parse the edited output from scratch and sanity check everything
m2 = Mdf2File(out, nv)
print(f"\nre-parsed materials: {len(m2.materials)}")
for mat2 in m2.materials:
    print(f"  [{mat2.index}] name={mat2.name!r} mmtr={mat2.mmtr_path!r} tex={len(mat2.textures)} props={len(mat2.props)}")
    for t in mat2.textures:
        print(f"      {t.type_str!r} -> {t.path_str!r}")

# Verify prop names still intact (weren't corrupted by unrelated offset shifts)
print("\nprop name sanity (material 0, first 5):")
for p in m2.materials[0].props[:5]:
    print(f"  {p.name_str!r}")

with open(path + ".edited_test", "wb") as f:
    f.write(out)
print("\nwrote edited test file alongside original")
