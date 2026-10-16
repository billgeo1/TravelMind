"""高德服务解析层测试。

这些测试不启动 MCP 子进程、不发网络请求:用 FakeMcpTool 伪造
``MCPTool.run`` 的真实返回格式(带 ``工具 '...' 执行结果:`` 前缀的字符串),
覆盖 POI 搜索补坐标、天气、路线、地理编码、详情缓存的解析与失败分支。
"""

from __future__ import annotations

import json
import shlex
from typing import Any, Dict, List

import pytest

from app.config import get_settings
from app.services import amap_service as amap_module
from app.services.amap_service import (
    DEFAULT_MCP_COMMAND,
    AmapMcpError,
    AmapService,
    _resolve_mcp_command,
    parse_location,
    parse_mcp_result,
)


class FakeMcpTool:
    """伪造 MCPTool:按其真实字符串格式返回预设内容。"""

    def __init__(self, responses: Dict[str, Any]) -> None:
        self.responses = responses
        self.calls: List[tuple] = []

    def run(self, payload: Dict[str, Any]) -> Any:
        tool_name = payload.get("tool_name")
        self.calls.append((tool_name, payload.get("arguments")))
        value = self.responses.get(tool_name)
        if value is None:
            return "异步操作失败: Connection closed"
        if callable(value):
            return value(payload.get("arguments") or {})
        return value

    def calls_for(self, tool_name: str) -> List[Dict[str, Any]]:
        return [args for name, args in self.calls if name == tool_name]


def tool_result(tool_name: str, payload: Any) -> str:
    """复刻 MCPTool.run 的成功返回格式。"""
    return f"工具 '{tool_name}' 执行结果:\n" + json.dumps(payload, ensure_ascii=False)


def build_service(responses: Dict[str, Any]) -> tuple:
    service = AmapService.__new__(AmapService)  # 跳过 __init__,避免启动 MCP
    fake = FakeMcpTool(responses)
    service.mcp_tool = fake
    return service, fake


@pytest.fixture(autouse=True)
def _clear_service_caches():
    """清空进程内缓存,避免用例之间通过缓存互相污染。"""
    amap_module._poi_detail_cache.clear()
    amap_module._route_cache.clear()
    amap_module._weather_cache.clear()
    amap_module.reset_transit_breaker()
    yield
    amap_module._poi_detail_cache.clear()
    amap_module._route_cache.clear()
    amap_module._weather_cache.clear()
    amap_module.reset_transit_breaker()


def test_parse_mcp_result_strips_tool_prefix():
    raw = tool_result("maps_text_search", {"pois": [{"id": "1", "name": "外滩"}]})
    assert parse_mcp_result(raw) == {"pois": [{"id": "1", "name": "外滩"}]}


def test_parse_mcp_result_passes_through_dict():
    payload = {"pois": []}
    assert parse_mcp_result(payload) is payload


def test_parse_mcp_result_raises_on_connection_closed():
    with pytest.raises(AmapMcpError) as excinfo:
        parse_mcp_result("异步操作失败: Connection closed")
    assert "Connection closed" in str(excinfo.value)


def test_parse_mcp_result_raises_on_garbage():
    with pytest.raises(AmapMcpError):
        parse_mcp_result("完全看不懂的输出")


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_parse_mcp_result_raises_on_empty(raw):
    with pytest.raises(AmapMcpError):
        parse_mcp_result(raw)


def test_parse_mcp_result_ignores_noise_around_json():
    raw = "工具 'maps_geo' 执行结果:\n前缀文本\n{\"return\": []}\n后缀"
    assert parse_mcp_result(raw) == {"return": []}


def test_parse_location_accepts_amap_string():
    location = parse_location("121.4737,31.2304")
    assert location is not None
    assert location.longitude == pytest.approx(121.4737)
    assert location.latitude == pytest.approx(31.2304)


def test_parse_location_accepts_dict_and_nested():
    assert parse_location({"longitude": 116.4, "latitude": 39.9}) is not None
    assert parse_location({"lng": 116.4, "lat": 39.9}) is not None
    nested = parse_location({"location": "116.4,39.9"})
    assert nested is not None and nested.latitude == pytest.approx(39.9)


@pytest.mark.parametrize(
    "value",
    [None, "", "abc", "not-a-coord", {"longitude": 999, "latitude": 999}, "0,0", {}],
)
def test_parse_location_rejects_invalid(value):
    assert parse_location(value) is None


def test_resolve_mcp_command_falls_back_to_default(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "amap_mcp_command", "", raising=False)
    assert _resolve_mcp_command() == shlex.split(DEFAULT_MCP_COMMAND)
    monkeypatch.setattr(settings, "amap_mcp_command", "   ", raising=False)
    assert _resolve_mcp_command() == shlex.split(DEFAULT_MCP_COMMAND)


def test_resolve_mcp_command_respects_override(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "amap_mcp_command",
        'uvx --with "pydantic<2.13" amap-mcp-server',
        raising=False,
    )
    assert _resolve_mcp_command() == [
        "uvx",
        "--with",
        "pydantic<2.13",
        "amap-mcp-server",
    ]


def test_resolve_mcp_command_default_pins_pydantic():
    parts = _resolve_mcp_command("")
    assert "amap-mcp-server" in parts
    assert "pydantic<2.14" in parts


def test_resolve_mcp_command_falls_back_on_bad_quoting(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "amap_mcp_command", 'uvx "unclosed', raising=False)
    assert _resolve_mcp_command() == shlex.split(DEFAULT_MCP_COMMAND)


_TEXT_SEARCH_OK = {
    "suggestion": {"keywords": [], "cities": []},
    "pois": [
        {"id": "B001", "name": "外滩", "address": "中山东一路", "typecode": "110202"},
        {"id": "B002", "name": "外滩码头", "address": "滨江大道", "typecode": "110200"},
    ],
}

_DETAILS = {
    "B001": {
        "id": "B001",
        "name": "外滩",
        "location": "121.490317,31.236305",
        "address": "中山东一路",
        "city": "上海",
        "tel": "021-12345678",
    },
    "B002": {
        "id": "B002",
        "name": "外滩码头",
        "location": "121.501,31.239",
        "address": "滨江大道",
        "city": "上海",
    },
}


def _search_responses() -> Dict[str, Any]:
    return {
        "maps_text_search": tool_result("maps_text_search", _TEXT_SEARCH_OK),
        "maps_search_detail": lambda args: tool_result(
            "maps_search_detail", _DETAILS[args["id"]]
        ),
    }


def test_search_poi_backfills_coordinates_from_detail():
    service, fake = build_service(_search_responses())
    pois = service.search_poi("外滩", "上海")

    assert [poi.name for poi in pois] == ["外滩", "外滩码头"]
    assert pois[0].location.longitude == pytest.approx(121.490317)
    assert pois[0].location.latitude == pytest.approx(31.236305)
    assert pois[0].address == "中山东一路"
    assert pois[0].tel == "021-12345678"
    assert pois[0].type == "110202"
    assert len(fake.calls_for("maps_search_detail")) == 2


def test_search_poi_passes_arguments_to_mcp():
    service, fake = build_service(_search_responses())
    service.search_poi("外滩", "上海", citylimit=True)
    assert fake.calls_for("maps_text_search")[0] == {
        "keywords": "外滩",
        "city": "上海",
        "citylimit": "true",
    }


def test_search_poi_uses_detail_cache_across_calls():
    service, fake = build_service(_search_responses())
    service.search_poi("外滩", "上海")
    calls_after_first = len(fake.calls_for("maps_search_detail"))
    service.search_poi("外滩", "上海")
    assert len(fake.calls_for("maps_search_detail")) == calls_after_first


def test_search_poi_returns_empty_on_mcp_failure():
    service, _ = build_service({})  # 未配置的工具体现为 Connection closed
    assert service.search_poi("外滩", "上海") == []


def test_search_poi_returns_empty_on_tool_error_payload():
    service, _ = build_service(
        {
            "maps_text_search": tool_result(
                "maps_text_search", {"error": "Text Search failed: INVALID_USER_KEY"}
            )
        }
    )
    assert service.search_poi("外滩", "上海") == []


def test_search_poi_drops_pois_without_coordinates():
    responses = {
        "maps_text_search": tool_result(
            "maps_text_search",
            {"pois": [{"id": "X1", "name": "没坐标的点", "address": "?", "typecode": "1"}]},
        ),
        "maps_search_detail": tool_result(
            "maps_search_detail", {"id": "X1", "name": "没坐标的点"}
        ),
    }
    service, _ = build_service(responses)
    assert service.search_poi("没坐标的点", "上海") == []


def test_search_poi_detail_limit_zero_skips_detail_calls():
    service, fake = build_service(_search_responses())
    assert service.search_poi("外滩", "上海", detail_limit=0) == []
    assert fake.calls_for("maps_search_detail") == []


def test_search_poi_ignores_detail_failure_and_keeps_going():
    """第一条详情失败不影响后续条目。"""

    def detail(args):
        if args["id"] == "B001":
            return "异步操作失败: Connection closed"
        return tool_result("maps_search_detail", _DETAILS["B002"])

    service, _ = build_service(
        {
            "maps_text_search": tool_result("maps_text_search", _TEXT_SEARCH_OK),
            "maps_search_detail": detail,
        }
    )
    assert [poi.name for poi in service.search_poi("外滩", "上海")] == ["外滩码头"]


def test_get_weather_parses_flat_casts():
    payload = {
        "city": "上海市",
        "forecasts": [
            {
                "date": "2026-10-15",
                "dayweather": "晴",
                "nightweather": "多云",
                "daytemp": "26",
                "nighttemp": "18",
                "daywind": "东南",
                "daypower": "1-3",
            }
        ],
    }
    service, _ = build_service({"maps_weather": tool_result("maps_weather", payload)})
    infos = service.get_weather("上海")
    assert len(infos) == 1
    assert infos[0].date == "2026-10-15"
    assert infos[0].day_weather == "晴"
    assert infos[0].day_temp == 26
    assert infos[0].night_temp == 18
    assert infos[0].wind_power == "1-3"


def test_get_weather_parses_nested_casts():
    payload = {
        "city": "北京",
        "forecasts": [
            {
                "city": "北京",
                "casts": [
                    {
                        "date": "2026-10-16",
                        "dayweather": "雨",
                        "daytemp": "20°C",
                        "nighttemp": "12",
                    }
                ],
            }
        ],
    }
    service, _ = build_service({"maps_weather": tool_result("maps_weather", payload)})
    infos = service.get_weather("北京")
    assert len(infos) == 1
    assert infos[0].day_temp == 20


def test_get_weather_returns_empty_on_error():
    service, _ = build_service({})
    assert service.get_weather("上海") == []


_WALKING_OK = {
    "route": {
        "origin": "121.49,31.23",
        "destination": "121.50,31.24",
        "paths": [{"distance": "1200", "duration": "900", "steps": []}],
    }
}

_TRANSIT_OK = {
    "route": {
        "origin": "121.49,31.23",
        "destination": "121.50,31.24",
        "distance": "5600",
        "transits": [{"duration": "1800", "walking_distance": "300", "segments": []}],
    }
}


def test_plan_route_walking_prefers_coordinate_tool():
    service, fake = build_service(
        {
            "maps_direction_walking_by_coordinates": tool_result(
                "maps_direction_walking_by_coordinates", _WALKING_OK
            )
        }
    )
    route = service.plan_route("121.49,31.23", "121.50,31.24", route_type="walking")
    assert [name for name, _ in fake.calls] == ["maps_direction_walking_by_coordinates"]
    assert route["distance"] == pytest.approx(1200.0)
    assert route["duration"] == 900
    assert route["route_type"] == "walking"
    assert "15 分钟" in route["description"]


def test_plan_route_address_uses_address_tool():
    service, fake = build_service(
        {
            "maps_direction_walking_by_address": tool_result(
                "maps_direction_walking_by_address", _WALKING_OK
            )
        }
    )
    route = service.plan_route(
        "外滩", "陆家嘴", origin_city="上海", destination_city="上海"
    )
    assert [name for name, _ in fake.calls] == ["maps_direction_walking_by_address"]
    assert route["duration"] == 900


def test_plan_route_transit_uses_route_level_distance():
    service, _ = build_service(
        {
            "maps_direction_transit_integrated_by_coordinates": tool_result(
                "maps_direction_transit_integrated_by_coordinates", _TRANSIT_OK
            )
        }
    )
    route = service.plan_route(
        "121.49,31.23",
        "121.50,31.24",
        origin_city="上海",
        destination_city="上海",
        route_type="transit",
    )
    assert route["distance"] == pytest.approx(5600.0)
    assert route["duration"] == 1800
    assert route["route_type"] == "transit"


def test_plan_route_returns_empty_on_failure():
    service, _ = build_service({})
    assert service.plan_route("121.49,31.23", "121.50,31.24") == {}


def test_plan_route_returns_empty_when_shape_unknown():
    service, _ = build_service(
        {
            "maps_direction_walking_by_coordinates": tool_result(
                "maps_direction_walking_by_coordinates", {"unexpected": True}
            )
        }
    )
    assert service.plan_route("121.49,31.23", "121.50,31.24") == {}


def test_geocode_parses_first_result():
    payload = {
        "return": [
            {
                "city": "上海市",
                "district": "黄浦区",
                "location": "121.4737,31.2304",
                "level": "POI",
            }
        ]
    }
    service, fake = build_service({"maps_geo": tool_result("maps_geo", payload)})
    location = service.geocode("外滩", "上海")
    assert location is not None
    assert location.longitude == pytest.approx(121.4737)
    assert fake.calls_for("maps_geo")[0] == {"address": "外滩", "city": "上海"}


def test_geocode_returns_none_without_results():
    service, _ = build_service({"maps_geo": tool_result("maps_geo", {"return": []})})
    assert service.geocode("不存在的地方") is None


def test_geocode_returns_none_on_failure():
    service, _ = build_service({})
    assert service.geocode("外滩") is None


_DETAIL_PAYLOAD = {
    "id": "B001",
    "name": "外滩",
    "location": "121.490317,31.236305",
    "address": "中山东一路",
    "city": "上海",
    "type": "风景名胜;风景名胜",
}


def test_get_poi_detail_returns_payload():
    service, _ = build_service(
        {"maps_search_detail": tool_result("maps_search_detail", _DETAIL_PAYLOAD)}
    )
    detail = service.get_poi_detail("B001")
    assert detail["name"] == "外滩"
    assert detail["location"] == "121.490317,31.236305"


def test_get_poi_detail_unwraps_pois_list():
    service, _ = build_service(
        {
            "maps_search_detail": tool_result(
                "maps_search_detail", {"pois": [_DETAIL_PAYLOAD]}
            )
        }
    )
    assert service.get_poi_detail("B001")["name"] == "外滩"


def test_get_poi_detail_uses_cache_and_can_bypass():
    service, fake = build_service(
        {"maps_search_detail": tool_result("maps_search_detail", _DETAIL_PAYLOAD)}
    )
    service.get_poi_detail("B001")
    service.get_poi_detail("B001")
    assert len(fake.calls_for("maps_search_detail")) == 1
    service.get_poi_detail("B001", use_cache=False)
    assert len(fake.calls_for("maps_search_detail")) == 2


def test_get_poi_detail_returns_empty_on_failure_and_empty_id():
    service, _ = build_service({})
    assert service.get_poi_detail("B999") == {}
    assert service.get_poi_detail("") == {}


def test_amap_poi_matcher_marks_matched_with_parsed_coordinates():
    """回归测试:修复前 search_poi 恒返回 [],截图识别里所有地点都会是「未匹配」。"""
    from app.services.travelmind.image_import import (
        AmapPoiMatcher,
        RawCandidate,
        VisionPayload,
        match_candidates,
    )

    service, _ = build_service(_search_responses())
    matcher = AmapPoiMatcher(amap_service=service)

    payload = VisionPayload(
        detected_city="上海",
        candidates=[RawCandidate(raw_name="外滩", category="景点", ordering_hint=1)],
        warnings=[],
    )
    results, warnings = match_candidates(payload, matcher, city_hint="上海")

    assert len(results) == 1
    assert results[0].match_status == "matched"
    assert results[0].location is not None
    assert results[0].location.longitude == pytest.approx(121.490317)
    assert not any("未匹配" in warning for warning in warnings)


# ============ 限流(QPS)退避重试 ============

def _rate_limit_result(tool_name: str = "maps_text_search") -> str:
    """高德并发超限时的真实返回形态。"""
    return tool_result(
        tool_name,
        {"error": f"{tool_name} failed: CUQPS_HAS_EXCEEDED_THE_LIMIT"},
    )


def test_call_tool_retries_after_rate_limit(monkeypatch):
    """命中 CUQPS 限流时退避重试,第二次成功,不再丢结果。"""
    monkeypatch.setattr(amap_module, "RATE_LIMIT_BACKOFF_SECONDS", 0.0)
    attempts = {"count": 0}

    def flaky(_args: Dict[str, Any]) -> str:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return _rate_limit_result()
        return tool_result("maps_text_search", _TEXT_SEARCH_OK)

    service, fake = build_service({"maps_text_search": flaky})
    data = service._call_tool("maps_text_search", {"keywords": "外滩"})

    assert attempts["count"] == 2
    assert len(fake.calls) == 2
    assert data["pois"][0]["name"] == "外滩"


def test_call_tool_stops_after_bounded_retries(monkeypatch):
    """限流重试有上限:连续失败时调用次数受控,最终仍然抛出异常。"""
    monkeypatch.setattr(amap_module, "RATE_LIMIT_BACKOFF_SECONDS", 0.0)
    service, fake = build_service(
        {"maps_text_search": lambda _args: _rate_limit_result()}
    )

    with pytest.raises(AmapMcpError):
        service._call_tool("maps_text_search", {"keywords": "外滩"})

    assert len(fake.calls) == amap_module.RATE_LIMIT_RETRIES + 1


def test_call_tool_does_not_retry_other_errors():
    """非限流错误(如密钥非法)不重试,避免无谓放大调用量。"""
    service, fake = build_service(
        {
            "maps_text_search": tool_result(
                "maps_text_search", {"error": "Text Search failed: INVALID_USER_KEY"}
            )
        }
    )

    with pytest.raises(AmapMcpError):
        service._call_tool("maps_text_search", {"keywords": "外滩"})

    assert len(fake.calls) == 1


def test_call_tool_retries_transport_level_rate_limit(monkeypatch):
    """限流信息出现在子进程层异常文本里时同样重试。"""
    monkeypatch.setattr(amap_module, "RATE_LIMIT_BACKOFF_SECONDS", 0.0)
    attempts = {"count": 0}

    def flaky(_args: Dict[str, Any]) -> str:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return "工具执行失败: CUQPS_HAS_EXCEEDED_THE_LIMIT"
        return tool_result("maps_text_search", _TEXT_SEARCH_OK)

    service, _ = build_service({"maps_text_search": flaky})
    data = service._call_tool("maps_text_search", {"keywords": "外滩"})

    assert attempts["count"] == 2
    assert data["pois"][0]["name"] == "外滩"


# ============ MCP 调用超时 & 公交熔断降级 ============
#
# 背景(实测):当前版本的 amap-mcp-server 里,公交/地铁工具
# ``maps_direction_transit_integrated_by_coordinates`` 会返回单引号(Python repr)
# 的非法 JSON,MCP 客户端解析失败后**无限等待**。修复前「行程体检」一旦遇到
# 公共交通行程就会被这条调用拖到前端超时。下面的用例锁定修复行为:
#   1) 单次 MCP 调用有超时,超时即失败(而不是永久挂起);
#   2) 公交接口连续失败达到阈值后熔断,改用驾车耗时近似并要求如实标注 proxied;
#   3) 熔断期间不会再调用公交接口,后续请求立即返回近似值。


def test_call_tool_raises_instead_of_hanging_on_timeout(monkeypatch):
    """MCP 调用卡住时必须按超时失败返回,不能把整个请求挂死。"""
    import time as _time

    settings = get_settings()
    monkeypatch.setattr(settings, "amap_mcp_timeout_seconds", 0.05, raising=False)

    def hang(_args: Dict[str, Any]) -> str:
        _time.sleep(0.5)
        return tool_result("maps_text_search", _TEXT_SEARCH_OK)

    service, fake = build_service({"maps_text_search": hang})

    started = _time.monotonic()
    with pytest.raises(AmapMcpError) as excinfo:
        service._call_tool("maps_text_search", {"keywords": "外滩"})
    elapsed = _time.monotonic() - started

    assert "超时" in str(excinfo.value)
    # 超时不重试:只发起一次调用,且很快返回
    assert len(fake.calls) == 1
    assert elapsed < 0.4


def test_plan_route_transit_failure_falls_back_to_driving(monkeypatch):
    """公交接口返回非法 JSON 时报错 -> 自动改用驾车耗时近似,并标注 proxied。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "amap_transit_failure_threshold", 1, raising=False)

    service, fake = build_service(
        {
            # 复刻真实故障:非法 JSON(Python repr 单引号)
            "maps_direction_transit_integrated_by_coordinates": (
                "工具 'maps_direction_transit_integrated_by_coordinates' 执行结果:\n"
                "{'route': {'transits': [{'duration': '1800'}]}}"
            ),
            "maps_direction_driving_by_coordinates": tool_result(
                "maps_direction_driving_by_coordinates", _WALKING_OK
            ),
        }
    )

    route = service.plan_route(
        "121.49,31.23",
        "121.50,31.24",
        route_type="transit",
        origin_city="上海",
        destination_city="上海",
    )

    assert route["duration"] == 900
    assert route["proxied"] is True
    assert route["route_type"] == "transit"
    assert [name for name, _ in fake.calls] == [
        "maps_direction_transit_integrated_by_coordinates",
        "maps_direction_driving_by_coordinates",
    ]


def test_plan_route_transit_skips_broken_tool_while_breaker_open(monkeypatch):
    """熔断期内不再调用公交接口,直接返回驾车近似值,避免每次体检都白等超时。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "amap_transit_failure_threshold", 1, raising=False)
    monkeypatch.setattr(settings, "amap_transit_cooldown_seconds", 600, raising=False)

    service, fake = build_service(
        {
            "maps_direction_transit_integrated_by_coordinates": (
                "工具 'maps_direction_transit_integrated_by_coordinates' 执行结果:\n"
                "not json at all"
            ),
            "maps_direction_driving_by_coordinates": tool_result(
                "maps_direction_driving_by_coordinates", _WALKING_OK
            ),
        }
    )

    service.plan_route(
        "121.49,31.23", "121.50,31.24", route_type="transit", origin_city="上海"
    )
    route = service.plan_route(
        "121.50,31.24", "121.51,31.25", route_type="transit", origin_city="上海"
    )

    assert route.get("proxied") is True
    transit_calls = [name for name, _ in fake.calls if "transit" in name]
    assert transit_calls == ["maps_direction_transit_integrated_by_coordinates"]


def test_plan_route_transit_returns_empty_when_proxy_disabled(monkeypatch):
    """显式关闭驾车近似时,公交失败就如实返回空(体检会报"未核实")。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "amap_transit_failure_threshold", 1, raising=False)
    monkeypatch.setattr(settings, "amap_transit_fallback_driving", False, raising=False)

    service, fake = build_service({"maps_direction_driving_by_coordinates": tool_result(
        "maps_direction_driving_by_coordinates", _WALKING_OK
    )})

    assert service.plan_route(
        "121.49,31.23", "121.50,31.24", route_type="transit", origin_city="上海"
    ) == {}
    # 尝试过一次公交接口之后如实放弃,不会偷偷用驾车结果冒充公交
    assert [name for name, _ in fake.calls] == [
        "maps_direction_transit_integrated_by_coordinates"
    ]


def test_transit_breaker_opens_at_threshold_and_resets(monkeypatch):
    """熔断器:达到阈值才打开,冷却期结束后自动恢复尝试,可手动重置。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "amap_transit_failure_threshold", 2, raising=False)
    monkeypatch.setattr(settings, "amap_transit_cooldown_seconds", 300, raising=False)

    assert amap_module._transit_available() is True
    amap_module._mark_transit_failure()
    assert amap_module._transit_available() is True  # 未达阈值
    amap_module._mark_transit_failure()
    assert amap_module._transit_available() is False  # 达到阈值 -> 熔断

    amap_module._mark_transit_success()
    assert amap_module._transit_available() is False  # 熔断期内成功也不提前恢复

    amap_module.reset_transit_breaker()
    assert amap_module._transit_available() is True


def test_transit_breaker_recovers_after_cooldown(monkeypatch):
    """冷却期结束后恢复尝试公交接口(而不是永久降级)。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "amap_transit_failure_threshold", 1, raising=False)
    monkeypatch.setattr(settings, "amap_transit_cooldown_seconds", 300, raising=False)

    amap_module._mark_transit_failure()
    assert amap_module._transit_available() is False

    with amap_module._TRANSIT_LOCK:
        amap_module._TRANSIT_DISABLED_UNTIL = amap_module.time.time() - 1
    assert amap_module._transit_available() is True


def test_hung_mcp_call_uses_daemon_thread(monkeypatch):
    """超时被放弃的调用必须跑在守护线程里,否则进程会卡在退出阶段。"""
    import threading as _threading
    import time as _time

    started = _threading.Event()
    seen: Dict[str, Any] = {}

    def slow() -> str:
        seen["daemon"] = _threading.current_thread().daemon
        started.set()
        _time.sleep(0.3)
        return "工具结果:\n{}"

    with pytest.raises(TimeoutError):
        amap_module._run_mcp_with_timeout(slow, 0.05)

    assert started.wait(0.5)
    assert seen["daemon"] is True


def test_mcp_timeout_returns_value_when_call_is_fast():
    """未超时的调用照常把返回值/异常回传给调用方。"""
    assert amap_module._run_mcp_with_timeout(lambda: {"ok": 1}, 1.0) == {"ok": 1}

    def boom() -> None:
        raise ValueError("子进程炸了")

    with pytest.raises(ValueError):
        amap_module._run_mcp_with_timeout(boom, 1.0)


def test_transit_hangs_do_not_block_other_tools(monkeypatch):
    """公交调用卡死超时后不占用 worker 名额,步行/驾车/POI/天气照常可用。"""
    import time as _time

    settings = get_settings()
    monkeypatch.setattr(settings, "amap_mcp_timeout_seconds", 0.05, raising=False)
    service, _ = build_service(
        {
            # 复刻真实故障:调用永不返回
            "maps_direction_transit_integrated_by_coordinates": lambda _a: (
                _time.sleep(2.0) or "工具结果:\n{}"
            ),
            "maps_weather": tool_result("maps_weather", {"city": "上海", "forecasts": []}),
        }
    )

    # 连续多次卡死的公交调用
    for _ in range(12):
        with pytest.raises(AmapMcpError):
            service._call_tool("maps_direction_transit_integrated_by_coordinates", {})

    # 其他工具依然秒回(不会被挂起的调用排队堵住)
    started = _time.monotonic()
    assert service._call_tool("maps_weather", {"city": "上海"}) == {
        "city": "上海",
        "forecasts": [],
    }
    assert _time.monotonic() - started < 0.5


def _attraction(name: str, longitude: float, latitude: float):
    from app.models.schemas import Attraction, Location

    return Attraction(
        name=name,
        address=f"{name}地址",
        location=Location(longitude=longitude, latitude=latitude),
        visit_duration=60,
        description=name,
    )


def test_amap_fact_provider_marks_proxied_transit_as_estimate():
    """"驾车近似"必须如实标注来源与备注,不能伪装成公交实测值。"""
    from app.services.travelmind.facts import AmapFactProvider

    class ProxiedAmap:
        def plan_route(self, *_args, **_kwargs):
            return {
                "distance": 5600.0,
                "duration": 1200,
                "route_type": "transit",
                "proxied": True,
            }

    class PlainAmap:
        def plan_route(self, *_args, **_kwargs):
            return {"distance": 5600.0, "duration": 1200, "route_type": "transit"}

    origin = _attraction("外滩", 121.49, 31.23)
    destination = _attraction("陆家嘴", 121.50, 31.24)

    proxied = AmapFactProvider(amap_service=ProxiedAmap()).travel_time_minutes(
        origin, destination, "transit", "上海"
    )
    assert proxied is not None
    assert proxied.minutes == 20
    assert proxied.source == "amap_proxy"
    assert proxied.note and "近似" in proxied.note

    plain = AmapFactProvider(amap_service=PlainAmap()).travel_time_minutes(
        origin, destination, "transit", "上海"
    )
    assert plain is not None
    assert plain.source == "amap"
    assert plain.note is None
