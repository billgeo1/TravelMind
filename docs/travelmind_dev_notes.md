# TravelMind 开发说明与验收记录

> 增量开发说明，对应 `TravelMind_技术设计与实施规范.md` 的 Phase A → E。
> 本文件记录**已实现内容、已运行命令与真实结果**；未验证项一律标注。

---

## 一、实施概览（Phase A → E）

| 阶段 | 内容 | 状态 |
|---|---|---|
| Phase A | 仓库审计、数据模型扩展、规范化层、事实适配器 | 已完成 |
| Phase B | 行程体检规则引擎 + 修复候选 + 差异服务 + 前端体检/修复 | 已完成 |
| Phase C | 突发事件重规划 + 前端事件表单/预览 | 已完成 |
| Phase D | 攻略截图识别 + POI 匹配 + 前端上传确认 | 已完成 |
| Phase E | 路由注册、统一错误、前端接线、端到端验收、文档 | 已完成 |

**工程约定**

- 保留原 Vue3 + TypeScript + Ant Design Vue、FastAPI + Pydantic、HelloAgents、高德 MCP 架构，`POST /api/trip/plan` 与旧 `TripPlan` 字段完全兼容（新字段均为可选默认值）。
- 旧 `models/schemas.py` 只在 `Attraction` / `TripPlan` 上追加可选字段；新 Schema 全部放在独立的 `models/travelmind.py`，不重复定义同名类。
- 规则（客观约束）与 AI（提取/排序）分离：LLM 输出必须经 Pydantic + 规则引擎二次校验；`travelmind_enable_llm_repair` 默认关闭，确定性规则即可满足 P0。
- 所有修复/重规划接口只返回**预览**，用户确认后才在前端应用；未确认前不改当前计划、不自动下单。

---

## 二、运行与测试（已执行）

### 后端测试

```bash
cd code/chapter13/travelmind/backend
python -m pytest -q -p no:warnings
```

结果：**57 passed**（`tests/` 下 5 个 TravelMind 测试文件）。

说明：`conftest.py` 会注入 `AMAP_API_KEY=test-amap-key`，所有用例使用 Mock 事实源，**不依赖真实付费 API**。

### 前端构建

```bash
cd code/chapter13/travelmind/frontend
npm run build
```

结果：`vue-tsc` 类型检查 + `vite build` 通过（3497 modules transformed），仅有单 chunk > 500 kB 的体积告警（沿用原有未拆包结构，非错误）。

### 端到端冒烟（真实 HTTP 调用，demo 模式）

临时启动 `TRAVELMIND_DEMO_MODE=true` 后端（端口 8010）并实测 5 个接口，结果：

| 用例 | 结果 |
|---|---|
| `GET /health` | 200 |
| 空行程 health-check | `score=null`、`insufficient_data`、规则 `0/11` |
| 含 `TIME_OVERLAP` + 锁定节点 | `score=85`、`partial`、规则 `6/11`，issues 覆盖 TIME_OVERLAP(auto_fix)/ROUTE_UNVERIFIED/OPENING_HOURS_UNKNOWN/RESERVATION_UNCONFIRMED/BAD_WEATHER_EXPOSURE |
| repair-preview（无修复机会） | 200，`changes=0`、`unresolved=1`（不假成功） |
| repair-preview（过期版本 5） | **409 `STALE_PLAN_REVISION`**（retryable） |
| replan-preview（延误 90min + 锁定） | 200，`changes=1` time_update，未移动锁定节点，`unresolved=1` |
| import-image（demo） | 200，`source=mock`，识别城市 + 5 候选（matched/ambiguous 混合） |
| 非法类型 `text/plain` | **415 `UNSUPPORTED_IMAGE`** |
| 11 MiB PNG | **413 `IMAGE_TOO_LARGE`** |

> 上述为一次性真实 HTTP 冒烟测试，脚本为临时文件，测试后已删除，未纳入仓库。

---

## 三、接口清单

所有新接口挂载在 `/api` 前缀下，统一错误体 `{"error": {"code", "message", "retryable"}}`。

| 方法 | 路由 | 内容类型 | 成功返回 |
|---|---|---|---|
| POST | `/api/trip/plan` | JSON | `TripPlan`（原有，未改动） |
| POST | `/api/trip/health-check` | JSON | `HealthReport` |
| POST | `/api/trip/repair-preview` | JSON | `PlanPreview` |
| POST | `/api/trip/replan-preview` | JSON | `PlanPreview` |
| POST | `/api/trip/import-image` | multipart | `ImageImportResult` |
| POST | `/api/trip/plan-from-import` | JSON | `PlanFromImportResponse`（`trip_plan` + `unplaced_attractions` + `warnings`） |

错误码：`INVALID_INPUT`(422)、`IMAGE_TOO_LARGE`(413)、`UNSUPPORTED_IMAGE`(415)、`VISION_NOT_CONFIGURED`(503)、`EXTERNAL_PROVIDER_UNAVAILABLE`(503, retryable)、`NO_FEASIBLE_PLAN`(422)、`STALE_PLAN_REVISION`(409, retryable)、`RATE_LIMITED`(429)。

并发保护：`repair-preview` / `replan-preview` 通过 `_guard_revision` 校验 `base_revision == plan.revision`，不一致返回 409；前端 `applyPreview` 再次比对 `preview.base_revision`，不符则拒绝覆盖。`plan-from-import` 对疑似占位行程（形如 `XX景点1`）追加告警。

---

## 四、改动文件清单

### 后端（新增）

- `backend/app/models/travelmind.py` — 新 API 全部 Schema。
- `backend/app/api/routes/travelmind.py` — 5 个接口 + 版本守卫 + 占位数据告警。
- `backend/app/services/travelmind/`
  - `errors.py` — 统一错误码与异常处理器注册。
  - `normalization.py` — 旧 `TripPlan` → 增强结构，补充 `uid`、规范化时区/时间。
  - `facts.py` — `FactProvider` 接口 + 真实/`MockFactProvider` 两种实现。
  - `validation.py` — 确定性体检规则引擎与评分。
  - `repair.py` — 修复候选生成 + 规则复检。
  - `replan.py` — 事件影响分析 + 最小变更重规划。
  - `image_import.py` — 图片校验/解码、视觉提取、POI 匹配、`plan-from-import` 编排。
  - `diff.py` — 计划前后差异。
  - `llm_agents.py` — 可选的 LLM 修复适配（默认不启用）。
- `backend/tests/`
  - `test_travelmind_validation.py`（9）、`test_travelmind_repair.py`（6）、`test_travelmind_replan.py`（11）、`test_travelmind_import.py`（18）、`test_travelmind_routes.py`（13）。
- `backend/conftest.py`、`backend/pytest.ini`。

### 后端（修改）

- `backend/app/models/schemas.py` — `Attraction` 追加 `uid` / `poi_id` / `planned_start` / `planned_end` / `verification_status` / `price_status` / `requires_reservation` / `reservation_confirmed` / `locked` / `completed` / `priority` / `photos`；`TripPlan` 追加 `plan_id` / `revision`（全部可选、带默认值，向后兼容）。
- `backend/app/api/main.py` — 注册 `travelmind` 路由与统一异常处理。
- `backend/app/config.py` — 新增 TravelMind 配置项。
- `backend/.env.example` — 新增配置示例。
- `backend/.gitignore` — 例外放行 `tests/`（仓库根 `.gitignore` 的 `test_*.py` 规则会误伤新测试）。

### 前端（新增）

- `frontend/src/types/travelmind.ts` — 与 Pydantic 对齐的 TS 类型。
- `frontend/src/services/travelmind.ts` — 5 接口封装 + `TravelMindApiError` + `describeError`。
- `frontend/src/components/travelmind/` — `TripHealthPanel.vue`、`RiskIssueList.vue`、`PlanDiffDrawer.vue`、`ReplanEventForm.vue`、`PoiConfirmationList.vue`、`ImageImportPanel.vue`。

### 前端（修改）

- `frontend/src/types/index.ts` — 同步 `Attraction` / `TripPlan` 新可选字段。
- `frontend/src/views/Home.vue` — 顶部 Tab（`手动填写` / `上传攻略截图`），接入 `ImageImportPanel`。
- `frontend/src/views/Result.vue` — 标题栏「🩺 AI 行程体检」「🚨 突发情况」入口、体检分标签、体检抽屉、重规划弹窗、变更预览抽屉与应用逻辑（含 `revision` 校验、防重复提交）。

### 文档（新增）

- `docs/travelmind_user_guide.md`、`docs/travelmind_dev_notes.md`（本文件）。

---

## 五、配置项

`.env` 中与 TravelMind 相关的配置：

| 变量 | 默认 | 说明 |
|---|---|---|
| `AMAP_API_KEY` | 空 | 高德地图（必需，否则启动校验失败） |
| `LLM_API_KEY` / `LLM_MODEL_ID` / `LLM_BASE_URL` | 空 | HelloAgents LLM（可选，缺少时走兜底） |
| `TRAVELMIND_DEMO_MODE` | `false` | 显式开启后才允许 mock 事实/识别结果 |
| `TRAVELMIND_MAX_IMAGE_MB` | `10` | 上传截图体积上限（服务端为准） |
| `TRAVELMIND_ENABLE_LLM_REPAIR` | `false` | 是否启用 LLM 生成修复候选（默认关闭） |
| `VISION_MODEL` / `VISION_API_KEY` / `VISION_BASE_URL` | 空 | 视觉模型；三者为空时 `import-image` 返回 `VISION_NOT_CONFIGURED` |

> 敏感性说明：密钥只经服务端读取，不写入前端、不写入日志。

---

## 六、数据模型变更

- `Attraction`：新增可选的 `uid`（计划内稳定节点 ID，前端编辑移动节点时保留）、`poi_id`、`planned_start` / `planned_end`（目的地的带时区 ISO8601）、`verification_status`、`price_status`、`requires_reservation`、`reservation_confirmed`、`locked`、`completed`、`priority`、`photos`。
- `TripPlan`：新增可选 `plan_id`、`revision`（默认 0；客户端方案版本号，非数据库事务版本）。
- 新增独立 Schema（`models/travelmind.py`）：`Severity`、`Evidence`、`HealthIssue`、`HealthReport`、`PlanChange`、`PlanPreview`、`ValidationOptions`、`HealthCheckRequest`、`RepairPreferences`、`RepairPreviewRequest`、`ReplanEvent`、`ReplanPreviewRequest`、`ImportCandidate`、`ImageImportResult`、`ConfirmedAttraction`、`ImportTripRequest`、`UnplacedAttraction`、`PlanFromImportRequest`、`PlanFromImportResponse`、统一错误体。
- 兼容性：旧字段（`city` / `start_date` / `end_date` / `days` / `weather_info` / `overall_suggestions` / `budget` 等）保持不变，旧计划缺失 `planned_start` 时退化为「时间未安排」，不做精确冲突判定。

---

## 七、已知限制与后续工作

**限制**

- 未配置视觉模型时截图导入只能返回 `VISION_NOT_CONFIGURED` 或走 `TRAVELMIND_DEMO_MODE`；本环境下**未使用真实视觉/LLM 密钥验证**。
- 营业时间 / 天气 / 票价 / 预约余量在缺少可靠来源时统一 `unknown` / `unverified`，刻意不做精确判定。
- 突发情况为手动触发（P0），无定时监控、主动推送、实时报价或自动预订。
- 重规划在硬约束无解时返回带 `unresolved_issues` 的预览，不代表问题已解决。
- 应用导入/修复候选后，页面沿用原有 `loadAttractionPhotos`，不会为新节点重新拉取真实 POI 图片。
- 前端为单页单 chunk 构建，存在 > 500 kB 体积告警。

**后续建议**

- 接入真实视觉模型（OpenAI 兼容多模态接口）并补充对应集成测试。
- 引入服务端行程存储后，将 409 版本守卫升级为服务端乐观锁（当前为单浏览器前端状态管理）。
- 增加按需代码拆分以消除构建体积告警。
