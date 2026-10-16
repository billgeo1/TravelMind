"""功能 F01:智能修复候选生成。

流程:
1. 基于确定性规则重新排期,消除时间冲突 / 赶路不足 / 缺失时段。
2. 依据可核验的营业时间把景点挪到开放时段。
3. 若允许删除,按优先级降低超强度日程。
4. 生成候选计划后,用**同一规则引擎**复检;无法证明修复的风险进入 unresolved_issues。
5. 可选:调用 LLM 提出排序候选,但必须通过 uid 白名单校验与规则复检才采纳。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

from ...models.schemas import Attraction, DayPlan, TripPlan
from ...models.travelmind import (
    HealthIssue,
    HealthReport,
    PlanChange,
    PlanPreview,
    RepairPreferences,
    Severity,
    ValidationOptions,
)
from .diff import budget_delta, diff_plans
from .facts import FactProvider, NullFactProvider, OpeningHoursFact
from .llm_agents import RepairLLM
from .normalization import normalize_trip_plan
from .validation import _day_start, _parse_dt, _route_mode, validate_plan


def _protected(attraction: Attraction, preferences: RepairPreferences) -> bool:
    if attraction.locked or attraction.completed:
        return True
    if preferences.preserve_confirmed_bookings and (
        attraction.reservation_confirmed or attraction.requires_reservation is True
    ):
        return True
    return False


def _find_open_slot(
    opening: OpeningHoursFact,
    earliest: datetime,
    duration: int,
    latest: datetime,
) -> Optional[datetime]:
    """在 [earliest, latest] 内按 30 分钟步长寻找开放时段。"""
    candidate = earliest
    minute = candidate.minute
    if minute % 30 != 0:
        candidate = candidate.replace(minute=0, second=0, microsecond=0) + timedelta(
            minutes=(30 if minute < 30 else 60)
        )
    for _ in range(48):
        if candidate + timedelta(minutes=duration) > latest:
            return None
        if opening.is_open_at(candidate):
            return candidate
        candidate += timedelta(minutes=30)
    return None


def _resolve_tz(day: DayPlan):
    for attraction in day.attractions:
        dt = _parse_dt(attraction.planned_start)
        if dt is not None and dt.tzinfo is not None:
            return dt.tzinfo
    return None


def _reschedule_day(
    day: DayPlan,
    city: str,
    facts: FactProvider,
    options: ValidationOptions,
    allow_remove: bool,
    preferences: RepairPreferences,
    venue_unresolved: Set[str],
) -> None:
    """确定性重排:消除重叠、补齐时段、保证交通缓冲、规避闭馆。"""
    mode = _route_mode(day.transportation)
    tz = _resolve_tz(day)
    day_start = _day_start(day.date)
    latest = day_start.replace(hour=21, minute=0)
    if tz is not None:
        day_start = day_start.replace(tzinfo=tz)
        latest = latest.replace(tzinfo=tz)

    kept: List[Attraction] = []
    cursor: Optional[datetime] = None
    prev: Optional[Attraction] = None

    for attraction in list(day.attractions):
        gap = 0
        if prev is not None:
            travel = facts.travel_time_minutes(prev, attraction, mode, city)
            # 与体检规则保持一致:相邻景点之间预留 交通时间 + 安全缓冲
            gap = (
                travel.minutes + options.travel_buffer_minutes
                if travel
                else options.travel_buffer_minutes
            )

        explicit = _parse_dt(attraction.planned_start)
        if explicit is not None and explicit.tzinfo is None and tz is not None:
            explicit = explicit.replace(tzinfo=tz)

        if cursor is None:
            start = explicit or day_start
        else:
            earliest = cursor + timedelta(minutes=gap)
            start = max(explicit, earliest) if explicit else earliest

        duration = max(int(attraction.visit_duration or 0), 15)

        if _protected(attraction, preferences):
            # 已锁定 / 已完成 / 已预约的节点绝不改时段、绝不删除;
            # 仅把它当作固定锚点推进游标,由此产生的冲突会作为未解决风险上报。
            explicit_end = _parse_dt(attraction.planned_end)
            if explicit_end is not None and explicit_end.tzinfo is None and tz is not None:
                explicit_end = explicit_end.replace(tzinfo=tz)
            cursor = explicit_end or (start + timedelta(minutes=duration))
            prev = attraction
            kept.append(attraction)
            continue

        opening = facts.opening_hours(attraction, city)
        if opening and opening.confirmed and opening.is_open_at(start) is False:
            slot = _find_open_slot(opening, start, duration, latest)
            if slot is not None:
                start = slot
            else:
                venue_unresolved.add(attraction.uid or attraction.name)
                if allow_remove and not _protected(attraction, preferences):
                    continue

        end = start + timedelta(minutes=duration)
        attraction.planned_start = start.isoformat()
        attraction.planned_end = end.isoformat()
        cursor = end
        prev = attraction
        kept.append(attraction)

    day.attractions = kept


def _enforce_pace(
    day: DayPlan,
    city: str,
    facts: FactProvider,
    options: ValidationOptions,
    preferences: RepairPreferences,
) -> None:
    """超强度时按优先级删除可牺牲节点(仅在用户允许删除时)。"""
    if not preferences.allow_remove_attractions:
        return
    mode = _route_mode(day.transportation)

    def total_minutes() -> float:
        total = sum(max(int(a.visit_duration or 0), 0) for a in day.attractions)
        for i in range(len(day.attractions) - 1):
            travel = facts.travel_time_minutes(
                day.attractions[i], day.attractions[i + 1], mode, city
            )
            if travel:
                total += travel.minutes
        return total

    changed = False
    while total_minutes() > options.daily_max_minutes and len(day.attractions) > 1:
        candidates = [a for a in day.attractions if not _protected(a, preferences)]
        if not candidates:
            break
        victim = min(
            candidates,
            key=lambda a: (
                a.priority if a.priority is not None else 50,
                -max(int(a.visit_duration or 0), 0),
            ),
        )
        day.attractions.remove(victim)
        changed = True

    if changed:
        _reschedule_day(
            day, city, facts, options, False, preferences, set()
        )


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group())
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _try_llm_ordering(
    plan: TripPlan,
    candidate: TripPlan,
    llm: RepairLLM,
    options: ValidationOptions,
    facts: FactProvider,
) -> TripPlan:
    """让 LLM 提出排序建议;非法输出或未改善则保持确定性结果。"""
    allowed: Dict[int, Set[str]] = {
        day_index: {a.uid or "" for a in day.attractions}
        for day_index, day in enumerate(plan.days)
    }
    prompt = (
        "你是行程排期助手。仅输出 JSON,格式为 "
        '{"order":[{"day_index":0,"uids":["uid1","uid2"]}]},'
        "每个 day 的 uids 必须是给定集合的排列,不得新增/删除/改名。\n"
        + json.dumps(
            {
                "days": [
                    {
                        "day_index": i,
                        "attractions": [
                            {"uid": a.uid, "name": a.name, "visit_duration": a.visit_duration}
                            for a in day.attractions
                        ],
                    }
                    for i, day in enumerate(plan.days)
                ]
            },
            ensure_ascii=False,
        )
    )
    try:
        raw = llm(prompt)
    except Exception:
        return candidate
    data = _extract_json(raw or "")
    if not data:
        return candidate

    trial = candidate.model_copy(deep=True)
    try:
        for item in data.get("order", []):
            day_index = int(item.get("day_index"))
            uids = [str(u) for u in item.get("uids", [])]
            if day_index not in allowed or set(uids) != allowed[day_index]:
                return candidate
            by_uid = {a.uid: a for a in trial.days[day_index].attractions}
            trial.days[day_index].attractions = [by_uid[uid] for uid in uids]
    except (KeyError, TypeError, ValueError, IndexError):
        return candidate

    before = validate_plan(candidate, options, facts)
    after = validate_plan(trial, options, facts)
    before_bad = sum(1 for i in before.issues if i.severity != Severity.info)
    after_bad = sum(1 for i in after.issues if i.severity != Severity.info)
    return trial if after_bad < before_bad else candidate


def repair_plan(
    plan: TripPlan,
    report: Optional[HealthReport] = None,
    preferences: Optional[RepairPreferences] = None,
    options: Optional[ValidationOptions] = None,
    facts: Optional[FactProvider] = None,
    base_revision: Optional[int] = None,
    llm: Optional[RepairLLM] = None,
) -> PlanPreview:
    """生成修复预览(不修改当前行程,不自动下单)。"""
    options = options or ValidationOptions()
    preferences = preferences or RepairPreferences()
    facts = facts or NullFactProvider()
    plan = normalize_trip_plan(plan)
    if base_revision is None:
        base_revision = plan.revision

    original_report = report or validate_plan(plan, options, facts)

    candidate = plan.model_copy(deep=True)
    venue_unresolved: Set[str] = set()
    for day in candidate.days:
        _reschedule_day(
            day,
            candidate.city,
            facts,
            options,
            preferences.allow_remove_attractions,
            preferences,
            venue_unresolved,
        )
    for day in candidate.days:
        _enforce_pace(day, candidate.city, facts, options, preferences)

    if llm is not None:
        candidate = _try_llm_ordering(plan, candidate, llm, options, facts)

    candidate.revision = plan.revision
    candidate_report = validate_plan(candidate, options, facts)

    changes: List[PlanChange] = diff_plans(plan, candidate)
    delta = budget_delta(plan, candidate)
    if delta:
        changes.append(
            PlanChange(
                change_type="budget_update",
                before=f"¥{plan.budget.total if plan.budget else 0}",
                after=f"¥{candidate.budget.total if candidate.budget else 0}",
                reason=f"预算变化 {delta:+d} 元",
            )
        )

    unresolved: List[HealthIssue] = [
        issue for issue in candidate_report.issues if issue.severity != Severity.info
    ]

    if not changes:
        warning = "未生成可自动应用的变更;当前风险可能需要人工处理或补充可核验事实。"
    elif any(issue.severity in (Severity.critical, Severity.high) for issue in unresolved):
        warning = "存在未能自动修复的高风险项,请在应用前人工确认。"
    else:
        warning = None

    return PlanPreview(
        base_revision=base_revision,
        candidate_plan=candidate,
        changes=changes,
        unresolved_issues=unresolved,
        budget_delta=delta,
        warning=warning,
        report=candidate_report,
    )
