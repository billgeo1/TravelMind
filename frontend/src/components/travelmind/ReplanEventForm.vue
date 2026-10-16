<template>
  <a-form layout="vertical">
    <a-form-item label="突发情况类型">
      <a-select v-model:value="eventType" :disabled="disabled">
        <a-select-option value="rain">🌧️ 天气突变(降雨/高温等)</a-select-option>
        <a-select-option value="attraction_closed">🚧 景点临时闭馆/无法前往</a-select-option>
        <a-select-option value="delay">⏰ 行程延误(交通/排队)</a-select-option>
        <a-select-option value="fatigue">😮‍💨 体力不支,需要减少强度</a-select-option>
        <a-select-option value="other">❓ 其他情况</a-select-option>
      </a-select>
    </a-form-item>

    <a-form-item label="受影响的天">
      <a-select v-model:value="dayIndex" :disabled="disabled">
        <a-select-option v-for="(day, index) in plan.days" :key="index" :value="index">
          第{{ day.day_index + 1 }}天({{ day.date }})
        </a-select-option>
      </a-select>
    </a-form-item>

    <a-form-item v-if="eventType === 'attraction_closed'" label="受影响的景点">
      <a-select
        v-model:value="attractionUid"
        allow-clear
        placeholder="选择无法前往的景点"
        :disabled="disabled"
      >
        <a-select-option
          v-for="attraction in dayAttractions"
          :key="attraction.uid || attraction.name"
          :value="attraction.uid || attraction.name"
        >
          {{ attraction.name }}
          <template v-if="attraction.locked">(🔒 已锁定)</template>
        </a-select-option>
      </a-select>
    </a-form-item>

    <a-form-item v-if="eventType === 'delay'" label="预计延误时长(分钟)">
      <a-input-number
        v-model:value="delayMinutes"
        :min="0"
        :max="1440"
        :step="15"
        style="width: 100%"
        :disabled="disabled"
      />
    </a-form-item>

    <a-form-item label="补充说明(可选)">
      <a-textarea
        v-model:value="description"
        :rows="2"
        :maxlength="200"
        show-count
        placeholder="例如:下午三点后开始下暴雨,带着老人同行"
        :disabled="disabled"
      />
    </a-form-item>

    <a-form-item label="最多可接受额外预算(元,可选)">
      <a-input-number
        v-model:value="maxExtraBudget"
        :min="0"
        :step="50"
        style="width: 100%"
        placeholder="留空表示不限制"
        :disabled="disabled"
      />
    </a-form-item>

    <a-alert
      class="replan-hint"
      type="info"
      show-icon
      message="生成的是候选方案,确认后才会替换当前行程,不会自动下单。"
    />

    <a-space class="replan-actions">
      <a-button
        type="primary"
        :loading="loading"
        :disabled="disabled || !plan.days.length"
        @click="submit"
      >
        🔄 生成重规划方案
      </a-button>
    </a-space>
  </a-form>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { describeError, replanPlanPreview, TravelMindApiError } from '@/services/travelmind'
import type { TripPlan } from '@/types'
import type { PlanPreview, ReplanEventType } from '@/types/travelmind'

const props = withDefaults(
  defineProps<{
    plan: TripPlan
    disabled?: boolean
  }>(),
  { disabled: false }
)

const emit = defineEmits<{
  (e: 'preview', preview: PlanPreview): void
  (e: 'stale'): void
}>()

const eventType = ref<ReplanEventType>('rain')
const dayIndex = ref<number>(0)
const attractionUid = ref<string | undefined>(undefined)
const delayMinutes = ref<number>(60)
const description = ref('')
const maxExtraBudget = ref<number | null>(null)
const loading = ref(false)

const dayAttractions = computed(
  () => props.plan.days[dayIndex.value]?.attractions ?? []
)

watch(dayIndex, () => {
  attractionUid.value = undefined
})

watch(eventType, () => {
  attractionUid.value = undefined
})

async function submit(): Promise<void> {
  if (loading.value) return
  loading.value = true
  try {
    const lockedUids = props.plan.days
      .flatMap((day) => day.attractions)
      .filter((attraction) => attraction.locked || attraction.completed)
      .map((attraction) => attraction.uid)
      .filter((uid): uid is string => Boolean(uid))

    const preview = await replanPlanPreview({
      trip_plan: props.plan,
      base_revision: props.plan.revision ?? 0,
      event: {
        type: eventType.value,
        affected_day_index: dayIndex.value,
        affected_attraction_uid: attractionUid.value ?? null,
        delay_minutes: eventType.value === 'delay' ? delayMinutes.value : null,
        description: description.value || null,
        source: 'user_reported',
      },
      locked_attraction_uids: lockedUids,
      max_extra_budget_yuan: maxExtraBudget.value,
    })
    emit('preview', preview)
  } catch (error) {
    if (error instanceof TravelMindApiError && error.code === 'STALE_PLAN_REVISION') {
      emit('stale')
    }
    message.error(describeError(error))
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.replan-hint {
  margin-bottom: 16px;
}

.replan-actions {
  width: 100%;
}
</style>
