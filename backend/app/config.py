"""配置管理模块"""

import os
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# 加载环境变量
# 首先尝试加载当前目录的.env
load_dotenv()

# 然后尝试加载HelloAgents的.env(如果存在)
helloagents_env = Path(__file__).parent.parent.parent.parent / "HelloAgents" / ".env"
if helloagents_env.exists():
    load_dotenv(helloagents_env, override=False)  # 不覆盖已有的环境变量


class Settings(BaseSettings):
    """应用配置"""

    # 应用基本配置
    app_name: str = "TravelMind 智能旅行助手"
    app_version: str = "2.0.0"
    debug: bool = False

    # 服务器配置
    host: str = "0.0.0.0"
    port: int = 8000

    # CORS配置 - 使用字符串,在代码中分割
    cors_origins: str = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000"

    # 高德地图API配置
    amap_api_key: str = ""

    # Unsplash API配置
    unsplash_access_key: str = ""
    unsplash_secret_key: str = ""

    # LLM配置 (从环境变量读取,由HelloAgents管理)
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4"

    # ===== TravelMind 增量配置 =====
    # 演示模式:仅在显式开启时允许使用带 mock 标识的演示事实/识别结果
    travelmind_demo_mode: bool = False
    # 上传攻略截图的最大体积(MiB),服务端为准
    travelmind_max_image_mb: int = 10
    # 是否允许调用 LLM 生成候选排序(默认关闭,规则引擎已足够)
    travelmind_enable_llm_repair: bool = False
    # 视觉模型配置(未配置时截图导入返回 VISION_NOT_CONFIGURED)
    vision_model: str = ""
    vision_api_key: str = ""
    vision_base_url: str = "https://api.openai.com/v1"

    # 高德 MCP 启动命令(留空使用内置默认值)
    # 默认锁定 pydantic<2.14:amap-mcp-server 依赖 mcp==1.8.1,而 mcp 1.8.1
    # 会 import pydantic._internal._typing_extra.eval_type_backport(pydantic>=2.14 已移除),
    # 导致子进程启动失败、工具数量为 0。可用 AMAP_MCP_COMMAND 覆盖。
    amap_mcp_command: str = ""
    # 单次高德 MCP 调用的超时(秒)。
    # 实测 `maps_direction_transit_integrated_*`(公交/地铁)在当前版本的
    # amap-mcp-server 上会返回非法 JSON 并让客户端无限等待;没有超时保护时
    # 体检会被这条调用拖死。超时后该次调用按失败处理。
    amap_mcp_timeout_seconds: float = 20.0
    # 公交/地铁接口连续失败多少次后判定为"不可用",后续直接走驾车近似估算
    amap_transit_failure_threshold: int = 2
    # 判定公交接口不可用后的冷却时间(秒),期间不再尝试该接口
    amap_transit_cooldown_seconds: int = 900
    # 公交接口不可用时,是否用驾车耗时做近似估算(False 则该段交通标记为未核实)
    amap_transit_fallback_driving: bool = True
    # 文本搜索不返回经纬度,需要二次查询详情的条目数上限
    travelmind_poi_detail_limit: int = 5

    # ===== 截图导入链路的性能与超时参数 =====
    # 说明:高德 MCP 每次调用都会重新拉起一个 `uvx amap-mcp-server` 子进程,
    # 单次往返在本机实测约 15s。截图识别需要按候选地点逐个查询 POI,
    # 因此这里提供并发度与时间预算,避免"地点多就必然超时"。
    # 送给视觉模型前,图片长边缩放上限(像素);0 表示不缩放
    travelmind_vision_max_dimension: int = 1600
    # 视觉模型单次调用的读超时(秒)
    travelmind_vision_timeout_seconds: int = 90
    # 截图导入时 POI 匹配的并发度(1 表示串行)
    travelmind_poi_concurrency: int = 4
    # 截图导入时每个候选额外补齐坐标的详情条目数(越小越快)
    travelmind_import_poi_detail_limit: int = 2
    # 截图导入时 POI 匹配阶段的总时间预算(秒);超时返回已完成的部分结果
    travelmind_import_poi_budget_seconds: int = 90

    # ===== 行程体检(health-check)的事实核验性能参数 =====
    # 体检要逐景点核营业时间、逐对相邻景点核交通耗时、逐天核天气,而高德 MCP
    # 每次调用都会重建子进程(冷启动 13-15 秒)。因此把"去重后的最小事实集合"
    # 并发取回,并给出总时间预算;超出预算时降级为 partial 报告而不是挂死请求。
    # 事实核验的并发度(高德限流,建议 4)
    travelmind_health_concurrency: int = 4
    # 事实核验的总时间预算(秒);超出后未取回的事实标记为「未核实」
    travelmind_health_budget_seconds: int = 150

    # 日志配置
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"  # 忽略额外的环境变量

    def get_cors_origins_list(self) -> List[str]:
        """获取CORS origins列表"""
        return [origin.strip() for origin in self.cors_origins.split(',')]


# 创建全局配置实例
settings = Settings()


def get_settings() -> Settings:
    """获取配置实例"""
    return settings


# 验证必要的配置
def validate_config():
    """验证配置是否完整"""
    errors = []
    warnings = []

    if not settings.amap_api_key:
        errors.append("AMAP_API_KEY未配置")

    # HelloAgentsLLM会自动从LLM_API_KEY读取,不强制要求OPENAI_API_KEY
    llm_api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not llm_api_key:
        warnings.append("LLM_API_KEY或OPENAI_API_KEY未配置,LLM功能可能无法使用")

    if errors:
        error_msg = "配置错误:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ValueError(error_msg)

    if warnings:
        print("\n⚠️  配置警告:")
        for w in warnings:
            print(f"  - {w}")

    return True


# 打印配置信息(用于调试)
def print_config():
    """打印当前配置(隐藏敏感信息)"""
    print(f"应用名称: {settings.app_name}")
    print(f"版本: {settings.app_version}")
    print(f"服务器: {settings.host}:{settings.port}")
    print(f"高德地图API Key: {'已配置' if settings.amap_api_key else '未配置'}")

    # 检查LLM配置
    llm_api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    llm_base_url = os.getenv("LLM_BASE_URL") or settings.openai_base_url
    llm_model = os.getenv("LLM_MODEL_ID") or settings.openai_model

    print(f"LLM API Key: {'已配置' if llm_api_key else '未配置'}")
    print(f"LLM Base URL: {llm_base_url}")
    print(f"LLM Model: {llm_model}")
    print(f"日志级别: {settings.log_level}")

