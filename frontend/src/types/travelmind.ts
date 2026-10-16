/**
 * TravelMind 增量功能的类型定义。
 *
 * 与后端 `backend/app/models/travelmind.py` 中的 Pydantic Schema 一一对应,
 * 字段名保持 snake_case 以避免额外的序列化映射。
 */

import type { Location, TripPlan } from './index'

// ============ 通用 ============

export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'info'

export type HealthStatus = 'complete' | 'partial' | 'insufficient_data'

export interface Evidence {
  source: string
  observed_at?: string | null
  detail?: string | null
  confidence?: number | null
}

export interface HealthIssue {
  issue_id: string
  code: string
  severity: Severity
  title: string
  description: string
  affected_day_indices: number[]
  affected_attraction_uids: string[]
  evidence: Evidence[]
  suggestion: string
  can_auto_fix: boolean
}

export interface HealthReport {
  score: number | null
  status: HealthStatus
  issues: HealthIssue[]
  checked_rule_count: number
  total_rule_count: number
  coverage: number | null
  checked_fact_count: number
  total_fact_count: number
  disclaimer?: string | null
}

export type PlanChangeType =
  | 'move'
  | 'replace'
  | 'remove'
  | 'add'
  | 'time_update'
  | 'budget_update'

export interface PlanChange {
  change_type: PlanChangeType
  attraction_uid?: string | null
  attraction_name?: string | null
  day_index?: number | null
  before?: string | null
  after?: string | null
  reason: string
}

export interface PlanPreview {
  base_revision: number
  candidate_plan: TripPlan
  changes: PlanChange[]
  unresolved_issues: HealthIssue[]
  budget_delta?: number | null
  warning?: string | null
  report?: HealthReport | null
}

// ============ 体检 / 修复 ============

export interface ValidationOptions {
  daily_max_minutes?: number
  travel_buffer_minutes?: number
  budget_limit_yuan?: number | null
}

export interface HealthCheckRequest {
  trip_plan: TripPlan
  options?: ValidationOptions
}

export interface RepairPreferences {
  preserve_confirmed_bookings?: boolean
  allow_remove_attractions?: boolean
}

export interface RepairPreviewRequest {
  trip_plan: TripPlan
  health_report?: HealthReport | null
  base_revision?: number
  preferences?: RepairPreferences
  options?: ValidationOptions
}

// ============ 突发事件重规划 ============

export type ReplanEventType =
  | 'rain'
  | 'attraction_closed'
  | 'delay'
  | 'fatigue'
  | 'other'

export interface ReplanEvent {
  type: ReplanEventType
  affected_day_index: number
  affected_attraction_uid?: string | null
  delay_minutes?: number | null
  description?: string | null
  event_time?: string | null
  source?: 'user_reported' | 'mock' | 'verified_provider'
}

export interface ReplanPreviewRequest {
  trip_plan: TripPlan
  base_revision?: number
  event: ReplanEvent
  locked_attraction_uids?: string[]
  max_extra_budget_yuan?: number | null
  options?: ValidationOptions
}

// ============ 攻略截图导入 ============

export type MatchStatus = 'matched' | 'ambiguous' | 'not_found'

export interface ImportCandidate {
  candidate_id: string
  raw_name: string
  canonical_name?: string | null
  poi_id?: string | null
  address?: string | null
  location?: Location | null
  city?: string | null
  match_status: MatchStatus
  confidence?: number | null
  alternatives: Array<Record<string, any>>
}

export interface ImageImportResult {
  detected_city?: string | null
  candidates: ImportCandidate[]
  warnings: string[]
  source: 'vision' | 'mock'
}

export interface ConfirmedAttraction {
  candidate_id?: string | null
  poi_id?: string | null
  name: string
  address?: string | null
  location?: Location | null
  city?: string | null
}

export interface ImportTripRequest {
  city: string
  start_date: string
  end_date: string
  travel_days?: number | null
  days?: number | null
  transportation?: string
  accommodation?: string
  preferences?: string[] | string
  budget?: string | null
  free_text_input?: string
}

export interface UnplacedAttraction {
  name: string
  reason: string
  poi_id?: string | null
  candidate_id?: string | null
}

export interface PlanFromImportRequest {
  request: ImportTripRequest
  confirmed_attractions: ConfirmedAttraction[]
  additional_preferences?: string
}

export interface PlanFromImportResponse {
  trip_plan: TripPlan
  unplaced_attractions: UnplacedAttraction[]
  warnings: string[]
}

// ============ 统一错误体 ============

export interface TravelMindErrorBody {
  code: string
  message: string
  retryable: boolean
}

export interface TravelMindErrorResponse {
  error: TravelMindErrorBody
  /** 兼容旧前端:请求校验错误时附带的字段 */
  detail?: string
}
