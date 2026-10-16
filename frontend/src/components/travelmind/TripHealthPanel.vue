<template>
  <div class="health-panel">
    <div class="panel-actions">
      <a-space wrap>
        <a-button
          type="primary"
          :loading="checking"
          :disabled="disabled"
          @click="runHealthCheck"
        >
          {{ report ? '🔁 重新体检' : '🩺 开始 AI 行程体检' }}
        </a-button>
        <a-button
          :loading="repairing"
          :disabled="disabled || !report || !autoFixableCount"
          @click="requestRepair"
        >
          🛠️ 生成智能修复方案
        </a-button>
        <a-checkbox v-model:checked="allowRemove" :disabled="disabled">
          允许删除景点
        </a-checkbox>
      </a-space>
    </div>

    <a-alert
      v-if="errorText"
      class="panel-alert"
      type="error"
      show-icon
      :message="errorText"
    />

    <template v-if="checking || repairing">
      <a-spin class="panel-loading" :tip="loadingTip" />
      <p class="panel-loading-hint">
        ⏳ 已等待 {{ elapsedSeconds }} 秒。体检需要逐个景点核对营业时间、
        逐对相邻景点核对交通耗时,首次调用高德服务约需 15 秒预热,请保持页面打开。
      </p>
    </template>

    <template v-else-if="report">
      <div class="score-row" :class="statusClass">
        <div class="score-value">
          <template v-if="report.score !== null">{{ report.score }}</template>
          <template v-else>—</template>
        </div>
        <div class="score-detail">
          <div class="score-status">{{ statusLabel }}</div>
          <div class="score-meta">
            共 {{ report.issues.length }} 项风险,其中
            {{ autoFixableCount }} 项可智能修复<br />
            规则覆盖 {{ report.checked_rule_count }}/{{ report.total_rule_count }},
            事实覆盖 {{ report.checked_fact_count }}/{{ report.total_fact_count }}
            <template v-if="report.coverage !== null">
              ({{ Math.round(report.coverage * 100) }}%)
            </template>
          </div>
        </div>
      </div>

      <a-alert
        v-if="report.status !== 'complete'"
        class="panel-alert"
        type="warning"
        show-icon
        :message="
          report.disclaimer ||
          '部分营业时间/交通耗时/天气无法核验,结论可能不完整,请以现场信息为准。'
        "
      />

      <RiskIssueList
        class="panel-issues"
        :issues="report.issues"
        empty-text="未发现明显风险项"
        @locate="emit('locate', $event)"
      />
    </template>

    <a-empty
      v-else
      class="panel-empty"
      description="点击上方按钮,AI 会检查时间冲突、闭馆、预算、天气与行程节奏等风险"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import RiskIssueList from './RiskIssueList.vue'
import { checkTripHealth, describeError, repairPlanPreview, TravelMindApiError } from '@/services/travelmind'
import type { TripPlan } from '@/types'
import type { HealthIssue, HealthReport, PlanPreview } from '@/types/travelmind'

const props = withDefaults(
  defineProps<{
    plan: TripPlan
    disabled?: boolean
  }>(),
  { disabled: false }
)

const emit = defineEmits<{
  (e: 'preview', preview: PlanPreview): void
  (e: 'health', report: HealthReport): void
  (e: 'locate', issue: HealthIssue): void
  (e: 'stale'): void
}>()

const checking = ref(false)
const repairing = ref(false)
const elapsedSeconds = ref(0)
let elapsedTimer: ReturnType<typeof setInterval> | null = null
const report = ref<HealthReport | null>(null)
const errorText = ref('')
const allowRemove = ref(false)

const autoFixableCount = computed(
  () => report.value?.issues.filter((issue) => issue.can_auto_fix).length ?? 0
)

const loadingTip = computed(() =>
  repairing.value ? '正在生成修复方案...' : '正在体检...'
)

function startElapsedTimer(): void {
  stopElapsedTimer()
  elapsedSeconds.value = 0
  elapsedTimer = setInterval(() => {
    elapsedSeconds.value += 1
  }, 1000)
}

function stopElapsedTimer(): void {
  if (elapsedTimer !== null) {
    clearInterval(elapsedTimer)
    elapsedTimer = null
  }
}

onUnmounted(stopElapsedTimer)

const statusLabel = computed(() => {
  switch (report.value?.status) {
    case 'complete':
      return '数据完整,结论可信'
    case 'partial':
      return '部分数据缺失,结论仅供参考'
    case 'insufficient_data':
      return '数据不足,无法给出评分'
    default:
      return ''
  }
})

const statusClass = computed(() => {
  const score = report.value?.score
  if (score === null || score === undefined) return 'status-unknown'
  if (score >= 85) return 'status-good'
  if (score >= 60) return 'status-warn'
  return 'status-bad'
})

// 行程变化后旧报告即失效,避免把过期结论展示给用户
watch(
  () => props.plan,
  () => {
    report.value = null
    errorText.value = ''
  }
)

function handleError(error: unknown): void {
  if (error instanceof TravelMindApiError && error.code === 'STALE_PLAN_REVISION') {
    emit('stale')
  }
  errorText.value = describeError(error)
  message.error(errorText.value)
}

async function runHealthCheck(): Promise<void> {
  if (checking.value || repairing.value) return
  checking.value = true
  errorText.value = ''
  startElapsedTimer()
  try {
    const result = await checkTripHealth(props.plan)
    report.value = result
    emit('health', result)
  } catch (error) {
    handleError(error)
  } finally {
    stopElapsedTimer()
    checking.value = false
  }
}

async function requestRepair(): Promise<void> {
  if (checking.value || repairing.value) return
  repairing.value = true
  errorText.value = ''
  startElapsedTimer()
  try {
    const preview = await repairPlanPreview({
      trip_plan: props.plan,
      health_report: report.value,
      base_revision: props.plan.revision ?? 0,
      preferences: {
        preserve_confirmed_bookings: true,
        allow_remove_attractions: allowRemove.value,
      },
    })
    emit('preview', preview)
  } catch (error) {
    handleError(error)
  } finally {
    stopElapsedTimer()
    repairing.value = false
  }
}
</script>

<style scoped>
.panel-actions {
  margin-bottom: 16px;
}

.panel-alert {
  margin-bottom: 16px;
}

.panel-loading {
  display: block;
  text-align: center;
  padding: 32px 0;
}

.panel-loading-hint {
  margin: -16px 0 16px;
  text-align: center;
  font-size: 13px;
  color: #8c8c8c;
  line-height: 1.7;
}

.panel-empty {
  padding: 24px 0;
}

.score-row {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 16px 20px;
  border-radius: 12px;
  margin-bottom: 16px;
  color: #fff;
  background: linear-gradient(135deg, #8c8c8c 0%, #bfbfbf 100%);
}

.score-row.status-good {
  background: linear-gradient(135deg, #52c41a 0%, #95de64 100%);
}

.score-row.status-warn {
  background: linear-gradient(135deg, #fa8c16 0%, #ffc069 100%);
}

.score-row.status-bad {
  background: linear-gradient(135deg, #cf1322 0%, #ff7875 100%);
}

.score-value {
  font-size: 48px;
  font-weight: 800;
  line-height: 1;
  min-width: 96px;
  text-align: center;
}

.score-status {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 6px;
}

.score-meta {
  font-size: 13px;
  opacity: 0.92;
  line-height: 1.6;
}

.panel-issues {
  margin-top: 8px;
}
</style>
