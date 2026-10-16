"""TravelMind 增量业务接口(规范 Phase B/C/D)。

提供规范第 7 节要求的 5 个接口:

- ``POST /api/trip/health-check``      AI 行程体检
- ``POST /api/trip/repair-preview``    AI 行程智能修复(预览)
- ``POST /api/trip/replan-preview``    突发事件动态重规划(预览)
- ``POST /api/trip/import-image``      攻略截图识别(仅识别,不生成行程)
- ``POST /api/trip/plan-from-import``  基于用户确认的候选生成行程

设计约定:

- 所有"修复/重规划"接口只返回**预览**,不写数据库、不自动下单;是否应用由
  用户在前端确认后决定(见规范 Phase B/C 的"预览->差异->确认"流程)。
- AI/外部服务输出一律先经 Pydantic 结构校验,再由规则引擎二次校验。
- 统一错误体 ``{"error": {"code", "message", "retryable"}}``。
"""

from __future__ import annotations

import re
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.concurrency import run_in_threadpool

from ...config import get_settings
from ...models.schemas import TripPlan
from ...models.travelmind import (
    HealthCheckRequest,
    HealthReport,
    ImageImportResult,
    PlanFromImportRequest,
    PlanFromImportResponse,
    PlanPreview,
    RepairPreviewRequest,
    ReplanPreviewRequest,
)
from ...services.travelmind.errors import ErrorCode, TravelMindError
from ...services.travelmind.facts import get_fact_provider
from ...services.travelmind.image_import import (
    compose_plan_from_import,
    import_image_bytes,
)
from ...services.travelmind.llm_agents import build_repair_llm
from ...services.travelmind.normalization import normalize_trip_plan
from ...services.travelmind.repair import repair_plan
from ...services.travelmind.replan import replan_plan
from ...services.travelmind.validation import validate_plan

router = APIRouter(prefix="/trip", tags=["TravelMind"])

# PlannerAgent 兜底行程的景点名形如 "北京景点1"
_FALLBACK_NAME_RE = re.compile(r"^.*景点\d+$")


def _guard_revision(plan: TripPlan, base_revision: int) -> None:
    """乐观并发控制:阻止基于过期版本生成的预览被应用。"""
    if base_revision != plan.revision:
        raise TravelMindError(
            ErrorCode.STALE_PLAN_REVISION,
            f"计划版本不一致:请求基于 revision={base_revision},"
            f"当前为 revision={plan.revision},请重新加载行程后再试。",
        )


def _looks_like_fallback(plan: TripPlan) -> bool:
    """识别 PlannerAgent 内部兜底生成的占位行程(不编造为真实结果)。"""
    names = [a.name for day in plan.days for a in day.attractions]
    if not names:
        return True
    return all(_FALLBACK_NAME_RE.match(name or "") for name in names)


@router.post(
    "/health-check",
    response_model=HealthReport,
    summary="AI 行程体检",
    description="对给定行程执行规则体检,返回风险清单、评分与覆盖度。",
)
async def travelmind_health_check(request: HealthCheckRequest) -> HealthReport:
    """行程体检:规范化为增强结构后再运行规则引擎。"""
    plan = normalize_trip_plan(request.trip_plan)
    # 规则引擎会同步调用外部事实源(天气等),放进线程池避免阻塞事件循环
    return await run_in_threadpool(
        validate_plan, plan, request.options, get_fact_provider()
    )


@router.post(
    "/repair-preview",
    response_model=PlanPreview,
    summary="AI 行程智能修复(预览)",
    description="基于体检报告生成修复候选方案与差异,需用户确认后才应用。",
)
async def travelmind_repair_preview(request: RepairPreviewRequest) -> PlanPreview:
    plan = normalize_trip_plan(request.trip_plan)
    _guard_revision(plan, request.base_revision)
    return await run_in_threadpool(
        repair_plan,
        plan,
        request.health_report,
        request.preferences,
        request.options,
        get_fact_provider(),
        request.base_revision,
        build_repair_llm(),
    )


@router.post(
    "/replan-preview",
    response_model=PlanPreview,
    summary="突发事件动态重规划(预览)",
    description="针对天气/闭馆/延误/疲劳等事件生成重规划候选方案与差异。",
)
async def travelmind_replan_preview(request: ReplanPreviewRequest) -> PlanPreview:
    plan = normalize_trip_plan(request.trip_plan)
    _guard_revision(plan, request.base_revision)
    return await run_in_threadpool(
        replan_plan,
        plan,
        request.event,
        request.locked_attraction_uids,
        request.max_extra_budget_yuan,
        request.options,
        get_fact_provider(),
        request.base_revision,
    )


@router.post(
    "/import-image",
    response_model=ImageImportResult,
    summary="攻略截图识别",
    description="校验并识别 PNG/JPEG/WebP 攻略截图,返回待确认的地点候选。",
)
async def travelmind_import_image(
    file: UploadFile = File(..., description="攻略截图(PNG/JPEG/WebP)"),
    city_hint: Optional[str] = Form(default=None, description="可选的城市提示"),
) -> ImageImportResult:
    """截图识别:体积在读取阶段就做上限保护,文件不落盘。"""
    settings = get_settings()
    max_mb = max(int(getattr(settings, "travelmind_max_image_mb", 10) or 10), 1)
    limit_bytes = max_mb * 1024 * 1024
    # 有界读取:最多读取 上限+1 字节,避免超大文件占满内存
    data = await file.read(limit_bytes + 1)
    if len(data) > limit_bytes:
        raise TravelMindError(
            ErrorCode.IMAGE_TOO_LARGE,
            f"图片体积超过 {max_mb} MiB 上限。",
        )
    # 识别链路包含视觉模型请求与多次高德 MCP 调用(均为同步阻塞 I/O),
    # 必须放进线程池:否则会卡住整个事件循环,连其它接口一并失去响应。
    return await run_in_threadpool(
        import_image_bytes,
        data,
        filename=file.filename,
        content_type=file.content_type,
        city_hint=city_hint,
        max_mb=max_mb,
    )


@router.post(
    "/plan-from-import",
    response_model=PlanFromImportResponse,
    summary="根据截图确认结果生成行程",
    description="使用原有 PlannerAgent 生成行程,并保证用户确认的景点不被静默丢弃。",
)
async def travelmind_plan_from_import(
    request: PlanFromImportRequest,
) -> PlanFromImportResponse:
    # 延迟导入:避免与常见启动路径形成循环依赖,也便于测试替换
    from ...agents.trip_planner_agent import get_trip_planner_agent

    planner = get_trip_planner_agent()
    result = await run_in_threadpool(compose_plan_from_import, request, planner.plan_trip)

    warnings = list(result.warnings)
    settings = get_settings()
    if not getattr(settings, "travelmind_demo_mode", False) and _looks_like_fallback(
        result.trip_plan
    ):
        warnings.append(
            "行程生成服务未返回可核验的真实景点(可能未配置高德/LLM 密钥),"
            "当前结果可能为占位数据,请核对后再使用。"
        )
    if warnings != result.warnings:
        result = result.model_copy(update={"warnings": warnings})
    return result
