"""旧 TripPlan 到增强结构的兼容与规范化。

关键点:
- `uid` 在首次规范化时赋值,之后随计划一起保存/传输,编辑移动节点时必须保留。
- 不使用 `name` 作为唯一键。
- 不编造 `planned_start` / `planned_end`:缺失就是缺失,由体检判定为"待完善时间"。
"""

from __future__ import annotations

import re
import uuid
from typing import Optional

from ...models.schemas import Attraction, TripPlan

# 固定的命名空间,保证同一计划重复规范化得到相同 uid
_UID_NAMESPACE = uuid.UUID("6f2c1d9e-2b1a-4c3d-9f6e-1a2b3c4d5e6f")


def _slug(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"\s+", "-", text)
    return re.sub(r"[^0-9a-z\u4e00-\u9fff\-]", "", text)[:32]


def stable_uid(city: str, date: str, day_index: int, position: int, name: str) -> str:
    """基于 city/date/位置/名称生成稳定 uid(供新增节点复用)。"""
    seed = f"{city}|{date}|{day_index}|{position}|{name}"
    digest = uuid.uuid5(_UID_NAMESPACE, seed).hex[:12]
    return f"a_{digest}"


_stable_uid = stable_uid  # 兼容内部旧引用


def ensure_plan_id(plan: TripPlan) -> str:
    """为计划补一个稳定的 plan_id(仅在缺失时生成)。"""
    if plan.plan_id:
        return plan.plan_id
    seed = f"{plan.city}|{plan.start_date}|{plan.end_date}"
    plan.plan_id = f"plan_{uuid.uuid5(_UID_NAMESPACE, seed).hex[:12]}"
    return plan.plan_id


def normalize_trip_plan(plan: TripPlan) -> TripPlan:
    """返回规范化后的新计划(深拷贝),不修改入参。

    - 补齐 plan_id,revision 归一为非负整数
    - 为缺失 uid 的景点分配稳定 uid,并处理同日内 uid 冲突
    - 保持其余字段原样(不臆造时间/坐标/价格)
    """
    normalized = plan.model_copy(deep=True)
    ensure_plan_id(normalized)
    if normalized.revision is None or normalized.revision < 0:
        normalized.revision = 0

    used: set[str] = set()
    for day_index, day in enumerate(normalized.days):
        for position, attraction in enumerate(day.attractions):
            uid = (attraction.uid or "").strip()
            if not uid:
                uid = _stable_uid(
                    normalized.city, day.date, day_index, position, attraction.name
                )
            if uid in used:
                uid = f"{uid}_{position}"
            if not uid:
                uid = _stable_uid(
                    normalized.city, day.date, day_index, position, attraction.name
                )
            attraction.uid = uid
            used.add(uid)
    return normalized


def find_attraction_by_uid(
    plan: TripPlan, uid: Optional[str]
) -> Optional[tuple[int, int, Attraction]]:
    """按 uid 定位 (day_index, position, attraction)。"""
    if not uid:
        return None
    for day_index, day in enumerate(plan.days):
        for position, attraction in enumerate(day.attractions):
            if attraction.uid == uid:
                return day_index, position, attraction
    return None


def collect_attraction_uids(plan: TripPlan) -> set[str]:
    """收集计划中全部 uid。"""
    uids: set[str] = set()
    for day in plan.days:
        for attraction in day.attractions:
            if attraction.uid:
                uids.add(attraction.uid)
    return uids
