"""Phase E:TravelMind 接口层测试(规范第 10.4 节第 21-25 条)。

覆盖:

- 21. 原有 ``POST /api/trip/plan`` 响应结构未被破坏。
- 22. ``health-check`` 兼容"无扩展字段"的旧 ``TripPlan``。
- 23. 5 个新接口的成功路径(含演示模式截图识别)。
- 24. 统一错误体 ``{"error": {"code", "message", "retryable"}}``。
- 25. 版本不一致 -> 409;图片过大 -> 413;伪造图片 -> 415;未配置视觉 -> 503。

所有外部依赖(高德、LLM、事实源)都在测试内被替换,断言不依赖网络。
"""

from __future__ import annotations

from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.api.routes import travelmind as travelmind_routes
from app.api.routes import trip as trip_routes
from app.config import get_settings
from app.models.schemas import TripPlan
from app.services.travelmind.errors import ErrorCode
from app.services.travelmind.facts import FakeFactProvider

client = TestClient(app)


# ============ 夹具:请求体构造 ============

def _attraction_json(name: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name,
        "address": f"北京市{name}路1号",
        "location": {"longitude": 116.4, "latitude": 39.9},
        "visit_duration": 120,
        "description": f"{name}的描述",
        "category": "景点",
    }
    payload.update(overrides)
    return payload


def _plan_json(*, city: str = "北京", revision: int = 0) -> Dict[str, Any]:
    """严格只包含"旧"字段的 TripPlan,用于验证向后兼容。"""
    return {
        "city": city,
        "start_date": "2025-06-02",
        "end_date": "2025-06-03",
        "days": [
            {
                "date": "2025-06-02",
                "day_index": 0,
                "description": "第1天行程",
                "transportation": "公共交通",
                "accommodation": "经济型酒店",
                "attractions": [
                    _attraction_json("故宫博物院"),
                    _attraction_json("天安门广场"),
                ],
                "meals": [],
            },
            {
                "date": "2025-06-03",
                "day_index": 1,
                "description": "第2天行程",
                "transportation": "公共交通",
                "accommodation": "经济型酒店",
                "attractions": [_attraction_json("颐和园")],
                "meals": [],
            },
        ],
        "weather_info": [],
        "overall_suggestions": "测试用行程",
        "budget": {"total": 1000},
        "revision": revision,
    }


@pytest.fixture
def no_network_facts(monkeypatch):
    """让所有事实源都返回"未知",避免命中高德网络调用。"""
    monkeypatch.setattr(travelmind_routes, "get_fact_provider", lambda: FakeFactProvider())


@pytest.fixture(autouse=True)
def reset_demo_mode():
    """每个用例结束后恢复默认(非演示)配置,避免相互污染。"""
    settings = get_settings()
    yield
    settings.travelmind_demo_mode = False
    settings.vision_model = ""
    settings.vision_api_key = ""


# ============ 21. 原有 /api/trip/plan 未被破坏 ============

class _StubPlanner:
    def __init__(self, plan: TripPlan) -> None:
        self._plan = plan

    def plan_trip(self, _request) -> TripPlan:
        return self._plan


def test_original_plan_endpoint_shape_unchanged(
    monkeypatch, make_plan_factory, make_attraction_factory
):
    plan = make_plan_factory(
        [
            [make_attraction_factory("故宫博物院")],
            [make_attraction_factory("颐和园")],
        ]
    )
    monkeypatch.setattr(trip_routes, "get_trip_planner_agent", lambda: _StubPlanner(plan))

    response = client.post(
        "/api/trip/plan",
        json={
            "city": "北京",
            "start_date": "2025-06-02",
            "end_date": "2025-06-03",
            "travel_days": 2,
            "transportation": "公共交通",
            "accommodation": "经济型酒店",
            "preferences": ["历史文化"],
            "free_text_input": "",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    # 顶层结构保持不变
    assert set(body) >= {"success", "message", "data"}
    assert body["success"] is True
    data = body["data"]
    # 原有字段必须原样保留
    for legacy_key in (
        "city",
        "start_date",
        "end_date",
        "days",
        "weather_info",
        "overall_suggestions",
        "budget",
    ):
        assert legacy_key in data, f"破坏了原有响应字段:{legacy_key}"
    assert data["city"] == "北京"
    assert [a["name"] for a in data["days"][0]["attractions"]] == ["故宫博物院"]


# ============ 22. 体检兼容无扩展字段的旧计划 ============

def test_health_check_accepts_legacy_plan_without_new_fields(no_network_facts):
    response = client.post(
        "/api/trip/health-check", json={"trip_plan": _plan_json()}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] in {"complete", "partial", "insufficient_data"}
    assert isinstance(body["issues"], list)
    assert body["total_rule_count"] >= 1


def test_health_check_of_empty_plan_is_insufficient_data(no_network_facts):
    plan = _plan_json()
    plan["days"] = []
    response = client.post("/api/trip/health-check", json={"trip_plan": plan})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "insufficient_data"
    assert body["score"] is None


# ============ 23. 5 个新接口的成功路径 ============

def test_repair_preview_success(no_network_facts):
    response = client.post(
        "/api/trip/repair-preview",
        json={"trip_plan": _plan_json(), "base_revision": 0},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["base_revision"] == 0
    assert body["candidate_plan"]["city"] == "北京"
    assert isinstance(body["changes"], list)
    # 预览不得就地改写原始请求(响应里带回的是候选,而非"已应用")
    assert "report" in body


def test_replan_preview_success(no_network_facts):
    response = client.post(
        "/api/trip/replan-preview",
        json={
            "trip_plan": _plan_json(),
            "base_revision": 0,
            "event": {
                "type": "rain",
                "affected_day_index": 0,
                "description": "下午突降暴雨",
            },
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["base_revision"] == 0
    assert body["candidate_plan"]["city"] == "北京"


def test_import_image_success_in_demo_mode(png_bytes, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "travelmind_demo_mode", True)

    response = client.post(
        "/api/trip/import-image",
        files={"file": ("guide.png", png_bytes(), "image/png")},
        data={"city_hint": "北京"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "mock", "演示结果必须带 mock 标识"
    assert body["detected_city"]
    assert body["candidates"], "演示模式也应返回候选地点"


def test_plan_from_import_success(monkeypatch, make_plan_factory, make_attraction_factory):
    from app.agents import trip_planner_agent

    plan = make_plan_factory([[make_attraction_factory("天安门广场")]])
    monkeypatch.setattr(
        trip_planner_agent, "get_trip_planner_agent", lambda: _StubPlanner(plan)
    )

    response = client.post(
        "/api/trip/plan-from-import",
        json={
            "request": {
                "city": "北京",
                "start_date": "2025-06-02",
                "end_date": "2025-06-02",
                "days": 1,
            },
            "confirmed_attractions": [
                {
                    "candidate_id": "c_001",
                    "name": "故宫博物院",
                    "location": {"longitude": 116.397, "latitude": 39.916},
                }
            ],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    placed = [
        attraction["name"]
        for day in body["trip_plan"]["days"]
        for attraction in day["attractions"]
    ]
    assert "故宫博物院" in placed, "已确认景点必须进入行程"


# ============ 24. 统一错误体 ============

def test_invalid_input_uses_unified_error_envelope():
    response = client.post("/api/trip/health-check", json={"trip_plan": {"city": ""}})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == ErrorCode.INVALID_INPUT
    assert body["error"]["retryable"] is False
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    # 兼容旧前端:保留 detail 字段
    assert "detail" in body


# ============ 25. 版本不一致 / 图片错误码 ============

def test_repair_preview_stale_revision_returns_409(no_network_facts):
    response = client.post(
        "/api/trip/repair-preview",
        json={"trip_plan": _plan_json(revision=0), "base_revision": 7},
    )

    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == ErrorCode.STALE_PLAN_REVISION
    assert body["error"]["retryable"] is True


def test_replan_preview_stale_revision_returns_409(no_network_facts):
    response = client.post(
        "/api/trip/replan-preview",
        json={
            "trip_plan": _plan_json(revision=2),
            "base_revision": 1,
            "event": {"type": "delay", "affected_day_index": 0, "delay_minutes": 60},
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == ErrorCode.STALE_PLAN_REVISION


def test_import_image_without_vision_returns_503(png_bytes, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "travelmind_demo_mode", False)
    monkeypatch.setattr(settings, "vision_model", "")
    monkeypatch.setattr(settings, "vision_api_key", "")

    response = client.post(
        "/api/trip/import-image", files={"file": ("guide.png", png_bytes(), "image/png")}
    )

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == ErrorCode.VISION_NOT_CONFIGURED
    assert body["error"]["retryable"] is False


def test_import_image_oversized_returns_413(png_bytes, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "travelmind_max_image_mb", 1)
    payload = png_bytes() + b"\x00" * (1024 * 1024 + 16)

    response = client.post(
        "/api/trip/import-image", files={"file": ("big.png", payload, "image/png")}
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == ErrorCode.IMAGE_TOO_LARGE


def test_import_image_fake_header_returns_415():
    response = client.post(
        "/api/trip/import-image",
        files={"file": ("fake.png", b"not an image at all", "image/png")},
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == ErrorCode.UNSUPPORTED_IMAGE
