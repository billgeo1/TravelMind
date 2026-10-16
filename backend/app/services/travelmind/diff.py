"""行程差异计算:把旧/新 TripPlan 转成可读的 PlanChange 列表。"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ...models.schemas import Attraction, TripPlan
from ...models.travelmind import PlanChange


def _index_plan(plan: TripPlan) -> Dict[str, Tuple[int, int, Attraction]]:
    index: Dict[str, Tuple[int, int, Attraction]] = {}
    for day_index, day in enumerate(plan.days):
        for position, attraction in enumerate(day.attractions):
            uid = attraction.uid or f"{day_index}:{position}:{attraction.name}"
            index[uid] = (day_index, position, attraction)
    return index


def _describe(attraction: Attraction) -> str:
    when = ""
    if attraction.planned_start:
        when = f" ({attraction.planned_start}"
        if attraction.planned_end:
            when += f"~{attraction.planned_end}"
        when += ")"
    return f"{attraction.name}{when}"


def diff_plans(old_plan: TripPlan, new_plan: TripPlan) -> List[PlanChange]:
    """比较两个计划,返回按天排序的变更列表。"""
    old_index = _index_plan(old_plan)
    new_index = _index_plan(new_plan)
    changes: List[PlanChange] = []

    removed = [uid for uid in old_index if uid not in new_index]
    added = [uid for uid in new_index if uid not in old_index]

    # 同一日内移除+新增视为"替换"(更贴近用户直觉)
    replace_pairs: List[Tuple[str, str]] = []
    for old_uid in list(removed):
        old_day = old_index[old_uid][0]
        for new_uid in list(added):
            if new_index[new_uid][0] == old_day and (old_uid, new_uid) not in replace_pairs:
                replace_pairs.append((old_uid, new_uid))
                break

    paired_old = {pair[0] for pair in replace_pairs}
    paired_new = {pair[1] for pair in replace_pairs}

    for old_uid, new_uid in replace_pairs:
        _, _, old_attr = old_index[old_uid]
        new_day, _, new_attr = new_index[new_uid]
        changes.append(
            PlanChange(
                change_type="replace",
                attraction_uid=new_uid,
                attraction_name=new_attr.name,
                day_index=new_day,
                before=old_attr.name,
                after=new_attr.name,
                reason=f"用「{new_attr.name}」替换受影响的「{old_attr.name}」",
            )
        )

    for uid in removed:
        if uid in paired_old:
            continue
        day_index, _, old_attr = old_index[uid]
        changes.append(
            PlanChange(
                change_type="remove",
                attraction_uid=uid,
                attraction_name=old_attr.name,
                day_index=day_index,
                before=_describe(old_attr),
                after=None,
                reason=f"从第{day_index + 1}天移除「{old_attr.name}」",
            )
        )

    for uid in added:
        if uid in paired_new:
            continue
        day_index, _, new_attr = new_index[uid]
        changes.append(
            PlanChange(
                change_type="add",
                attraction_uid=uid,
                attraction_name=new_attr.name,
                day_index=day_index,
                before=None,
                after=_describe(new_attr),
                reason=f"在第{day_index + 1}天新增「{new_attr.name}」",
            )
        )

    for uid, (old_day, _, old_attr) in old_index.items():
        if uid not in new_index:
            continue
        new_day, _, new_attr = new_index[uid]
        if old_day != new_day:
            changes.append(
                PlanChange(
                    change_type="move",
                    attraction_uid=uid,
                    attraction_name=new_attr.name,
                    day_index=new_day,
                    before=f"第{old_day + 1}天",
                    after=f"第{new_day + 1}天",
                    reason=f"「{new_attr.name}」从第{old_day + 1}天调整到第{new_day + 1}天",
                )
            )
        if (old_attr.planned_start, old_attr.planned_end) != (
            new_attr.planned_start,
            new_attr.planned_end,
        ):
            changes.append(
                PlanChange(
                    change_type="time_update",
                    attraction_uid=uid,
                    attraction_name=new_attr.name,
                    day_index=new_day,
                    before=f"{old_attr.planned_start or '未安排'}~{old_attr.planned_end or '未安排'}",
                    after=f"{new_attr.planned_start or '未安排'}~{new_attr.planned_end or '未安排'}",
                    reason=f"调整「{new_attr.name}」的游览时段",
                )
            )

    changes.sort(key=lambda change: (change.day_index if change.day_index is not None else 99))
    return changes


def budget_delta(old_plan: TripPlan, new_plan: TripPlan) -> Optional[int]:
    """返回新计划相对旧计划的预算变化(元);任一缺失则返回 None。"""
    old_total = old_plan.budget.total if old_plan.budget else None
    new_total = new_plan.budget.total if new_plan.budget else None
    if old_total is None and new_total is None:
        return None
    return (new_total or 0) - (old_total or 0)
