# TravelMind · 智能旅行助手 🌍✈️

TravelMind 是一个基于 **HelloAgents 框架 + 高德地图 MCP 服务** 构建的智能旅行助手:
输入目的地与偏好,自动产出包含景点、路线、天气与预算的完整行程;行程生成后还能做 **AI 体检**、
**智能修复** 与 **突发事件动态重规划**,并支持 **上传攻略截图直接生成行程**。

> 本项目参考开源项目「HelloAgents 智能旅行助手」二次开发,原项目的行程生成、地图、预算、
> 手动编辑与导出能力全部保留并继续可用,详见文末 [参考来源](#-参考来源与致谢)。

## ✨ 主要功能

### 基础能力(沿用原项目实现)

- 🤖 **AI 驱动的旅行规划**: 基于 HelloAgents 框架的 SimpleAgent,智能生成详细的多日旅程
- 🗺️ **高德地图集成**: 通过 MCP 协议接入高德地图服务,支持景点搜索、路线规划、天气查询
- 🧠 **智能工具调用**: Agent 自动调用高德地图 MCP 工具,获取实时 POI、路线和天气信息
- 🎨 **现代化前端**: Vue3 + TypeScript + Vite,响应式设计,流畅的用户体验
- 📱 **完整行程信息**: 包含住宿、交通、餐饮和景点游览时间推荐
- ✏️ **手动编辑与导出**: 行程可拖动排序、增删景点,支持导出为图片 / PDF

### 🆕 本次新增的三项核心能力(重点贡献)

#### 1. AI 行程体检与智能修复

- 对任意行程执行**规则化体检**:输出 0-100 体检分、风险清单(按严重度分级)、风险覆盖度与建议。
- 体检维度覆盖:行程过密 / 通勤不合理 / 景点重复 / 用餐缺失 / 开放时间冲突 / 预算失衡 / 体力强度等。
- 一键**智能修复**:基于体检报告生成修复候选方案,逐条给出「改了什么、为什么改」的差异说明。
- **新方案必须经用户确认后才会应用**,取消不会对当前行程产生任何副作用。

#### 2. 突发事件动态重规划

- 支持录入天气突变、景点闭馆、交通延误、体力不支等突发事件,生成重规划候选方案。
- 支持**锁定不想被改动的景点**(`locked_attraction_uids`)、限制额外预算(`max_extra_budget_yuan`)。
- 重规划结果同样以候选方案 + 差异预览的形式给出,确认后才替换当前行程。

#### 3. 攻略截图识别并生成行程

- 直接上传小红书 / 马蜂窝等**攻略截图**,自动识别其中的地名并匹配为真实高德 POI。
- 识别结果以**候选地点清单**呈现,可逐条勾选、编辑名称后再生成行程。
- 生成时使用原有 PlannerAgent,并保证「用户已确认的景点不会被静默丢弃」,未排入的地点会显式提示。

## 🏗️ 技术栈

### 后端
- **框架**: HelloAgents (基于SimpleAgent)
- **API**: FastAPI
- **MCP工具**: amap-mcp-server (高德地图)
- **LLM**: 支持多种LLM提供商(OpenAI, DeepSeek等)
- **数据校验**: Pydantic v2(所有 AI 输出都会经过模型校验后才返回/落库)
- **测试**: pytest(后端 139 项测试,含高德服务与 TravelMind 全链路)

### 前端
- **框架**: Vue 3 + TypeScript
- **构建工具**: Vite
- **UI组件库**: Ant Design Vue
- **地图服务**: 高德地图 JavaScript API
- **HTTP客户端**: Axios
- **行程导出**: html2canvas + jsPDF

## 🧩 我的修改与贡献

| 类型 | 内容 | 主要位置 |
| --- | --- | --- |
| 🆕 新增功能 | AI 行程体检(评分/风险分级/覆盖度) | `backend/app/services/travelmind/validation.py` |
| 🆕 新增功能 | AI 智能修复,输出候选方案与差异 | `backend/app/services/travelmind/repair.py`、`diff.py` |
| 🆕 新增功能 | 突发事件动态重规划(可锁景点/限预算) | `backend/app/services/travelmind/replan.py` |
| 🆕 新增功能 | 攻略截图识别并生成行程 | `backend/app/services/travelmind/image_import.py` |
| 🆕 新增接口 | `/api/trip/health-check`、`/repair-preview`、`/replan-preview`、`/import-image`、`/plan-from-import` | `backend/app/api/routes/travelmind.py` |
| 🆕 新增模型 | 体检报告、风险项、候选方案、差异、截图识别结果 | `backend/app/models/travelmind.py` |
| 🆕 新增前端 | 体检面板、突发事件表单、差异确认抽屉、截图导入面板等 6 个组件 | `frontend/src/components/travelmind/` |
| 🆕 新增前端 | TravelMind 服务层与类型定义 | `frontend/src/services/travelmind.ts`、`frontend/src/types/travelmind.ts` |
| 🐛 缺陷修复 | **重写 `search_poi`**:原实现为空壳(恒返回 `[]`),导致截图识别结果全部「未匹配」;现已实现高德 Web 服务 API 的 POI 检索 / 详情 / 地理编码,并补齐搜索结果经纬度 | `backend/app/services/amap_service.py` |
| 🐛 缺陷修复 | **修复 MCP 子进程启动失败**:`amap-mcp-server` 依赖 `mcp==1.8.1`,与 `pydantic>=2.14` 不兼容,默认启动命令改为 `uvx --with "pydantic<2.14" amap-mcp-server` | `backend/app/services/amap_service.py`、`backend/.env.example` |
| 🐛 缺陷修复 | **修复景点地图白屏**:缺少/加载失败 Web 端 JS Key 时给出可见提示,并在重复初始化前销毁旧地图实例 | `frontend/src/views/Result.vue` |
| 🐛 缺陷修复 | **修复 AI 行程体检超时**:高德公交/地铁路由接口返回非法 JSON 会导致调用挂死;新增 MCP 调用超时 + 熔断 + 驾车近似降级,并对同一事实做去重与并发预取 | `backend/app/services/amap_service.py`、`backend/app/services/travelmind/validation.py`、`backend/app/services/travelmind/facts.py` |
| 🎨 品牌改造 | 全站改名为 TravelMind:前端整体视觉改版(品牌头部 / 页脚 / 首页 / 结果页)、站点图标、包名、后端应用名与版本 | `frontend/`、`backend/app/config.py` |
| ✅ 质量保障 | 新增高德服务与 TravelMind 单元测试、Mock 事实提供者,支持无外部密钥条件下开发与测试 | `backend/tests/`、`backend/conftest.py` |

## 📁 项目结构

```
travelmind/
├── backend/                     # 后端服务
│   ├── app/
│   │   ├── agents/              # Agent实现
│   │   │   └── trip_planner_agent.py
│   │   ├── api/                 # FastAPI路由
│   │   │   ├── main.py
│   │   │   └── routes/
│   │   │       ├── trip.py
│   │   │       ├── poi.py
│   │   │       ├── map.py
│   │   │       └── travelmind.py        # 🆕 体检/修复/重规划/截图导入接口
│   │   ├── services/            # 服务层
│   │   │   ├── amap_service.py          # 高德服务(含重写的 search_poi)
│   │   │   ├── llm_service.py
│   │   │   └── travelmind/              # 🆕 TravelMind 业务实现
│   │   │       ├── validation.py        #   行程体检规则引擎
│   │   │       ├── repair.py            #   智能修复
│   │   │       ├── replan.py            #   突发事件重规划
│   │   │       ├── image_import.py      #   攻略截图识别
│   │   │       ├── normalization.py     #   行程结构规范化
│   │   │       ├── facts.py             #   事实数据提供者(Mock/真实)
│   │   │       ├── diff.py              #   候选方案差异
│   │   │       ├── llm_agents.py        #   LLM Agent 封装
│   │   │       └── errors.py            #   统一错误码/异常处理
│   │   ├── models/
│   │   │   ├── schemas.py
│   │   │   └── travelmind.py            # 🆕 TravelMind 数据模型
│   │   └── config.py            # 配置管理
│   ├── tests/                   # 🆕 后端测试(含高德服务与 TravelMind)
│   ├── requirements.txt
│   ├── run.py                   # 启动脚本
│   ├── .env.example
│   └── .gitignore
├── frontend/                     # 前端应用
│   ├── public/favicon.svg        # 🆕 站点图标
│   ├── src/
│   │   ├── components/travelmind/   # 🆕 体检/重规划/差异确认/截图导入组件
│   │   ├── services/             # API服务(api.ts / travelmind.ts)
│   │   ├── types/                # TypeScript类型(index.ts / travelmind.ts)
│   │   ├── App.vue               # 🎨 TravelMind 品牌布局
│   │   └── views/                # 页面视图(Home.vue / Result.vue)
│   ├── package.json
│   └── vite.config.ts
├── docs/
│   ├── travelmind_dev_notes.md   # 🆕 技术设计与实现说明
│   └── travelmind_user_guide.md  # 🆕 使用说明
└── README.md
```

## 🚀 快速开始

### 前提条件

- Python 3.10+
- Node.js 16+
- 高德地图API密钥 (Web服务API和Web端(JS API))
- LLM API密钥 (OpenAI/DeepSeek等)
- (可选)视觉模型密钥 (gpt-4o / qwen-vl 等),用于攻略截图识别;未配置时该接口会明确返回 `VISION_NOT_CONFIGURED`

### 后端安装

1. 进入后端目录
```bash
cd backend
```

2. 创建虚拟环境
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```

3. 安装依赖
```bash
pip install -r requirements.txt
```

4. 配置环境变量
```bash
cp .env.example .env
# 编辑 .env,至少填写:
#   AMAP_API_KEY        高德「Web服务」Key(后端调用 POI/天气/路线)
#   LLM_API_KEY / LLM_MODEL_ID / LLM_BASE_URL
#   (可选) VISION_MODEL / VISION_API_KEY,截图识别所需的视觉模型
#   (可选) TRAVELMIND_DEMO_MODE=true,无外部密钥时用演示数据跑通全流程
```

5. 启动后端服务
```bash
python run.py
# 等价于: uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000
```

> ⚠️ 如果启动时报 `ModuleNotFoundError: No module named 'uvicorn'`,说明依赖装到了别的解释器里。
> 请确认虚拟环境已激活(`venv\Scripts\activate`),并用 `python -m pip install -r requirements.txt`
> 重新安装依赖后再启动。

### 前端安装

1. 进入前端目录
```bash
cd frontend
```

2. 安装依赖
```bash
npm install
```

3. 配置环境变量

```bash
# Windows: copy .env.example .env.local
cp .env.example .env.local
```

`.env.local`(会被 git 忽略,不会进版本库)中至少需要:

```
VITE_API_BASE_URL=http://localhost:8000
# 高德「Web端(JS API)」Key —— 用于前端地图渲染,与后端 Web 服务 Key 不同!
VITE_AMAP_WEB_JS_KEY=你的JS API Key
```

> 未配置 `VITE_AMAP_WEB_JS_KEY` 时地图区域会显示明确提示而不是白屏。

4. 启动开发服务器
```bash
npm run dev
```

5. 打开浏览器访问 `http://localhost:5173`

## 📝 使用指南

1. 在首页填写旅行信息:
   - 目的地城市
   - 旅行日期和天数
   - 交通方式偏好
   - 住宿偏好
   - 旅行风格标签

2. 点击"生成旅行计划"按钮

3. 系统将:
   - 调用HelloAgents Agent生成初步计划
   - Agent自动调用高德地图MCP工具搜索景点
   - Agent获取天气信息和路线规划
   - 整合所有信息生成完整行程

4. 查看结果:
   - 每日详细行程
   - 景点信息与地图标记
   - 交通路线规划
   - 天气预报
   - 餐饮推荐

### 攻略截图生成行程

1. 在首页切换到「📸 攻略截图生成行程」标签页,上传 PNG / JPEG / WebP 截图(单张 ≤ 10MiB,可在 `.env` 调整)。
2. 点击「🔍 识别截图」,系统提取截图中的地名并匹配为真实高德 POI。
3. 在候选清单中勾选/修改名称,补全城市与日期后点击「🚀 生成行程」。
4. 未被排入行程的地点会显式提示,不会静默丢失。

### AI 行程体检与智能修复

1. 在结果页点击「🩺 AI 行程体检」,查看体检分、风险清单与建议。
2. 点击风险项可跳转到对应日期;点击「智能修复」生成修复候选方案。
3. 在差异抽屉中逐条核对改动,**确认后**才会写入当前行程;取消则完全不影响原行程。

### 突发事件动态重规划

1. 在结果页点击「🚨 突发情况」,选择事件类型(天气突变 / 景点闭馆 / 交通延误 / 体力不支等)。
2. 可锁定不希望改动的景点、限制额外预算。
3. 同样在差异抽屉中确认后应用。

## 🔧 核心实现

### TravelMind 设计约束(三项新功能共同遵循)

1. **AI 输出必须校验**:LLM/视觉模型的返回先经过 Pydantic 模型校验与规范化,
   字段缺失、类型错误或结构异常都会被拒绝或降级,不合法结果不会进入响应。
2. **新方案必须经用户确认后才应用**:体检/修复/重规划都只返回 `PlanPreview` 候选方案与差异,
   前端以抽屉形式展示,用户点击确认才替换当前行程。
3. **版本冲突保护**:请求携带 `base_revision`,若期间行程已被修改,后端返回 `409 STALE_PLAN_REVISION`,
   避免覆盖用户的手动编辑。
4. **可测试的 Mock 服务**:`TRAVELMIND_DEMO_MODE=true` 或缺少外部密钥时,事实提供者切换到
   内置 Mock 数据(带「演示数据」标识),保证无密钥环境也能开发和跑测试。

### HelloAgents Agent集成

```python
from hello_agents import SimpleAgent, HelloAgentsLLM
from hello_agents.tools import MCPTool

# 创建高德地图MCP工具
amap_tool = MCPTool(
    name="amap",
    server_command=["uvx", "amap-mcp-server"],
    env={"AMAP_MAPS_API_KEY": "your_api_key"},
    auto_expand=True
)

# 创建旅行规划Agent
agent = SimpleAgent(
    name="旅行规划助手",
    llm=HelloAgentsLLM(),
    system_prompt="你是一个专业的旅行规划助手..."
)

# 添加工具
agent.add_tool(amap_tool)
```

### MCP工具调用

Agent可以自动调用以下高德地图MCP工具:
- `maps_text_search`: 搜索景点POI
- `maps_weather`: 查询天气
- `maps_direction_walking_by_address`: 步行路线规划
- `maps_direction_driving_by_address`: 驾车路线规划
- `maps_direction_transit_integrated_by_address`: 公共交通路线规划

## 📄 API文档

启动后端服务后,访问 `http://localhost:8000/docs` 查看完整的API文档。

原有端点:
- `POST /api/trip/plan` - 生成旅行计划
- `GET /api/map/poi` - 搜索POI
- `GET /api/map/weather` - 查询天气
- `POST /api/map/route` - 规划路线

🆕 TravelMind 新增端点:

- `POST /api/trip/health-check` - AI 行程体检:返回体检分、风险清单、覆盖度与建议
- `POST /api/trip/repair-preview` - AI 智能修复:返回候选方案与差异(需用户确认后应用)
- `POST /api/trip/replan-preview` - 突发事件动态重规划:返回候选方案与差异(需用户确认后应用)
- `POST /api/trip/import-image` - 攻略截图识别:返回待确认的地点候选清单
- `POST /api/trip/plan-from-import` - 按截图确认结果生成行程,并保证已确认景点不被静默丢弃

## 🧪 测试

```bash
cd backend
python -m pytest -q
```

- 当前后端共 **139 项测试全部通过**,覆盖:行程体检规则、智能修复、突发事件重规划、
  截图识别与生成、接口路由、高德服务(POI 检索 / 详情 / 地理编码 / 天气 / 路线),
  以及高德公交接口超时熔断与驾车近似降级。
- 测试使用可替换的 Mock 事实提供者与 Mock LLM,**无需真实外部密钥**即可运行。
- 前端类型检查与构建:`cd frontend && npm run build`。

## 📚 相关文档

- [`docs/travelmind_user_guide.md`](docs/travelmind_user_guide.md) - 三项新功能的使用说明与启动方式
- [`docs/travelmind_dev_notes.md`](docs/travelmind_dev_notes.md) - 技术设计、数据模型、接口契约与实现说明

## 🤝 贡献指南

欢迎提交 Pull Request 或 Issue。

## 📜 开源协议

本项目沿用原项目的授权协议 [CC BY-NC-SA 4.0](LICENSE.txt)(署名—非商业性使用—相同方式共享)。
二次开发与再分发请保留署名与相同的授权协议。

## 🙏 参考来源与致谢

本项目为**学习 / 个人项目性质**的二次开发作品,参考并复用了以下开源资料:

| 参考来源 | 说明 |
| --- | --- |
| [Hello-Agents](https://github.com/datawhalechina/Hello-Agents) | 智能体教程,原「智能旅行助手」示例所在仓库(`code/chapter13`) |
| [HelloAgents 框架](https://github.com/jjyaoao/HelloAgents) | 本项目 Agent/LLM 能力的底层框架(SimpleAgent 等) |
| [amap-mcp-server](https://github.com/sugarforever/amap-mcp-server) | 高德地图 MCP 服务器,提供 POI / 天气 / 路线工具 |
| [高德开放平台](https://lbs.amap.com/) | Web 服务 API 与 Web 端(JS API)地图能力 |

原项目的基础行程生成、地图展示、预算计算、手动编辑与导出功能均来自上述开源项目;
TravelMind 在其基础上重做了前端视觉与品牌,并新增了「AI 行程体检与智能修复」「突发事件动态重规划」
「攻略截图识别生成行程」三项功能及配套测试。

原作者信息已不在本仓库的提交历史中,原始历史请访问上述开源仓库。

---

**TravelMind** - 让旅行计划变得简单而智能 🌈

