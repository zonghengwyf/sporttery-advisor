# 竞彩足球投注顾问

基于统计概率模型 + 赛事情报 + 竞彩规则知识的 AI 驱动足球投注分析工具，为中国竞彩购彩者生成可直接购买的投注方案。

## 功能

- **今日分析** — 自动同步当日竞彩赛单，展示赔率快照与 AI 风险标签
- **单场详情** — Dixon-Coles 概率条图、赔率价值对比、情报摘要、一键 AI 分析
- **投注方案** — 稳健票 / 均衡票 / 博高赔票 / 比分小注 + 自动资金分配
- **AI 对话** — SSE 流式追问式分析，注入竞彩 Skills 领域知识
- **回测报告** — Brier / Log-loss / RPS / ECE 精度指标，对标竞彩 SP 基线
- **系统设置** — 多 LLM 模型配置 + 数据源 API Key 管理

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3 + Vite + Tailwind CSS + Pinia |
| 后端 | FastAPI (Python 3.11+) |
| LLM | 多模型统一客户端（Claude / GPT / Gemini / DeepSeek / Kimi / GLM / 自定义中转） |
| 统计模型 | Dixon-Coles + 市场融合 + 温度校准 |
| 快照存储 | DuckDB（预测历史、回测结果） |
| 主数据库 | PostgreSQL |
| 缓存 | Redis |
| 爬虫 | Playwright（无 API Key 时降级） |
| 调度 | APScheduler（每日 08:00 同步，09:00 分析） |
| 部署 | Docker Compose（5 个服务） |

## 快速开始

### 前置要求

- Docker & Docker Compose
- （可选）各数据源 API Key

### 启动

```bash
# 1. 克隆项目
git clone <repo-url> sporttery-advisor
cd sporttery-advisor

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填写 SECRET_KEY 和可选的数据源 Key

# 3. 启动所有服务
docker-compose up -d

# 4. 访问前端
open http://localhost:5173
```

### 环境变量

```env
# 必填
DATABASE_URL=postgresql+asyncpg://sporttery:sporttery@postgres:5432/sporttery
REDIS_URL=redis://redis:6379/0
DUCKDB_PATH=/app/data/snapshots/sporttery.duckdb
SKILLS_DIR=/app/skills
SECRET_KEY=your-secret-key-here

# 可选数据源 Key（留空时自动使用爬虫/免费源降级）
SPORTTERY_API_KEY=
ODDS_API_KEY=
API_FOOTBALL_KEY=
```

## 架构

```
Vue 3 Frontend
  └─ HTTP / SSE ──► FastAPI Backend
                      ├─ Layer 1: Dixon-Coles 统计概率
                      │           市场融合 + 温度校准
                      ├─ Layer 2: Skills 注入 + LLM 情报
                      │           伤停 / 战术 / 激励分析
                      └─ Layer 3: 竞彩票型生成 + 资金分配

数据源（优先级降级链）
  竞彩 API Key → Playwright 爬虫 → Redis 缓存 → 免费源

存储
  PostgreSQL — 用户 / 配置 / 赛事索引
  DuckDB    — 预测快照 / 回测结果
  Redis     — 接口缓存
```

### Skills 注入机制

不依赖 Claude Code 运行时。`core/llm/skills_injector.py` 将竞彩决策规则 Markdown 文件注入 LLM system prompt：

| Skills 文件 | 激活条件 |
|---|---|
| `SKILL.md` + `factor-model.md` + `sporttery-output.md` | 始终注入 |
| `tournament-incentives.md` | `is_tournament = True` |
| `form-context.md` | `has_abnormal_form = True` |

### 多模型支持

所有中国模型（DeepSeek / Kimi / GLM）均暴露 OpenAI 兼容 API，统一用 `base_url + api_key` 通过 openai SDK 调用，三方中转站同理。LLM 配置通过设置页持久化，无需修改代码。

## Docker Compose 服务

| 服务 | 说明 | 端口 |
|---|---|---|
| `frontend` | Vue 3 + Nginx | 5173 |
| `backend` | FastAPI | 8000 |
| `worker` | APScheduler 每日调度 | — |
| `postgres` | 主数据库 | 5432 |
| `redis` | 缓存 | 6379 |

## 目录结构

```
sporttery-advisor/
├── backend/
│   ├── api/                # FastAPI 路由
│   │   ├── auth.py         # JWT 认证
│   │   ├── matches.py      # 赛事列表 / 同步
│   │   ├── predictions.py  # 预测结果 / 批量状态
│   │   ├── tickets.py      # 投注方案生成
│   │   ├── chat.py         # SSE 流式对话
│   │   ├── backtest.py     # 回测指标
│   │   └── settings.py     # LLM / 数据源配置
│   ├── core/
│   │   ├── llm/
│   │   │   ├── client.py           # 多模型统一客户端
│   │   │   └── skills_injector.py  # Skills 注入系统
│   │   ├── modeling/
│   │   │   ├── dixon_coles.py      # Dixon-Coles 模型
│   │   │   ├── calibration.py      # 温度校准
│   │   │   ├── odds.py             # 去水差 + 价值评估
│   │   │   └── fusion.py           # 多源概率融合
│   │   ├── data/
│   │   │   ├── providers/          # 6 个数据提供者
│   │   │   ├── source_manager.py   # 降级链 + Redis 缓存
│   │   │   └── sync.py             # 赛单同步编排
│   │   ├── tickets/
│   │   │   └── generator.py        # 4 类票型 + 资金分配
│   │   └── pipeline.py             # 端到端分析流水线
│   ├── skills/                     # Skills Markdown 文件
│   ├── db/
│   │   ├── models.py               # SQLAlchemy ORM
│   │   └── session.py
│   └── workers/
│       ├── scheduler.py            # APScheduler
│       └── tasks.py
├── frontend/
│   └── src/
│       ├── views/                  # 6 个页面
│       ├── api.ts                  # Axios（Bearer token）
│       ├── router.ts
│       └── style.css               # 设计系统（CSS 变量 + 组件类）
└── docker-compose.yml
```

## 设计系统

Data-Dense Dashboard 风格，适配深色侧边栏 + 浅色内容区。

| Token | 用途 |
|---|---|
| `primary`（深海军蓝）| 主操作、导航激活态 |
| `accent`（琥珀）| 次要操作、警示 |
| `win / draw / loss` | 胜平负语义色 |
| `surface`（浅灰体系）| 背景、分割线 |
| Noto Sans SC | 中文正文 |
| Fira Code | 数字、赔率、概率值 |

## 开发进度

| 阶段 | 内容 | 状态 |
|---|---|---|
| Phase 1 | 骨架搭建：FastAPI + Vue 3 + 多模型 LLM + Skills 注入 | ✅ 完成 |
| Phase 2 | 统计模型：Dixon-Coles + 市场融合 + 校准 + DuckDB | ✅ 完成 |
| Phase 3 | 核心分析层：LLM 情报 + Skills 条件激活 + 票型生成 | ✅ 完成 |
| Phase 4 | 前端完整功能：概率图表 + 投注方案联调 + 分析状态徽章 | ✅ 完成 |
| Phase 5 | 生产化：多用户 JWT + 自动调度 + Docker 部署 | ⏳ 待 |

## 致谢

本项目整合以下两个项目的规则与模型：

- [china-sporttery-football-advisor](../china-sporttery-football-advisor/) — 竞彩决策规则 Skills（SKILL.md 等 5 个文件）
- [football-prediction-skill](../china-sporttery-football-advisor/football-prediction-skill/) — Dixon-Coles 统计模型参考实现

## 免责声明

本工具由 AI 基于统计概率和情报生成分析建议，不代表盈利承诺。购彩请量力而行，理性娱乐。
