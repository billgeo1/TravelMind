<template>
  <div class="home-container">
    <!-- 背景装饰:天空光晕、航线轨迹与旅行元素 -->
    <div class="bg-decoration" aria-hidden="true">
      <div class="glow glow-1"></div>
      <div class="glow glow-2"></div>
      <div class="glow glow-3"></div>
      <svg class="flight-path" viewBox="0 0 1200 320" preserveAspectRatio="none">
        <path d="M-30 250 C 220 60, 520 320, 780 150 S 1120 20, 1240 100" />
      </svg>
      <span class="sky-icon sky-plane">✈️</span>
      <span class="sky-icon sky-sun">☀️</span>
      <span class="sky-icon sky-palm">🌴</span>
      <span class="sky-icon sky-mountain">⛰️</span>
      <span class="sky-icon sky-camera">📸</span>
      <span class="sky-icon sky-suitcase">🧳</span>
    </div>

    <!-- 页面标题 -->
    <div class="page-header">
      <span class="hero-chip">✈️ AI 智能旅行助手</span>
      <h1 class="page-title">TravelMind</h1>
      <p class="page-subtitle">说清目的地与偏好,自动生成含景点、路线、天气与预算的完整行程</p>
      <div class="hero-features">
        <span class="feature-pill">🗺️ 智能规划</span>
        <span class="feature-pill">🩺 AI 行程体检</span>
        <span class="feature-pill">🚨 突发重规划</span>
        <span class="feature-pill">📸 攻略截图导入</span>
      </div>
    </div>

    <a-card class="form-card" :bordered="false">
      <a-tabs v-model:activeKey="activeTab" size="large" class="mode-tabs">
        <a-tab-pane key="plan" tab="🗺️ 智能行程规划">
      <a-form
        :model="formData"
        layout="vertical"
        @finish="handleSubmit"
      >
        <!-- 第一步:目的地和日期 -->
        <div class="form-section">
          <div class="section-header">
            <span class="section-icon">📍</span>
            <span class="section-title">目的地与日期</span>
          </div>

          <a-row :gutter="24">
            <a-col :span="8">
              <a-form-item name="city" :rules="[{ required: true, message: '请输入目的地城市' }]">
                <template #label>
                  <span class="form-label">目的地城市</span>
                </template>
                <a-input
                  v-model:value="formData.city"
                  placeholder="例如: 北京"
                  size="large"
                  class="custom-input"
                >
                  <template #prefix>
                    <span style="color: #3b82f6;">🏙️</span>
                  </template>
                </a-input>
              </a-form-item>
            </a-col>
            <a-col :span="6">
              <a-form-item name="start_date" :rules="[{ required: true, message: '请选择开始日期' }]">
                <template #label>
                  <span class="form-label">开始日期</span>
                </template>
                <a-date-picker
                  v-model:value="formData.start_date"
                  style="width: 100%"
                  size="large"
                  class="custom-input"
                  placeholder="选择日期"
                />
              </a-form-item>
            </a-col>
            <a-col :span="6">
              <a-form-item name="end_date" :rules="[{ required: true, message: '请选择结束日期' }]">
                <template #label>
                  <span class="form-label">结束日期</span>
                </template>
                <a-date-picker
                  v-model:value="formData.end_date"
                  style="width: 100%"
                  size="large"
                  class="custom-input"
                  placeholder="选择日期"
                />
              </a-form-item>
            </a-col>
            <a-col :span="4">
              <a-form-item>
                <template #label>
                  <span class="form-label">旅行天数</span>
                </template>
                <div class="days-display-compact">
                  <span class="days-value">{{ formData.travel_days }}</span>
                  <span class="days-unit">天</span>
                </div>
              </a-form-item>
            </a-col>
          </a-row>
        </div>

        <!-- 第二步:偏好设置 -->
        <div class="form-section">
          <div class="section-header">
            <span class="section-icon">⚙️</span>
            <span class="section-title">偏好设置</span>
          </div>

          <a-row :gutter="24">
            <a-col :span="8">
              <a-form-item name="transportation">
                <template #label>
                  <span class="form-label">交通方式</span>
                </template>
                <a-select v-model:value="formData.transportation" size="large" class="custom-select">
                  <a-select-option value="公共交通">🚇 公共交通</a-select-option>
                  <a-select-option value="自驾">🚗 自驾</a-select-option>
                  <a-select-option value="步行">🚶 步行</a-select-option>
                  <a-select-option value="混合">🔀 混合</a-select-option>
                </a-select>
              </a-form-item>
            </a-col>
            <a-col :span="8">
              <a-form-item name="accommodation">
                <template #label>
                  <span class="form-label">住宿偏好</span>
                </template>
                <a-select v-model:value="formData.accommodation" size="large" class="custom-select">
                  <a-select-option value="经济型酒店">💰 经济型酒店</a-select-option>
                  <a-select-option value="舒适型酒店">🏨 舒适型酒店</a-select-option>
                  <a-select-option value="豪华酒店">⭐ 豪华酒店</a-select-option>
                  <a-select-option value="民宿">🏡 民宿</a-select-option>
                </a-select>
              </a-form-item>
            </a-col>
            <a-col :span="8">
              <a-form-item name="preferences">
                <template #label>
                  <span class="form-label">旅行偏好</span>
                </template>
                <div class="preference-tags">
                  <a-checkbox-group v-model:value="formData.preferences" class="custom-checkbox-group">
                    <a-checkbox value="历史文化" class="preference-tag">🏛️ 历史文化</a-checkbox>
                    <a-checkbox value="自然风光" class="preference-tag">🏞️ 自然风光</a-checkbox>
                    <a-checkbox value="美食" class="preference-tag">🍜 美食</a-checkbox>
                    <a-checkbox value="购物" class="preference-tag">🛍️ 购物</a-checkbox>
                    <a-checkbox value="艺术" class="preference-tag">🎨 艺术</a-checkbox>
                    <a-checkbox value="休闲" class="preference-tag">☕ 休闲</a-checkbox>
                  </a-checkbox-group>
                </div>
              </a-form-item>
            </a-col>
          </a-row>
        </div>

        <!-- 第三步:额外要求 -->
        <div class="form-section">
          <div class="section-header">
            <span class="section-icon">💬</span>
            <span class="section-title">额外要求</span>
          </div>

          <a-form-item name="free_text_input">
            <a-textarea
              v-model:value="formData.free_text_input"
              placeholder="请输入您的额外要求,例如:想去看升旗、需要无障碍设施、对海鲜过敏等..."
              :rows="3"
              size="large"
              class="custom-textarea"
            />
          </a-form-item>
        </div>

        <!-- 提交按钮 -->
        <a-form-item>
          <a-button
            type="primary"
            html-type="submit"
            :loading="loading"
            size="large"
            block
            class="submit-button"
          >
            <template v-if="!loading">
              <span class="button-icon">🚀</span>
              <span>开始规划我的旅行</span>
            </template>
            <template v-else>
              <span>正在生成中...</span>
            </template>
          </a-button>
        </a-form-item>

        <!-- 加载进度条 -->
        <a-form-item v-if="loading">
          <div class="loading-container">
            <a-progress
              :percent="loadingProgress"
              status="active"
              :stroke-color="{
                '0%': '#3b82f6',
                '100%': '#6366f1',
              }"
              :stroke-width="10"
            />
            <p class="loading-status">
              {{ loadingStatus }}
            </p>
          </div>
        </a-form-item>
      </a-form>
        </a-tab-pane>
        <a-tab-pane key="import" tab="📸 攻略截图生成行程">
          <ImageImportPanel />
        </a-tab-pane>
      </a-tabs>
    </a-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { generateTripPlan } from '@/services/api'
import type { TripFormData } from '@/types'
import type { Dayjs } from 'dayjs'
import ImageImportPanel from '@/components/travelmind/ImageImportPanel.vue'

const router = useRouter()
const loading = ref(false)
const loadingProgress = ref(0)
const loadingStatus = ref('')
const activeTab = ref('plan')

type TripFormState = Omit<TripFormData, 'start_date' | 'end_date'> & {
  start_date: Dayjs | null
  end_date: Dayjs | null
}

const formData = reactive<TripFormState>({
  city: '',
  start_date: null,
  end_date: null,
  travel_days: 1,
  transportation: '公共交通',
  accommodation: '经济型酒店',
  preferences: [],
  free_text_input: ''
})

// 监听日期变化,自动计算旅行天数
watch([() => formData.start_date, () => formData.end_date], ([start, end]) => {
  if (start && end) {
    const days = end.diff(start, 'day') + 1
    if (days > 0 && days <= 30) {
      formData.travel_days = days
    } else if (days > 30) {
      message.warning('旅行天数不能超过30天')
      formData.end_date = null
    } else {
      message.warning('结束日期不能早于开始日期')
      formData.end_date = null
    }
  }
})

const handleSubmit = async () => {
  if (!formData.start_date || !formData.end_date) {
    message.error('请选择日期')
    return
  }

  loading.value = true
  loadingProgress.value = 0
  loadingStatus.value = '正在初始化...'

  // 模拟进度更新
  const progressInterval = setInterval(() => {
    if (loadingProgress.value < 90) {
      loadingProgress.value += 10

      // 更新状态文本
      if (loadingProgress.value <= 30) {
        loadingStatus.value = '🔍 正在搜索景点...'
      } else if (loadingProgress.value <= 50) {
        loadingStatus.value = '🌤️ 正在查询天气...'
      } else if (loadingProgress.value <= 70) {
        loadingStatus.value = '🏨 正在推荐酒店...'
      } else {
        loadingStatus.value = '📋 正在生成行程计划...'
      }
    }
  }, 500)

  try {
    const requestData: TripFormData = {
      city: formData.city,
      start_date: formData.start_date.format('YYYY-MM-DD'),
      end_date: formData.end_date.format('YYYY-MM-DD'),
      travel_days: formData.travel_days,
      transportation: formData.transportation,
      accommodation: formData.accommodation,
      preferences: formData.preferences,
      free_text_input: formData.free_text_input
    }

    const response = await generateTripPlan(requestData)

    clearInterval(progressInterval)
    loadingProgress.value = 100
    loadingStatus.value = '✅ 完成!'

    if (response.success && response.data) {
      // 保存到sessionStorage
      sessionStorage.setItem('tripPlan', JSON.stringify(response.data))

      message.success('旅行计划生成成功!')

      // 短暂延迟后跳转
      setTimeout(() => {
        router.push('/result')
      }, 500)
    } else {
      message.error(response.message || '生成失败')
    }
  } catch (error: any) {
    clearInterval(progressInterval)
    message.error(error.message || '生成旅行计划失败,请稍后重试')
  } finally {
    setTimeout(() => {
      loading.value = false
      loadingProgress.value = 0
      loadingStatus.value = ''
    }, 1000)
  }
}
</script>

<style scoped>
.home-container {
  min-height: 100%;
  background: radial-gradient(circle at 12% 0%, #bae6fd 0%, transparent 45%),
    radial-gradient(circle at 88% 6%, #ddd6fe 0%, transparent 45%),
    linear-gradient(160deg, #0ea5e9 0%, #4f46e5 58%, #7c3aed 100%);
  padding: 56px 20px 72px;
  position: relative;
  overflow: hidden;
}

/* 背景装饰 */
.bg-decoration {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}

.glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(60px);
  opacity: 0.55;
  animation: float 18s infinite ease-in-out;
}

.glow-1 {
  width: 320px;
  height: 320px;
  top: -120px;
  left: -80px;
  background: rgba(56, 189, 248, 0.6);
}

.glow-2 {
  width: 260px;
  height: 260px;
  top: 38%;
  right: -90px;
  background: rgba(244, 114, 182, 0.45);
  animation-delay: 5s;
}

.glow-3 {
  width: 220px;
  height: 220px;
  bottom: -80px;
  left: 26%;
  background: rgba(45, 212, 191, 0.5);
  animation-delay: 9s;
}

/* 航线轨迹 */
.flight-path {
  position: absolute;
  top: 2%;
  left: 0;
  width: 100%;
  height: 320px;
  opacity: 0.45;
}

.flight-path path {
  fill: none;
  stroke: #ffffff;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-dasharray: 10 14;
  animation: dash 26s linear infinite;
}

@keyframes dash {
  to {
    stroke-dashoffset: -480;
  }
}

/* 漂浮的旅行元素 */
.sky-icon {
  position: absolute;
  font-size: 30px;
  opacity: 0.92;
  filter: drop-shadow(0 8px 14px rgba(15, 23, 42, 0.25));
  animation: drift 14s infinite ease-in-out;
}

.sky-plane {
  top: 10%;
  left: 4%;
  font-size: 40px;
}

.sky-sun {
  top: 5%;
  right: 6%;
  font-size: 46px;
  animation-delay: 2s;
}

.sky-palm {
  bottom: 6%;
  left: 3%;
  font-size: 42px;
  animation-delay: 4s;
}

.sky-mountain {
  bottom: 5%;
  right: 5%;
  font-size: 44px;
  animation-delay: 1s;
}

.sky-camera {
  top: 42%;
  left: 7%;
  animation-delay: 6s;
}

.sky-suitcase {
  top: 34%;
  right: 9%;
  animation-delay: 8s;
}

@keyframes float {
  0%, 100% {
    transform: translateY(0) scale(1);
  }
  50% {
    transform: translateY(-28px) scale(1.06);
  }
}

@keyframes drift {
  0%, 100% {
    transform: translateY(0) rotate(-3deg);
  }
  50% {
    transform: translateY(-22px) rotate(3deg);
  }
}

/* 页面标题 */
.page-header {
  text-align: center;
  margin-bottom: 44px;
  animation: fadeInDown 0.8s ease-out;
  position: relative;
  z-index: 1;
}

.hero-chip {
  display: inline-block;
  margin-bottom: 18px;
  padding: 6px 16px;
  border-radius: 999px;
  font-size: 13px;
  letter-spacing: 0.6px;
  color: #ffffff;
  background: rgba(255, 255, 255, 0.18);
  border: 1px solid rgba(255, 255, 255, 0.35);
  backdrop-filter: blur(6px);
}

.page-title {
  font-size: 60px;
  font-weight: 800;
  color: #ffffff;
  margin-bottom: 14px;
  letter-spacing: 1px;
  text-shadow: 0 8px 28px rgba(15, 23, 42, 0.35);
}

.page-subtitle {
  font-size: 17px;
  color: rgba(255, 255, 255, 0.94);
  margin: 0 auto;
  max-width: 620px;
  line-height: 1.7;
  font-weight: 400;
}

.hero-features {
  margin-top: 24px;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 10px;
}

.feature-pill {
  padding: 8px 16px;
  border-radius: 999px;
  font-size: 14px;
  color: #ffffff;
  background: rgba(255, 255, 255, 0.14);
  border: 1px solid rgba(255, 255, 255, 0.28);
  transition: all 0.25s ease;
}

.feature-pill:hover {
  background: rgba(255, 255, 255, 0.26);
  transform: translateY(-2px);
}

/* 表单卡片 */
.form-card {
  max-width: 1180px;
  margin: 0 auto;
  border-radius: 20px;
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.28);
  animation: fadeInUp 0.8s ease-out;
  position: relative;
  z-index: 1;
  backdrop-filter: blur(10px);
  background: rgba(255, 255, 255, 0.98) !important;
  overflow: hidden;
}

/* 卡片顶部的品牌色带 */
.form-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 6px;
  background: linear-gradient(90deg, #38bdf8 0%, #6366f1 55%, #8b5cf6 100%);
}

/* 表单分区 */
.form-section {
  margin-bottom: 32px;
  padding: 24px;
  background: linear-gradient(135deg, #f5f7fa 0%, #ffffff 100%);
  border-radius: 16px;
  border: 1px solid #e8e8e8;
  transition: all 0.3s ease;
}

/* 模式切换标签 */
.mode-tabs :deep(.ant-tabs-nav) {
  padding: 8px 24px 0;
  margin-bottom: 8px;
}

.mode-tabs :deep(.ant-tabs-nav::before) {
  border-bottom-color: var(--tm-line, #e6ebf4);
}

.mode-tabs :deep(.ant-tabs-tab) {
  font-size: 16px;
  font-weight: 600;
  padding: 12px 4px;
}

.mode-tabs :deep(.ant-tabs-tab-active .ant-tabs-tab-btn) {
  color: #4f46e5;
}

.mode-tabs :deep(.ant-tabs-ink-bar) {
  height: 3px;
  border-radius: 3px;
  background: linear-gradient(90deg, #38bdf8 0%, #6366f1 100%);
}

.form-card :deep(.ant-card-body) {
  padding: 16px 32px 32px;
}

.form-section:hover {
  box-shadow: 0 8px 24px rgba(59, 130, 246, 0.16);
  transform: translateY(-2px);
}

.section-header {
  display: flex;
  align-items: center;
  margin-bottom: 20px;
  padding-bottom: 12px;
  border-bottom: 2px solid #3b82f6;
}

.section-icon {
  font-size: 24px;
  margin-right: 12px;
}

.section-title {
  font-size: 18px;
  font-weight: 600;
  color: #333;
}

/* 表单标签 */
.form-label {
  font-size: 15px;
  font-weight: 500;
  color: #555;
}

/* 自定义输入框 */
.custom-input :deep(.ant-input),
.custom-input :deep(.ant-picker) {
  border-radius: 12px;
  border: 2px solid #e8e8e8;
  transition: all 0.3s ease;
}

.custom-input :deep(.ant-input:hover),
.custom-input :deep(.ant-picker:hover) {
  border-color: #3b82f6;
}

.custom-input :deep(.ant-input:focus),
.custom-input :deep(.ant-picker-focused) {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.14);
}

/* 自定义选择框 */
.custom-select :deep(.ant-select-selector) {
  border-radius: 12px !important;
  border: 2px solid #e8e8e8 !important;
  transition: all 0.3s ease;
}

.custom-select:hover :deep(.ant-select-selector) {
  border-color: #3b82f6 !important;
}

.custom-select :deep(.ant-select-focused .ant-select-selector) {
  border-color: #3b82f6 !important;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.14) !important;
}

/* 天数显示 - 紧凑版 */
.days-display-compact {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 40px;
  padding: 8px 16px;
  background: linear-gradient(135deg, #3b82f6 0%, #6366f1 100%);
  border-radius: 12px;
  color: white;
}

.days-display-compact .days-value {
  font-size: 24px;
  font-weight: 700;
  margin-right: 4px;
}

.days-display-compact .days-unit {
  font-size: 14px;
}

/* 偏好标签 */
.preference-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.custom-checkbox-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  width: 100%;
}

.preference-tag :deep(.ant-checkbox-wrapper) {
  margin: 0 !important;
  padding: 8px 16px;
  border: 2px solid #e8e8e8;
  border-radius: 20px;
  transition: all 0.3s ease;
  background: white;
  font-size: 14px;
}

.preference-tag :deep(.ant-checkbox-wrapper:hover) {
  border-color: #3b82f6;
  background: #eff6ff;
}

.preference-tag :deep(.ant-checkbox-wrapper-checked) {
  border-color: #3b82f6;
  background: linear-gradient(135deg, #3b82f6 0%, #6366f1 100%);
  color: white;
}

/* 自定义文本域 */
.custom-textarea :deep(.ant-input) {
  border-radius: 12px;
  border: 2px solid #e8e8e8;
  transition: all 0.3s ease;
}

.custom-textarea :deep(.ant-input:hover) {
  border-color: #3b82f6;
}

.custom-textarea :deep(.ant-input:focus) {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.14);
}

/* 提交按钮 */
.submit-button {
  height: 56px;
  border-radius: 28px;
  font-size: 18px;
  font-weight: 600;
  background: linear-gradient(135deg, #3b82f6 0%, #6366f1 100%);
  border: none;
  box-shadow: 0 8px 24px rgba(59, 130, 246, 0.38);
  transition: all 0.3s ease;
}

.submit-button:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 32px rgba(59, 130, 246, 0.46);
}

.submit-button:active {
  transform: translateY(0);
}

.button-icon {
  margin-right: 8px;
  font-size: 20px;
}

/* 加载容器 */
.loading-container {
  text-align: center;
  padding: 24px;
  background: linear-gradient(135deg, #f5f7fa 0%, #ffffff 100%);
  border-radius: 16px;
  border: 2px dashed #3b82f6;
}

.loading-status {
  margin-top: 16px;
  color: #3b82f6;
  font-size: 18px;
  font-weight: 500;
}

/* 动画 */
@keyframes fadeInDown {
  from {
    opacity: 0;
    transform: translateY(-30px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(30px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>

