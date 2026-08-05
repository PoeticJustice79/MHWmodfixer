"""
Fast pre-check: for each mdf2 unit in a mod (loose file or entry inside the
mod's own standalone .pak), will fixing it actually change anything?
Reuses plan_mod (the exact same donor-resolution + staleness comparison
process_mod uses) so this can never disagree with what a real run would
do -- the naive approach of comparing the .mdf2.NN trailing version number
turned out to be unreliable in practice (Capcom has shipped structural
changes -- different prop/texture-slot counts -- under an unchanged
trailing number), so staleness is judged by comparing each material's
actual structure against its resolved donor's.
"""
from __future__ import annotations

from pathlib import Path

from auto_fix import FilePlan, plan_mod
from game_archive import GameArchive
from pak_mod_fix import PakPlan


def diagnose(mod_root: Path, game: GameArchive, allow_cross_piece: bool = True) -> tuple[list[FilePlan], list[PakPlan]]:
    return plan_mod(mod_root, game, allow_cross_piece)


def _material_names(plan) -> list[str]:
    if isinstance(plan, PakPlan):
        return [m.mod_mat["name"] for e in plan.mdf_entries for m in e.materials if m.stale]
    return [m.mod_mat["name"] for m in plan.materials if m.stale]


def summarize(plans: tuple[list, list]) -> str:
    file_plans, pak_plans = plans
    applicable_pak_plans = [p for p in pak_plans if p.applicable]
    all_plans = list(file_plans) + applicable_pak_plans

    outdated = [p for p in all_plans if not p.unresolved and p.needs_rebuild]
    unresolved = [p for p in all_plans if p.unresolved]
    current = [p for p in all_plans if not p.unresolved and not p.needs_rebuild]

    def label(p):
        return str(p.rel) if isinstance(p, FilePlan) else f"{p.pak_path.name} (pak)"

    lines = [f"총 {len(all_plans)}개 mdf2 확인 (loose {len(file_plans)}개 + pak 내부 {len(applicable_pak_plans)}개)"]
    if outdated:
        lines.append(f"\n구조가 달라짐 (업데이트 필요): {len(outdated)}개")
        for p in outdated[:20]:
            lines.append(f"  {label(p)}  (머티리얼: {', '.join(_material_names(p))})")
        if len(outdated) > 20:
            lines.append(f"  ... 외 {len(outdated) - 20}개")
    if current:
        lines.append(f"\n이미 최신 구조: {len(current)}개")
    if unresolved:
        lines.append(f"\n안전하게 매칭 가능한 바닐라 도너를 찾지 못함: {len(unresolved)}개")
        for p in unresolved[:10]:
            lines.append(f"  {label(p)}")
    return "\n".join(lines)
