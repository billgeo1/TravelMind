"""TravelMind 业务服务包。

新增能力:
- validation  行程体检规则引擎
- repair      AI 智能修复候选
- replan      突发事件动态重规划
- image_import 攻略截图识别与 POI 匹配
- facts       事实提供者(真实/演示/Mock)
- diff        行程差异
- normalization 旧计划兼容与稳定节点 ID
"""

from .errors import TravelMindError, ErrorCode, register_exception_handlers
from .normalization import normalize_trip_plan, ensure_plan_id

__all__ = [
    "TravelMindError",
    "ErrorCode",
    "register_exception_handlers",
    "normalize_trip_plan",
    "ensure_plan_id",
]
