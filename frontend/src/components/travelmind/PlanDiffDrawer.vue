<template>
  <a-drawer
    :open="open"
    title="📋 候选方案预览(确认后才会应用)"
    width="560"
    :body-style="{ paddingBottom: '80px' }"
    @close="handleCancel"
  >
    <a-spin v-if="loading" tip="正在生成候选方案..." />

    <template v-else-if="preview">
      <a-alert
        v-if="staleNotice"
        class="drawer-block"
        type="error"
        show-icon
        message="行程已发生变化"
        :description="staleNotice"
      />

      <a-alert
        v-else
        class="drawer-block"
        type="info"
        show-icon
        message="以下改动尚未生效"
        description="确认后才会写入当前行程;不确认则保持原样。系统不会自动下单或提交预约。"
      />

      <a-alert
        v-if="preview.warning"
        class="drawer-block"
        type="warning"
        show-icon
        :message="preview.warning"
      />

      <div class="summary">
        <div class="summary-item">
          <div class="summary-value">{{ preview.changes.length }}</div>
          <div class="summary-label">项改动</div>
        </div>
        <div class="summary-item">
          <div class="summary-value">{{ preview.unresolved_issues.length }}</div>
          <div class="summary-label">项未解决</div>
        </div>
        <div class="summary-item">
          <div class="summary-value">{{ budgetDeltaText }}</div>
          <div class="summary-label">预算变化</div>
        </div>
        <div class="summary-item" v-if="preview.report">
          <div class="summary-value">{{ preview.report.score ?? '—' }}</div>
          <div class="summary-label">复检评分</div>
        </div>
      </div>

      <a-divider orientation="left">改动明细</a-divider>
      <a-empty v-if="!preview.changes.length" description="没有产生任何改动" />
      <div v-else class="change-list">
        <div v-for="(change, index) in preview.changes" :key="index" class="change-item">
          <a-tag :color="changeColor(change.change_type)">
            {{ changeLabel(change.change_type) }}
          </a-tag>
          <div class="change-body">
            <div class="change-title">
              {{ change.attraction_name || '行程调整' }}
              <span v-if="change.day_index !== null && change.day_index !== undefined" class="change-day">
                第{{ change.day_index + 1 }}天
              </span>
            </div>
            <div v-if="change.before || change.after" class="change-diff">
              <span v-if="change.before" class="before">{{ change.before }}</span>
              <span v-if="change.before && change.after" class="arrow">→</span>
              <span v-if="change.after" class="after">{{ change.after }}</span>
            </div>
            <div v-if="change.reason" class="change-reason">💡 {{ change.reason }}</div>
          </div>
        </div>
      </div>

      <template v-if="preview.unresolved_issues.length">
        <a-divider orientation="left">未能自动解决的问题</a-divider>
        <RiskIssueList :issues="preview.unresolved_issues" />
      </template>
    </template>

    <template #footer>
      <a-space>
        <a-button @click="handleCancel" :disabled="applying">取消</a-button>
        <a-button
          type="primary"
          :loading="applying"
          :disabled="!preview || Boolean(staleNotice)"
          @click="emit('confirm')"
        >
          确认并应用到行程
        </a-button>
      </a-space>
    </template>
  </a-drawer>
</template>

<script setup lang="ts">
import RiskIssueList from './RiskIssueList.vue'
import type { PlanChangeType, PlanPreview } from '@/types/travelmind'

const props = withDefaults(
  defineProps<{
    open: boolean
    preview?: PlanPreview | null
    loading?: boolean
    applying?: boolean
    staleNotice?: string
  }>(),
  { preview: null, loading: false, applying: false, staleNotice: '' }
)

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'confirm'): void
  (e: 'cancel'): void
}>()

const CHANGE_LABELS: Record<PlanChangeType, string> = {
  move: '移动',
  replace: '替换',
  remove: '移除',
  add: '新增',
  time_update: '时间调整',
  budget_update: '预算调整',
}

const CHANGE_COLORS: Record<PlanChangeType, string> = {
  move: 'blue',
  replace: 'purple',
  remove: 'red',
  add: 'green',
  time_update: 'cyan',
  budget_update: 'gold',
}

const changeLabel = (type: PlanChangeType): string => CHANGE_LABELS[type] ?? type
const changeColor = (type: PlanChangeType): string => CHANGE_COLORS[type] ?? 'default'

const budgetDeltaText = (): string => {
  const delta = props.preview?.budget_delta
  if (delta === null || delta === undefined) return '—'
  if (delta === 0) return '无变化'
  return delta > 0 ? `+¥${delta}` : `-¥${Math.abs(delta)}`
}

function handleCancel(): void {
  if (props.applying) return
  emit('update:open', false)
  emit('cancel')
}
</script>

<style scoped>
.drawer-block {
  margin-bottom: 16px;
}

.summary {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.summary-item {
  flex: 1 1 90px;
  text-align: center;
  padding: 12px;
  border-radius: 10px;
  background: #f5f7fa;
}

.summary-value {
  font-size: 22px;
  font-weight: 700;
  color: #1677ff;
}

.summary-label {
  font-size: 12px;
  color: #8c8c8c;
  margin-top: 4px;
}

.change-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.change-item {
  display: flex;
  gap: 10px;
  padding: 12px;
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  background: #fafafa;
}

.change-title {
  font-weight: 600;
  color: #262626;
}

.change-day {
  margin-left: 8px;
  font-size: 12px;
  color: #8c8c8c;
  font-weight: 400;
}

.change-diff {
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.6;
}

.change-diff .before {
  color: #8c8c8c;
  text-decoration: line-through;
}

.change-diff .arrow {
  margin: 0 8px;
  color: #1677ff;
}

.change-diff .after {
  color: #0958d9;
  font-weight: 500;
}

.change-reason {
  margin-top: 6px;
  font-size: 13px;
  color: #8c8c8c;
  line-height: 1.6;
}
</style>
