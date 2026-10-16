<template>
  <div class="risk-issue-list">
    <a-empty v-if="!issues.length" :description="emptyText" :image="simpleImage" />

    <div v-else class="issue-items">
      <div
        v-for="issue in issues"
        :key="issue.issue_id"
        class="issue-item"
        :class="`severity-${issue.severity}`"
      >
        <div class="issue-head">
          <a-tag :color="severityColor(issue.severity)">
            {{ severityLabel(issue.severity) }}
          </a-tag>
          <span class="issue-title">{{ issue.title }}</span>
          <a-tag v-if="issue.can_auto_fix" color="processing" class="auto-tag">可智能修复</a-tag>
          <span class="issue-code">{{ issue.code }}</span>
        </div>

        <p class="issue-desc">{{ issue.description }}</p>

        <p v-if="issue.affected_day_indices.length" class="issue-meta">
          📅 涉及天数:{{ dayLabels(issue) }}
        </p>

        <p v-if="issue.suggestion" class="issue-suggestion">
          💡 建议:{{ issue.suggestion }}
        </p>

        <p v-if="evidenceText(issue)" class="issue-evidence">
          🔎 依据:{{ evidenceText(issue) }}
        </p>

        <div v-if="issue.affected_day_indices.length" class="issue-actions">
          <a-button type="link" size="small" @click="emit('locate', issue)">
            📍 定位节点
          </a-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { h } from 'vue'
import { Empty } from 'ant-design-vue'
import type { HealthIssue, Severity } from '@/types/travelmind'

withDefaults(
  defineProps<{
    issues: HealthIssue[]
    emptyText?: string
  }>(),
  { emptyText: '暂无风险项' }
)

const emit = defineEmits<{
  (e: 'locate', issue: HealthIssue): void
}>()

// a-empty 的简单占位图,避免额外引入图标依赖
const simpleImage = h(Empty.PRESENTED_IMAGE_SIMPLE)

const SEVERITY_LABELS: Record<Severity, string> = {
  critical: '严重',
  high: '高',
  medium: '中',
  low: '低',
  info: '提示',
}

const SEVERITY_COLORS: Record<Severity, string> = {
  critical: 'red',
  high: 'volcano',
  medium: 'orange',
  low: 'blue',
  info: 'default',
}

const severityLabel = (severity: Severity): string =>
  SEVERITY_LABELS[severity] ?? severity

const severityColor = (severity: Severity): string =>
  SEVERITY_COLORS[severity] ?? 'default'

const dayLabels = (issue: HealthIssue): string =>
  issue.affected_day_indices.map((index) => `第${index + 1}天`).join('、')

const evidenceText = (issue: HealthIssue): string => {
  const parts = issue.evidence
    .map((item) => [item.source, item.detail].filter(Boolean).join(':'))
    .filter((text) => Boolean(text))
  return parts.join(';')
}
</script>

<style scoped>
.issue-items {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.issue-item {
  border: 1px solid #f0f0f0;
  border-left-width: 4px;
  border-radius: 8px;
  padding: 12px 16px;
  background: #fafafa;
}

.issue-item.severity-critical {
  border-left-color: #cf1322;
  background: #fff1f0;
}

.issue-item.severity-high {
  border-left-color: #fa541c;
  background: #fff2e8;
}

.issue-item.severity-medium {
  border-left-color: #fa8c16;
  background: #fff7e6;
}

.issue-item.severity-low {
  border-left-color: #1677ff;
  background: #f0f5ff;
}

.issue-item.severity-info {
  border-left-color: #d9d9d9;
}

.issue-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.issue-title {
  font-weight: 600;
  color: #262626;
}

.auto-tag {
  margin-left: 4px;
}

.issue-code {
  margin-left: auto;
  font-size: 12px;
  color: #bfbfbf;
  font-family: monospace;
}

.issue-desc {
  margin: 8px 0 0;
  color: #595959;
  line-height: 1.6;
}

.issue-meta,
.issue-suggestion,
.issue-evidence {
  margin: 6px 0 0;
  font-size: 13px;
  color: #8c8c8c;
  line-height: 1.6;
}

.issue-suggestion {
  color: #0958d9;
}

.issue-actions {
  margin-top: 4px;
}
</style>
