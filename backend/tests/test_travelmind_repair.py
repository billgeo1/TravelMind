"""Phase B/C:AI 智能修复候选生成测试(规范第 10.2 节相关条目)。"""

from __future__ import annotations

from app.models.travelmind import RepairPreferences, ValidationOptions
from app.services.travelmind.facts import (
    FakeFactProvider,
    OpeningHoursFact,
    TravelTimeFact,
)
from app.services.travelmind.llm_agents import FakeLLM
from app.services.travelmind.repair import repair_plan
from app.services.travelmind.validation import validate_plan


def _facts() -> FakeFactProvider:
    return FakeFactProvider(
        opening_hours={
            "故宫": OpeningHoursFact(
                source="test", confirmed=True, open_time="08:30", close_time="17:00"
            ),
            "天安门广场": OpeningHoursFact(
                source="test", confirmed=True, open_time="05:00", close_time="22:00"
            ),
        },
        travel_times={("故宫", "天安门广场"): TravelTimeFact(minutes=20, source="test")},
    )


def _codes(report) -> set[str]:
    return {issue.code for issue in report.issues}


def test_repair_resolves_overlap_and_travel_risk(make_attraction_factory, make_plan_factory):
    """修复候选必须消除 TIME_OVERLAP 与 TRAVEL_TIME_INSUFFICIENT,并给出可审计差异。"""
    a = make_attraction_factory(
        "故宫",
        planned_start="2025-06-02T09:00:00",
        planned_end="2025-06-02T11:00:00",
    )
    b = make_attraction_factory(
        "天安门广场",
        planned_start="2025-06-02T10:30:00",
        planned_end="2025-06-02T12:30:00",
    )
    plan = make_plan_factory([[a, b]])
    facts = _facts()

    preview = repair_plan(plan, None, None, ValidationOptions(), facts)

    assert "TIME_OVERLAP" in _codes(validate_plan(plan, ValidationOptions(), facts))
    assert "TIME_OVERLAP" not in _codes(preview.report)
    assert "TRAVEL_TIME_INSUFFICIENT" not in _codes(preview.report)
    assert preview.changes, "修复必须产生可审计的变更列表"
    assert any(change.change_type == "time_update" for change in preview.changes)


def test_repair_never_modifies_locked_attraction(make_attraction_factory, make_plan_factory):
    """已锁定节点在修复中既不能被删除,也不能被改时段(规范 10.2-8)。"""
    locked = make_attraction_factory(
        "故宫",
        planned_start="2025-06-02T09:00:00",
        planned_end="2025-06-02T11:00:00",
        locked=True,
    )
    other = make_attraction_factory(
        "天安门广场",
        planned_start="2025-06-02T10:00:00",
        planned_end="2025-06-02T12:00:00",
    )
    plan = make_plan_factory([[locked, other]])

    preview = repair_plan(
        plan,
        None,
        RepairPreferences(allow_remove_attractions=True),
        ValidationOptions(),
        _facts(),
    )

    names = [a.name for a in preview.candidate_plan.days[0].attractions]
    assert "故宫" in names, "锁定节点被错误删除"
    kept = next(a for a in preview.candidate_plan.days[0].attractions if a.name == "故宫")
    assert kept.planned_start == "2025-06-02T09:00:00"
    assert kept.planned_end == "2025-06-02T11:00:00"


def test_repair_keeps_all_attractions_without_permission(
    make_attraction_factory, make_plan_factory
):
    """未授权删除时,超强度只作为未解决风险上报,不擅自删点。"""
    attractions = [
        make_attraction_factory(f"景点{i}", visit_duration=200) for i in range(3)
    ]
    plan = make_plan_factory([attractions])

    preview = repair_plan(
        plan,
        None,
        RepairPreferences(allow_remove_attractions=False),
        ValidationOptions(daily_max_minutes=300),
        FakeFactProvider(),
    )

    assert len(preview.candidate_plan.days[0].attractions) == 3
    assert any(issue.code == "EXCESSIVE_PACE" for issue in preview.unresolved_issues)


def test_repair_removes_lowest_priority_when_allowed(
    make_attraction_factory, make_plan_factory
):
    """授权删除时,按优先级移除可牺牲节点以降低强度(数值越小越先被牺牲)。"""
    a = make_attraction_factory("必须去", visit_duration=200, priority=99)
    b = make_attraction_factory("可牺牲", visit_duration=200, priority=1)
    c = make_attraction_factory("次优先", visit_duration=200, priority=50)
    plan = make_plan_factory([[a, b, c]])

    preview = repair_plan(
        plan,
        None,
        RepairPreferences(allow_remove_attractions=True),
        ValidationOptions(daily_max_minutes=450),
        FakeFactProvider(),
    )

    names = [x.name for x in preview.candidate_plan.days[0].attractions]
    assert "必须去" in names
    assert "次优先" in names
    assert "可牺牲" not in names
    assert len(names) == 2


def test_repair_ignores_invalid_llm_output(make_attraction_factory, make_plan_factory):
    """LLM 返回非法内容时必须被丢弃,保持确定性结果。"""
    a = make_attraction_factory(
        "故宫", planned_start="2025-06-02T09:00:00", planned_end="2025-06-02T11:00:00"
    )
    b = make_attraction_factory(
        "天安门广场",
        planned_start="2025-06-02T10:30:00",
        planned_end="2025-06-02T12:30:00",
    )
    plan = make_plan_factory([[a, b]])
    facts = _facts()

    deterministic = repair_plan(plan, None, None, ValidationOptions(), facts)
    with_llm = repair_plan(
        plan, None, None, ValidationOptions(), facts, llm=FakeLLM(["这不是 JSON"])
    )

    assert deterministic.candidate_plan.model_dump() == with_llm.candidate_plan.model_dump()


def test_repair_does_not_mutate_input_or_revision(make_attraction_factory, make_plan_factory):
    """预览阶段绝不能篡改当前计划;candidate 也不得擅自递增 revision。"""
    a = make_attraction_factory(
        "故宫", planned_start="2025-06-02T09:00:00", planned_end="2025-06-02T11:00:00"
    )
    b = make_attraction_factory(
        "天安门广场",
        planned_start="2025-06-02T10:30:00",
        planned_end="2025-06-02T12:30:00",
    )
    plan = make_plan_factory([[a, b]], revision=2)
    before = plan.model_dump()

    preview = repair_plan(plan, None, None, ValidationOptions(), _facts(), base_revision=1)

    assert plan.model_dump() == before, "预览不得修改入参计划"
    assert preview.base_revision == 1, "预览必须回显其所基于的版本,便于前端做 stale 拦截"
    assert preview.candidate_plan.revision == 2
