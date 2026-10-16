# TravelMind 用户操作指南

> 面向使用者的操作说明。开发/部署细节见同目录 `travelmind_dev_notes.md`。

TravelMind 在原有「智能旅行助手」基础上新增三项能力：

1. **AI 行程体检**：体检已生成的行程，给出健康分、风险清单、证据与覆盖度，并支持「预览 → 差异 → 确认应用」的智能修复。
2. **突发事件动态重规划**：在下雨 / 闭馆 / 延误 / 疲惫等情况下，只调整受影响部分，保护已锁定与已完成节点。
3. **攻略截图转行程**：上传攻略截图，识别其中的地点并匹配真实 POI，用户确认后一键生成正式行程。

原有功能（行程生成、地图、预算、手动编辑、图片/PDF 导出）全部保留，未做破坏性改动。

---

## 一、启动

### 后端

```bash
cd code/chapter13/travelmind/backend
pip install -r requirements.txt      # 若尚未安装依赖
cp .env.example .env                 # 复制后按需填写
python run.py                         # 默认 http://localhost:8000
```

`.env` 至少需要 `AMAP_API_KEY`（高德地图）。其余可选项见「五、配置项」。

### 前端

```bash
cd code/chapter13/travelmind/frontend
npm install
npm run dev                           # 默认 http://localhost:5173
```

前端默认请求 `http://localhost:8000` 的后端接口。

---

## 二、AI 行程体检与智能修复

**入口**：先生成一次行程，进入「行程结果」页，点击标题栏的 **🩺 AI 行程体检**。

流程：

1. 点击「AI 行程体检」，右侧抽屉展示：
   - **健康分**（0–100，关键事实几乎全缺时显示为空）；
   - **可信度标签**：`完整 / 部分 / 数据不足`；
   - **覆盖度**：已核验事实数 / 事实总数、已执行规则数 / 规则总数；
   - **风险列表**：每条含等级、日期、影响景点、证据来源与时间、建议，并提供「📍 定位节点」跳到地图对应标记。
2. 若存在可自动修复的风险，点击 **智能修复** → 生成候选方案。
3. 弹出 **变更预览抽屉**：按日展示移动 / 替换 / 删除 / 新增 / 时间调整 / 预算变化，并列出**未解决风险**。
4. 只有点击 **应用方案** 才会替换当前行程、重算地图标记与预算、并把版本号 `revision` 加一；点击 **取消** 则当前行程、编辑状态、版本号完全不变。

体检规则（确定性代码，不依赖 LLM）：

| 规则码 | 含义 | 默认等级 |
|---|---|---|
| `TIME_OVERLAP` | 同日已知时段重叠 | high |
| `TRAVEL_TIME_INSUFFICIENT` | 相邻景点间交通 + 缓冲超出可用间隔 | high |
| `ROUTE_UNVERIFIED` | 缺少可核验的路线耗时 | info |
| `VENUE_CLOSED` / `OPENING_HOURS_UNKNOWN` | 已确认不营业 / 未查到营业时间 | critical / info |
| `RESERVATION_UNCONFIRMED` | 疑似需要预约但未确认 | medium |
| `BUDGET_EXCEEDED` | 已知合计费用超出明确预算上限 | high |
| `BAD_WEATHER_EXPOSURE` | 访问时段天气明确不适于室外 | medium |
| `EXCESSIVE_PACE` | 单日游览 + 交通总时长超阈值 | medium |
| `POI_UNVERIFIED` | 未匹配到可定位 POI | info |
| `MISSING_SCHEDULE` | 缺少 `planned_start` / `planned_end` | info |

计分：`critical=25`、`high=15`、`medium=7`、`low=3`、`info=0`，`score = max(0, 100 - 去重后扣分)`。**分数不是安全保证**，请同时看覆盖度。

---

## 三、突发事件动态重规划

**入口**：行程结果页 → **🚨 突发情况**。

填写表单：

- **事件类型**：`rain`（下雨）/ `attraction_closed`（临时闭馆）/ `delay`（延误）/ `fatigue`（疲惫）/ `other`（其它，文字描述）；
- **受影响日期**（第几天）；
- **受影响景点**（可选）；
- **延误分钟数**（`delay` 时填写，0–1440）；
- **情况描述**（可选，≤1000 字）；
- **锁定节点**：勾选后这些景点不会被移动或删除。

点击 **生成新方案** 后，同样进入「变更预览抽屉」，展示调整后的行程、变更原因、预算变化与**未解决风险**；确认后点击「应用方案」才生效。

保护规则：已完成 / 已预约 / 用户锁定的节点默认不可修改；无解时会明确列出 `unresolved_issues`，不会伪装成「已全部解决」。

> P0 采用**手动触发**，不包含定时后台监控与主动推送。

---

## 四、攻略截图转行程

**入口**：首页顶部切换 Tab 到 **上传攻略截图**。

流程：

1. 拖拽上传 PNG / JPEG / WebP 截图（单张 ≤ 10 MiB，服务端为准）；
2. 可选填写「城市提示」（如「北京」），点击 **🔍 识别截图**；
3. 系统提取地点候选并做真实 POI 匹配，标记 `matched` / `ambiguous` / `not_found`；
4. 在候选列表中勾选 / 删除 / 调整地点（默认不勾选 `ambiguous` / `not_found`，需你人工确认）；
5. 补全日期、预算、交通、住宿等信息，点击生成行程；
6. 后端复用原有 PlannerAgent 生成行程，并保证**你确认的景点不被静默丢弃**——无法安排的地点会在 `unplaced_attractions` 中列出并说明原因；
7. 成功后进入结果页，可继续体检与重规划。

安全说明：截图中的文字仅作为被分析的数据，不会被当作系统指令；图片不做长期保存。

---

## 五、接口说明（JSON 示例）

所有新接口统一错误体：

```json
{ "error": { "code": "VISION_NOT_CONFIGURED", "message": "未配置支持图片识别的模型。", "retryable": false } }
```

### 1. `POST /api/trip/health-check`

请求：

```json
{
  "trip_plan": { "city": "北京", "start_date": "2026-11-06", "end_date": "2026-11-08", "days": [], "weather_info": [], "overall_suggestions": "", "budget": null, "revision": 0 },
  "options": { "daily_max_minutes": 540, "travel_buffer_minutes": 15, "budget_limit_yuan": null }
}
```

响应 `HealthReport`（节选）：

```json
{
  "score": 85,
  "status": "partial",
  "issues": [
    {
      "issue_id": "...",
      "code": "TIME_OVERLAP",
      "severity": "high",
      "title": "同一天行程时段重叠",
      "description": "...",
      "affected_day_indices": [0],
      "affected_attraction_uids": ["u1", "u2"],
      "evidence": [{ "source": "derived", "detail": "...", "confidence": 0.9 }],
      "suggestion": "调整其中一处时间",
      "can_auto_fix": true
    }
  ],
  "checked_rule_count": 6,
  "total_rule_count": 11,
  "coverage": 0.55
}
```

空行程返回 `status=insufficient_data` 且 `score=null`，不会给 100 分。

### 2. `POST /api/trip/repair-preview`

```json
{
  "trip_plan": { "city": "北京", "...": "...", "revision": 0 },
  "health_report": { "score": 85, "status": "partial", "issues": [] },
  "base_revision": 0,
  "preferences": { "preserve_confirmed_bookings": true, "allow_remove_attractions": false }
}
```

返回 `PlanPreview`（`candidate_plan` / `changes` / `unresolved_issues` / `budget_delta` / `report`）。`base_revision` 与当前 `revision` 不一致时返回 `409 STALE_PLAN_REVISION`。

### 3. `POST /api/trip/replan-preview`

```json
{
  "trip_plan": { "city": "北京", "...": "...", "revision": 2 },
  "base_revision": 2,
  "event": { "type": "delay", "affected_day_index": 0, "delay_minutes": 90, "source": "user_reported", "description": "交通拥堵导致晚到 90 分钟" },
  "locked_attraction_uids": [],
  "max_extra_budget_yuan": 200
}
```

返回 `PlanPreview`。

### 4. `POST /api/trip/import-image`

`multipart/form-data`，字段：`file`（必填）、`city_hint`（可选）。

返回 `ImageImportResult`：

```json
{
  "detected_city": "北京",
  "candidates": [
    { "candidate_id": "c_001", "raw_name": "故宫", "canonical_name": "故宫博物院", "poi_id": "...", "address": "...", "location": { "longitude": 116.397, "latitude": 39.916 }, "match_status": "matched", "confidence": 0.93, "alternatives": [] }
  ],
  "warnings": [],
  "source": "vision"
}
```

### 5. `POST /api/trip/plan-from-import`

```json
{
  "request": { "city": "北京", "start_date": "2026-11-06", "end_date": "2026-11-08", "days": 3, "preferences": "历史文化", "budget": "中等", "transportation": "公共交通", "accommodation": "经济型酒店" },
  "confirmed_attractions": [ { "candidate_id": "c_001", "poi_id": "...", "name": "故宫博物院" } ],
  "additional_preferences": "希望每天不要太赶"
}
```

返回 `{ "trip_plan": TripPlan, "unplaced_attractions": [...], "warnings": [] }`。

---

## 六、错误码

| 错误码 | HTTP | 可重试 | 说明 |
|---|---|---|---|
| `INVALID_INPUT` | 422 | 否 | 请求参数不合法 |
| `IMAGE_TOO_LARGE` | 413 | 否 | 图片超过体积上限 |
| `UNSUPPORTED_IMAGE` | 415 | 否 | 非 PNG/JPEG/WebP 或签名校验失败 |
| `VISION_NOT_CONFIGURED` | 503 | 否 | 未配置视觉模型 |
| `EXTERNAL_PROVIDER_UNAVAILABLE` | 503 | 是 | 外部服务（地图/天气/LLM）不可用 |
| `NO_FEASIBLE_PLAN` | 422 | 否 | 约束下无可行方案 |
| `STALE_PLAN_REVISION` | 409 | 是 | 行程版本已变化，需重新加载 |
| `RATE_LIMITED` | 429 | 是 | 触发限流 |

---

## 七、Demo 模式与限制

**演示模式**（`TRAVELMIND_DEMO_MODE=true`）用于缺少外部密钥时跑通完整流程：

- 截图识别返回内置固定示例结果，`source=mock`，前端显示「演示数据」提示；
- 所有演示数据都带 mock 标识，**不代表真实 POI / 天气 / 营业时间**。

生产环境请保持 `TRAVELMIND_DEMO_MODE=false`。

当前限制：

- 未配置视觉模型时截图导入会明确返回 `VISION_NOT_CONFIGURED`，需走演示模式或配置 `VISION_*`；
- 营业时间、天气、票价、预约余量在缺少可靠数据源时统一标记为 `unknown` / `unverified`，不做精确判定；
- 突发情况为手动触发，暂无定时监控与主动通知；
- 预算展示为「估算」，除非有真实报价来源；
- 版本号 `revision` 属于单浏览器前端状态管理，不是跨设备协同锁。
