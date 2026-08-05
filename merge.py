"""
Merge logic: take a freshly-extracted "vanilla" MDF2 file (guaranteed to load
correctly in the current game version) and reapply a mod's texture overrides
onto it, matching materials by name and texture slots by their Type string.

This is deliberately conservative: we never touch anything except texture
Path strings, and only for (material, texture-type) pairs that exist in BOTH
files. Everything else -- shader params, gpbf, the mmtr reference, material
count/order, any brand-new fields the update added -- comes untouched from
the vanilla file, since that's the only copy guaranteed to match what the
current game build expects.
"""
from __future__ import annotations

from mdf2 import Mdf2File


def merge_material_textures(vanilla: Mdf2File, mod: Mdf2File, log=lambda s: None) -> int:
    """Mutates `vanilla` in place. Returns the number of texture paths changed.

    Materials are matched by INDEX POSITION, not name. This matters for
    "custom slot" mods (e.g. ones injected via a mod manager under a fake
    character code like mh03 standing in for the real vanilla ch03): the
    mod author renames materials to their own convention (e.g. 'skin',
    'banshee_UseSC') while the freshly-pulled vanilla donor file still has
    its original names (e.g. 'ch03_014_0003_helm_UseSC'). The two files are
    still the same mesh's material array in the same order, so index
    matching is what actually lines them up; name matching would silently
    match nothing for these mods.
    """
    changed = 0

    if len(vanilla.materials) != len(mod.materials):
        log(f"    [warn] material count differs: vanilla has {len(vanilla.materials)}, "
            f"mod has {len(mod.materials)} -- matching by index up to the shorter length")

    for vmat, mmat in zip(vanilla.materials, mod.materials):
        if vmat.name != mmat.name:
            log(f"    [info] material[{vmat.index}]: name differs (vanilla {vmat.name!r} vs mod {mmat.name!r}) "
                f"-- matched by position anyway")

        mod_tex_by_type = {t.type_str: t.path_str for t in mmat.textures}
        vanilla_types = {t.type_str for t in vmat.textures}

        for vtex in vmat.textures:
            new_path = mod_tex_by_type.get(vtex.type_str)
            if new_path is None:
                continue  # slot doesn't exist in the mod's file; keep vanilla default
            if new_path != vtex.path_str:
                vanilla.set_texture_path(vtex, new_path)
                changed += 1

        extra_in_mod = set(mod_tex_by_type) - vanilla_types
        if extra_in_mod:
            log(f"    [warn] material[{vmat.index}]: mod has texture slot(s) {sorted(extra_in_mod)} "
                f"that no longer exist in the vanilla layout -- dropped, can't be carried over")

    return changed
