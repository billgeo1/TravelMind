"""截图识别超时修复的回归测试(并发 / 时间预算 / 缓存 / 图片缩放)。

背景:高德 MCP 每次调用都会重新拉起一个 `uvx amap-mcp-server` 子进程,
本机实测单次 POI 查询约 15s。截图识别按候选地点逐个查询,串行时
10 个地点就需要约 150s,前端 axios(120s)必然超时。
"""

from __future__ import annotations

import threading
import time
from io import BytesIO

import pytest

from app.config import get_settings
from app.models.schemas import Location, POIInfo
from app.services.travelmind import image_import as module
from app.services.travelmind.image_import import (
    AmapPoiMatcher,
    RawCandidate,
    VisionPayload,
    match_candidates,
)


class _SlowMatcher:
    """模拟高德 MCP 的固定耗时查询。"""

    def __init__(self, delay: float = 0.25, per_name=None) -> None:
        self.delay = delay
        self.per_name = per_name or {}
        self.calls: list = []
        self._lock = threading.Lock()

    def search(self, name, city):
        with self._lock:
            self.calls.append(name)
        time.sleep(self.per_name.get(name, self.delay))
        return [
            {
                "poi_id": f"poi_{name}",
                "name": name,
                "address": "某地址",
                "location": {"longitude": 116.4, "latitude": 39.9},
                "city": city or "北京",
            }
        ]


class _FakeAmapService:
    """记录调用参数的高德服务替身。"""

    def __init__(self) -> None:
        self.calls: list = []

    def search_poi(self, keywords, city="", citylimit=True, detail_limit=None):
        self.calls.append(
            {
                "keywords": keywords,
                "city": city,
                "citylimit": citylimit,
                "detail_limit": detail_limit,
            }
        )
        return [
            POIInfo(
                id=f"poi_{keywords}",
                name=keywords,
                type="景点",
                address="某地址",
                location=Location(longitude=116.4, latitude=39.9),
                tel=None,
            )
        ]


def _payload(names):
    return VisionPayload(
        detected_city="北京",
        candidates=[RawCandidate(raw_name=name) for name in names],
        warnings=[],
    )


def test_match_candidates_runs_searches_concurrently():
    names = [f"地点{i}" for i in range(8)]
    matcher = _SlowMatcher(delay=0.3)

    start = time.perf_counter()
    results, _ = match_candidates(_payload(names), matcher, city_hint="北京", concurrency=4)
    elapsed = time.perf_counter() - start

    # 结果必须保持候选原始顺序
    assert [item.raw_name for item in results] == names
    assert all(item.match_status == "matched" for item in results)
    # 串行需要 2.4s;并发 4 路应该明显更快
    assert elapsed < 1.5, f"并发未生效,耗时 {elapsed:.2f}s"


def test_match_candidates_stops_at_budget_and_warns():
    names = ["慢地点1", "慢地点2", "慢地点3"]
    matcher = _SlowMatcher(per_name={name: 5.0 for name in names})

    start = time.perf_counter()
    results, warnings = match_candidates(
        _payload(names), matcher, city_hint="北京", concurrency=1, budget_seconds=1
    )
    elapsed = time.perf_counter() - start

    # 不能等后台的 5s 调用,必须按预算立刻返回
    assert elapsed < 3.0, f"时间预算未生效,耗时 {elapsed:.2f}s"
    assert len(results) == len(names)
    assert all(item.match_status == "not_found" for item in results)
    assert any("时间预算" in warning for warning in warnings)


def test_match_candidates_propagates_matcher_failure():
    class _BoomMatcher:
        def search(self, name, city):
            raise RuntimeError("connection closed")

    from app.services.travelmind.errors import ErrorCode, TravelMindError

    with pytest.raises(TravelMindError) as excinfo:
        match_candidates(_payload(["某地点"]), _BoomMatcher(), city_hint="北京")

    assert excinfo.value.code == ErrorCode.EXTERNAL_PROVIDER_UNAVAILABLE


def test_amap_poi_matcher_passes_configured_detail_limit():
    service = _FakeAmapService()
    matcher = AmapPoiMatcher(amap_service=service, detail_limit=2)
    matcher.search("外滩", "上海")

    assert service.calls[0]["detail_limit"] == 2
    assert service.calls[0]["keywords"] == "外滩"
    assert service.calls[0]["city"] == "上海"


def test_amap_poi_matcher_caches_duplicate_names_in_one_request():
    service = _FakeAmapService()
    matcher = AmapPoiMatcher(amap_service=service)

    matcher.search("外滩", "上海")
    matcher.search("外滩", "上海")
    matcher.search(" 外滩 ", "上海")

    assert len(service.calls) == 1, "同一张截图里的重复地点不应重复查询 MCP"


def test_amap_poi_matcher_default_detail_limit_comes_from_settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "travelmind_import_poi_detail_limit", 3, raising=False)
    service = _FakeAmapService()
    AmapPoiMatcher(amap_service=service).search("外滩", "上海")
    assert service.calls[0]["detail_limit"] == 3


# ============ 图片缩放(减少视觉模型上传体积) ============

def _large_png(width=2400, height=3200):
    Image = pytest.importorskip("PIL.Image")
    buffer = BytesIO()
    Image.new("RGB", (width, height), (200, 120, 60)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_prepare_for_vision_downsizes_large_image():
    pytest.importorskip("PIL.Image")
    data = _large_png()

    scaled, mime = module._prepare_for_vision(data, "image/png", 1600)

    assert mime == "image/jpeg"
    assert len(scaled) < len(data)
    from PIL import Image

    with Image.open(BytesIO(scaled)) as image:
        assert max(image.size) == 1600


def test_prepare_for_vision_keeps_small_image_untouched():
    pytest.importorskip("PIL.Image")
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (320, 240), (10, 10, 10)).save(buffer, format="PNG")
    data = buffer.getvalue()

    scaled, mime = module._prepare_for_vision(data, "image/png", 1600)

    assert scaled is data
    assert mime == "image/png"


def test_prepare_for_vision_disabled_when_dimension_zero():
    data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    scaled, mime = module._prepare_for_vision(data, "image/png", 0)
    assert scaled is data
    assert mime == "image/png"


def test_vision_provider_uses_configured_timeout(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "travelmind_demo_mode", False, raising=False)
    monkeypatch.setattr(settings, "vision_model", "fake-vl", raising=False)
    monkeypatch.setattr(settings, "vision_api_key", "sk-test", raising=False)
    monkeypatch.setattr(settings, "travelmind_vision_timeout_seconds", 123, raising=False)
    monkeypatch.setattr(settings, "travelmind_vision_max_dimension", 1024, raising=False)

    provider = module.get_vision_provider()

    assert isinstance(provider, module.LiveVisionProvider)
    assert provider.timeout_seconds == 123
    assert provider.max_dimension == 1024
