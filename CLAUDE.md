# 竞彩足球投注顾问 — 项目上下文

## gstack

Use /browse from gstack for all web browsing. Never use mcp__claude-in-chrome__* tools.

Available skills: /office-hours, /plan-ceo-review, /plan-eng-review, /plan-design-review,
/design-consultation, /design-shotgun, /design-html, /review, /ship, /land-and-deploy,
/canary, /benchmark, /browse, /open-gstack-browser, /qa, /qa-only, /design-review,
/setup-browser-cookies, /setup-deploy, /setup-gbrain, /sync-gbrain, /retro, /investigate,
/document-release, /document-generate, /codex, /cso, /autoplan, /pair-agent, /careful, /freeze,
/guard, /unfreeze, /gstack-upgrade, /learn, /spec, /diagram, /make-pdf.

**Skill routing for this project:**
- 新功能规划 → `/office-hours` → `/plan-ceo-review` → `/plan-eng-review`
- 编码完成后 → `/review` → `/qa http://localhost:5173` → `/ship`
- 安全检查 → `/cso`
- 架构文档 → `/document-release`

## 项目概述

**产品名称**：竞彩足球投注顾问（Sporttery Advisor）

**核心价值**：为中国竞彩购彩者提供 AI 驱动的足球投注分析，基于统计概率模型 + 赛事情报 + 竞彩规则知识，生成可直接购买的投注方案。

**目标用户**：中国竞彩足球购彩者（非专业赌徒，普通彩票用户）

**主要功能**：
1. **今日分析** — 自动同步当日竞彩赛单，展示赔率和 AI 概率预测
2. **投注方案** — 生成稳健票/均衡票/博高赔票/比分小注 + 资金分配
3. **AI 对话** — 流式 SSE 追问式分析，注入 Skills 领域知识
4. **回测报告** — Brier / Log-loss / RPS / ECE 精度指标，对标竞彩 SP 基线
5. **系统设置** — LLM 多模型配置 + 数据源 API Key 管理

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
| 调度 | APScheduler（每日 08:00 同步，09:00 分析） |
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
│   │   ├── chat.py                    # SSE 流式 AI 对话
│   │   ├── backtest.py                # 回测指标（DuckDB）
│   │   └── settings.py                # LLM/数据源配置 CRUD
│   ├── core/
│   │   ├── llm/
│   │   │   ├── client.py              # 多模型统一客户端
│   │   │   └── skills_injector.py     # Skills Markdown 注入系统
│   │   ├── modeling/
│   │   │   ├── dixon_coles.py         # Dixon-Coles 拟合 + 预测
│   │   │   ├── calibration.py         # 温度校准
│   │   │   ├── odds.py                # 去水差 + 价值评估
│   │   │   └── fusion.py              # 多源概率融合
│   │   ├── data/
│   │   │   ├── providers/
│   │   │   │   ├── sporttery_api.py   # 竞彩官方 API
│   │   │   │   ├── sporttery_scraper.py # Playwright 爬虫降级
│   │   │   │   ├── odds_api.py        # The Odds API 海外赔率
│   │   │   │   ├── api_football.py    # 伤停/阵容
│   │   │   │   ├── football_data.py   # 历史数据（免费）
│   │   │   │   └── clubelo.py         # Elo 评分（免费）
│   │   │   ├── source_manager.py      # 优先级降级链 + Redis 缓存
│   │   │   ├── snapshot.py            # DuckDB 快照管理
│   │   │   └── sync.py                # 赛单同步编排
│   │   ├── tickets/
│   │   │   └── generator.py           # 票型生成器（Phase 3 完善）
│   │   └── pipeline.py                # 每日端到端流水线（Phase 3）
│   ├── skills/                         # Skills Markdown 文件（注入 LLM）
│   │   ├── SKILL.md                   # 主工作流（来自 china-sporttery-football-advisor）
│   │   ├── factor-model.md            # 因素权重
│   │   ├── form-context.md            # 异常阵型/状态
│   │   ├── sporttery-output.md        # 竞彩输出格式
│   │   └── tournament-incentives.md   # 大赛激励分析
│   ├── db/
│   │   ├── models.py                  # SQLAlchemy ORM（6 个模型）
│   │   └── session.py                 # AsyncSessionLocal + get_db
│   └── workers/
│       ├── scheduler.py               # APScheduler 每日调度
│       └── tasks.py                   # run_daily_sync / run_daily_analysis
├── frontend/
│   ├── src/
│   │   ├── layouts/MainLayout.vue     # 响应式布局（PC 侧边栏 + 移动底导航）
│   │   ├── views/
│   │   │   ├── Login.vue              # 登录页
│   │   │   ├── DailyAnalysis.vue      # 今日赛事列表
│   │   │   ├── MatchDetail.vue        # 单场详情 + 概率图
│   │   │   ├── BettingTickets.vue     # 投注方案 4 票型
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
    └── ARCHITECTURE.md                # 技术架构文档（/plan-eng-review 输出）
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
- Vue 3 完整前端（6 个页面全部实现）
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

### ⏳ Phase 5 — 生产化（待）
- 完整 JWT 多用户流程
- APScheduler 每日自动调度
- Docker 完整打包 + 部署文档

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
SourceManager 优先级：`竞彩 API Key → Playwright 爬虫 → Redis 缓存 → 免费源（ClubElo / football-data.co.uk）`

### 市场角色分离
- REFERENCE：用于生成先验概率（海外盘口）
- TARGET：竞彩赔率（仅用于价值对比，不参与概率生成）
- BENCHMARK：历史基线

## 开发规范

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
- `../china-sporttery-football-advisor/football-prediction-skill/` — Dixon-Coles 统计模型参考实现

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
- Author a backlog-ready spec/issue → invoke /spec
