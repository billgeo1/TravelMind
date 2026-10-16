"""TravelMind 新增 API 的 Pydantic Schema。

这些模型独立于旧 `schemas.py`,仅通过组合/引用的方式复用旧 `TripPlan` /
`Location` 等类型,避免破坏原有 `/api/trip/plan` 的序列化结构。
"""

from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from .schemas import Location, TripPlan


# ============ 通用枚举 / 基础结构 ============

class Severity(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


class Evidence(BaseModel):
    """风险/结论的证据来源,便于审计与展示。"""

    source: str = Field(..., description="amap | weather | user | derived | mock | unknown")
    observed_at: Optional[str] = Field(default=None, description="观测时间")
    detail: Optional[str] = Field(default=None, description="证据说明")
    confidence: Optional[float] = Field(default=None, ge=0, le=1, description="置信度 0-1")


class HealthIssue(BaseModel):
    issue_id: str
    code: str
    severity: Severity
    title: str
    description: str
    affected_day_indices: List[int] = Field(default_factory=list)
    affected_attraction_uids: List[str] = Field(default_factory=list)
    evidence: List[Evidence] = Field(default_factory=list)
    suggestion: str = ""
    can_auto_fix: bool = False


class HealthReport(BaseModel):
    score: Optional[int] = Field(default=None, ge=0, le=100)
    status: Literal["complete", "partial", "insufficient_data"]
    issues: List[HealthIssue] = Field(default_factory=list)
    checked_rule_count: int = 0
    total_rule_count: int = 0
    coverage: Optional[float] = Field(default=None, ge=0, le=1)
    checked_fact_count: int = 0
    total_fact_count: int = 0
    disclaimer: Optional[str] = None


class PlanChange(BaseModel):
    change_type: Literal["move", "replace", "remove", "add", "time_update", "budget_update"]
    attraction_uid: Optional[str] = None
    attraction_name: Optional[str] = None
    day_index: Optional[int] = None
    before: Optional[str] = None
    after: Optional[str] = None
    reason: str = ""


class PlanPreview(BaseModel):
    base_revision: int
    candidate_plan: TripPlan
    changes: List[PlanChange] = Field(default_factory=list)
    unresolved_issues: List[HealthIssue] = Field(default_factory=list)
    budget_delta: Optional[int] = None
    warning: Optional[str] = None
    report: Optional[HealthReport] = Field(
        default=None, description="候选计划复检后的体检报告"
    )


# ============ 体检 / 修复 ============

class ValidationOptions(BaseModel):
    daily_max_minutes: int = Field(default=540, ge=0, le=1440, description="每日活动时长上限(分钟)")
    travel_buffer_minutes: int = Field(default=15, ge=0, le=600, description="两景点间安全缓冲(分钟)")
    budget_limit_yuan: Optional[int] = Field(default=None, ge=0, description="明确预算上限,未提供则跳过精确超限")


class HealthCheckRequest(BaseModel):
    trip_plan: TripPlan
    options: ValidationOptions = Field(default_factory=ValidationOptions)


class RepairPreferences(BaseModel):
    preserve_confirmed_bookings: bool = True
    allow_remove_attractions: bool = False


class RepairPreviewRequest(BaseModel):
    trip_plan: TripPlan
    health_report: Optional[HealthReport] = None
    base_revision: int = 0
    preferences: RepairPreferences = Field(default_factory=RepairPreferences)
    options: ValidationOptions = Field(default_factory=ValidationOptions)


# ============ 突发事件重规划 ============

class ReplanEvent(BaseModel):
    type: Literal["rain", "attraction_closed", "delay", "fatigue", "other"]
    affected_day_index: int = Field(ge=0)
    affected_attraction_uid: Optional[str] = None
    delay_minutes: Optional[int] = Field(default=None, ge=0, le=1440)
    description: Optional[str] = Field(default=None, max_length=1000)
    event_time: Optional[str] = None
    source: Literal["user_reported", "mock", "verified_provider"] = "user_reported"


class ReplanPreviewRequest(BaseModel):
    trip_plan: TripPlan
    base_revision: int = 0
    event: ReplanEvent
    locked_attraction_uids: List[str] = Field(default_factory=list)
    max_extra_budget_yuan: Optional[int] = Field(default=None, ge=0)
    options: ValidationOptions = Field(default_factory=ValidationOptions)


# ============ 攻略截图导入 ============

class ImportCandidate(BaseModel):
    candidate_id: str
    raw_name: str
    canonical_name: Optional[str] = None
    poi_id: Optional[str] = None
    address: Optional[str] = None
    location: Optional[Location] = None
    city: Optional[str] = None
    match_status: Literal["matched", "ambiguous", "not_found"]
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    alternatives: List[dict] = Field(default_factory=list)


class ImageImportResult(BaseModel):
    detected_city: Optional[str] = None
    candidates: List[ImportCandidate] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    source: Literal["vision", "mock"]


class ConfirmedAttraction(BaseModel):
    candidate_id: Optional[str] = None
    poi_id: Optional[str] = None
    name: str
    address: Optional[str] = None
    location: Optional[Location] = None
    city: Optional[str] = None


class ImportTripRequest(BaseModel):
    """`plan-from-import` 的内部请求结构,兼容规范中的 `days`/字符串偏好写法。"""

    city: str
    start_date: str
    end_date: str
    travel_days: Optional[int] = Field(default=None, ge=1, le=30)
    days: Optional[int] = Field(default=None, ge=1, le=30)
    transportation: str = "公共交通"
    accommodation: str = "经济型酒店"
    preferences: Union[List[str], str] = Field(default_factory=list)
    budget: Optional[str] = None
    free_text_input: str = ""

    @field_validator("preferences", mode="before")
    @classmethod
    def _normalize_preferences(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            parts = [p.strip() for p in v.replace(",", " ").replace("、", " ").split()]
            return [p for p in parts if p]
        return v

    @model_validator(mode="after")
    def _fill_travel_days(self):
        if self.travel_days is None:
            self.travel_days = self.days
        return self


class UnplacedAttraction(BaseModel):
    name: str
    reason: str
    poi_id: Optional[str] = None
    candidate_id: Optional[str] = None


class PlanFromImportRequest(BaseModel):
    request: ImportTripRequest
    confirmed_attractions: List[ConfirmedAttraction] = Field(default_factory=list)
    additional_preferences: str = ""


class PlanFromImportResponse(BaseModel):
    trip_plan: TripPlan
    unplaced_attractions: List[UnplacedAttraction] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


# ============ 统一错误结构 ============

class TravelMindErrorBody(BaseModel):
    code: str
    message: str
    retryable: bool = False


class TravelMindErrorResponse(BaseModel):
    error: TravelMindErrorBody
