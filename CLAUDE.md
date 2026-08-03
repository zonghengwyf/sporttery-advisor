# 竞彩足球投注顾问 — 项目上下文

## gstack

Use /browse from gstack for all web browsing. Never use mcp__claude-in-chrome__* tools.

### 全部可用 skills

**gstack 原生：**
/office-hours, /plan-ceo-review, /plan-eng-review, /plan-design-review,
/design-consultation, /design-shotgun, /design-html, /review, /ship, /land-and-deploy,
/canary, /benchmark, /browse, /open-gstack-browser, /qa, /qa-only, /design-review,
/setup-browser-cookies, /setup-deploy, /setup-gbrain, /sync-gbrain, /retro, /investigate,
/document-release, /document-generate, /codex, /cso, /autoplan, /pair-agent, /careful,
/freeze, /guard, /unfreeze, /gstack-upgrade, /learn, /spec, /diagram, /make-pdf,
/context-save, /context-restore, /plan-tune

**agent-skills（扩展包）：**
/ui-ux-pro-max, /design-taste-frontend, /high-end-visual-design, /frontend-ui-engineering,
/design-system, /ui-styling, /image-to-code,
/planning-and-task-breakdown, /incremental-implementation, /full-output-enforcement,
/source-driven-development, /spec-driven-development, /doubt-driven-development,
/test-driven-development, /debugging-and-error-recovery, /code-review-and-quality,
/security-and-hardening, /performance-optimization, /observability-and-instrumentation,
/api-and-interface-design, /idea-refine, /brand, /git-workflow-and-versioning,
/shipping-and-launch, /deprecation-and-migration, /context-engineering,
/slides, /devex-review, /plan-devex-review, /using-agent-skills, /skillify

### 本项目 Skill 流水线

**🎨 UI / 视觉设计（当前最高优先级）**
- 任何 UI 改动开始前 → `/ui-ux-pro-max`（定方向：风格 + 调色板 + 字体组合）
- 组件/页面重设计 → `/design-taste-frontend`（Anti-slop 实现，防 AI 默认美学）
- 高端科技感效果 → `/high-end-visual-design`（Barlow + 数据密集型仪表盘）
- 多方案对比 → `/design-shotgun`（生成 3 个方向，结构化反馈后收敛）
- Vue 组件落地 → `/frontend-ui-engineering`（可访问性、响应式、生产级）

**📋 功能规划**
- 新功能/产品讨论 → `/office-hours` → `/idea-refine` → `/spec`
- 任务拆分 → `/planning-and-task-breakdown`
- API 接口设计 → `/api-and-interface-design`
- 架构评审 → `/plan-eng-review`

**⚙️ 编码**
- 多文件改动 → `/incremental-implementation`（逐步落地，防大爆炸）
- 复杂逻辑/LLM 调用 → `/doubt-driven-development`（对抗性自审）
- 参考官方文档 → `/source-driven-development`（Vue 3 / FastAPI / SQLAlchemy）
- 需要测试覆盖 → `/test-driven-development`

**🔍 质量保障**
- 合并前代码审查 → `/review`
- 安全 / 鉴权 / 输入校验 → `/security-and-hardening` / `/cso`
- Bug 排查 → `/debugging-and-error-recovery` / `/investigate`
- 性能问题 → `/performance-optimization`
- 日志 / 告警 → `/observability-and-instrumentation`
- 防输出截断 → `/full-output-enforcement`（大文件生成时前置）

**🚀 交付**
- 功能验收 → `/qa http://localhost:5173`
- 发布准备 → `/shipping-and-launch`（checklist + rollback）
- 合并 / PR → `/ship`
- 文档 → `/document-release`

**🗂️ 上下文管理**
- 会话快照 → `/context-save` / `/context-restore`
- 切换任务前 → `/context-engineering`（重置上下文，提升质量）

## 项目概述

**产品名称**：竞彩足球投注顾问（Sporttery Advisor）

**核心价值**：为中国竞彩购彩者提供 AI 驱动的足球投注分析，基于统计概率模型 + 赛事情报 + 竞彩规则知识，生成可直接购买的投注方案。

**目标用户**：中国竞彩足球购彩者（非专业赌徒，普通彩票用户）

**主要功能**：
1. **今日分析** — 自动同步当日竞彩赛单，展示赔率和 AI 概率预测
2. **投注方案** — 稳健/均衡/博高赔 + M串N 容错方案（例如3串4等）+ 比分小注，Kelly 动态资金分配
3. **自动追踪** — 系统每日自动出票（设置页 DB 配置驱动开关/预算/时间），赛后同步赛果，生成「推荐→赛果→盈亏」时间线
4. **AI 对话** — 流式 SSE 追问式分析，注入 Skills 领域知识
5. **回测报告** — Brier / Log-loss / RPS / ECE 精度指标，对标竞彩 SP 基线
6. **系统设置** — LLM 多模型配置（含状态/token 用量监控）+ 数据源 API Key 管理 + 自动出票配置

**差异化**：
- Skills 注入机制：将 `china-sporttery-football-advisor` 的竞彩决策规则（控分识别、激励分析、异常阵型等）注入 LLM system prompt，不依赖 Claude Code 运行时
- 三层流水线：Dixon-Coles 统计 → Skills+LLM 情报 → 票型生成
- 多源降级：有 API Key 走 API，无 Key 走 Playwright 爬虫

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3 + Vite + Tailwind CSS + Pinia |
| 后端 | FastAPI (Python 3.11+) |
| LLM | 多模型统一客户端（Claude / GPT / Gemini / DeepSeek / Kimi / GLM / 自定义中转） |
| 统计模型 | Dixon-Coles + 市场融合 + 温度校准 |
| 快照存储 | DuckDB（预测历史、回测结果） |
| 主数据库 | PostgreSQL（用户、配置、赛事） |
| 缓存 | Redis |
| 爬虫 | Playwright（无 API Key 时） |
| 调度 | APScheduler（09:00 分析、整点赛果同步、定时自动出票，DB 配置驱动） |
| 部署 | Docker Compose（5 services） |

## 目录结构

```
sporttery-advisor/
├── backend/
│   ├── main.py                        # FastAPI 入口，lifespan 管理
│   ├── config.py                      # Settings (pydantic-settings, .env)
│   ├── api/
│   │   ├── auth.py                    # JWT 认证
│   │   ├── matches.py                 # 赛事列表/详情/手动同步
│   │   ├── predictions.py             # 预测结果查询
│   │   ├── tickets.py                 # 投注方案生成
│   │   ├── bets.py                    # 用户投注记录 CRUD（/api/bets）
│   │   ├── track.py                   # 自动出票追踪 + 赛果同步（/api/track）
│   │   ├── daily.py                   # 今日推荐方案 + 多模型集成分析（/api/daily）
│   │   ├── public.py                  # 公开分享端点，无需认证（/api/public）
│   │   ├── chat.py                    # SSE 流式 AI 对话
│   │   ├── backtest.py                # 回测指标（DuckDB）
│   │   └── settings.py                # LLM/数据源配置 CRUD
│   ├── core/
│   │   ├── llm/
│   │   │   ├── client.py              # 多模型统一客户端（含 token 用量捕获）
│   │   │   ├── usage.py               # LLM 调用用量/状态回写
│   │   │   └── skills_injector.py     # Skills Markdown 注入系统
│   │   ├── modeling/
│   │   │   ├── dixon_coles.py         # Dixon-Coles 拟合 + 预测
│   │   │   ├── calibration.py         # 温度校准
│   │   │   ├── odds.py                # 去水差 + 价值评估
│   │   │   ├── fusion.py              # 多源概率融合
│   │   │   ├── factor_scorer.py       # 8因素置信度评分（来自 factor-model.md）
│   │   │   ├── metrics.py             # 共享评估指标（RPS 等）
│   │   │   └── model_registry.py      # Champion/Challenger 模型注册 + DuckDB 晋升门控
│   │   ├── data/
│   │   │   ├── providers/
│   │   │   │   ├── sporttery.py       # 竞彩官方接口（在售 getMatchCalculatorV1 + 赛果 getMatchResultV1，免 Key）
│   │   │   │   ├── odds_api.py        # The Odds API 海外赔率/赛果降级
│   │   │   │   ├── api_football.py    # 伤停/阵容
│   │   │   │   ├── football_data.py   # 历史数据（免费）
│   │   │   │   └── clubelo.py         # Elo 评分（免费）
│   │   │   ├── source_manager.py      # 优先级降级链 + Redis 缓存
│   │   │   ├── snapshot.py            # DuckDB 快照管理
│   │   │   └── sync.py                # 赛单同步编排
│   │   ├── tickets/
│   │   │   ├── generator.py           # 票型生成器（Kelly 分配 + M串N 容错）
│   │   │   └── hhad.py                # 让球盘（HHAD）概率转换：HAD + 让球数 → 三结果分布
│   │   └── pipeline.py                # 每日端到端流水线（Phase 3）
│   ├── skills/                         # Skills Markdown 文件（注入 LLM）
│   │   ├── SKILL.md                   # 主工作流（来自 china-sporttery-football-advisor）
│   │   ├── factor-model.md            # 因素权重
│   │   ├── form-context.md            # 异常阵型/状态
│   │   ├── sporttery-output.md        # 竞彩输出格式
│   │   └── tournament-incentives.md   # 大赛激励分析
│   ├── db/
│   │   ├── models.py                  # SQLAlchemy ORM（User/LLMConfig/DataSourceConfig/Match/Prediction/ChatSession/AutoTicketRun）
│   │   └── session.py                 # AsyncSessionLocal + get_db
│   └── workers/
│       ├── scheduler.py               # APScheduler 每日调度
│       └── tasks.py                   # run_daily_sync / run_daily_analysis
├── frontend/
│   ├── src/
│   │   ├── layouts/MainLayout.vue     # 响应式布局（PC 侧边栏 + 移动底导航）
│   │   ├── components/
│   │   │   └── ChatFab.vue            # 浮动 AI 对话按钮（跨页面悬浮，可拖拽，含内联聊天面板）
│   │   ├── stores/
│   │   │   ├── auth.ts                # 用户认证状态（JWT）
│   │   │   ├── betting.ts             # 投注记录 + 方案状态
│   │   │   └── chat.ts                # 全局对话状态（ChatFab 共享）
│   │   ├── views/
│   │   │   ├── Login.vue              # 登录页
│   │   │   ├── DailyAnalysis.vue      # 今日赛事列表
│   │   │   ├── MatchDetail.vue        # 单场详情 + 概率图
│   │   │   ├── BettingTickets.vue     # 投注方案（动态 tab，含 M串N 容错）
│   │   │   ├── BetRecord.vue          # 自动出票追踪 + 赛果时间线（追踪页）
│   │   │   ├── BacktestReport.vue     # 回测精度报告
│   │   │   ├── ChatAnalysis.vue       # AI 流式对话
│   │   │   └── Settings.vue           # LLM/数据源配置
│   │   ├── api.ts                     # Axios 实例（Bearer token）
│   │   ├── router.ts                  # Vue Router（含登录守卫）
│   │   ├── style.css                  # 完整设计系统（CSS 变量 + 组件类）
│   │   └── tailwind.config.js         # 全量设计 token
│   └── vite.config.ts                 # Vite + /api 反向代理
├── docker-compose.yml                 # 5 services: frontend/backend/worker/postgres/redis
├── DESIGN.md                          # 产品设计文档（/office-hours 输出）
└── docs/
    ├── ARCHITECTURE.md                # 技术架构文档（/plan-eng-review 输出）
    ├── AUTO_TRACK_DESIGN.md           # 自动追踪功能设计（数据模型 + 菜单决策）
    ├── TRACK_PAGE_REQUIREMENTS.md     # 追踪页面详细需求（2026-07-31）
    └── adr/                           # Architecture Decision Records
        ├── TEMPLATE.md                # ADR 写作模板
        ├── ADR-001-skills-injection.md
        ├── ADR-002-duckdb-postgres-split.md
        ├── ADR-003-llm-openai-compat.md
        ├── ADR-004-data-source-fallback.md
        ├── ADR-005-model-registry-champion-challenger.md
        └── ADR-006-clv-tracking-and-rps-gate.md
```

## 当前进度

### ✅ Phase 1 — 骨架搭建（完成）
- Docker Compose 5 服务配置
- FastAPI 主应用 + 所有 API 路由骨架
- PostgreSQL 数据模型（User / LLMConfig / DataSourceConfig / Match / Prediction / ChatSession）
- 多模型 LLM 统一客户端（Claude SDK + OpenAI 兼容通用层）
- Skills 注入系统（SkillsInjector，条件激活 5 个 Markdown skills）
- SSE 流式 AI 对话（`/api/chat/stream`）
- JWT 认证
- Vue 3 完整前端骨架（初始 6 个页面）
- 响应式布局（PC 深色侧边栏 + 移动端底导航）
- 完整设计系统（Tailwind + CSS 变量，Data-Dense Dashboard 风格）

### ✅ Phase 2 — 数据与统计层（完成）
- Dixon-Coles 模型（L-BFGS-B + τ 低比分修正 + 时间衰减）
- 温度校准（logit 缩放 + softmax）
- 去水差（multiplicative / Power / Shin）+ 价值评估
- 多源概率融合（加权几何均值 + LLM 情报修正）
- 6 个数据提供者（竞彩 API / Playwright 爬虫 / The Odds API / API-Football / football-data.co.uk / ClubElo）
- SourceManager 优先级降级链 + Redis 缓存
- DuckDB 快照管理（预测 + 回测结果）
- 赛单同步编排（upsert PostgreSQL + DuckDB 快照）
- 手动触发同步接口 `POST /matches/sync`
- 回测指标接口（接入 DuckDB）
- workers/tasks.py 真实实现

### ✅ Phase 3 — 核心分析层（完成）
- `core/pipeline.py` 三层流水线（Dixon-Coles → Skills+LLM → 票型生成）
- `core/tickets/generator.py` 4 类票型 + 多场合并 + 资金分配
- `api/predictions.py` 单场同步/异步分析触发 + `GET /batch` 批量状态端点
- `api/tickets.py` 多场合并票型接口联通前端

### ✅ Phase 4 — 前端完整功能（完成）
- 所有页面调用真实 API（无占位符数据）
- `DailyAnalysis.vue`：赛事卡显示分析状态徽章（调用 `/predictions/batch`）
- `BettingTickets.vue`：emoji → Heroicons SVG 图标（符合预检清单）
- `BacktestReport.vue`：ECharts 置信度趋势图（按 risk_label 颜色分组）
- `MatchDetail.vue`：概率条图、赔率对比、立即 AI 分析按钮
- `ChatAnalysis.vue`：SSE 流式对话，关联比赛上下文
- 设计审查（ui-ux-pro-max）：确认设计系统对齐 Data-Dense Dashboard 规范

### ✅ Phase 5 — 自动出票追踪（完成）
- `BetRecord.vue`：自动出票追踪页面，含整体统计、分类准确率、收益分析、选项精度、赛果分布
- `api/track.py`：历史出票列表、单次详情、赛果同步（`/api/track`）
- `api/bets.py`：用户投注记录 CRUD（`/api/bets`）
- `api/daily.py`：今日推荐方案 + 多模型集成分析（`/api/daily`）
- `api/public.py`：公开分享端点（`/api/public`）
- `db/models.py`：新增 `AutoTicketRun` 表（出票记录 + 赛果结果）
- 导航整合：底部导航新增「追踪」菜单项

### ⏳ Phase 6 — 生产化（待）
- 完整 JWT 多用户流程
- Docker 完整打包 + 部署文档
- ~~APScheduler 每日自动调度~~（已完成：09:00 分析 / 整点赛果同步 / 定时自动出票）

## 关键设计决策

### Skills 注入机制
不依赖 Claude Code 运行时。在 `backend/core/llm/skills_injector.py` 中：
- 始终注入：SKILL.md + factor-model.md + sporttery-output.md
- 条件注入：tournament-incentives.md（is_tournament=True）
- 条件注入：form-context.md（has_abnormal_form=True）
- 统计概率注入：将 Dixon-Coles 输出格式化后附加到 system prompt

### 多模型适配
所有中国模型（DeepSeek / Kimi / GLM）均暴露 OpenAI 兼容 API。统一用 `base_url + api_key` 通过 openai SDK 调用。三方中转站同理。

### 数据源降级
赛果降级链：竞彩赛果接口（getMatchResultV1，批量）→ 竞彩在售接口（当天完赛）→ The Odds API /scores → 人工录入（/api/backtest/record）。情报源：ClubElo / football-data.co.uk 等免费源。

### 时区约定（重要）
`Match.kickoff_at` 存**北京时间 naive datetime**。任何与当前时间的比较必须用 `datetime.utcnow() + timedelta(hours=8)`，直接用 `utcnow()` 会晚 8 小时（曾导致赛果同步/出票同步失效）。

### 自动出票配置（DB 驱动）
开关/预算/时间存 `DataSourceConfig`（`source_name="auto_ticket"`，UI 设置页维护），scheduler 始终注册任务、每轮读 DB 逐用户执行（当日幂等）；cron 启动时优先取 DB。env 的 `AUTO_TICKET_*` 仅为兼底默认，`AUTO_TICKET_ENABLED` 已废弃。

### M串N 容错方案
3~4 场全单选腿时自动生成容错方案（3串4 / 4串11，全部 2串1~n串1 子组合），`combo_sizes` 字段标识；中奖概率/等效赔率用 2^n 枚举精确计算；结算（`_compute_run_roi` / `track._serialize_run`）按中奖子组合独立派奖。多选腿不做容错（注数爆炸、无官方命名）。

### LLM 状态与用量
`LLMConfig` 记录 status/last_error/last_used_at/累计调用与 token；`client.chat()` 捕获 API usage，`record_llm_usage` 异步回写（不阻断主流程）；设置页展示。API 不提供真实余额查询，展示的是累计 token 消耗。

### 市场角色分离
- REFERENCE：用于生成先验概率（海外盘口）
- TARGET：竞彩赔率（仅用于价值对比，不参与概率生成）
- BENCHMARK：历史基线

## 开发规范

### 前端设计规范（强制）
- **移动端优先**：视口 < 768px 为主要设计目标；PC（≥768px）为兼容适配。所有交互元素最小点击区域 44×44px，触摸优先
- **所有前端页面改动必须同时调用 `design-taste-frontend` + `ui-ux-pro-max-skill` 两个技能**
- 先用 `/design-taste-frontend` 输出 Design Read + 拨盘设定，再执行实现
- 本项目 UI 基调：Data-Dense Dashboard，VARIANCE:5 / MOTION:2 / DENSITY:9
- 禁止 AI 默认美学（紫色渐变、居中 Hero、三等分 feature 卡）
- 图标统一用 SVG inline（项目已有约定），禁止 emoji 代替图标

### 语言
- 回复中文
- 代码注释简洁，仅注释"为什么"，不注释"是什么"

### 代码风格
- Python：类型注解 + dataclass，异步优先（async/await）
- Vue：`<script setup lang="ts">` + Composition API
- 禁止在 API 边界之外添加防御性 try/except

### 数据库
- 所有 DB 操作通过 `get_db()` 依赖注入的 AsyncSession
- DuckDB 仅用于快照（预测历史、回测），不存用户数据

### 测试验证
- Phase 1 验证：`docker-compose up` → 前端可访问 → 设置页保存 LLM 配置并测试连通
- Phase 2 验证：`POST /matches/sync` → `/api/matches/` 返回今日赛单
- Phase 3 验证：`/api/predict/{match_id}` 返回完整 JSON（概率 + 情报 + 风险标签）
- Phase 4 验证：前端投注方案页显示 4 类票型，AI 对话流式回答

## 环境变量（.env）

```env
DATABASE_URL=postgresql+asyncpg://sporttery:sporttery@postgres:5432/sporttery
REDIS_URL=redis://redis:6379/0
DUCKDB_PATH=/app/data/snapshots/sporttery.duckdb
SKILLS_DIR=/app/skills
SECRET_KEY=your-secret-key-here

# 可选数据源 Key（留空使用爬虫/免费源）
SPORTTERY_API_KEY=
ODDS_API_KEY=
API_FOOTBALL_KEY=
```

## 参考资料

本项目整合两个现有项目：
- `../china-sporttery-football-advisor/` — 竞彩决策规则 Skills（SKILL.md 等 5 个文件）
- `../football-prediction-skill/` — Dixon-Coles 统计模型参考实现
- `../sports-skills/`

## Skill routing

When the user's request matches an available skill, **invoke it via the Skill tool before doing anything else.** When in doubt, invoke the skill.

### UI / 视觉设计
- 任何 UI 改动、重设计、科技感升级 → invoke /ui-ux-pro-max 确定方向，再 invoke /design-taste-frontend 实现
- 高端视觉效果、仪表盘美化 → invoke /high-end-visual-design
- 需要多方案对比 → invoke /design-shotgun
- Vue 组件生产级实现 → invoke /frontend-ui-engineering
- HTML 原型 → invoke /design-html
- 设计系统 / Token → invoke /design-system

### 需求 / 规划
- 产品讨论、头脑风暴 → invoke /office-hours
- 想法细化 → invoke /idea-refine
- 写 spec / 需求文档 → invoke /spec
- 任务拆分 → invoke /planning-and-task-breakdown
- API / 接口设计 → invoke /api-and-interface-design
- 架构评审 → invoke /plan-eng-review
- 策略评审 → invoke /plan-ceo-review

### 编码
- 多文件改动 → invoke /incremental-implementation
- 高风险 / 复杂逻辑 → invoke /doubt-driven-development
- 需参考文档 → invoke /source-driven-development
- 需要测试 → invoke /test-driven-development
- 大段代码生成防截断 → invoke /full-output-enforcement

### 质量 / 调试
- 代码审查 → invoke /review
- 完整 review 流水线 → invoke /autoplan（仅 PR 上线前）
- Bug 排查 → invoke /investigate 或 /debugging-and-error-recovery
- 安全审计 → invoke /cso 或 /security-and-hardening
- 性能 → invoke /performance-optimization
- 日志 / 监控 → invoke /observability-and-instrumentation
- QA 验收 → invoke /qa http://localhost:5173

### 交付
- Ship / PR → invoke /ship 或 /land-and-deploy
- 发布检查 → invoke /shipping-and-launch
- 文档 → invoke /document-release

### 上下文
- 保存进度 → invoke /context-save
- 恢复上下文 → invoke /context-restore
- 任务切换前清理 → invoke /context-engineering
