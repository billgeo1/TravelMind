<template>
  <div id="app">
    <a-layout class="app-shell">
      <!-- 顶部导航 -->
      <a-layout-header class="app-header">
        <div class="header-inner">
          <router-link class="brand" to="/">
            <span class="brand-mark" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="22" height="22">
                <path
                  d="M2.4 20.6 21.6 12 2.4 3.4l-.4 6.2 13.6 2.4-13.6 2.4z"
                  fill="currentColor"
                />
              </svg>
            </span>
            <span class="brand-text">
              <strong>TravelMind</strong>
              <small>AI 智能旅行助手</small>
            </span>
          </router-link>

          <nav class="header-nav">
            <router-link class="nav-link" to="/">🧭 规划行程</router-link>
            <a
              class="nav-link"
              href="http://localhost:8000/docs"
              target="_blank"
              rel="noreferrer"
            >
              📚 API 文档
            </a>
          </nav>
        </div>
      </a-layout-header>

      <a-layout-content class="app-content">
        <router-view />
      </a-layout-content>

      <!-- 页脚 -->
      <a-layout-footer class="app-footer">
        <div class="footer-inner">
          <p class="footer-brand">
            <span class="footer-mark">✈️</span>
            TravelMind · 让每一次出发都有 AI 同行
          </p>
          <p class="footer-links">
            <span class="footer-label">参考来源</span>
            <a href="https://github.com/datawhalechina/Hello-Agents" target="_blank" rel="noreferrer">
              Hello-Agents
            </a>
            <span class="dot">·</span>
            <a href="https://github.com/jjyaoao/HelloAgents" target="_blank" rel="noreferrer">
              HelloAgents 框架
            </a>
            <span class="dot">·</span>
            <a href="https://github.com/sugarforever/amap-mcp-server" target="_blank" rel="noreferrer">
              amap-mcp-server
            </a>
            <span class="dot">·</span>
            <a href="https://lbs.amap.com/" target="_blank" rel="noreferrer">高德开放平台</a>
          </p>
          <p class="footer-note">
            本项目在原「HelloAgents 智能旅行助手」基础上二次开发,新增 AI 行程体检与智能修复、突发事件动态重规划、攻略截图识别生成行程三项能力。
          </p>
        </div>
      </a-layout-footer>
    </a-layout>
  </div>
</template>

<script setup lang="ts">
</script>

<style>
/* ===== TravelMind 品牌设计令牌 ===== */
:root {
  --tm-sky: #38bdf8;
  --tm-blue: #3b82f6;
  --tm-indigo: #6366f1;
  --tm-violet: #8b5cf6;
  --tm-sun: #f59e0b;
  --tm-teal: #14b8a6;
  --tm-ink: #0f172a;
  --tm-muted: #64748b;
  --tm-line: #e6ebf4;
  --tm-bg: #f6f8fc;
  --tm-gradient: linear-gradient(135deg, #38bdf8 0%, #6366f1 58%, #8b5cf6 100%);
  --tm-shadow-sm: 0 2px 8px rgba(15, 23, 42, 0.06);
  --tm-shadow-md: 0 10px 30px rgba(15, 23, 42, 0.1);
  --tm-radius: 16px;
}

#app {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial,
    'Noto Sans', 'PingFang SC', 'Microsoft YaHei', sans-serif;
  color: var(--tm-ink);
}

/* 布局骨架:头部吸顶 + 内容区撑满 + 页脚收尾 */
.app-shell {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--tm-bg);
}

.app-header {
  height: auto !important;
  line-height: normal !important;
  padding: 0 !important;
  background: var(--tm-gradient) !important;
  position: sticky;
  top: 0;
  z-index: 20;
  box-shadow: 0 4px 20px rgba(59, 130, 246, 0.25);
  overflow: hidden;
}

.app-header::after {
  content: '';
  position: absolute;
  inset: 0;
  background-image: radial-gradient(circle at 12% 20%, rgba(255, 255, 255, 0.25), transparent 45%),
    radial-gradient(circle at 88% 80%, rgba(255, 255, 255, 0.18), transparent 40%);
  pointer-events: none;
}

.header-inner {
  position: relative;
  z-index: 1;
  max-width: 1280px;
  margin: 0 auto;
  padding: 14px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  text-decoration: none;
}

.brand-mark {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--tm-blue);
  background: #ffffff;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.18);
  transform: rotate(-8deg);
  transition: transform 0.3s ease;
}

.brand:hover .brand-mark {
  transform: rotate(0deg) translateY(-2px);
}

.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}

.brand-text strong {
  font-size: 20px;
  font-weight: 800;
  letter-spacing: 0.6px;
  color: #ffffff;
}

.brand-text small {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.85);
  letter-spacing: 0.4px;
}

.header-nav {
  display: flex;
  align-items: center;
  gap: 8px;
}

.nav-link {
  padding: 8px 16px;
  border-radius: 999px;
  font-size: 14px;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.92) !important;
  background: rgba(255, 255, 255, 0.14);
  border: 1px solid rgba(255, 255, 255, 0.22);
  text-decoration: none;
  transition: all 0.25s ease;
}

.nav-link:hover {
  background: rgba(255, 255, 255, 0.28);
  transform: translateY(-1px);
}

.app-content {
  flex: 1;
  padding: 0 !important;
  display: flex;
  flex-direction: column;
}

.app-content > * {
  flex: 1;
}

.app-footer {
  background: var(--tm-ink) !important;
  padding: 28px 24px !important;
  text-align: center;
}

.footer-inner {
  max-width: 980px;
  margin: 0 auto;
}

.footer-brand {
  color: #ffffff;
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 10px;
}

.footer-mark {
  margin-right: 6px;
}

.footer-links {
  color: rgba(226, 232, 240, 0.75);
  font-size: 13px;
  margin-bottom: 10px;
}

.footer-links a {
  color: #93c5fd;
  text-decoration: none;
  transition: color 0.2s ease;
}

.footer-links a:hover {
  color: #ffffff;
  text-decoration: underline;
}

.footer-label {
  margin-right: 6px;
}

.dot {
  margin: 0 6px;
  color: rgba(148, 163, 184, 0.6);
}

.footer-note {
  color: rgba(148, 163, 184, 0.85);
  font-size: 12px;
  line-height: 1.7;
  margin: 0;
}

@media (max-width: 640px) {
  .header-inner {
    padding: 12px 16px;
  }

  .brand-text small {
    display: none;
  }

  .app-footer {
    padding: 22px 16px !important;
  }
}
</style>

