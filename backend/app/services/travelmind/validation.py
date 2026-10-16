"""功能 F01:AI 行程体检的确定性规则引擎。

设计要点:
- 纯规则、可单测、同样输入/事实必然得到同样结果。
- 事实不足时降级为 info/unknown,绝不编造营业时间、天气、价格。
- 评分 = max(0, 100 - 去重后风险扣分);覆盖度过低时 `score=None`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from ...config import get_settings
from ...models.schemas import Attraction, DayPlan, TripPlan
from ...models.travelmind import (
    Evidence,
    HealthIssue,
    HealthReport,
    Severity,
    ValidationOptions,
)
from .facts import (
    CachingFactProvider,
    FactProvider,
    NullFactProvider,
    OpeningHoursFact,
    TravelTimeFact,
    WeatherFact,
    attraction_is_outdoor,
)
from .normalization import normalize_trip_plan

# 各严重级别扣分(规范第 4.2 节)
SEVERITY_DEDUCTION: Dict[Severity, int] = {
    Severity.critical: 25,
    Severity.high: 15,
    Severity.medium: 7,
    Severity.low: 3,
    Severity.info: 0,
}

RULE_COUNT_TOTAL = 11  # 参与体检的规则条数(用于"覆盖了几条规则")
DEFAULT_DAY_START = time(9, 0)

_TRANSPORT_MODE = {
    "公共交通": "transit",
    "地铁": "transit",
    "公交": "transit",
    "自驾": "driving",
    "驾车": "driving",
    "步行": "walking",
}


def _route_mode(transportation: str) -> str:
    text = transportation or ""
    for key, mode in _TRANSPORT_MODE.items():
        if key in text:
            return mode
    return "walking"


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _day_start(date_str: str) -> datetime:
    try:
        base = datetime.strptime(date_str, "%Y-%m-%d")
    except (TypeError, ValueError):
        base = datetime(2000, 1, 1)
    return datetime.combine(base.date(), DEFAULT_DAY_START)


@dataclass
class TimelineEntry:
    attraction: Attraction
    start: Optional[datetime]
    end: Optional[datetime]
    explicit: bool  # True 表示时间来自计划本身,而非体检派生


@dataclass
class _DayFacts:
    weather: Optional[WeatherFact] = None
    opening: Dict[str, Optional[OpeningHoursFact]] = field(default_factory=dict)
    travel: Dict[Tuple[str, str], Optional[TravelTimeFact]] = field(default_factory=dict)


def _build_timeline(
    day: DayPlan,
    facts: FactProvider,
    options: ValidationOptions,
    city: str = "",
) -> List[TimelineEntry]:
    entries: List[TimelineEntry] = []
    cursor: Optional[datetime] = None
    prev: Optional[Attraction] = None
    mode = _route_mode(day.transportation)
    for attraction in day.attractions:
        explicit = bool(attraction.planned_start)
        start = _parse_dt(attraction.planned_start)
        end = _parse_dt(attraction.planned_end)
        if start is None:
            if cursor is not None:
                if prev is not None:
                    travel = facts.travel_time_minutes(prev, attraction, mode, city)
                    # 派生的时间线必须预留安全缓冲,否则会给所有"无显式时间"的计划
                    # 误报 TRAVEL_TIME_INSUFFICIENT,与规则定义(travel + buffer)冲突。
                    gap = (
                        travel.minutes + options.travel_buffer_minutes
                        if travel
                        else options.travel_buffer_minutes
                    )
                else:
                    gap = 0
                start = cursor + timedelta(minutes=gap)
            else:
                start = _day_start(day.date)
        if end is None:
            duration = max(int(attraction.visit_duration or 0), 0)
            end = start + timedelta(minutes=duration)
        entries.append(TimelineEntry(attraction, start, end, explicit))
        cursor = end
        prev = attraction
    return entries


def prefetch_plan_facts(
    plan: TripPlan,
    facts: Optional[FactProvider],
    options: Optional[ValidationOptions] = None,
) -> None:
    """并发预热体检/修复/重规划所需事实(仅对 CachingFactProvider 生效)。

    高德 MCP 的每次调用都会重建子进程(冷启动 13-15 秒),逐个串行查询会让
    一次体检耗时数分钟并撞上前端超时。这里按"去重后的最小事实集合"一次性
    并发取回,规则引擎随后全部命中缓存;超出时间预算时由 provider 进入降级
    模式,体检以 partial 报告收尾而不是把请求挂死。
    """
    if not isinstance(facts, CachingFactProvider):
        return

    plan = normalize_trip_plan(plan)
    settings = get_settings()
    key_of = CachingFactProvider._attraction_key

    jobs: List[Callable[[], Any]] = []
    seen_opening: set[str] = set()
    seen_travel: set[Tuple[str, str, str]] = set()
    seen_weather: set[Tuple[str, str]] = set()

    for day in plan.days:
        mode = _route_mode(day.transportation)
        for attraction in day.attractions:
            key = key_of(attraction)
            if key in seen_opening:
                continue
            seen_opening.add(key)
            jobs.append(lambda a=attraction: facts.opening_hours(a, plan.city))
        for i in range(len(day.attractions) - 1):
            origin, destination = day.attractions[i], day.attractions[i + 1]
            pair = (key_of(origin), key_of(destination), mode)
            if pair in seen_travel:
                continue
            seen_travel.add(pair)
            jobs.append(
                lambda o=origin, d=destination, m=mode: facts.travel_time_minutes(
                    o, d, m, plan.city
                )
            )
        if (plan.city, day.date) not in seen_weather:
            seen_weather.add((plan.city, day.date))
            jobs.append(lambda c=plan.city, dt=day.date: facts.weather(c, dt))

    facts.warm(
        jobs,
        concurrency=int(getattr(settings, "travelmind_health_concurrency", 4) or 4),
        budget_seconds=float(
            getattr(settings, "travelmind_health_budget_seconds", 150.0) or 150.0
        ),
    )


def _issue(
    code: str,
    severity: Severity,
    title: str,
    description: str,
    suggestion: str,
    day_indices: Optional[List[int]] = None,
    uids: Optional[List[str]] = None,
    evidence: Optional[List[Evidence]] = None,
    can_auto_fix: bool = False,
) -> HealthIssue:
    day_indices = day_indices or []
    uids = uids or []
    key = "-".join(uids) if uids else "-".join(str(i) for i in day_indices)
    return HealthIssue(
        issue_id=f"{code.lower()}:{key or 'plan'}",
        code=code,
        severity=severity,
        title=title,
        description=description,
        affected_day_indices=day_indices,
        affected_attraction_uids=uids,
        evidence=evidence or [],
        suggestion=suggestion,
        can_auto_fix=can_auto_fix,
    )


def _fmt(dt: Optional[datetime]) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else "未知"


def _dedup(issues: List[HealthIssue]) -> List[HealthIssue]:
    """同一规则、同一目标时间窗只保留一次。"""
    seen: set[str] = set()
    result: List[HealthIssue] = []
    for issue in issues:
        window = "-".join(
            sorted(
                e.detail or ""
                for e in issue.evidence
                if e.detail and "T" in (e.detail or "")
            )
        )
        key = f"{issue.code}|{issue.affected_attraction_uids}|{issue.affected_day_indices}|{window}"
        if key in seen:
            continue
        seen.add(key)
        result.append(issue)
    return result


def validate_plan(
    plan: TripPlan,
    options: Optional[ValidationOptions] = None,
    facts: Optional[FactProvider] = None,
) -> HealthReport:
    """对计划执行完整体检,返回 HealthReport。"""
    options = options or ValidationOptions()
    facts = facts or NullFactProvider()
    plan = normalize_trip_plan(plan)

    # 先把本次行程需要的事实并发取回(串行逐个查询会撞上前端超时)
    prefetch_plan_facts(plan, facts, options)

    attraction_count = sum(len(day.attractions) for day in plan.days)
    if not plan.days or attraction_count == 0:
        return HealthReport(
            score=None,
            status="insufficient_data",
            issues=[
                _issue(
                    "MISSING_SCHEDULE",
                    Severity.info,
                    "行程为空",
                    "当前计划没有任何景点,无法进行可行性体检。",
                    "请先生成或补充行程后再体检。",
                )
            ],
            checked_rule_count=0,
            total_rule_count=RULE_COUNT_TOTAL,
            coverage=0.0,
            checked_fact_count=0,
            total_fact_count=0,
            disclaimer=_DISCLAIMER,
        )

    issues: List[HealthIssue] = []
    checked_facts = 0
    total_facts = 0
    # 是否出现过"驾车近似"的公共交通耗时(高德公交接口不可用时的降级值)。
    # 出现时必须在报告里如实说明,不能让近似值看起来像实测值。
    has_proxied_travel = False

    timelines: List[List[TimelineEntry]] = []

    for day in plan.days:
        mode = _route_mode(day.transportation)
        day_facts = _DayFacts()
        day_facts.weather = facts.weather(plan.city, day.date)

        entries = _build_timeline(day, facts, options, plan.city)
        timelines.append(entries)

        any_explicit = any(entry.explicit for entry in entries)

        # ---- 规则:MISSING_SCHEDULE ----
        if not any_explicit:
            issues.append(
                _issue(
                    "MISSING_SCHEDULE",
                    Severity.info,
                    "待完善时间安排",
                    f"第{day.day_index + 1}天的景点没有计划到达/离开时间,无法精确校验时间冲突。",
                    "补充每个景点的计划时间,或使用智能修复生成建议时段。",
                    day_indices=[day.day_index],
                    evidence=[Evidence(source="derived", detail="计划缺少 planned_start/planned_end")],
                )
            )

        # ---- 规则:TIME_OVERLAP(仅基于计划自带的显式时间) ----
        explicit_entries = [entry for entry in entries if entry.explicit and entry.start and entry.end]
        for i in range(len(explicit_entries)):
            for j in range(i + 1, len(explicit_entries)):
                a, b = explicit_entries[i], explicit_entries[j]
                if a.start < b.end and b.start < a.end:
                    issues.append(
                        _issue(
                            "TIME_OVERLAP",
                            Severity.high,
                            "时间冲突",
                            f"第{day.day_index + 1}天「{a.attraction.name}」与「{b.attraction.name}」的游览时段重叠。",
                            "调整其中一个景点的时段,或使用智能修复重新排期。",
                            day_indices=[day.day_index],
                            uids=[a.attraction.uid or "", b.attraction.uid or ""],
                            evidence=[
                                Evidence(
                                    source="derived",
                                    detail=f"{a.attraction.name}:{_fmt(a.start)}",
                                ),
                                Evidence(
                                    source="derived",
                                    detail=f"{b.attraction.name}:{_fmt(b.start)}",
                                ),
                            ],
                            can_auto_fix=True,
                        )
                    )

        # ---- 规则:TRAVEL_TIME_INSUFFICIENT / ROUTE_UNVERIFIED ----
        for i in range(len(entries) - 1):
            prev, nxt = entries[i], entries[i + 1]
            total_facts += 1
            travel = facts.travel_time_minutes(prev.attraction, nxt.attraction, mode, plan.city)
            if travel is None:
                issues.append(
                    _issue(
                        "ROUTE_UNVERIFIED",
                        Severity.info,
                        "交通耗时未核实",
                        f"第{day.day_index + 1}天「{prev.attraction.name}」→「{nxt.attraction.name}」缺少路线数据。",
                        "接入路线服务后重新体检可获得精确结论。",
                        day_indices=[day.day_index],
                        uids=[prev.attraction.uid or "", nxt.attraction.uid or ""],
                    )
                )
                continue
            checked_facts += 1
            if travel.note:
                has_proxied_travel = True
            if prev.end and nxt.start:
                gap = (nxt.start - prev.end).total_seconds() / 60
                if gap < travel.minutes + options.travel_buffer_minutes:
                    issues.append(
                        _issue(
                            "TRAVEL_TIME_INSUFFICIENT",
                            Severity.high,
                            "赶路时间不足",
                            (
                                f"第{day.day_index + 1}天「{prev.attraction.name}」→「{nxt.attraction.name}」"
                                f"可用间隔约 {int(gap)} 分钟,低于交通 {travel.minutes} 分钟 + 缓冲 "
                                f"{options.travel_buffer_minutes} 分钟。"
                            ),
                            "后移下一个景点或缩短停留时间。",
                            day_indices=[day.day_index],
                            uids=[prev.attraction.uid or "", nxt.attraction.uid or ""],
                            evidence=[
                                Evidence(
                                    source=travel.source,
                                    detail=(
                                        f"预计交通 {travel.minutes} 分钟"
                                        + (f"({travel.note})" if travel.note else "")
                                    ),
                                )
                            ],
                            can_auto_fix=True,
                        )
                    )

        # ---- 规则:VENUE_CLOSED / OPENING_HOURS_UNKNOWN ----
        for entry in entries:
            attraction = entry.attraction
            uid = attraction.uid or ""
            total_facts += 1
            opening = facts.opening_hours(attraction, plan.city)
            day_facts.opening[uid] = opening
            if entry.explicit and entry.start:
                if opening and opening.confirmed:
                    checked_facts += 1
                    if opening.is_open_at(entry.start) is False:
                        issues.append(
                            _issue(
                                "VENUE_CLOSED",
                                Severity.critical,
                                "景点可能闭馆",
                                (
                                    f"第{day.day_index + 1}天 {_fmt(entry.start)} 访问「{attraction.name}」,"
                                    f"但按 {opening.source} 数据该时段不营业"
                                    + (f"({opening.note})" if opening.note else "")
                                    + "。"
                                ),
                                "调整到营业时段或更换景点。",
                                day_indices=[day.day_index],
                                uids=[uid],
                                evidence=[Evidence(source=opening.source, detail=f"{opening.open_time}-{opening.close_time}")],
                                can_auto_fix=True,
                            )
                        )
                else:
                    issues.append(
                        _issue(
                            "OPENING_HOURS_UNKNOWN",
                            Severity.info,
                            "营业时间未核实",
                            f"「{attraction.name}」缺少可核验的营业时间,无法判断是否闭馆。",
                            "出行前请以官方渠道为准。",
                            day_indices=[day.day_index],
                            uids=[uid],
                        )
                    )
            elif opening and opening.confirmed:
                checked_facts += 1

        # ---- 规则:RESERVATION_UNCONFIRMED ----
        for entry in entries:
            attraction = entry.attraction
            uid = attraction.uid or ""
            if attraction.requires_reservation is True and not attraction.reservation_confirmed:
                issues.append(
                    _issue(
                        "RESERVATION_UNCONFIRMED",
                        Severity.medium,
                        "预约未确认",
                        f"「{attraction.name}」可能需要预约,但尚未确认。",
                        "确认预约后再出行,或标记为已预约。",
                        day_indices=[day.day_index],
                        uids=[uid],
                    )
                )
        if entries and all(
            entry.attraction.requires_reservation is None for entry in entries
        ):
            issues.append(
                _issue(
                    "RESERVATION_UNCONFIRMED",
                    Severity.info,
                    "预约规则未核实",
                    f"第{day.day_index + 1}天未获取到预约规则,无法确认是否需要预约。",
                    "请以景区官方信息为准。",
                    day_indices=[day.day_index],
                )
            )

        # ---- 规则:EXCESSIVE_PACE ----
        total_minutes = 0.0
        for entry in entries:
            total_minutes += max(int(entry.attraction.visit_duration or 0), 0)
        for i in range(len(entries) - 1):
            travel = facts.travel_time_minutes(
                entries[i].attraction, entries[i + 1].attraction, mode, plan.city
            )
            if travel:
                total_minutes += travel.minutes
                if travel.note:
                    has_proxied_travel = True
        if total_minutes > options.daily_max_minutes:
            issues.append(
                _issue(
                    "EXCESSIVE_PACE",
                    Severity.medium,
                    "行程强度偏高",
                    (
                        f"第{day.day_index + 1}天可计算活动时长约 {int(total_minutes)} 分钟,"
                        f"超过每日上限 {options.daily_max_minutes} 分钟。"
                    ),
                    "减少景点或缩短单个景点停留时间。",
                    day_indices=[day.day_index],
                    evidence=[Evidence(source="derived", detail=f"活动时长 {int(total_minutes)} 分钟")],
                    can_auto_fix=True,
                )
            )

        # ---- 规则:BAD_WEATHER_EXPOSURE ----
        total_facts += 1
        weather = day_facts.weather
        if weather is None:
            issues.append(
                _issue(
                    "BAD_WEATHER_EXPOSURE",
                    Severity.info,
                    "天气不可用",
                    f"第{day.day_index + 1}天({day.date})没有可核验的天气数据。",
                    "出行前再次查询天气。",
                    day_indices=[day.day_index],
                )
            )
        elif weather.confirmed:
            checked_facts += 1
            has_outdoor = any(attraction_is_outdoor(entry.attraction) for entry in entries)
            if weather.is_bad_outdoor and has_outdoor:
                issues.append(
                    _issue(
                        "BAD_WEATHER_EXPOSURE",
                        Severity.medium,
                        "天气影响户外行程",
                        f"第{day.day_index + 1}天天气为「{weather.condition}」,当天含户外景点。",
                        "考虑更换室内景点或调整时段。",
                        day_indices=[day.day_index],
                        evidence=[Evidence(source=weather.source, detail=weather.condition)],
                        can_auto_fix=True,
                    )
                )

    # ---- 规则:POI_UNVERIFIED ----
    for day in plan.days:
        for attraction in day.attractions:
            total_facts += 1
            if attraction.poi_id or attraction.verification_status == "verified":
                checked_facts += 1
            else:
                issues.append(
                    _issue(
                        "POI_UNVERIFIED",
                        Severity.info,
                        "地点未核实",
                        f"「{attraction.name}」没有匹配到可定位的地图 POI。",
                        "在地图中核对或手动确认位置。",
                        day_indices=[day.day_index],
                        uids=[attraction.uid or ""],
                    )
                )

    # ---- 规则:BUDGET_EXCEEDED ----
    total_facts += 1
    if options.budget_limit_yuan is not None and plan.budget and plan.budget.total > 0:
        checked_facts += 1
        if plan.budget.total > options.budget_limit_yuan:
            issues.append(
                _issue(
                    "BUDGET_EXCEEDED",
                    Severity.high,
                    "预算超支",
                    f"预估总费用 ¥{plan.budget.total} 超过设定上限 ¥{options.budget_limit_yuan}。",
                    "减少高消费景点或调整住宿/餐饮档次。",
                    evidence=[
                        Evidence(
                            source="derived",
                            detail=f"预估 ¥{plan.budget.total} / 上限 ¥{options.budget_limit_yuan}",
                        )
                    ],
                )
            )
    elif options.budget_limit_yuan is not None:
        issues.append(
            _issue(
                "BUDGET_EXCEEDED",
                Severity.info,
                "预算不可核实",
                "计划没有可靠的费用合计,无法判断是否超支。",
                "补充门票/酒店/餐饮估算后再体检。",
            )
        )

    issues = _dedup(issues)
    coverage = (checked_facts / total_facts) if total_facts else 0.0

    if coverage >= 0.99:
        status = "complete"
    elif coverage >= 0.35:
        status = "partial"
    else:
        status = "insufficient_data"

    if status == "insufficient_data":
        score: Optional[int] = None
    else:
        deduction = sum(
            SEVERITY_DEDUCTION[issue.severity]
            for issue in issues
            if issue.severity != Severity.info
        )
        score = max(0, 100 - deduction)

    checked_rules = _RULES_CAN_CHECK(plan, facts)

    disclaimer = _DISCLAIMER
    if getattr(facts, "degraded", False):
        disclaimer += _DEGRADED_DISCLAIMER
    if has_proxied_travel:
        disclaimer += _PROXY_DISCLAIMER

    return HealthReport(
        score=score,
        status=status,
        issues=issues,
        checked_rule_count=checked_rules,
        total_rule_count=RULE_COUNT_TOTAL,
        coverage=round(coverage, 4),
        checked_fact_count=checked_facts,
        total_fact_count=total_facts,
        disclaimer=disclaimer,
    )


_DISCLAIMER = (
    "本报告基于当前可核验的事实与规则,分数不代表安全保证;"
    "标为未知/未核实的项请以官方渠道为准。"
)

_DEGRADED_DISCLAIMER = (
    "本次核验超过时间预算,部分营业时间/交通耗时/天气未取回,"
    "标记为「未核实」的项可能实际可以查到;稍后重新体检可获得更完整的结论。"
)

_PROXY_DISCLAIMER = (
    "高德公共交通接口当前不可用,公共交通耗时已用驾车路线近似估算(来源标记为 "
    "amap_proxy),仅供排期参考,实际请以公交/地铁官方时间为准。"
)


def _RULES_CAN_CHECK(plan: TripPlan, facts: FactProvider) -> int:
    """返回本次实际能得出确定性结论的规则条数。"""
    count = 0
    has_schedule = any(
        attraction.planned_start
        for day in plan.days
        for attraction in day.attractions
    )
    if has_schedule:
        count += 2  # TIME_OVERLAP + MISSING_SCHEDULE 可判断
    if any(
        attractions_have_poi(day.attractions) for day in plan.days
    ):
        count += 1  # POI_UNVERIFIED
    if plan.budget and plan.budget.total > 0:
        count += 1  # BUDGET_EXCEEDED
    # 依赖外部事实的规则
    if any(
        (facts.opening_hours(a, plan.city) or None) is not None
        for day in plan.days
        for a in day.attractions
    ):
        count += 1  # VENUE_CLOSED
    if any(facts.weather(plan.city, day.date) for day in plan.days):
        count += 1  # BAD_WEATHER_EXPOSURE
    if len(plan.days) and any(len(day.attractions) >= 2 for day in plan.days):
        count += 1  # TRAVEL_TIME_INSUFFICIENT + EXCESSIVE_PACE
    count += 1  # RESERVATION_UNCONFIRMED(可基于计划字段判断)
    return min(count, RULE_COUNT_TOTAL)


def attractions_have_poi(attractions: List[Attraction]) -> bool:
    return any(a.poi_id or a.verification_status == "verified" for a in attractions)
