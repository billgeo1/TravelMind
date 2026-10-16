"""请求内事实缓存:CachingFactProvider 的命中行为与语义等价性。

背景:规则引擎会对同一事实重复提问(一对相邻景点会被问 3 次交通耗时、
每个景点被问 2 次营业时间),而真实高德 MCP 每次调用都会重建子进程
(冷启动 13-15 秒)。没有请求内缓存时一次 3 天行程体检会产生 40+ 次
往返,直接撞上前端请求超时。
"""

from __future__ import annotations

import time

from app.models.schemas import Attraction, Location
from app.models.travelmind import ValidationOptions
from app.services.travelmind.facts import (
    CachingFactProvider,
    FakeFactProvider,
    OpeningHoursFact,
    TravelTimeFact,
)
from app.services.travelmind.validation import validate_plan


def _attraction(index: int) -> Attraction:
    return Attraction(
        name=f"景点{index}",
        address=f"北京市测试路{index}号",
        location=Location(longitude=116.3 + index * 0.01, latitude=39.9 + index * 0.01),
        visit_duration=120,
        description="测试景点",
        poi_id=f"B{index:08d}",
    )


def _nine_attraction_plan(make_plan_factory):
    days = [[_attraction(day * 3 + index) for index in range(3)] for day in range(3)]
    return make_plan_factory(days)


def _full_facts() -> FakeFactProvider:
    return FakeFactProvider(
        opening_hours={
            f"B{index:08d}": OpeningHoursFact(
                source="test", confirmed=True, open_time="08:30", close_time="18:00"
            )
            for index in range(9)
        },
        travel_times={
            (f"B{index:08d}", f"B{index + 1:08d}"): TravelTimeFact(
                minutes=20, source="test"
            )
            for index in range(9)
        },
    )


def test_caching_provider_hits_for_repeated_queries():
    inner = FakeFactProvider()
    provider = CachingFactProvider(inner)
    first, second = _attraction(1), _attraction(2)

    for _ in range(3):
        provider.travel_time_minutes(first, second, "walking")
        provider.opening_hours(first, "北京")
        provider.weather("北京", "2025-06-02")

    assert inner.calls["travel_time"] == 1
    assert inner.calls["opening_hours"] == 1
    assert inner.calls["weather"] == 1
    assert provider.hits == 6
    assert provider.misses == 3


def test_caching_provider_keeps_direction_and_caches_unknown():
    """交通耗时保留方向性;查询不到(None)同样只打一次底层调用。"""
    inner = FakeFactProvider()
    provider = CachingFactProvider(inner)
    a, b = _attraction(1), _attraction(2)

    assert provider.travel_time_minutes(a, b, "walking") is None
    assert provider.travel_time_minutes(a, b, "walking") is None
    assert provider.travel_time_minutes(b, a, "walking") is None

    assert inner.calls["travel_time"] == 2  # 两个方向各查一次
    assert provider.hits == 1


def test_caching_provider_distinguishes_mode_and_city():
    inner = FakeFactProvider()
    provider = CachingFactProvider(inner)
    a, b = _attraction(1), _attraction(2)

    provider.travel_time_minutes(a, b, "walking", "北京")
    provider.travel_time_minutes(a, b, "transit", "北京")
    provider.travel_time_minutes(a, b, "walking", "上海")
    provider.weather("北京", "2025-06-02")
    provider.weather("北京", "2025-06-03")

    assert inner.calls["travel_time"] == 3
    assert inner.calls["weather"] == 2


def test_caching_provider_forwards_city_to_inner_provider():
    """城市必须透传到内层 provider(公交按坐标规划需要城市,否则查不到路线)。"""
    seen: list = []

    class _Recording(FakeFactProvider):
        def travel_time_minutes(self, origin, destination, mode, city=""):
            seen.append(city)
            return super().travel_time_minutes(origin, destination, mode, city)

    provider = CachingFactProvider(_Recording())
    provider.travel_time_minutes(_attraction(1), _attraction(2), "transit", "北京")

    assert seen == ["北京"]


def test_caching_provider_does_not_leak_indoor_list_mutation():
    inner = FakeFactProvider(
        indoor_alternatives={"景点1": [{"name": "博物馆", "source": "mock"}]}
    )
    provider = CachingFactProvider(inner)
    target = _attraction(1)

    first = provider.indoor_alternatives("北京", target)
    first.append({"name": "被污染的条目"})

    second = provider.indoor_alternatives("北京", target)
    assert [item["name"] for item in second] == ["博物馆"]
    assert inner.calls["indoor"] == 1


def test_validate_plan_queries_each_distinct_fact_once(make_plan_factory):
    """3 天 9 景点体检:底层查询次数应等于去重后的最小集合。"""
    plan = _nine_attraction_plan(make_plan_factory)
    inner = _full_facts()

    report = validate_plan(plan, ValidationOptions(), CachingFactProvider(inner))

    # 每天 2 对相邻景点 × 3 天 = 6 个唯一方向;9 个景点;3 天天气
    assert inner.calls["travel_time"] == 6
    assert inner.calls["opening_hours"] == 9
    assert inner.calls["weather"] == 3
    assert report.checked_fact_count > 0


def test_validate_plan_result_is_identical_with_caching(make_plan_factory):
    """缓存只是加速,报告内容必须与非缓存版本完全一致。"""
    plan = _nine_attraction_plan(make_plan_factory)
    facts = _full_facts()

    plain = validate_plan(plan, ValidationOptions(), facts)
    cached = validate_plan(plan, ValidationOptions(), CachingFactProvider(facts))

    assert plain.model_dump() == cached.model_dump()


# ============ 并发预热与时间预算 ============

class _SlowFacts(FakeFactProvider):
    """每次查询固定阻塞 delay 秒,用于验证并发与预算行为。"""

    delay = 0.2

    def _wait(self) -> None:
        time.sleep(self.delay)

    def opening_hours(self, attraction, city):
        self._wait()
        return super().opening_hours(attraction, city)

    def travel_time_minutes(self, origin, destination, mode, city=""):
        self._wait()
        return super().travel_time_minutes(origin, destination, mode, city)

    def weather(self, city, date):
        self._wait()
        return super().weather(city, date)


def test_warm_runs_jobs_concurrently_and_fills_cache():
    inner = _SlowFacts()
    provider = CachingFactProvider(inner)
    jobs = [
        (lambda index=index: provider.opening_hours(_attraction(index), "北京"))
        for index in range(8)
    ]

    started = time.perf_counter()
    provider.warm(jobs, concurrency=4, budget_seconds=5)
    elapsed = time.perf_counter() - started

    # 8 个 0.2s 的任务,4 路并发 -> 约 0.4s;串行会是 1.6s
    assert elapsed < 1.0
    assert inner.calls["opening_hours"] == 8
    assert provider.degraded is False
    # 预热后再查询必须命中缓存,不再阻塞
    started = time.perf_counter()
    provider.opening_hours(_attraction(0), "北京")
    assert time.perf_counter() - started < 0.05


def test_warm_marks_degraded_when_budget_is_exhausted():
    inner = _SlowFacts()
    provider = CachingFactProvider(inner)
    jobs = [
        (lambda index=index: provider.opening_hours(_attraction(index), "北京"))
        for index in range(10)
    ]

    started = time.perf_counter()
    provider.warm(jobs, concurrency=1, budget_seconds=0.05)
    elapsed = time.perf_counter() - started

    assert provider.degraded is True
    assert elapsed < 1.0  # 不会等满 10 × 0.2s

    # 降级后未命中的查询直接返回"未知",不再发起阻塞查询
    before = inner.calls["opening_hours"]
    assert provider.opening_hours(_attraction(99), "北京") is None
    assert inner.calls["opening_hours"] == before


def test_warm_is_idempotent(make_plan_factory):
    """预热只做一次,重复调用不会再来一轮并发查询。"""
    plan = _nine_attraction_plan(make_plan_factory)
    inner = FakeFactProvider()
    provider = CachingFactProvider(inner)

    from app.services.travelmind.validation import prefetch_plan_facts

    prefetch_plan_facts(plan, provider)
    first = dict(inner.calls)
    prefetch_plan_facts(plan, provider)

    assert dict(inner.calls) == first
    assert first["opening_hours"] == 9
    assert first["travel_time"] == 6
    assert first["weather"] == 3


def test_validate_plan_appends_degraded_disclaimer(make_plan_factory):
    plan = _nine_attraction_plan(make_plan_factory)
    provider = CachingFactProvider(FakeFactProvider())
    # 直接置为降级态,模拟"本次核验超过时间预算"
    provider.degraded = True

    report = validate_plan(plan, ValidationOptions(), provider)

    assert "时间预算" in report.disclaimer
    assert report.status in {"partial", "insufficient_data"}
