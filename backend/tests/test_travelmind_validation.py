"""Phase B:AI 行程体检规则引擎单元测试(规范第 10.1 节第 1-7 条)。

全部使用 FakeFactProvider / NullFactProvider,不访问任何真实外部服务。
"""

from __future__ import annotations

from app.models.schemas import Budget
from app.models.travelmind import ValidationOptions
from app.services.travelmind.facts import (
    FakeFactProvider,
    NullFactProvider,
    OpeningHoursFact,
    TravelTimeFact,
    WeatherFact,
)
from app.services.travelmind.validation import validate_plan


def _codes(report) -> set[str]:
    return {issue.code for issue in report.issues}


def _issue(report, code: str):
    matches = [issue for issue in report.issues if issue.code == code]
    assert matches, f"期望出现 {code},实际为 {_codes(report)}"
    return matches[0]


def _facts(**kwargs) -> FakeFactProvider:
    """一套"事实齐全"的提供者(故宫/天安门广场 + 交通 + 晴天)。"""
    base = dict(
        opening_hours={
            "故宫": OpeningHoursFact(
                source="test", confirmed=True, open_time="08:30", close_time="17:00"
            ),
            "天安门广场": OpeningHoursFact(
                source="test", confirmed=True, open_time="05:00", close_time="22:00"
            ),
        },
        travel_times={
            # 注意:FakeFactProvider 的键优先取 poi_id,其次才是名称
            ("p_gugong", "p_tam"): TravelTimeFact(minutes=20, source="test"),
        },
        weather={
            "2025-06-02": WeatherFact(
                date="2025-06-02", condition="晴", is_bad_outdoor=False, source="test"
            )
        },
    )
    base.update(kwargs)
    return FakeFactProvider(**base)


def _budget(total: int = 500) -> Budget:
    return Budget(
        total_attractions=total,
        total_hotels=0,
        total_meals=0,
        total_transportation=0,
        total=total,
    )


# ============ 0. 公共交通降级:近似值必须如实标注 ============

def test_proxied_travel_time_is_disclosed_in_evidence_and_disclaimer(
    make_attraction_factory, make_plan_factory
):
    """公交接口不可用时用驾车近似:证据带来源+备注,报告给出总体说明。"""
    a = make_attraction_factory(
        "故宫",
        poi_id="p_gugong",
        planned_start="2025-06-02T09:00:00",
        planned_end="2025-06-02T09:10:00",
    )
    b = make_attraction_factory(
        "天安门广场",
        poi_id="p_tam",
        planned_start="2025-06-02T09:15:00",
        planned_end="2025-06-02T11:00:00",
    )
    plan = make_plan_factory([[a, b]], budget=_budget())
    note = "公交/地铁接口不可用,此处为驾车耗时近似值"
    facts = _facts(
        travel_times={
            ("p_gugong", "p_tam"): TravelTimeFact(
                minutes=20, source="amap_proxy", mode="transit", note=note
            )
        }
    )

    report = validate_plan(plan, ValidationOptions(budget_limit_yuan=1000), facts)

    issue = _issue(report, "TRAVEL_TIME_INSUFFICIENT")
    assert issue.evidence[0].source == "amap_proxy"
    assert "近似" in issue.evidence[0].detail
    assert "amap_proxy" in report.disclaimer
    assert "近似" in report.disclaimer


def test_plain_travel_time_does_not_add_proxy_disclaimer(
    make_attraction_factory, make_plan_factory
):
    """正常(非降级)的交通耗时不加"近似"说明,避免制造噪音。"""
    a = make_attraction_factory("故宫", poi_id="p_gugong")
    b = make_attraction_factory("天安门广场", poi_id="p_tam")
    plan = make_plan_factory([[a, b]], budget=_budget())

    report = validate_plan(plan, ValidationOptions(budget_limit_yuan=1000), _facts())

    assert "amap_proxy" not in report.disclaimer


# ============ 1. 时间冲突 ============

def test_time_overlap_is_detected_and_scored(make_attraction_factory, make_plan_factory):
    """两个景点显式时段重叠 -> TIME_OVERLAP 与 TRAVEL_TIME_INSUFFICIENT(high),扣分可审计。"""
    a = make_attraction_factory(
        "故宫",
        poi_id="p_gugong",
        planned_start="2025-06-02T09:00:00",
        planned_end="2025-06-02T11:00:00",
    )
    b = make_attraction_factory(
        "天安门广场",
        poi_id="p_tam",
        planned_start="2025-06-02T10:30:00",
        planned_end="2025-06-02T12:30:00",
    )
    plan = make_plan_factory([[a, b]], budget=_budget())

    report = validate_plan(
        plan,
        ValidationOptions(budget_limit_yuan=1000),
        _facts(),
    )

    assert "TIME_OVERLAP" in _codes(report)
    assert _issue(report, "TIME_OVERLAP").severity.value == "high"
    # 两条 high(重叠 + 赶路不足)各扣 15 分
    assert report.score == 100 - 2 * 15
    assert report.status in ("partial", "complete")


# ============ 2. 缺少时间 -> 待补充,而不是"完全正常" ============

def test_missing_schedule_is_reported(make_attraction_factory, make_plan_factory):
    """没有显式时间时给出 MISSING_SCHEDULE(info),而不是判为一切正常。"""
    a = make_attraction_factory("故宫", poi_id="p_gugong")
    b = make_attraction_factory("天安门广场", poi_id="p_tam")
    plan = make_plan_factory([[a, b]], budget=_budget())

    report = validate_plan(plan, ValidationOptions(budget_limit_yuan=1000), _facts())

    issue = _issue(report, "MISSING_SCHEDULE")
    assert issue.severity.value == "info"
    # 时间字段缺失不能导出"完全正常"的结论
    assert report.score is not None
    assert report.checked_fact_count <= report.total_fact_count


# ============ 3. 闭馆结论必须来自可核验数据 ============

def test_venue_closed_requires_confirmed_opening_hours(
    make_attraction_factory, make_plan_factory
):
    """可核验的营业时间显示闭馆 -> VENUE_CLOSED(critical)。"""
    a = make_attraction_factory(
        "故宫",
        poi_id="p_gugong",
        planned_start="2025-06-02T18:00:00",
        planned_end="2025-06-02T20:00:00",
    )
    plan = make_plan_factory([[a]], budget=_budget())

    report = validate_plan(plan, ValidationOptions(budget_limit_yuan=1000), _facts())

    assert _issue(report, "VENUE_CLOSED").severity.value == "critical"


def test_no_opening_data_never_claims_venue_closed(
    make_attraction_factory, make_plan_factory
):
    """仅缺少营业时间时,只能给出 unknown,绝不能产生 VENUE_CLOSED。"""
    a = make_attraction_factory(
        "故宫",
        poi_id="p_gugong",
        planned_start="2025-06-02T18:00:00",
        planned_end="2025-06-02T20:00:00",
    )
    plan = make_plan_factory([[a]], budget=_budget())

    report = validate_plan(
        plan, ValidationOptions(budget_limit_yuan=1000), NullFactProvider()
    )

    assert "VENUE_CLOSED" not in _codes(report)
    assert _issue(report, "OPENING_HOURS_UNKNOWN").severity.value == "info"


# ============ 4. 赶路时间不足 ============

def test_travel_time_insufficient(make_attraction_factory, make_plan_factory):
    """间隔小于交通 + 缓冲 -> TRAVEL_TIME_INSUFFICIENT,且不误报时间重叠。"""
    a = make_attraction_factory(
        "故宫",
        poi_id="p_gugong",
        planned_start="2025-06-02T09:00:00",
        planned_end="2025-06-02T11:00:00",
    )
    b = make_attraction_factory(
        "天安门广场",
        poi_id="p_tam",
        planned_start="2025-06-02T11:10:00",
        planned_end="2025-06-02T13:00:00",
    )
    plan = make_plan_factory([[a, b]], budget=_budget())

    report = validate_plan(plan, ValidationOptions(budget_limit_yuan=1000), _facts())

    issue = _issue(report, "TRAVEL_TIME_INSUFFICIENT")
    assert issue.severity.value == "high"
    assert issue.can_auto_fix is True
    assert "TIME_OVERLAP" not in _codes(report)


# ============ 5. 预算超支只在有明确上限时判定 ============

def test_budget_exceeded_with_explicit_limit(make_attraction_factory, make_plan_factory):
    """已知可靠费用 > 明确数值上限 -> BUDGET_EXCEEDED(high)。"""
    a = make_attraction_factory("故宫", poi_id="p_gugong")
    plan = make_plan_factory([[a]], budget=_budget(1200))

    report = validate_plan(plan, ValidationOptions(budget_limit_yuan=1000), _facts())

    assert _issue(report, "BUDGET_EXCEEDED").severity.value == "high"


def test_budget_not_exceeded_without_numeric_limit(
    make_attraction_factory, make_plan_factory
):
    """没有明确数值预算时,不能给出确定金额的超限结论。"""
    a = make_attraction_factory("故宫", poi_id="p_gugong")
    plan = make_plan_factory([[a]], budget=_budget(9999))

    report = validate_plan(plan, ValidationOptions(budget_limit_yuan=None), _facts())

    high_budget = [
        issue
        for issue in report.issues
        if issue.code == "BUDGET_EXCEEDED" and issue.severity.value == "high"
    ]
    assert high_budget == []


# ============ 6. 确定性 ============

def test_same_input_same_report(make_attraction_factory, make_plan_factory):
    """同样输入 + 同样事实 -> 完全一致的报告(不依赖模型随机性)。"""
    a = make_attraction_factory(
        "故宫",
        poi_id="p_gugong",
        planned_start="2025-06-02T09:00:00",
        planned_end="2025-06-02T11:00:00",
    )
    b = make_attraction_factory("天安门广场", poi_id="p_tam")
    plan = make_plan_factory([[a, b]], budget=_budget())

    first = validate_plan(plan, ValidationOptions(budget_limit_yuan=1000), _facts())
    second = validate_plan(plan, ValidationOptions(budget_limit_yuan=1000), _facts())

    assert first.model_dump() == second.model_dump()


# ============ 7. 未知状态被保留 ============

def test_unknown_weather_and_price_are_preserved(
    make_attraction_factory, make_plan_factory
):
    """天气不可用 -> info"天气不可用";未确认价格保持 unknown,不伪装成官方事实。"""
    a = make_attraction_factory(
        "故宫",
        poi_id="p_gugong",
        planned_start="2025-06-02T09:00:00",
        planned_end="2025-06-02T11:00:00",
        price_status="unknown",
    )
    plan = make_plan_factory([[a]], budget=_budget())
    facts = _facts(weather={})  # 明确没有天气事实

    report = validate_plan(plan, ValidationOptions(budget_limit_yuan=1000), facts)

    weather_issue = _issue(report, "BAD_WEATHER_EXPOSURE")
    assert weather_issue.severity.value == "info"
    assert "天气" in weather_issue.title
    # 报告必须显式声明未知,并且分数仍可计算而非直接判 0
    assert report.disclaimer
    assert report.score is not None
