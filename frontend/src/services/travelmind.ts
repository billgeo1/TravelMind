/**
 * TravelMind 增量接口封装。
 *
 * 复用原有 axios 实例(`services/api.ts`),因此 baseURL / 超时 / 拦截器都与
 * 原有 `/api/trip/plan` 保持一致。
 *
 * 所有接口失败时统一抛出 `TravelMindApiError`,前端可据 `code` 做差异化处理:
 * - `STALE_PLAN_REVISION`(409):行程已被改动,必须重新加载后再试。
 * - `VISION_NOT_CONFIGURED`(503):未配置视觉模型,提示改用演示模式。
 * - `EXTERNAL_PROVIDER_UNAVAILABLE`(503,retryable):可重试。
 */

import apiClient from './api'
import type { TripPlan } from '@/types'
import type {
  HealthCheckRequest,
  HealthReport,
  ImageImportResult,
  PlanFromImportRequest,
  PlanFromImportResponse,
  PlanPreview,
  RepairPreviewRequest,
  ReplanPreviewRequest,
  TravelMindErrorBody,
} from '@/types/travelmind'

export class TravelMindApiError extends Error {
  code: string
  retryable: boolean
  status: number

  constructor(body: TravelMindErrorBody, status: number) {
    super(body.message || '请求失败')
    this.name = 'TravelMindApiError'
    this.code = body.code || 'UNKNOWN'
    this.retryable = Boolean(body.retryable)
    this.status = status
  }
}

/** 触发请求的业务动作,用于给出**对得上场景**的超时说明。 */
export type TravelMindOperation = 'health' | 'repair' | 'replan' | 'import' | 'plan'

/**
 * 各接口的请求超时(毫秒)。
 *
 * 体检 / 修复 / 重规划都要多次调用高德 MCP(每次调用会重建子进程,
 * 冷启动 13-15 秒),不能沿用实例默认的 120s。
 */
export const OPERATION_TIMEOUTS: Record<TravelMindOperation, number> = {
  health: 240000,
  repair: 360000,
  replan: 360000,
  import: 300000,
  plan: 120000,
}

const TIMEOUT_MESSAGES: Record<TravelMindOperation, string> = {
  health:
    '体检超时:后端仍在核验营业时间、交通耗时与天气。' +
    '请稍等片刻后重试;景点较多的行程耗时会更长。',
  repair:
    '生成修复方案超时:后端仍在重新排期并复检风险。' +
    '请稍等片刻后重试。',
  replan:
    '重规划超时:后端仍在查询替代景点与路线。' +
    '请稍等片刻后重试。',
  import:
    '截图识别超时:识别需要调用视觉模型 + 逐个查询高德 POI。' +
    '请稍等片刻后重试,或减少截图中的地点数量。',
  plan: '生成行程超时:请稍等片刻后重试,或适当减少行程天数与景点数量。',
}

function toTravelMindError(
  error: any,
  operation: TravelMindOperation = 'plan'
): TravelMindApiError {
  const status: number = error?.response?.status ?? 0
  const payload = error?.response?.data
  const body: TravelMindErrorBody | undefined = payload?.error
  if (body && typeof body === 'object' && body.code) {
    return new TravelMindApiError(body, status)
  }
  // 请求超时(axios: ECONNABORTED / ETIMEDOUT):给可执行的重试建议
  const axiosCode: string = error?.code ?? ''
  if (axiosCode === 'ECONNABORTED' || axiosCode === 'ETIMEDOUT') {
    return new TravelMindApiError(
      {
        code: 'REQUEST_TIMEOUT',
        message: TIMEOUT_MESSAGES[operation] || TIMEOUT_MESSAGES.plan,
        retryable: true,
      },
      status
    )
  }
  // 兼容非统一错误体(网络错误 / 旧接口 / 5xx 兜底)
  return new TravelMindApiError(
    {
      code: status === 0 ? 'NETWORK_ERROR' : 'UNKNOWN',
      message:
        payload?.detail ||
        error?.message ||
        '请求失败,请稍后重试',
      retryable: status === 0 || status >= 500,
    },
    status
  )
}

/** AI 行程体检(不修改任何数据)。 */
export async function checkTripHealth(
  tripPlan: TripPlan,
  options?: HealthCheckRequest['options']
): Promise<HealthReport> {
  const payload: HealthCheckRequest = { trip_plan: tripPlan, options }
  try {
    const response = await apiClient.post<HealthReport>('/api/trip/health-check', payload, {
      // 体检要逐个景点核对营业时间、逐对相邻景点核对交通耗时、逐天核对天气,
      // 高德 MCP 冷启动约 15s,因此放宽到 4 分钟。
      timeout: OPERATION_TIMEOUTS.health,
    })
    return response.data
  } catch (error: any) {
    throw toTravelMindError(error, 'health')
  }
}

/** 生成智能修复候选方案(仅预览,需用户确认)。 */
export async function repairPlanPreview(
  payload: RepairPreviewRequest
): Promise<PlanPreview> {
  try {
    const response = await apiClient.post<PlanPreview>('/api/trip/repair-preview', payload, {
      timeout: OPERATION_TIMEOUTS.repair,
    })
    return response.data
  } catch (error: any) {
    throw toTravelMindError(error, 'repair')
  }
}

/** 生成突发事件重规划候选方案(仅预览,需用户确认)。 */
export async function replanPlanPreview(
  payload: ReplanPreviewRequest
): Promise<PlanPreview> {
  try {
    const response = await apiClient.post<PlanPreview>('/api/trip/replan-preview', payload, {
      timeout: OPERATION_TIMEOUTS.replan,
    })
    return response.data
  } catch (error: any) {
    throw toTravelMindError(error, 'replan')
  }
}

/** 识别攻略截图,返回待确认的地点候选(不生成行程)。 */
export async function importGuideImage(
  file: File,
  cityHint?: string
): Promise<ImageImportResult> {
  const form = new FormData()
  form.append('file', file)
  if (cityHint) {
    form.append('city_hint', cityHint)
  }
  try {
    const response = await apiClient.post<ImageImportResult>('/api/trip/import-image', form, {
      // 覆盖实例默认的 application/json,交给浏览器补 multipart boundary
      headers: { 'Content-Type': undefined as unknown as string },
      // 识别链路包含视觉模型 + 多次高德 MCP 调用(本机实测每次 POI 查询约 15s),
      // 因此单独把该接口的超时放宽到 5 分钟。
      timeout: OPERATION_TIMEOUTS.import,
    })
    return response.data
  } catch (error: any) {
    throw toTravelMindError(error, 'import')
  }
}

/** 基于用户确认的候选生成行程。 */
export async function planFromImport(
  payload: PlanFromImportRequest
): Promise<PlanFromImportResponse> {
  try {
    const response = await apiClient.post<PlanFromImportResponse>(
      '/api/trip/plan-from-import',
      payload
    )
    return response.data
  } catch (error: any) {
    throw toTravelMindError(error, 'plan')
  }
}

/** 把错误转成可展示的文本(带可重试提示)。 */
export function describeError(error: unknown): string {
  if (error instanceof TravelMindApiError) {
    const suffix = error.retryable ? '(可重试)' : ''
    return `${error.message}${suffix}`
  }
  if (error instanceof Error) {
    return error.message
  }
  return '未知错误'
}
