"""高德地图MCP服务封装(带真实结果解析)

本模块负责把高德 MCP 工具返回的字符串结果解析为项目内部的数据模型。

启动命令说明:
    amap-mcp-server(0.1.x)依赖 mcp==1.8.1,而 mcp 1.8.1 会
    `from pydantic._internal._typing_extra import eval_type_backport`;
    该符号在 pydantic>=2.14 已被移除,会导致 MCP 子进程启动即 ImportError,
    外部表现为「工具数量: 0」以及「异步操作失败: Connection closed」。
    因此默认命令显式锁定 `pydantic<2.14`,也可用环境变量 AMAP_MCP_COMMAND 覆盖。
"""

import json
import re
import shlex
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from hello_agents.tools import MCPTool

from ..config import get_settings
from ..models.schemas import Location, POIInfo, WeatherInfo

# 默认启动命令(可用环境变量 AMAP_MCP_COMMAND 覆盖)
DEFAULT_MCP_COMMAND = 'uvx --with "pydantic<2.14" amap-mcp-server'

# 文本搜索接口不返回经纬度,需要二次查询详情的默认条目数
DEFAULT_POI_DETAIL_LIMIT = 5

# 高德接口限流(QPS 超限)错误标记。
# 截图识别等场景会并发调用高德,偶发命中每秒调用限额,表现为
# ``CUQPS_HAS_EXCEEDED_THE_LIMIT``。这类错误是瞬时的,短暂退避后重试即可,
# 否则该条 POI 会因为拿不到坐标而被静默丢弃。
RATE_LIMIT_MARKERS = (
    "cuqps_has_exceeded_the_limit",
    "over_query_limit",
    "exceeded_the_limit",
    "访问过于频繁",
)
# 限流重试次数与基础退避(秒),实际等待为 退避 * 2^第几次
RATE_LIMIT_RETRIES = 2
RATE_LIMIT_BACKOFF_SECONDS = 0.8

# 全局MCP工具实例
_amap_mcp_tool = None

# MCPTool.run() 没有超时参数,而高德的部分工具(尤其是公交/地铁)在异常响应下
# 会让客户端无限等待,直接把整个请求拖死。因此每次 MCP 调用都放在一个**守护
# 线程**里执行,由调用方设置等待上限;超时后放弃这次等待(守护线程留在后台,
# 请求照常返回"未核实"而不是挂死)。
#
# 为什么用守护线程而不是 ThreadPoolExecutor:
#   `concurrent.futures.thread` 注册了 atexit 钩子 `_python_exit()`,退出时会
#   join 所有 worker 线程。被放弃的公交调用是"永久挂起"的,一旦用线程池,
#   进程就会卡在退出阶段(脚本跑完不返回、`run.py` 按 Ctrl+C 关不掉)。
#   守护线程不参与 atexit join,同时也不占用任何 worker 名额,因此卡死的调用
#   既不会阻塞进程退出,也不会挤掉其他工具(步行/驾车/POI/天气)的调用能力。

# 公交/地铁接口熔断状态。
# 实测 amap-mcp-server 的 `maps_direction_transit_integrated_by_coordinates`
# 与 `..._by_address` 会返回单引号(Python repr)的非法 JSON,客户端解析失败后
# 一直等待,且服务端子进程会因写入失败而崩溃。因此连续失败若干次后直接判定
# 该接口不可用,在冷却期内改用驾车耗时做近似估算,避免每次体检都白等超时。
_TRANSIT_FAILURE_COUNT = 0
_TRANSIT_DISABLED_UNTIL = 0.0
_TRANSIT_LOCK = threading.Lock()


def _mcp_call_timeout_seconds() -> float:
    """读取单次 MCP 调用超时(秒),异常配置回退到 20s。"""
    try:
        value = float(getattr(get_settings(), "amap_mcp_timeout_seconds", 20.0) or 20.0)
    except (TypeError, ValueError):
        value = 20.0
    return value if value > 0 else 20.0


def _transit_available() -> bool:
    """公交/地铁接口当前是否可用(熔断冷却期结束后自动恢复尝试)。"""
    with _TRANSIT_LOCK:
        return time.time() >= _TRANSIT_DISABLED_UNTIL


def _mark_transit_failure() -> None:
    """记录一次公交/地铁调用失败,达到阈值后进入冷却期。"""
    global _TRANSIT_FAILURE_COUNT, _TRANSIT_DISABLED_UNTIL
    try:
        threshold = int(getattr(get_settings(), "amap_transit_failure_threshold", 2) or 2)
        cooldown = int(getattr(get_settings(), "amap_transit_cooldown_seconds", 900) or 900)
    except (TypeError, ValueError):
        threshold, cooldown = 2, 900
    with _TRANSIT_LOCK:
        _TRANSIT_FAILURE_COUNT += 1
        if _TRANSIT_FAILURE_COUNT >= max(threshold, 1):
            _TRANSIT_DISABLED_UNTIL = time.time() + max(cooldown, 1)
            _TRANSIT_FAILURE_COUNT = 0


def _mark_transit_success() -> None:
    """公交/地铁调用成功:清除失败计数。"""
    global _TRANSIT_FAILURE_COUNT
    with _TRANSIT_LOCK:
        _TRANSIT_FAILURE_COUNT = 0


def _transit_proxy_enabled() -> bool:
    """公交/地铁不可用时是否允许用驾车耗时做近似估算(默认允许)。"""
    try:
        return bool(getattr(get_settings(), "amap_transit_fallback_driving", True))
    except Exception:
        return True


def reset_transit_breaker() -> None:
    """重置公交熔断状态(供测试与排查使用)。"""
    global _TRANSIT_FAILURE_COUNT, _TRANSIT_DISABLED_UNTIL
    with _TRANSIT_LOCK:
        _TRANSIT_FAILURE_COUNT = 0
        _TRANSIT_DISABLED_UNTIL = 0.0


def _run_mcp_with_timeout(fn, timeout: float):
    """在守护线程中执行一次 MCP 调用,超时抛 ``TimeoutError``。

    超时后不等待后台线程结束:被放弃的调用最多泄漏一个守护线程(与一个子进程),
    由熔断机制保证不会反复发生。
    """
    done = threading.Event()
    box: Dict[str, Any] = {}

    def _target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # 原样回传给调用方
            box["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(
        target=_target, name="amap-mcp-call", daemon=True
    )
    thread.start()
    if not done.wait(timeout):
        raise TimeoutError(f"MCP 调用超过 {timeout:.0f}s 未返回")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _is_rate_limited(message: Any) -> bool:
    """判断错误信息是否为高德限流错误。"""
    text = str(message or "").lower()
    return any(marker in text for marker in RATE_LIMIT_MARKERS)

# POI 详情缓存(进程内,减少重复的 MCP 往返)
_poi_detail_cache: Dict[str, Dict[str, Any]] = {}
_POI_DETAIL_CACHE_MAX = 500

# 路线规划缓存(进程内)。MCPTool.run() 每次调用都会重建 amap-mcp-server 子进程
# (冷启动 13-15s),而行程体检/修复/重规划会对同一对相邻景点反复查询路线,
# 没有缓存时单个 3 天行程会产生数十次 MCP 往返并直接撞上前端请求超时。
_route_cache: Dict[Tuple[str, str, str, str, str], Dict[str, Any]] = {}
_ROUTE_CACHE_MAX = 500

# 天气缓存(进程内)。体检对每个"天"都查询天气,同一城市结果相同。
_weather_cache: Dict[str, List["WeatherInfo"]] = {}
_WEATHER_CACHE_MAX = 100


class AmapMcpError(RuntimeError):
    """高德 MCP 调用失败(连接中断、工具报错、返回非 JSON 等)"""


def _resolve_mcp_command(raw: Optional[str] = None) -> List[str]:
    """把配置字符串解析为 MCPTool 需要的 server_command 列表。

    缺失、空白或无法解析时回退到默认命令。
    """
    if raw is None:
        try:
            raw = get_settings().amap_mcp_command
        except Exception:
            raw = ""
    candidate = (raw or "").strip()
    if not candidate:
        return shlex.split(DEFAULT_MCP_COMMAND)
    try:
        parts = shlex.split(candidate)
    except ValueError:
        parts = []
    return parts or shlex.split(DEFAULT_MCP_COMMAND)


_RESULT_PREFIX_RE = re.compile(r"^\s*工具\s*'[^']*'\s*执行结果\s*[:：]\s*")
_FAILURE_HINTS = (
    "异步操作失败",
    "操作失败",
    "连接已关闭",
    "connection closed",
    "执行失败",
    "未找到工具",
)


def _decode_first_json(text: str) -> Optional[Any]:
    """从文本中提取第一个完整的 JSON 对象/数组,失败返回 None。"""
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except ValueError:
            continue
        if isinstance(value, (dict, list)):
            return value
    return None


def parse_mcp_result(raw: Any) -> Any:
    """把 MCPTool.run 的返回值规范化为 dict/list。

    MCPTool.run 成功时返回形如 ``工具 'maps_text_search' 执行结果:\\n{...}`` 的字符串,
    失败时返回 ``异步操作失败: Connection closed`` 之类的文本。
    解析不出 JSON 时抛出 :class:`AmapMcpError`,避免调用方把失败当成空结果。
    """
    if isinstance(raw, (dict, list)):
        return raw
    if raw is None:
        raise AmapMcpError("高德 MCP 未返回任何内容。")
    text = str(raw).strip()
    if not text:
        raise AmapMcpError("高德 MCP 返回空内容。")

    payload = _RESULT_PREFIX_RE.sub("", text, count=1).strip()
    data = _decode_first_json(payload)
    if data is not None:
        return data

    lowered = text.lower()
    for hint in _FAILURE_HINTS:
        if hint.lower() in lowered:
            raise AmapMcpError(f"高德 MCP 调用失败:{text[:300]}")
    raise AmapMcpError(f"无法解析高德 MCP 返回内容:{text[:200]}")


def _first_value(source: Dict[str, Any], *keys: str) -> Any:
    """按顺序返回第一个非空字段值。"""
    if not isinstance(source, dict):
        return None
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return value
    return None


def _validated_location(longitude: Any, latitude: Any) -> Optional[Location]:
    """把经纬度转换为 Location,并做范围校验。"""
    try:
        lng = float(longitude)
        lat = float(latitude)
    except (TypeError, ValueError):
        return None
    if not (-180.0 <= lng <= 180.0 and -90.0 <= lat <= 90.0):
        return None
    if lng == 0.0 and lat == 0.0:
        return None
    return Location(longitude=lng, latitude=lat)


def parse_location(value: Any) -> Optional[Location]:
    """兼容高德返回的多种坐标形式,统一解析为 Location。

    支持 ``"经度,纬度"`` 字符串、``[lng, lat]`` 序列、
    ``{"longitude": .., "latitude": ..}`` / ``{"lng": .., "lat": ..}``,
    以及带 ``location`` 嵌套的字典。
    """
    if value is None:
        return None
    if isinstance(value, Location):
        return value
    if isinstance(value, (list, tuple)):
        if len(value) >= 2:
            return _validated_location(value[0], value[1])
        return None
    if isinstance(value, str):
        parts = [part for part in re.split(r"[,，\s]+", value.strip()) if part]
        if len(parts) >= 2:
            return _validated_location(parts[0], parts[1])
        return None
    if isinstance(value, dict):
        nested = _first_value(value, "location", "lnglat", "ll")
        if nested is not None:
            parsed = parse_location(nested)
            if parsed is not None:
                return parsed
        return _validated_location(
            _first_value(value, "longitude", "lng", "lon"),
            _first_value(value, "latitude", "lat"),
        )
    return None


_COORD_PAIR_RE = re.compile(r"^\s*-?\d+(?:\.\d+)?\s*[,，]\s*-?\d+(?:\.\d+)?\s*$")


def _looks_like_coordinates(value: Optional[str]) -> bool:
    """判断字符串是否为 ``经纬度`` 形式(用于选择按坐标规划路线的工具)。"""
    return bool(value) and bool(_COORD_PAIR_RE.match(str(value)))


def get_amap_mcp_tool() -> MCPTool:
    """
    获取高德地图MCP工具实例(单例模式)
    
    Returns:
        MCPTool实例
    """
    global _amap_mcp_tool
    
    if _amap_mcp_tool is None:
        settings = get_settings()

        if not settings.amap_api_key:
            raise ValueError("高德地图API Key未配置,请在.env文件中设置AMAP_API_KEY")

        command = _resolve_mcp_command(settings.amap_mcp_command)

        # 创建MCP工具
        _amap_mcp_tool = MCPTool(
            name="amap",
            description="高德地图服务,支持POI搜索、路线规划、天气查询等功能",
            server_command=command,
            env={"AMAP_MAPS_API_KEY": settings.amap_api_key},
            auto_expand=True  # 自动展开为独立工具
        )

        tool_count = len(getattr(_amap_mcp_tool, "_available_tools", None) or [])

        if tool_count == 0:
            print("⚠️  高德地图MCP工具启动失败(可用工具数量为 0),POI/路线/天气查询将不可用")
            print(f"   启动命令: {' '.join(command)}")
            print("   排查建议:")
            print("     1) 确认已安装 uv/uvx(命令行执行 uvx --version);")
            print("     2) 确认 AMAP_API_KEY 为「Web服务」类型且已开通配额;")
            print("     3) amap-mcp-server 依赖 pydantic<2.14,可用 AMAP_MCP_COMMAND 覆盖启动命令。")
        else:
            print(f"✅ 高德地图MCP工具初始化成功")
            print(f"   启动命令: {' '.join(command)}")
            print(f"   工具数量: {tool_count}")

            # 打印可用工具列表
            if _amap_mcp_tool._available_tools:
                print("   可用工具:")
                for tool in _amap_mcp_tool._available_tools[:5]:  # 只打印前5个
                    print(f"     - {tool.get('name', 'unknown')}")
                if len(_amap_mcp_tool._available_tools) > 5:
                    print(f"     ... 还有 {len(_amap_mcp_tool._available_tools) - 5} 个工具")
    
    return _amap_mcp_tool


class AmapService:
    """高德地图服务封装类"""
    
    def __init__(self):
        """初始化服务"""
        self.mcp_tool = get_amap_mcp_tool()

    def _call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """
        调用高德 MCP 工具并把字符串结果解析为 JSON 结构

        Args:
            tool_name: MCP 工具名,例如 maps_text_search
            arguments: 工具参数

        Returns:
            解析后的 dict/list

        说明:
            命中高德每秒调用限额(``CUQPS_HAS_EXCEEDED_THE_LIMIT``)时会短暂
            退避重试 ``RATE_LIMIT_RETRIES`` 次。并发调用高德时这类错误是瞬时的,
            重试即可拿到结果;重试仍失败才抛出。

            每次 MCP 调用都受 ``amap_mcp_timeout_seconds`` 约束:高德部分工具
            返回异常响应时客户端会无限等待,超时后按失败处理,避免拖死整个请求。

        Raises:
            AmapMcpError: 连接断开、工具报错、返回内容无法解析或调用超时
        """
        payload = {
            key: value
            for key, value in dict(arguments or {}).items()
            if value is not None
        }
        attempts = RATE_LIMIT_RETRIES + 1
        timeout = _mcp_call_timeout_seconds()
        for attempt in range(attempts):
            try:
                raw = _run_mcp_with_timeout(
                    lambda: self.mcp_tool.run(
                        {
                            "action": "call_tool",
                            "tool_name": tool_name,
                            "arguments": payload,
                        }
                    ),
                    timeout,
                )
                data = parse_mcp_result(raw)
                if isinstance(data, dict) and data.get("error"):
                    raise AmapMcpError(
                        f"{tool_name} 执行失败:{str(data['error'])[:300]}"
                    )
                return data
            except TimeoutError as exc:
                # 超时通常意味着该工具在当前 MCP 版本下已不可用(如公交/地铁
                # 返回非法 JSON 后客户端一直等待),重试没有意义。
                raise AmapMcpError(f"{tool_name} 执行超时:{exc}") from None
            except Exception as exc:
                if attempt + 1 >= attempts or not _is_rate_limited(exc):
                    raise
                time.sleep(RATE_LIMIT_BACKOFF_SECONDS * (2 ** attempt))
        raise AmapMcpError(f"{tool_name} 执行失败:限流重试后仍失败")

    def search_poi(
        self,
        keywords: str,
        city: str = "",
        citylimit: bool = True,
        detail_limit: Optional[int] = None,
    ) -> List[POIInfo]:
        """
        搜索POI

        Args:
            keywords: 搜索关键词
            city: 城市
            citylimit: 是否限制在城市范围内
            detail_limit: 需要二次查询详情补齐坐标的条目数(None 时读取配置)

        Returns:
            POI信息列表(均带经纬度;无坐标的条目会被丢弃)

        说明:
            高德 MCP 的 maps_text_search 只返回 id/name/address/typecode,不含经纬度,
            因此这里对前 detail_limit 条调用 maps_search_detail 补齐坐标。
        """
        if detail_limit is None:
            detail_limit = getattr(
                get_settings(), "travelmind_poi_detail_limit", DEFAULT_POI_DETAIL_LIMIT
            )
        try:
            limit = max(0, int(detail_limit))
        except (TypeError, ValueError):
            limit = DEFAULT_POI_DETAIL_LIMIT

        try:
            data = self._call_tool(
                "maps_text_search",
                {
                    "keywords": keywords,
                    "city": city,
                    "citylimit": str(bool(citylimit)).lower(),
                },
            )
        except AmapMcpError as exc:
            print(f"❌ POI搜索失败: {exc}")
            return []
        except Exception as exc:  # MCP 子进程/网络层异常
            print(f"❌ POI搜索失败: {type(exc).__name__}: {exc}")
            return []

        items = data.get("pois") if isinstance(data, dict) else data
        if not isinstance(items, list):
            return []

        results: List[POIInfo] = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue

            poi_id = str(item.get("id") or "").strip()
            address = str(item.get("address") or "")
            tel = item.get("tel")
            location = parse_location(_first_value(item, "location", "lnglat"))

            if location is None and poi_id and index < limit:
                detail = self.get_poi_detail(poi_id)
                if detail:
                    location = parse_location(_first_value(detail, "location", "lnglat"))
                    address = str(_first_value(detail, "address") or address)
                    tel = _first_value(detail, "tel", "telephone") or tel

            if location is None:
                # 缺少坐标就无法用于落点/导航,按 POIInfo 契约丢弃
                continue

            results.append(
                POIInfo(
                    id=poi_id or f"{name}@{len(results)}",
                    name=name,
                    type=str(_first_value(item, "typecode", "type") or "未知"),
                    address=address,
                    location=location,
                    tel=str(tel) if tel else None,
                )
            )

        if not results and items:
            print("⚠️  POI 文本搜索有结果但均未能补齐坐标(详情查询失败?),返回空列表")
        return results
    
    def get_weather(self, city: str) -> List[WeatherInfo]:
        """
        查询天气

        Args:
            city: 城市名称

        Returns:
            天气信息列表
        """
        cache_key = str(city or "").strip()
        if cache_key and cache_key in _weather_cache:
            return list(_weather_cache[cache_key])
        try:
            data = self._call_tool("maps_weather", {"city": city})
        except AmapMcpError as exc:
            print(f"❌ 天气查询失败: {exc}")
            return []
        except Exception as exc:
            print(f"❌ 天气查询失败: {type(exc).__name__}: {exc}")
            return []

        if not isinstance(data, dict):
            return []

        casts: List[Any] = []
        forecasts = data.get("forecasts")
        if isinstance(forecasts, list):
            for entry in forecasts:
                if isinstance(entry, dict) and isinstance(entry.get("casts"), list):
                    casts.extend(entry["casts"])
                elif isinstance(entry, dict):
                    casts.append(entry)

        infos: List[WeatherInfo] = []
        for cast in casts:
            if not isinstance(cast, dict):
                continue
            try:
                infos.append(
                    WeatherInfo(
                        date=str(_first_value(cast, "date") or ""),
                        day_weather=str(
                            _first_value(cast, "dayweather", "day_weather") or ""
                        ),
                        night_weather=str(
                            _first_value(cast, "nightweather", "night_weather") or ""
                        ),
                        day_temp=_first_value(cast, "daytemp", "day_temp") or 0,
                        night_temp=_first_value(cast, "nighttemp", "night_temp") or 0,
                        wind_direction=str(
                            _first_value(cast, "daywind", "day_wind") or ""
                        ),
                        wind_power=str(
                            _first_value(cast, "daypower", "day_power") or ""
                        ),
                    )
                )
            except Exception:
                continue
        if cache_key and infos:
            if len(_weather_cache) >= _WEATHER_CACHE_MAX:
                _weather_cache.clear()
            _weather_cache[cache_key] = list(infos)
        return infos
    
    def plan_route(
        self,
        origin_address: str,
        destination_address: str,
        origin_city: Optional[str] = None,
        destination_city: Optional[str] = None,
        route_type: str = "walking"
    ) -> Dict[str, Any]:
        """
        规划路线

        Args:
            origin_address: 起点地址(也可以是 "经度,纬度" 坐标)
            destination_address: 终点地址(也可以是 "经度,纬度" 坐标)
            origin_city: 起点城市
            destination_city: 终点城市
            route_type: 路线类型 (walking/driving/transit/bicycling)

        Returns:
            路线信息 {distance, duration, route_type, description};失败返回 {}
        """
        normalized_type = (route_type or "walking").strip().lower()
        by_coordinates = _looks_like_coordinates(origin_address) and _looks_like_coordinates(
            destination_address
        )

        cache_key = (
            str(origin_address or "").strip(),
            str(destination_address or "").strip(),
            normalized_type,
            str(origin_city or "").strip(),
            str(destination_city or "").strip(),
        )
        if all(cache_key[:2]) and cache_key in _route_cache:
            return dict(_route_cache[cache_key])

        # 公交/地铁接口已熔断:直接用驾车耗时做近似估算,不再等待一次注定超时的调用。
        proxied = False
        if normalized_type == "transit" and not _transit_available():
            if _transit_proxy_enabled():
                proxied = True
            else:
                return {}

        if normalized_type == "transit":
            if proxied:
                # 用驾车路线近似公共交通耗时(通常略快,仅作为"可核验的估计值"),
                # 返回值里带 proxied=True 以便体检如实标注来源。
                if by_coordinates:
                    tool_name = "maps_direction_driving_by_coordinates"
                    arguments = {"origin": origin_address, "destination": destination_address}
                else:
                    tool_name = "maps_direction_driving_by_address"
                    arguments = {
                        "origin_address": origin_address,
                        "destination_address": destination_address,
                        "origin_city": origin_city,
                        "destination_city": destination_city,
                    }
            elif by_coordinates:
                tool_name = "maps_direction_transit_integrated_by_coordinates"
                arguments = {
                    "origin": origin_address,
                    "destination": destination_address,
                    "city": origin_city or destination_city or "",
                    "cityd": destination_city or origin_city or "",
                }
            else:
                tool_name = "maps_direction_transit_integrated_by_address"
                arguments = {
                    "origin_address": origin_address,
                    "destination_address": destination_address,
                    "origin_city": origin_city or "",
                    "destination_city": destination_city or "",
                }
        elif normalized_type == "driving":
            if by_coordinates:
                tool_name = "maps_direction_driving_by_coordinates"
                arguments = {"origin": origin_address, "destination": destination_address}
            else:
                tool_name = "maps_direction_driving_by_address"
                arguments = {
                    "origin_address": origin_address,
                    "destination_address": destination_address,
                    "origin_city": origin_city,
                    "destination_city": destination_city,
                }
        elif normalized_type == "bicycling":
            if by_coordinates:
                tool_name = "maps_bicycling_by_coordinates"
                arguments = {
                    "origin_coordinates": origin_address,
                    "destination_coordinates": destination_address,
                }
            else:
                tool_name = "maps_bicycling_by_address"
                arguments = {
                    "origin_address": origin_address,
                    "destination_address": destination_address,
                    "origin_city": origin_city,
                    "destination_city": destination_city,
                }
        else:
            normalized_type = "walking"
            if by_coordinates:
                tool_name = "maps_direction_walking_by_coordinates"
                arguments = {"origin": origin_address, "destination": destination_address}
            else:
                tool_name = "maps_direction_walking_by_address"
                arguments = {
                    "origin_address": origin_address,
                    "destination_address": destination_address,
                    "origin_city": origin_city,
                    "destination_city": destination_city,
                }

        try:
            data = self._call_tool(tool_name, arguments)
        except AmapMcpError as exc:
            print(f"❌ 路线规划失败: {exc}")
            return self._transit_downgrade(
                normalized_type,
                proxied,
                origin_address,
                destination_address,
                origin_city,
                destination_city,
                by_coordinates,
                cache_key,
            )
        except Exception as exc:
            print(f"❌ 路线规划失败: {type(exc).__name__}: {exc}")
            return self._transit_downgrade(
                normalized_type,
                proxied,
                origin_address,
                destination_address,
                origin_city,
                destination_city,
                by_coordinates,
                cache_key,
            )

        route = self._normalize_route(data, normalized_type)
        if route and normalized_type == "transit":
            _mark_transit_success()
        if route and proxied:
            route["proxied"] = True
        if route and all(cache_key[:2]):
            if len(_route_cache) >= _ROUTE_CACHE_MAX:
                _route_cache.clear()
            _route_cache[cache_key] = dict(route)
        return route

    def _transit_downgrade(
        self,
        normalized_type: str,
        proxied: bool,
        origin_address: str,
        destination_address: str,
        origin_city: Optional[str],
        destination_city: Optional[str],
        by_coordinates: bool,
        cache_key: Tuple[str, str, str, str, str],
    ) -> Dict[str, Any]:
        """公交/地铁调用失败后的降级:优先用驾车路线近似,否则返回空。"""
        if normalized_type != "transit":
            # 步行/驾车/骑行失败:没有可用的近似方案,如实返回空。
            return {}
        if proxied:
            # 本次已经是"驾车近似"却仍然失败:不再重试,如实返回空。
            return {}

        # 真正的公交/地铁调用失败:累计失败次数,并尝试用驾车耗时近似。
        _mark_transit_failure()
        if not _transit_proxy_enabled():
            return {}

        if by_coordinates:
            proxy_tool = "maps_direction_driving_by_coordinates"
            proxy_args: Dict[str, Any] = {
                "origin": origin_address,
                "destination": destination_address,
            }
        else:
            proxy_tool = "maps_direction_driving_by_address"
            proxy_args = {
                "origin_address": origin_address,
                "destination_address": destination_address,
                "origin_city": origin_city,
                "destination_city": destination_city,
            }
        try:
            data = self._call_tool(proxy_tool, proxy_args)
        except Exception as exc:
            print(f"❌ 公交降级到驾车也失败: {type(exc).__name__}: {exc}")
            return {}
        route = self._normalize_route(data, normalized_type)
        if not route:
            return {}
        route["proxied"] = True
        if all(cache_key[:2]):
            if len(_route_cache) >= _ROUTE_CACHE_MAX:
                _route_cache.clear()
            _route_cache[cache_key] = dict(route)
        return route

    @staticmethod
    def _normalize_route(data: Any, route_type: str) -> Dict[str, Any]:
        """把步行/驾车/公交/骑行的原始结构统一成 {distance, duration, ...}。"""
        if not isinstance(data, dict):
            return {}
        route = data.get("route")
        if not isinstance(route, dict):
            return {}

        distance: Any = None
        duration: Any = None

        paths = route.get("paths")
        if isinstance(paths, list) and paths and isinstance(paths[0], dict):
            distance = paths[0].get("distance")
            duration = paths[0].get("duration")

        transits = route.get("transits")
        if (
            duration in (None, "")
            or distance in (None, "")
        ) and isinstance(transits, list) and transits:
            first = transits[0] if isinstance(transits[0], dict) else {}
            if duration in (None, ""):
                duration = first.get("duration")
            if distance in (None, ""):
                distance = route.get("distance")
            if distance in (None, "") and isinstance(first.get("segments"), list):
                total = 0.0
                for segment in first["segments"]:
                    if not isinstance(segment, dict):
                        continue
                    walking = segment.get("walking") or {}
                    if isinstance(walking, dict):
                        try:
                            total += float(walking.get("distance") or 0)
                        except (TypeError, ValueError):
                            pass
                    buslines = (segment.get("bus") or {}).get("buslines") or []
                    if isinstance(buslines, list):
                        for line in buslines:
                            if not isinstance(line, dict):
                                continue
                            try:
                                total += float(line.get("distance") or 0)
                            except (TypeError, ValueError):
                                pass
                if total > 0:
                    distance = total

        try:
            distance_value = float(distance or 0)
        except (TypeError, ValueError):
            distance_value = 0.0
        try:
            duration_value = int(round(float(duration or 0)))
        except (TypeError, ValueError):
            duration_value = 0

        if distance_value <= 0 and duration_value <= 0:
            return {}

        minutes = int(round(duration_value / 60)) if duration_value else 0
        label = {
            "walking": "步行",
            "driving": "驾车",
            "transit": "公共交通",
            "bicycling": "骑行",
        }.get(route_type, route_type)
        if distance_value > 0:
            description = f"{label}约 {distance_value / 1000:.1f} 公里,预计 {minutes} 分钟"
        else:
            description = f"{label}预计 {minutes} 分钟"

        return {
            "distance": distance_value,
            "duration": duration_value,
            "route_type": route_type,
            "description": description,
            "origin": route.get("origin"),
            "destination": route.get("destination"),
        }
    
    def geocode(self, address: str, city: Optional[str] = None) -> Optional[Location]:
        """
        地理编码(地址转坐标)

        Args:
            address: 地址
            city: 城市

        Returns:
            经纬度坐标;失败返回 None
        """
        arguments: Dict[str, Any] = {"address": address}
        if city:
            arguments["city"] = city

        try:
            data = self._call_tool("maps_geo", arguments)
        except AmapMcpError as exc:
            print(f"❌ 地理编码失败: {exc}")
            return None
        except Exception as exc:
            print(f"❌ 地理编码失败: {type(exc).__name__}: {exc}")
            return None

        items: Any = None
        if isinstance(data, dict):
            items = data.get("return") or data.get("geocodes")
        elif isinstance(data, list):
            items = data
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            return None

        for item in items:
            if isinstance(item, dict):
                location = parse_location(_first_value(item, "location", "lnglat"))
            else:
                location = parse_location(item)
            if location is not None:
                return location
        return None

    def get_poi_detail(self, poi_id: str, use_cache: bool = True) -> Dict[str, Any]:
        """
        获取POI详情

        Args:
            poi_id: POI ID
            use_cache: 是否使用进程内缓存

        Returns:
            POI详情信息(含 location/address/city/tel 等);失败返回 {}
        """
        key = str(poi_id or "").strip()
        if not key:
            return {}
        if use_cache and key in _poi_detail_cache:
            return _poi_detail_cache[key]

        try:
            data = self._call_tool("maps_search_detail", {"id": key})
        except AmapMcpError as exc:
            print(f"❌ 获取POI详情失败: {exc}")
            return {}
        except Exception as exc:
            print(f"❌ 获取POI详情失败: {type(exc).__name__}: {exc}")
            return {}

        if not isinstance(data, dict):
            return {}

        # 兼容把结果包在 pois 列表中的返回形式
        pois = data.get("pois")
        if isinstance(pois, list) and pois and isinstance(pois[0], dict):
            data = pois[0]

        if use_cache:
            if len(_poi_detail_cache) >= _POI_DETAIL_CACHE_MAX:
                _poi_detail_cache.clear()
            _poi_detail_cache[key] = data
        return data


# 创建全局服务实例
_amap_service = None


def get_amap_service() -> AmapService:
    """获取高德地图服务实例(单例模式)"""
    global _amap_service
    
    if _amap_service is None:
        _amap_service = AmapService()
    
    return _amap_service

