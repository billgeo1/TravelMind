"""FactProvider:可核验事实的适配层。

设计原则(规范第 3.3 节):
- 无法确认的营业时间、天气、交通耗时、预约状态一律返回 `None`,由体检判定为 unknown。
- 绝不为了"看起来完整"而编造事实。
- 提供 `FakeFactProvider` 供单元测试;`DemoFactProvider` 仅在显式 demo 模式下使用,
  并且所有事实都带 `source="mock"`,前端必须标注"演示数据"。
"""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol, Sequence

from ...config import get_settings
from ...models.schemas import Attraction


def _parse_hhmm(value: str) -> Optional[time]:
    match = re.match(r"^(\d{1,2}):(\d{2})$", (value or "").strip())
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return time(hour, minute)
    return None


@dataclass
class OpeningHoursFact:
    """营业时间事实。`confirmed=False` 时不可用于判定闭馆。"""

    source: str
    confirmed: bool = False
    open_time: Optional[str] = None   # "09:00"
    close_time: Optional[str] = None  # "17:00"
    closed_weekdays: List[int] = field(default_factory=list)  # 0=周一
    note: Optional[str] = None

    def is_open_at(self, dt: datetime) -> Optional[bool]:
        """返回 True/False;事实不可靠时返回 None。"""
        if not self.confirmed:
            return None
        if dt.weekday() in self.closed_weekdays:
            return False
        open_t = _parse_hhmm(self.open_time) if self.open_time else None
        close_t = _parse_hhmm(self.close_time) if self.close_time else None
        if open_t is None or close_t is None:
            return None
        current = dt.time()
        if open_t <= close_t:
            return open_t <= current < close_t
        # 跨天营业
        return current >= open_t or current < close_t


@dataclass
class WeatherFact:
    """天气事实(必须带日期与来源)。"""

    date: str
    condition: str
    is_bad_outdoor: bool
    source: str
    confirmed: bool = True


@dataclass
class TravelTimeFact:
    """相邻景点交通耗时(分钟)。"""

    minutes: int
    source: str
    mode: str = "walking"
    # 事实来源备注:例如高德公交/地铁接口不可用时,此处标注"驾车近似"。
    # 体检报告必须如实透出,不能把近似值伪装成公共交通实测值。
    note: Optional[str] = None


class FactProvider(Protocol):
    """事实提供者接口。"""

    def opening_hours(self, attraction: Attraction, city: str) -> Optional[OpeningHoursFact]:
        ...

    def travel_time_minutes(
        self,
        origin: Attraction,
        destination: Attraction,
        mode: str,
        city: str = "",
    ) -> Optional[TravelTimeFact]:
        ...

    def weather(self, city: str, date: str) -> Optional[WeatherFact]:
        ...

    def indoor_alternatives(self, city: str, attraction: Attraction) -> List[dict]:
        ...


class NullFactProvider:
    """什么都不知道的事实提供者:返回全部未知。"""

    def opening_hours(self, attraction: Attraction, city: str) -> Optional[OpeningHoursFact]:
        return None

    def travel_time_minutes(
        self,
        origin: Attraction,
        destination: Attraction,
        mode: str,
        city: str = "",
    ) -> Optional[TravelTimeFact]:
        return None

    def weather(self, city: str, date: str) -> Optional[WeatherFact]:
        return None

    def indoor_alternatives(self, city: str, attraction: Attraction) -> List[dict]:
        return []


class FakeFactProvider:
    """测试专用:可脚本化地返回事实。

    键优先使用 poi_id,其次使用景点名称。
    """

    def __init__(
        self,
        opening_hours: Optional[Dict[str, OpeningHoursFact]] = None,
        travel_times: Optional[Dict[tuple, TravelTimeFact]] = None,
        weather: Optional[Dict[str, WeatherFact]] = None,
        indoor_alternatives: Optional[Dict[str, List[dict]]] = None,
    ) -> None:
        self._opening_hours = opening_hours or {}
        self._travel_times = travel_times or {}
        self._weather = weather or {}
        self._indoor = indoor_alternatives or {}
        self.calls: Dict[str, int] = {
            "opening_hours": 0,
            "travel_time": 0,
            "weather": 0,
            "indoor": 0,
        }

    @staticmethod
    def _key(attraction: Attraction) -> str:
        return (attraction.poi_id or "").strip() or attraction.name

    def opening_hours(self, attraction: Attraction, city: str) -> Optional[OpeningHoursFact]:
        self.calls["opening_hours"] += 1
        key = self._key(attraction)
        return self._opening_hours.get(key) or self._opening_hours.get(attraction.name)

    def travel_time_minutes(
        self,
        origin: Attraction,
        destination: Attraction,
        mode: str,
        city: str = "",
    ) -> Optional[TravelTimeFact]:
        self.calls["travel_time"] += 1
        pair = (self._key(origin), self._key(destination))
        if pair in self._travel_times:
            return self._travel_times[pair]
        reverse = (pair[1], pair[0])
        return self._travel_times.get(reverse)

    def weather(self, city: str, date: str) -> Optional[WeatherFact]:
        self.calls["weather"] += 1
        return self._weather.get(date)

    def indoor_alternatives(self, city: str, attraction: Attraction) -> List[dict]:
        self.calls["indoor"] += 1
        key = self._key(attraction)
        return list(self._indoor.get(key) or self._indoor.get(attraction.name) or [])


# ============ 演示数据(仅在 TRAVELMIND_DEMO_MODE=true 时使用) ============

_DEMO_OPENING_HOURS: Dict[str, OpeningHoursFact] = {
    "故宫博物院": OpeningHoursFact(
        source="mock", confirmed=True, open_time="08:30", close_time="17:00",
        closed_weekdays=[0], note="演示数据:周一闭馆",
    ),
    "故宫": OpeningHoursFact(
        source="mock", confirmed=True, open_time="08:30", close_time="17:00",
        closed_weekdays=[0], note="演示数据:周一闭馆",
    ),
    "中国国家博物馆": OpeningHoursFact(
        source="mock", confirmed=True, open_time="09:00", close_time="17:00",
        closed_weekdays=[0], note="演示数据:周一闭馆",
    ),
    "颐和园": OpeningHoursFact(
        source="mock", confirmed=True, open_time="06:30", close_time="18:00",
        note="演示数据",
    ),
    "天安门广场": OpeningHoursFact(
        source="mock", confirmed=True, open_time="05:00", close_time="22:00",
        note="演示数据",
    ),
    "上海博物馆": OpeningHoursFact(
        source="mock", confirmed=True, open_time="09:00", close_time="17:00",
        closed_weekdays=[0], note="演示数据:周一闭馆",
    ),
}

_DEMO_INDOOR_ALTERNATIVES: Dict[str, List[dict]] = {
    "颐和园": [
        {
            "name": "中国国家博物馆",
            "address": "北京市东城区东长安街16号",
            "location": {"longitude": 116.3958, "latitude": 39.9055},
            "poi_id": "demo_mock_national_museum",
            "category": "博物馆",
            "source": "mock",
        }
    ],
    "天安门广场": [
        {
            "name": "中国国家博物馆",
            "address": "北京市东城区东长安街16号",
            "location": {"longitude": 116.3958, "latitude": 39.9055},
            "poi_id": "demo_mock_national_museum",
            "category": "博物馆",
            "source": "mock",
        }
    ],
}


class DemoFactProvider(FakeFactProvider):
    """显式演示模式:返回带 mock 标识的固定事实。"""

    def __init__(self) -> None:
        super().__init__(
            opening_hours=dict(_DEMO_OPENING_HOURS),
            indoor_alternatives=dict(_DEMO_INDOOR_ALTERNATIVES),
        )


class AmapFactProvider:
    """基于现有高德服务的事实适配器(尽力而为)。

    现有 `AmapService` 尚未完整实现解析,因此大多数调用会返回 `None`,
    体检会如实给出 partial 报告而不是编造结论。
    """

    def __init__(self, amap_service=None) -> None:
        if amap_service is None:
            from ..amap_service import get_amap_service

            amap_service = get_amap_service()
        self.amap = amap_service

    def opening_hours(self, attraction: Attraction, city: str) -> Optional[OpeningHoursFact]:
        poi_id = (attraction.poi_id or "").strip()
        if not poi_id:
            return None
        try:
            detail = self.amap.get_poi_detail(poi_id)
        except Exception:
            return None
        if not isinstance(detail, dict):
            return None
        open_time = detail.get("open_time") or detail.get("opentime")
        if not open_time or "未知" in str(open_time):
            return None
        parts = re.findall(r"\d{1,2}:\d{2}", str(open_time))
        if len(parts) < 2:
            return None
        return OpeningHoursFact(
            source="amap", confirmed=True, open_time=parts[0], close_time=parts[1]
        )

    def travel_time_minutes(
        self,
        origin: Attraction,
        destination: Attraction,
        mode: str,
        city: str = "",
    ) -> Optional[TravelTimeFact]:
        if not (origin.location and destination.location):
            return None
        try:
            route = self.amap.plan_route(
                f"{origin.location.longitude},{origin.location.latitude}",
                f"{destination.location.longitude},{destination.location.latitude}",
                route_type=mode,
                # 公交/地铁路线按坐标规划时必须带城市,否则高德会返回空结果,
                # 体检就只能报"交通耗时未核实"。
                origin_city=city or None,
                destination_city=city or None,
            )
        except Exception:
            return None
        if not isinstance(route, dict):
            return None
        duration = route.get("duration")
        if not duration:
            return None
        try:
            minutes = int(round(float(duration) / 60))
        except (TypeError, ValueError):
            return None
        # 高德公交/地铁接口在多轮实测中会返回非法 JSON 并让客户端无限等待。
        # amap_service 会在熔断后改用驾车耗时做近似估算,并给结果打上
        # ``proxied=True``;这里必须把"近似"如实标注出来,不能当成公交实测值。
        note: Optional[str] = None
        source = "amap"
        if route.get("proxied"):
            source = "amap_proxy"
            note = "公交/地铁接口不可用,此处为驾车耗时近似值"
        return TravelTimeFact(minutes=minutes, source=source, mode=mode, note=note)

    def weather(self, city: str, date: str) -> Optional[WeatherFact]:
        try:
            infos = self.amap.get_weather(city)
        except Exception:
            return None
        if not infos:
            return None
        for info in infos:
            if getattr(info, "date", None) == date:
                condition = f"{info.day_weather}{info.night_weather}"
                return WeatherFact(
                    date=date,
                    condition=condition,
                    is_bad_outdoor=_condition_is_bad(condition),
                    source="amap",
                    confirmed=True,
                )
        return None

    def indoor_alternatives(self, city: str, attraction: Attraction) -> List[dict]:
        try:
            pois = self.amap.search_poi("博物馆 室内展览", city)
        except Exception:
            return []
        results: List[dict] = []
        for poi in pois or []:
            location = getattr(poi, "location", None)
            results.append(
                {
                    "name": getattr(poi, "name", ""),
                    "address": getattr(poi, "address", ""),
                    "location": (
                        {"longitude": location.longitude, "latitude": location.latitude}
                        if location
                        else None
                    ),
                    "poi_id": getattr(poi, "id", None),
                    "category": getattr(poi, "type", "博物馆"),
                    "source": "amap",
                }
            )
        return results


# ============ 工具函数 ============

class CachingFactProvider:
    """请求内事实缓存 + 并发预热(包装任意 FactProvider)。

    规则引擎会对同一事实重复提问:一对相邻景点会在「派生时间线」「赶路时间
    检查」「行程强度检查」里各问一次交通耗时,每个景点会被问两次营业时间,
    每个「天」都会被问一次天气。真实高德 MCP 的每次调用都会重建子进程
    (冷启动 13-15 秒),不缓存时一次 3 天 9 景点体检就会产生 40+ 次往返,
    远超前端请求超时。

    设计约束:
    - 只缓存**单次请求**内的结果(`get_fact_provider()` 每次调用返回新实例),
      因此不会跨请求返回陈旧数据。
    - 「查询过但拿不到」(`None`)同样缓存:未知结果同样昂贵。
    - 交通耗时保留方向性(origin→destination 不归一化),因为高峰期双向路况
      可能不同。
    - 线程安全:体检在线程池中执行。

    `warm()` 会把「本次行程需要的事实」并发预热到缓存里:高德 MCP 调用是
    纯阻塞网络 I/O,4 路并发即可把 18 次往返从 ~70 秒压到 ~20 秒。超过预算
    时进入**降级模式**:后续未命中的查询直接返回"未知",让体检以 partial
    报告收尾,而不是把请求挂到超时。
    """

    def __init__(self, inner: FactProvider) -> None:
        self._inner = inner
        self._lock = threading.Lock()
        self._opening_hours: Dict[tuple, Optional[OpeningHoursFact]] = {}
        self._travel: Dict[tuple, Optional[TravelTimeFact]] = {}
        self._weather: Dict[tuple, Optional[WeatherFact]] = {}
        self._indoor: Dict[tuple, List[dict]] = {}
        self.degraded = False
        self._warmed = False
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _attraction_key(attraction: Attraction) -> str:
        return (attraction.poi_id or "").strip() or attraction.name

    def _cached(
        self,
        cache: Dict[tuple, Any],
        key: tuple,
        factory: Callable[[], Any],
        fallback: Any = None,
    ) -> Any:
        with self._lock:
            if key in cache:
                self.hits += 1
                return cache[key]
            if self.degraded:
                # 预热预算已耗尽:不再发起新的阻塞查询,如实返回"未知"。
                self.hits += 1
                return fallback
        value = factory()
        with self._lock:
            cache[key] = value
            self.misses += 1
        return value

    def opening_hours(self, attraction: Attraction, city: str) -> Optional[OpeningHoursFact]:
        key = ("opening", self._attraction_key(attraction), city or "")
        return self._cached(
            self._opening_hours, key, lambda: self._inner.opening_hours(attraction, city)
        )

    def travel_time_minutes(
        self,
        origin: Attraction,
        destination: Attraction,
        mode: str,
        city: str = "",
    ) -> Optional[TravelTimeFact]:
        key = (
            "travel",
            self._attraction_key(origin),
            self._attraction_key(destination),
            mode or "",
            city or "",
        )
        return self._cached(
            self._travel,
            key,
            lambda: self._inner.travel_time_minutes(origin, destination, mode, city),
        )

    def weather(self, city: str, date: str) -> Optional[WeatherFact]:
        key = ("weather", city or "", date or "")
        return self._cached(self._weather, key, lambda: self._inner.weather(city, date))

    def indoor_alternatives(self, city: str, attraction: Attraction) -> List[dict]:
        key = ("indoor", city or "", self._attraction_key(attraction))
        return list(
            self._cached(
                self._indoor, key, lambda: self._inner.indoor_alternatives(city, attraction)
            )
            or []
        )

    def warm(
        self,
        jobs: Sequence[Callable[[], Any]],
        concurrency: int = 4,
        budget_seconds: float = 150.0,
    ) -> None:
        """并发预热事实缓存。

        Args:
            jobs: 需要预热的查询(调用 self.<method> 的零参可调用对象)。
            concurrency: 并发度(高德限流,默认 4)。
            budget_seconds: 总时间预算;超出后进入降级模式。
        """
        if self._warmed or not jobs:
            return
        self._warmed = True

        workers = max(1, min(int(concurrency or 1), len(jobs)))
        budget = max(float(budget_seconds or 0.0), 0.0)
        pool = ThreadPoolExecutor(max_workers=workers)
        try:
            futures = [pool.submit(self._safe_call, job) for job in jobs]
            done, pending = wait(futures, timeout=budget)
            if pending:
                self.degraded = True
        finally:
            # 不等待仍在跑的查询:它们只是填充缓存,晚到也无害。
            pool.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _safe_call(job: Callable[[], Any]) -> Any:
        try:
            return job()
        except Exception:
            return None


_BAD_OUTDOOR_KEYWORDS = ("雨", "雪", "暴雨", "大雨", "雷", "台风", "沙尘", "冰雹")
_OUTDOOR_KEYWORDS = (
    "公园", "山", "湖", "户外", "自然", "风景", "景区", "广场", "海滩", "长城",
    "园林", "花园", "湿地", "峡谷", "溶洞", "岛", "江", "河", "塔",
)
_INDOOR_KEYWORDS = (
    "博物馆", "美术馆", "展览", "购物", "商场", "室内", "剧院", "图书馆",
    "水族馆", "科技馆", "纪念馆", "寺", "庙", "宫殿", "故居", "文创",
)


def _condition_is_bad(condition: str) -> bool:
    text = condition or ""
    return any(word in text for word in _BAD_OUTDOOR_KEYWORDS)


def attraction_is_outdoor(attraction: Attraction) -> bool:
    """基于类别/描述粗略判断是否室外活动(仅用于提示,不作为硬结论)。"""
    text = f"{attraction.category or ''}{attraction.description or ''}{attraction.name}"
    if any(word in text for word in _INDOOR_KEYWORDS):
        return False
    return any(word in text for word in _OUTDOOR_KEYWORDS)


def get_fact_provider() -> FactProvider:
    """按配置选择事实提供者。

    - `TRAVELMIND_DEMO_MODE=true` -> DemoFactProvider(带 mock 标识的固定事实)
    - 配置了高德 Key -> AmapFactProvider
    - 否则 -> NullFactProvider(全部未知,报告为 partial)

    返回值统一套一层 `CachingFactProvider`:规则引擎会对同一事实重复提问,
    没有请求内缓存时一次体检会产生数十次高德 MCP 往返并直接触发前端超时。
    """
    settings = get_settings()
    if getattr(settings, "travelmind_demo_mode", False):
        return CachingFactProvider(DemoFactProvider())
    if getattr(settings, "amap_api_key", ""):
        try:
            return CachingFactProvider(AmapFactProvider())
        except Exception:
            return CachingFactProvider(NullFactProvider())
    return CachingFactProvider(NullFactProvider())
