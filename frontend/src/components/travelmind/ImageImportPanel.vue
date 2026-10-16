<template>
  <div class="image-import-panel">
    <a-alert
      class="panel-block"
      type="info"
      show-icon
      message="上传攻略截图,自动识别其中的地点并生成行程"
      description="支持 PNG / JPEG / WebP,单张不超过 10MiB。识别需要调用视觉模型并逐个查询高德 POI,通常 20–60 秒;识别结果需要你确认后才会写入行程。"
    />

    <a-upload-dragger
      v-if="!file"
      name="file"
      :multiple="false"
      :show-upload-list="false"
      accept="image/png,image/jpeg,image/webp"
      :before-upload="handleBeforeUpload"
    >
      <p class="ant-upload-drag-icon">📷</p>
      <p class="ant-upload-text">点击或拖拽攻略截图到此处</p>
      <p class="ant-upload-hint">图片仅用于识别,不会以文件形式长期保存</p>
    </a-upload-dragger>

    <div v-else class="preview-block">
      <img :src="previewUrl" alt="攻略截图预览" class="preview-image" />
      <a-space class="preview-actions">
        <a-input
          v-model:value="cityHint"
          placeholder="城市提示(可选),例如:北京"
          style="width: 220px"
        />
        <a-button type="primary" :loading="importing" @click="runImport">
          🔍 识别截图
        </a-button>
        <a-button @click="resetUpload" :disabled="importing">重新选择</a-button>
      </a-space>
      <p v-if="importing" class="hint-text">
        🔎 正在识别…已等待 {{ elapsedSeconds }} 秒。截图中的地点越多耗时越长,请保持页面打开。
      </p>
    </div>

    <a-alert
      v-if="importError"
      class="panel-block"
      type="error"
      show-icon
      :message="importError"
    />

    <template v-if="importResult">
      <a-alert
        v-if="importResult.source === 'mock'"
        class="panel-block"
        type="warning"
        show-icon
        message="当前为演示模式(mock 数据)"
        description="识别结果来自内置演示数据,不代表真实 POI,仅用于流程验证。"
      />

      <a-alert
        v-for="(warning, index) in importResult.warnings"
        :key="index"
        class="panel-block"
        type="warning"
        show-icon
        :message="warning"
      />

      <a-divider orientation="left">
        识别结果({{ importResult.candidates.length }} 个候选)
        <template v-if="detectedCityText"> · {{ detectedCityText }}</template>
      </a-divider>

      <PoiConfirmationList
        v-model="confirmedAttractions"
        :candidates="importResult.candidates"
      />

      <a-divider orientation="left">行程基本信息</a-divider>

      <a-form layout="vertical">
        <a-row :gutter="16">
          <a-col :span="8">
            <a-form-item label="目的地城市" required>
              <a-input v-model:value="tripRequest.city" placeholder="例如:北京" />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="开始日期" required>
              <a-date-picker
                v-model:value="startDate"
                style="width: 100%"
                value-format="YYYY-MM-DD"
              />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="结束日期" required>
              <a-date-picker
                v-model:value="endDate"
                style="width: 100%"
                value-format="YYYY-MM-DD"
              />
            </a-form-item>
          </a-col>
        </a-row>
        <a-row :gutter="16">
          <a-col :span="8">
            <a-form-item label="交通方式">
              <a-select v-model:value="tripRequest.transportation">
                <a-select-option value="公共交通">🚇 公共交通</a-select-option>
                <a-select-option value="自驾">🚗 自驾</a-select-option>
                <a-select-option value="步行">🚶 步行</a-select-option>
                <a-select-option value="混合">🔀 混合</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="住宿偏好">
              <a-select v-model:value="tripRequest.accommodation">
                <a-select-option value="经济型酒店">💰 经济型酒店</a-select-option>
                <a-select-option value="舒适型酒店">🏨 舒适型酒店</a-select-option>
                <a-select-option value="豪华酒店">⭐ 豪华酒店</a-select-option>
                <a-select-option value="民宿">🏡 民宿</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="额外要求">
              <a-input v-model:value="additionalPreferences" placeholder="例如:带上老人,不要太赶" />
            </a-form-item>
          </a-col>
        </a-row>
      </a-form>

      <a-space>
        <a-button
          type="primary"
          size="large"
          :loading="generating"
          :disabled="!confirmedAttractions.length"
          @click="generatePlan"
        >
          🚀 生成行程(已选 {{ confirmedAttractions.length }} 个地点)
        </a-button>
      </a-space>
      <p v-if="!confirmedAttractions.length" class="hint-text">
        请至少勾选一个已匹配的地点后再生成行程。
      </p>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import PoiConfirmationList from './PoiConfirmationList.vue'
import { describeError, importGuideImage, planFromImport } from '@/services/travelmind'
import type { ConfirmedAttraction, ImageImportResult } from '@/types/travelmind'

const router = useRouter()

const MAX_IMAGE_MB = 10
const ALLOWED_TYPES = ['image/png', 'image/jpeg', 'image/webp']

const file = ref<File | null>(null)
const previewUrl = ref('')
const cityHint = ref('')
const importing = ref(false)
const generating = ref(false)
const elapsedSeconds = ref(0)
let elapsedTimer: ReturnType<typeof setInterval> | null = null
const importError = ref('')
const importResult = ref<ImageImportResult | null>(null)
const confirmedAttractions = ref<ConfirmedAttraction[]>([])

const startDate = ref<string | null>(null)
const endDate = ref<string | null>(null)
const additionalPreferences = ref('')

const tripRequest = reactive({
  city: '',
  transportation: '公共交通',
  accommodation: '经济型酒店',
})

const detectedCityText = computed(() =>
  importResult.value?.detected_city
    ? `识别城市:${importResult.value.detected_city}`
    : ''
)

watch(importResult, (value) => {
  if (value?.detected_city && !tripRequest.city) {
    tripRequest.city = value.detected_city
    cityHint.value = value.detected_city
  }
})

onUnmounted(() => {
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
  }
  stopElapsedTimer()
})

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

function handleBeforeUpload(uploadFile: File): boolean {
  const error = validateFile(uploadFile)
  if (error) {
    message.error(error)
    return false
  }
  setFile(uploadFile)
  return false // 阻止 a-upload 自动上传,改用自有接口
}

function validateFile(candidate: File): string {
  if (candidate.size > MAX_IMAGE_MB * 1024 * 1024) {
    return `图片体积超过 ${MAX_IMAGE_MB}MiB 上限`
  }
  if (candidate.type && !ALLOWED_TYPES.includes(candidate.type)) {
    return '仅支持 PNG / JPEG / WebP 图片'
  }
  return ''
}

function setFile(value: File): void {
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
  }
  file.value = value
  previewUrl.value = URL.createObjectURL(value)
  importResult.value = null
  importError.value = ''
  confirmedAttractions.value = []
}

function resetUpload(): void {
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
  }
  file.value = null
  previewUrl.value = ''
  importResult.value = null
  importError.value = ''
  confirmedAttractions.value = []
}

async function runImport(): Promise<void> {
  if (!file.value || importing.value) return
  importing.value = true
  importError.value = ''
  startElapsedTimer()
  try {
    const result = await importGuideImage(file.value, cityHint.value || undefined)
    importResult.value = result
    confirmedAttractions.value = []
    if (!result.candidates.length) {
      message.warning('没有识别到地点,请更换更清晰的截图')
    }
  } catch (error) {
    importError.value = describeError(error)
    message.error(importError.value)
  } finally {
    stopElapsedTimer()
    importing.value = false
  }
}

async function generatePlan(): Promise<void> {
  if (generating.value) return
  if (!tripRequest.city) {
    message.error('请填写目的地城市')
    return
  }
  if (!startDate.value || !endDate.value) {
    message.error('请选择开始与结束日期')
    return
  }
  if (endDate.value < startDate.value) {
    message.error('结束日期不能早于开始日期')
    return
  }

  generating.value = true
  try {
    const response = await planFromImport({
      request: {
        city: tripRequest.city,
        start_date: startDate.value,
        end_date: endDate.value,
        transportation: tripRequest.transportation,
        accommodation: tripRequest.accommodation,
        free_text_input: additionalPreferences.value,
      },
      confirmed_attractions: confirmedAttractions.value,
      additional_preferences: additionalPreferences.value,
    })

    sessionStorage.setItem('tripPlan', JSON.stringify(response.trip_plan))

    if (response.unplaced_attractions.length) {
      const names = response.unplaced_attractions.map((item) => item.name).join('、')
      message.warning(`以下地点未能排入行程:${names}`, 5)
    }
    for (const warning of response.warnings) {
      message.warning(warning, 5)
    }
    message.success('行程已生成!')
    router.push('/result')
  } catch (error) {
    message.error(describeError(error))
  } finally {
    generating.value = false
  }
}
</script>

<style scoped>
.panel-block {
  margin-bottom: 16px;
}

.preview-block {
  display: flex;
  flex-direction: column;
  gap: 12px;
  align-items: center;
}

.preview-image {
  max-width: 100%;
  max-height: 260px;
  border-radius: 12px;
  border: 1px solid #f0f0f0;
}

.preview-actions {
  width: 100%;
  justify-content: center;
}

.hint-text {
  margin-top: 8px;
  color: #8c8c8c;
  font-size: 13px;
}
</style>
