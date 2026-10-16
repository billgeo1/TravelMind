<template>
  <div class="poi-list">
    <a-alert
      class="poi-hint"
      type="info"
      show-icon
      message="请核对识别结果后再生成行程"
      description="只有你勾选的地点会被写入行程;未匹配到坐标的地点不会被自动落点。"
    />

    <div v-for="candidate in candidates" :key="candidate.candidate_id" class="poi-item">
      <a-checkbox
        :checked="isChecked(candidate)"
        :disabled="candidate.match_status === 'not_found'"
        @change="(event: any) => toggle(candidate, event.target.checked)"
      />

      <div class="poi-body">
        <div class="poi-head">
          <span class="poi-name">{{ candidate.raw_name }}</span>
          <a-tag :color="statusColor(candidate.match_status)">
            {{ statusLabel(candidate.match_status) }}
          </a-tag>
          <span v-if="candidate.confidence !== null && candidate.confidence !== undefined" class="poi-confidence">
            置信度 {{ Math.round((candidate.confidence ?? 0) * 100) }}%
          </span>
        </div>

        <div v-if="candidate.match_status === 'not_found'" class="poi-warning">
          ⚠️ 未匹配到可用 POI,不会写入行程
        </div>

        <template v-else>
          <a-select
            v-if="options(candidate).length > 1"
            :value="chosenIndex(candidate)"
            size="small"
            class="poi-select"
            @change="(value: any) => chooseOption(candidate, Number(value))"
          >
            <a-select-option
              v-for="(option, index) in options(candidate)"
              :key="index"
              :value="index"
            >
              {{ option.name }}<template v-if="option.city">({{ option.city }})</template>
              <template v-if="option.address"> — {{ option.address }}</template>
            </a-select-option>
          </a-select>
          <div v-else class="poi-address">{{ options(candidate)[0]?.address || '暂无地址' }}</div>
        </template>
      </div>
    </div>

    <div v-if="!candidates.length">
      <a-empty description="没有识别到候选地点" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive } from 'vue'
import type { ConfirmedAttraction, ImportCandidate, MatchStatus } from '@/types/travelmind'

const props = defineProps<{
  candidates: ImportCandidate[]
  modelValue: ConfirmedAttraction[]
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: ConfirmedAttraction[]): void
}>()

interface PoiOption {
  poi_id?: string | null
  name: string
  address?: string | null
  city?: string | null
  location?: { longitude: number; latitude: number } | null
}

// 每个候选当前选择的 POI 下标(0 为主匹配,其余为歧义备选)
const chosen = reactive<Record<string, number>>({})

const STATUS_LABELS: Record<MatchStatus, string> = {
  matched: '已匹配',
  ambiguous: '同名歧义',
  not_found: '未匹配',
}

const STATUS_COLORS: Record<MatchStatus, string> = {
  matched: 'green',
  ambiguous: 'orange',
  not_found: 'red',
}

const statusLabel = (status: MatchStatus): string => STATUS_LABELS[status] ?? status
const statusColor = (status: MatchStatus): string => STATUS_COLORS[status] ?? 'default'

function options(candidate: ImportCandidate): PoiOption[] {
  const primary: PoiOption = {
    poi_id: candidate.poi_id,
    name: candidate.canonical_name || candidate.raw_name,
    address: candidate.address,
    city: candidate.city,
    location: candidate.location ?? null,
  }
  const alternatives = candidate.alternatives.map((item) => ({
    poi_id: item?.poi_id ?? null,
    name: item?.name ?? candidate.raw_name,
    address: item?.address ?? null,
    city: item?.city ?? null,
    location: item?.location ?? null,
  })) as PoiOption[]
  return [primary, ...alternatives]
}

function chosenIndex(candidate: ImportCandidate): number {
  return chosen[candidate.candidate_id] ?? 0
}

function isChecked(candidate: ImportCandidate): boolean {
  return props.modelValue.some((item) => item.candidate_id === candidate.candidate_id)
}

function toConfirmed(candidate: ImportCandidate, index: number): ConfirmedAttraction {
  const option = options(candidate)[index] ?? options(candidate)[0]
  return {
    candidate_id: candidate.candidate_id,
    poi_id: option.poi_id ?? null,
    name: option.name,
    address: option.address ?? null,
    location: option.location ?? null,
    city: option.city ?? null,
  }
}

function emitSelection(candidate: ImportCandidate, checked: boolean, index: number): void {
  const others = props.modelValue.filter(
    (item) => item.candidate_id !== candidate.candidate_id
  )
  const next = checked ? [...others, toConfirmed(candidate, index)] : others
  emit('update:modelValue', next)
}

function toggle(candidate: ImportCandidate, checked: boolean): void {
  emitSelection(candidate, checked, chosenIndex(candidate))
}

function chooseOption(candidate: ImportCandidate, index: number): void {
  chosen[candidate.candidate_id] = index
  if (isChecked(candidate)) {
    emitSelection(candidate, true, index)
  }
}
</script>

<style scoped>
.poi-hint {
  margin-bottom: 16px;
}

.poi-item {
  display: flex;
  gap: 12px;
  padding: 12px;
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  margin-bottom: 12px;
  background: #fff;
}

.poi-body {
  flex: 1;
  min-width: 0;
}

.poi-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.poi-name {
  font-weight: 600;
  color: #262626;
}

.poi-confidence {
  font-size: 12px;
  color: #8c8c8c;
}

.poi-address {
  margin-top: 6px;
  font-size: 13px;
  color: #8c8c8c;
}

.poi-select {
  margin-top: 8px;
  width: 100%;
}

.poi-warning {
  margin-top: 6px;
  font-size: 13px;
  color: #cf1322;
}
</style>
