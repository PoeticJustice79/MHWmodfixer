import sys
from mdf2 import Mdf2File, numVersion_from_filename

path = sys.argv[1]
with open(path, "rb") as f:
    data = f.read()

nv = numVersion_from_filename(path)
print(f"file: {path}")
print(f"numVersion: {nv}")

m = Mdf2File(data, nv)
print(f"materials: {len(m.materials)}")
for mat in m.materials:
    print(f"  [{mat.index}] name={mat.name!r} mmtr={mat.mmtr_path!r} tex={len(mat.textures)} props={len(mat.props)}")
    for t in mat.textures:
        print(f"      tex type={t.type_str!r} path={t.path_str!r}")

out = m.to_bytes()
print(f"original size: {len(data)}  reserialized size: {len(out)}")
if out == data:
    print("ROUNDTRIP OK: byte-identical")
else:
    print("ROUNDTRIP MISMATCH")
    # find first diff
    n = min(len(out), len(data))
    for i in range(n):
        if out[i] != data[i]:
            print(f"first differing byte at offset {i}: original={data[i]:02x} new={out[i]:02x}")
            break
    else:
        print("common prefix identical; length differs")
