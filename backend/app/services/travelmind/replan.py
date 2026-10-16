"""功能 F02:突发事件动态重规划。

约束(规范第 5.2 节):
- 已完成 / 已锁定 / 已预约节点不可修改或删除。
- 仅调整受影响的一天,尽量保留其余行程。
- 用户报告的事件只当作"假设成立",不得伪装成天气/闭馆接口数据。
- 返回 preview,不写回当前计划,不执行任何预订/退款。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set

from ...models.schemas import Attraction, DayPlan, Location, TripPlan
from ...models.travelmind import (
    Evidence,
    HealthIssue,
    PlanChange,
    PlanPreview,
    RepairPreferences,
    ReplanEvent,
    Severity,
    ValidationOptions,
)
from .diff import budget_delta, diff_plans
from .errors import ErrorCode, TravelMindError
from .facts import FactProvider, NullFactProvider, attraction_is_outdoor
from .normalization import normalize_trip_plan, stable_uid
from .repair import _reschedule_day
from .validation import _parse_dt, _route_mode, validate_plan


def _is_protected(attraction: Attraction, locked_uids: Set[str]) -> bool:
    if attraction.uid and attraction.uid in locked_uids:
        return True
    return bool(attraction.locked or attraction.completed or attraction.reservation_confirmed)


def _manual_issue(
    code: str,
    severity: Severity,
    title: str,
    description: str,
    suggestion: str,
    day_index: Optional[int] = None,
    uids: Optional[List[str]] = None,
) -> HealthIssue:
    uids = uids or []
    key = "-".join(uids) if uids else (str(day_index) if day_index is not None else "plan")
    return HealthIssue(
        issue_id=f"{code.lower()}:{key}",
        code=code,
        severity=severity,
        title=title,
        description=description,
        affected_day_indices=[] if day_index is None else [day_index],
        affected_attraction_uids=uids,
        evidence=[Evidence(source="user", detail="基于用户报告的事件")],
        suggestion=suggestion,
        can_auto_fix=False,
    )


def _alternative_to_attraction(
    alt: dict, base: Attraction, city: str, date: str, day_index: int, position: int
) -> Attraction:
    location = alt.get("location")
    location_model = None
    if isinstance(location, dict) and location.get("longitude") is not None:
        location_model = Location(
            longitude=float(location["longitude"]), latitude=float(location["latitude"])
        )
    name = alt.get("name") or base.name
    return Attraction(
        name=name,
        address=alt.get("address") or base.address,
        location=location_model or base.location,
        visit_duration=base.visit_duration,
        description=f"替代「{base.name}」的室内/备选方案。",
        category=alt.get("category") or "室内景点",
        rating=base.rating,
        poi_id=alt.get("poi_id") or "",
        ticket_price=base.ticket_price,
        uid=stable_uid(city, date, day_index, position, name),
        verification_status="verified" if alt.get("poi_id") else "unverified",
    )


def _day_total_minutes(day: DayPlan, facts: FactProvider, city: str = "") -> float:
    mode = _route_mode(day.transportation)
    total = sum(max(int(a.visit_duration or 0), 0) for a in day.attractions)
    for i in range(len(day.attractions) - 1):
        travel = facts.travel_time_minutes(
            day.attractions[i], day.attractions[i + 1], mode, city
        )
        if travel:
            total += travel.minutes
    return total


def _drop_lowest_priority(
    day: DayPlan,
    locked_uids: Set[str],
    target_minutes: float,
    facts: FactProvider,
    city: str = "",
) -> List[Attraction]:
    removed: List[Attraction] = []
    while _day_total_minutes(day, facts, city) > target_minutes and len(day.attractions) > 1:
        candidates = [a for a in day.attractions if not _is_protected(a, locked_uids)]
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
        removed.append(victim)
    return removed


def _apply_rain(
    day: DayPlan,
    city: str,
    locked_uids: Set[str],
    facts: FactProvider,
    unresolved: List[HealthIssue],
) -> None:
    for position, attraction in enumerate(list(day.attractions)):
        if _is_protected(attraction, locked_uids) or not attraction_is_outdoor(attraction):
            continue
        alternatives = facts.indoor_alternatives(city, attraction)
        if alternatives:
            replacement = _alternative_to_attraction(
                alternatives[0], attraction, city, day.date, day.day_index, position
            )
            day.attractions[position] = replacement
        else:
            unresolved.append(
                _manual_issue(
                    "RAIN_NO_ALTERNATIVE",
                    Severity.medium,
                    "缺少室内替代",
                    f"第{day.day_index + 1}天「{attraction.name}」为户外景点,但未找到可用的室内替代。",
                    "请手动选择室内景点或调整日期。",
                    day_index=day.day_index,
                    uids=[attraction.uid or ""],
                )
            )


def _apply_closed(
    day: DayPlan,
    city: str,
    event: ReplanEvent,
    locked_uids: Set[str],
    facts: FactProvider,
    unresolved: List[HealthIssue],
) -> None:
    target = None
    target_position = -1
    if event.affected_attraction_uid:
        for position, attraction in enumerate(day.attractions):
            if attraction.uid == event.affected_attraction_uid:
                target, target_position = attraction, position
                break
        if target is None:
            raise TravelMindError(
                ErrorCode.INVALID_INPUT,
                f"受影响景点 {event.affected_attraction_uid} 不属于第{day.day_index + 1}天。",
            )
    else:
        for position, attraction in enumerate(day.attractions):
            if not _is_protected(attraction, locked_uids):
                target, target_position = attraction, position
                break
        if target is None:
            raise TravelMindError(
                ErrorCode.INVALID_INPUT,
                f"第{day.day_index + 1}天没有可调整的景点(可能全部被锁定)。",
            )

    if _is_protected(target, locked_uids):
        unresolved.append(
            _manual_issue(
                "CLOSED_LOCKED",
                Severity.high,
                "受影响景点被锁定",
                f"「{target.name}」已锁定/已预约,无法自动移除或替换。",
                "请手动决定是否释放该锁定。",
                day_index=day.day_index,
                uids=[target.uid or ""],
            )
        )
        return

    alternatives = facts.indoor_alternatives(city, target)
    if alternatives:
        replacement = _alternative_to_attraction(
            alternatives[0], target, city, day.date, day.day_index, target_position
        )
        replacement.description = f"替代临时闭馆的「{target.name}」。"
        day.attractions[target_position] = replacement
    else:
        day.attractions.pop(target_position)
        unresolved.append(
            _manual_issue(
                "CLOSED_REMOVED",
                Severity.medium,
                "已移除闭馆景点",
                f"「{target.name}」因临时闭馆被移除,当天景点减少。",
                "可手动补充替代景点。",
                day_index=day.day_index,
                uids=[target.uid or ""],
            )
        )


def _apply_delay(
    day: DayPlan,
    minutes: int,
    city: str,
    locked_uids: Set[str],
    facts: FactProvider,
    options: ValidationOptions,
) -> None:
    for attraction in day.attractions:
        if _is_protected(attraction, locked_uids):
            continue
        start = _parse_dt(attraction.planned_start)
        end = _parse_dt(attraction.planned_end)
        if start:
            attraction.planned_start = (start + timedelta(minutes=minutes)).isoformat()
        if end:
            attraction.planned_end = (end + timedelta(minutes=minutes)).isoformat()
    _reschedule_day(day, city, facts, options, False, RepairPreferences(), set())


def _apply_fatigue(
    day: DayPlan,
    city: str,
    locked_uids: Set[str],
    facts: FactProvider,
    options: ValidationOptions,
) -> None:
    for attraction in day.attractions:
        if _is_protected(attraction, locked_uids):
            continue
        attraction.visit_duration = max(20, int((attraction.visit_duration or 60) * 0.7))
    target = options.daily_max_minutes * 0.75
    _drop_lowest_priority(day, locked_uids, target, facts, city)
    _reschedule_day(day, city, facts, options, False, RepairPreferences(), set())


def _resolve_other(event: ReplanEvent) -> tuple[str, Optional[int]]:
    text = (event.description or "").lower()
    if any(word in text for word in ("雨", "rain", "暴雨")):
        return "rain", None
    if any(word in text for word in ("闭馆", "关闭", "停业", "closed", "关门")):
        return "attraction_closed", None
    if any(word in text for word in ("延误", "堵", "晚点", "delay", "迟到")):
        return "delay", event.delay_minutes or 60
    if any(word in text for word in ("累", "疲", "疲劳", "fatigue", "不舒服")):
        return "fatigue", None
    return "unknown", None


def _recompute_budget(plan: TripPlan) -> None:
    if plan.budget is None:
        return
    attraction_total = sum(
        max(int(a.ticket_price or 0), 0) for day in plan.days for a in day.attractions
    )
    plan.budget.total_attractions = attraction_total
    plan.budget.total = (
        plan.budget.total_hotels
        + plan.budget.total_meals
        + plan.budget.total_transportation
        + attraction_total
    )


def replan_plan(
    plan: TripPlan,
    event: ReplanEvent,
    locked_attraction_uids: Optional[List[str]] = None,
    max_extra_budget_yuan: Optional[int] = None,
    options: Optional[ValidationOptions] = None,
    facts: Optional[FactProvider] = None,
    base_revision: Optional[int] = None,
) -> PlanPreview:
    """根据突发事件生成重规划预览。"""
    options = options or ValidationOptions()
    facts = facts or NullFactProvider()
    plan = normalize_trip_plan(plan)
    if base_revision is None:
        base_revision = plan.revision

    locked_uids = set(locked_attraction_uids or [])
    for day in plan.days:
        for attraction in day.attractions:
            if attraction.uid and (attraction.locked or attraction.completed):
                locked_uids.add(attraction.uid)

    if event.affected_day_index >= len(plan.days):
        raise TravelMindError(
            ErrorCode.INVALID_INPUT,
            f"受影响日期索引 {event.affected_day_index} 超出计划范围。",
        )

    candidate = plan.model_copy(deep=True)
    target_day = candidate.days[event.affected_day_index]
    unresolved: List[HealthIssue] = []

    event_type = event.type
    delay_minutes = event.delay_minutes
    if event_type == "other":
        event_type, delay_minutes = _resolve_other(event)

    if event_type == "rain":
        _apply_rain(target_day, candidate.city, locked_uids, facts, unresolved)
    elif event_type == "attraction_closed":
        _apply_closed(target_day, candidate.city, event, locked_uids, facts, unresolved)
    elif event_type == "delay":
        _apply_delay(
            target_day,
            delay_minutes or 60,
            candidate.city,
            locked_uids,
            facts,
            options,
        )
    elif event_type == "fatigue":
        _apply_fatigue(target_day, candidate.city, locked_uids, facts, options)
    else:
        unresolved.append(
            _manual_issue(
                "EVENT_UNRESOLVED",
                Severity.medium,
                "无法解析事件",
                "事件描述无法映射为可执行的重规划动作。",
                "请选择具体事件类型(下雨/闭馆/延误/疲惫)。",
                day_index=event.affected_day_index,
            )
        )

    _recompute_budget(candidate)
    candidate.revision = plan.revision
    candidate_report = validate_plan(candidate, options, facts)

    combined_unresolved: List[HealthIssue] = list(unresolved)
    for issue in candidate_report.issues:
        if issue.severity != Severity.info:
            combined_unresolved.append(issue)

    delta = budget_delta(plan, candidate)
    if (
        max_extra_budget_yuan is not None
        and delta is not None
        and delta > max_extra_budget_yuan
    ):
        combined_unresolved.append(
            _manual_issue(
                "BUDGET_CONSTRAINT",
                Severity.high,
                "超出新增预算",
                f"新方案预算增加 {delta} 元,超过允许的 {max_extra_budget_yuan} 元。",
                "请调整方案或放宽预算上限。",
                day_index=event.affected_day_index,
            )
        )

    changes: List[PlanChange] = diff_plans(plan, candidate)
    if delta:
        changes.append(
            PlanChange(
                change_type="budget_update",
                before=f"¥{plan.budget.total if plan.budget else 0}",
                after=f"¥{candidate.budget.total if candidate.budget else 0}",
                reason=f"预算变化 {delta:+d} 元",
            )
        )

    if not changes:
        warning = "未能生成有效变更,当前事件可能需要人工处理。"
    elif any(issue.severity in (Severity.critical, Severity.high) for issue in combined_unresolved):
        warning = "重规划后仍存在高风险或未解决事项,请确认后再应用。"
    else:
        warning = None

    return PlanPreview(
        base_revision=base_revision,
        candidate_plan=candidate,
        changes=changes,
        unresolved_issues=combined_unresolved,
        budget_delta=delta,
        warning=warning,
        report=candidate_report,
    )
