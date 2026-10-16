"""pytest 全局配置与夹具。

让 TravelMind 的测试在**没有任何真实密钥**的机器上也能完整运行:

- 把 ``backend`` 加入 ``sys.path``,保证 ``import app.*`` 可用。
- 注入一个假的 ``AMAP_API_KEY``,绕过应用启动时的 ``validate_config``
  (该值只用于通过配置校验,测试中的所有外部依赖都用 Mock 适配器)。
- 提供构造 ``TripPlan`` / ``Attraction`` 的便捷夹具与图片字节夹具。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import List, Optional

BACKEND_ROOT = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# 必须在导入 app.config 之前设置(env 优先级高于 .env)
os.environ["AMAP_API_KEY"] = "test-amap-key"
for _key in ("TRAVELMIND_DEMO_MODE", "VISION_MODEL", "VISION_API_KEY"):
    os.environ.pop(_key, None)

import pytest  # noqa: E402

from app.models.schemas import (  # noqa: E402
    Attraction,
    Budget,
    DayPlan,
    Location,
    TripPlan,
)
from app.services.travelmind.facts import (  # noqa: E402
    FakeFactProvider,
    OpeningHoursFact,
    TravelTimeFact,
    WeatherFact,
)


# ============ 行程构造工具 ============

def make_attraction(name: str, **kwargs) -> Attraction:
    """构造一个测试用景点,默认坐标固定便于断言。"""
    description = kwargs.pop("description", f"{name}的描述")
    category = kwargs.pop("category", "景点")
    poi_id = kwargs.pop("poi_id", "")
    data = dict(
        name=name,
        address=f"北京市{name}路1号",
        location=Location(longitude=116.4, latitude=39.9),
        visit_duration=120,
        description=description,
        category=category,
        poi_id=poi_id,
    )
    data.update(kwargs)
    return Attraction(**data)


def make_plan(
    days_attractions: List[List[Attraction]],
    *,
    city: str = "北京",
    start_date: str = "2025-06-02",
    end_date: Optional[str] = None,
    transportation: str = "公共交通",
    budget: Optional[Budget] = None,
    revision: int = 0,
) -> TripPlan:
    """按 ``days_attractions``(每天一个景点列表)构造 TripPlan。"""
    base = datetime.strptime(start_date, "%Y-%m-%d")
    days: List[DayPlan] = []
    for index, attractions in enumerate(days_attractions):
        days.append(
            DayPlan(
                date=(base + timedelta(days=index)).strftime("%Y-%m-%d"),
                day_index=index,
                description=f"第{index + 1}天行程",
                transportation=transportation,
                accommodation="经济型酒店",
                attractions=attractions,
                meals=[],
            )
        )
    if end_date is None:
        end_date = days[-1].date if days else start_date
    return TripPlan(
        city=city,
        start_date=start_date,
        end_date=end_date,
        days=days,
        weather_info=[],
        overall_suggestions="测试行程",
        budget=budget,
        revision=revision,
    )


# ============ 图片字节工具 ============

def _pillow_image(width: int, height: int, fmt: str) -> bytes:
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (width, height), (102, 126, 234)).save(buffer, format=fmt)
    return buffer.getvalue()


def _png_bytes(width: int = 8, height: int = 8) -> bytes:
    return _pillow_image(width, height, "PNG")


def _jpeg_bytes(width: int = 8, height: int = 8) -> bytes:
    return _pillow_image(width, height, "JPEG")


def _webp_bytes(width: int = 8, height: int = 8) -> bytes:
    return _pillow_image(width, height, "WEBP")


# ============ 事实夹具 ============

@pytest.fixture
def fake_facts() -> FakeFactProvider:
    """一套"事实齐全"的 FakeFactProvider,便于得到 partial/complete 报告。"""
    return FakeFactProvider(
        opening_hours={
            "故宫": OpeningHoursFact(
                source="test", confirmed=True, open_time="08:30", close_time="17:00"
            ),
            "天安门广场": OpeningHoursFact(
                source="test", confirmed=True, open_time="05:00", close_time="22:00"
            ),
        },
        travel_times={
            ("故宫", "天安门广场"): TravelTimeFact(minutes=20, source="test"),
        },
        weather={
            "2025-06-02": WeatherFact(
                date="2025-06-02", condition="晴", is_bad_outdoor=False, source="test"
            )
        },
    )


@pytest.fixture
def png_bytes():
    """返回 PNG 字节**工厂**(``png_bytes()`` 才得到 bytes)。

    这样测试既能按需指定尺寸,也能复用同一份样本。
    """
    return _png_bytes


@pytest.fixture
def jpeg_bytes():
    return _jpeg_bytes


@pytest.fixture
def webp_bytes():
    return _webp_bytes


@pytest.fixture
def make_plan_factory():
    return make_plan


@pytest.fixture
def make_attraction_factory():
    return make_attraction
