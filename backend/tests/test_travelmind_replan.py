"""Phase C:突发事件动态重规划测试(规范第 10.2 节第 8-14 条)。"""

from __future__ import annotations

import pytest

from app.models.schemas import TripPlan
from app.models.travelmind import ReplanEvent, ValidationOptions
from app.services.travelmind.errors import ErrorCode, TravelMindError
from app.services.travelmind.facts import (
    FakeFactProvider,
    OpeningHoursFact,
    TravelTimeFact,
)
from app.services.travelmind.normalization import normalize_trip_plan
from app.services.travelmind.replan import replan_plan


def _facts(
    *,
    indoor=None,
    opening=None,
    travel=None,
) -> FakeFactProvider:
    return FakeFactProvider(
        opening_hours=opening or {},
        travel_times=travel or {},
        indoor_alternatives=indoor or {},
    )


def _names(day) -> list[str]:
    return [a.name for a in day.attractions]


def _uid(plan: TripPlan, name: str) -> str:
    for day in plan.days:
        for attraction in day.attractions:
            if attraction.name == name:
                return attraction.uid or ""
    raise AssertionError(f"未找到 {name}")


# ============ 8. 锁定 / 已完成节点保护 ============

def test_locked_and_completed_nodes_are_preserved(
    make_attraction_factory, make_plan_factory
):
    """疲劳事件按优先级删点,但锁定/已完成节点必须保留且时段不变。"""
    locked = make_attraction_factory("锁定景点", visit_duration=200, locked=True)
    done = make_attraction_factory("已完成景点", visit_duration=200, completed=True)
    normal = make_attraction_factory("普通景点", visit_duration=200)
    plan = make_plan_factory([[locked, done, normal]])
    locked_uid = _uid(normalize_trip_plan(plan), "锁定景点")

    preview = replan_plan(
        plan,
        ReplanEvent(type="fatigue", affected_day_index=0),
        locked_attraction_uids=[locked_uid],
        options=ValidationOptions(daily_max_minutes=540),
        facts=_facts(),
    )

    names = _names(preview.candidate_plan.days[0])
    assert "锁定景点" in names
    assert "已完成景点" in names
    assert "普通景点" not in names
    kept = next(a for a in preview.candidate_plan.days[0].attractions if a.name == "锁定景点")
    assert kept.visit_duration == 200


def test_closed_on_locked_node_reports_unresolved(make_attraction_factory, make_plan_factory):
    """对锁定节点施加"临时闭馆"只能给出未解决风险,不能悄悄删除。"""
    locked = make_attraction_factory("锁定景点", locked=True)
    plan = make_plan_factory([[locked]])
    target_uid = _uid(normalize_trip_plan(plan), "锁定景点")

    preview = replan_plan(
        plan,
        ReplanEvent(
            type="attraction_closed",
            affected_day_index=0,
            affected_attraction_uid=target_uid,
        ),
        locked_attraction_uids=[target_uid],
        facts=_facts(),
    )

    assert "锁定景点" in _names(preview.candidate_plan.days[0])
    assert any(issue.code == "CLOSED_LOCKED" for issue in preview.unresolved_issues)
    assert preview.warning, "存在未解决高风险时必须给出提示"


# ============ 9. 恶劣天气只改受影响的那一天 ============

def test_rain_replaces_outdoor_only_on_affected_day(
    make_attraction_factory, make_plan_factory
):
    """暴雨只调整受影响日的户外节点,其余日期保持原样。"""
    outdoor = make_attraction_factory("颐和园", category="园林")
    day2_a = make_attraction_factory(
        "中国国家博物馆",
        category="博物馆",
        planned_start="2025-06-03T09:00:00",
        planned_end="2025-06-03T11:00:00",
    )
    plan = make_plan_factory([[outdoor], [day2_a]])
    facts = _facts(
        indoor={
            "颐和园": [
                {
                    "name": "中国国家博物馆",
                    "address": "北京市东城区东长安街16号",
                    "location": {"longitude": 116.3958, "latitude": 39.9055},
                    "poi_id": "p_museum",
                    "category": "博物馆",
                }
            ]
        }
    )

    preview = replan_plan(
        plan,
        ReplanEvent(type="rain", affected_day_index=0),
        facts=facts,
    )

    day1 = preview.candidate_plan.days[0]
    assert _names(day1) == ["中国国家博物馆"]
    # 未受影响的第二天完全不变
    day2 = preview.candidate_plan.days[1]
    assert _names(day2) == ["中国国家博物馆"]
    assert day2.attractions[0].planned_start == "2025-06-03T09:00:00"
    assert any(change.change_type == "replace" for change in preview.changes)


def test_rain_without_alternative_reports_risk(make_attraction_factory, make_plan_factory):
    """没有室内替代时,必须报告未解决风险而不是假装成功。"""
    outdoor = make_attraction_factory("颐和园", category="园林")
    plan = make_plan_factory([[outdoor]])

    preview = replan_plan(
        plan,
        ReplanEvent(type="rain", affected_day_index=0),
        facts=_facts(),
    )

    assert "颐和园" in _names(preview.candidate_plan.days[0])
    assert any(issue.code == "RAIN_NO_ALTERNATIVE" for issue in preview.unresolved_issues)


# ============ 10. 延误 ============

def test_delay_shifts_known_times(make_attraction_factory, make_plan_factory):
    """delay=90 能正确平移已知时段。"""
    a = make_attraction_factory(
        "故宫", planned_start="2025-06-02T09:00:00", planned_end="2025-06-02T11:00:00"
    )
    plan = make_plan_factory([[a]])
    facts = _facts(
        opening={
            "故宫": OpeningHoursFact(
                source="test", confirmed=True, open_time="08:30", close_time="17:00"
            )
        }
    )

    preview = replan_plan(
        plan,
        ReplanEvent(type="delay", affected_day_index=0, delay_minutes=90),
        facts=facts,
    )

    moved = preview.candidate_plan.days[0].attractions[0]
    assert moved.planned_start.startswith("2025-06-02T10:30")
    assert any(change.change_type == "time_update" for change in preview.changes)


def test_delay_beyond_opening_hours_reports_unresolved(
    make_attraction_factory, make_plan_factory
):
    """延误后无法满足营业时间时,必须给出 VENUE_CLOSED 未解决风险。"""
    a = make_attraction_factory(
        "故宫", planned_start="2025-06-02T09:00:00", planned_end="2025-06-02T10:00:00"
    )
    plan = make_plan_factory([[a]])
    facts = _facts(
        opening={
            "故宫": OpeningHoursFact(
                source="test", confirmed=True, open_time="09:00", close_time="11:00"
            )
        }
    )

    preview = replan_plan(
        plan,
        ReplanEvent(type="delay", affected_day_index=0, delay_minutes=120),
        facts=facts,
    )

    assert any(issue.code == "VENUE_CLOSED" for issue in preview.unresolved_issues)
    assert preview.warning


# ============ 11 / 13. 预览不落地、无解不伪装成功 ============

def test_preview_never_mutates_current_plan(make_attraction_factory, make_plan_factory):
    """用户"取消"的场景:原计划与 revision 完全不变。"""
    a = make_attraction_factory(
        "故宫", planned_start="2025-06-02T09:00:00", planned_end="2025-06-02T11:00:00"
    )
    plan = make_plan_factory([[a]], revision=3)
    before = plan.model_dump()

    replan_plan(
        plan,
        ReplanEvent(type="delay", affected_day_index=0, delay_minutes=30),
        facts=_facts(),
    )

    assert plan.model_dump() == before
    assert plan.revision == 3


def test_no_alternative_removes_and_reports(make_attraction_factory, make_plan_factory):
    """景点闭馆且无替代:移除并明确上报,而不是虚假成功。"""
    a = make_attraction_factory("某景点")
    b = make_attraction_factory("另一景点")
    plan = make_plan_factory([[a, b]])
    target_uid = _uid(normalize_trip_plan(plan), "某景点")

    preview = replan_plan(
        plan,
        ReplanEvent(
            type="attraction_closed",
            affected_day_index=0,
            affected_attraction_uid=target_uid,
        ),
        facts=_facts(),
    )

    assert "某景点" not in _names(preview.candidate_plan.days[0])
    assert any(issue.code == "CLOSED_REMOVED" for issue in preview.unresolved_issues)
    assert any(change.change_type == "remove" for change in preview.changes)


# ============ 非法输入 ============

def test_day_index_out_of_range_raises(make_attraction_factory, make_plan_factory):
    plan = make_plan_factory([[make_attraction_factory("故宫")]])

    with pytest.raises(TravelMindError) as excinfo:
        replan_plan(
            plan,
            ReplanEvent(type="rain", affected_day_index=5),
            facts=_facts(),
        )

    assert excinfo.value.code == ErrorCode.INVALID_INPUT


def test_unknown_attraction_uid_for_day_raises(make_attraction_factory, make_plan_factory):
    plan = make_plan_factory([[make_attraction_factory("故宫")]])

    with pytest.raises(TravelMindError) as excinfo:
        replan_plan(
            plan,
            ReplanEvent(
                type="attraction_closed",
                affected_day_index=0,
                affected_attraction_uid="不存在的uid",
            ),
            facts=_facts(),
        )

    assert excinfo.value.code == ErrorCode.INVALID_INPUT


# ============ 14. 新计划仍能被旧模块读取 ============

def test_candidate_plan_round_trips_for_legacy_modules(
    make_attraction_factory, make_plan_factory
):
    """修复/重规划后的计划必须能被原有 TripPlan 结构完整解析(地图/编辑/预算/导出)。"""
    a = make_attraction_factory(
        "故宫", planned_start="2025-06-02T09:00:00", planned_end="2025-06-02T11:00:00"
    )
    plan = make_plan_factory([[a]])

    preview = replan_plan(
        plan,
        ReplanEvent(type="delay", affected_day_index=0, delay_minutes=30),
        facts=_facts(),
    )

    payload = preview.candidate_plan.model_dump()
    restored = TripPlan.model_validate(payload)
    attraction = restored.days[0].attractions[0]
    # 旧页面依赖的字段都在
    assert attraction.name == "故宫"
    assert attraction.address
    assert attraction.location.longitude
    assert attraction.visit_duration > 0
    assert restored.overall_suggestions is not None
    # 新字段不会破坏旧结构
    assert restored.plan_id
    assert restored.revision >= 0
