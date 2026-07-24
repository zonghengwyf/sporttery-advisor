# 技术架构文档

> 本文档由 `/plan-eng-review` 生成并维护。

## 系统架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                     Vue 3 Frontend (Nginx)                       │
│  DailyAnalysis │ MatchDetail │ BettingTickets │ Chat │ Settings  │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP/SSE  (/api/*)
┌──────────────────────────▼──────────────────────────────────────┐
│                    FastAPI Backend (:8000)                        │
│                                                                  │
│  ┌──────────────┐  ┌─────────────────┐  ┌───────────────────┐  │
│  │  Layer 1     │  │    Layer 2       │  │     Layer 3       │  │
│  │  统计模型     │  │  情报 + Skills   │  │   票型生成        │  │
│  │  Dixon-Coles │  │  注入 LLM        │  │  资金分配         │  │
│  │  市场融合    │  │  伤停/战术/动力  │  │  竞彩格式化       │  │
│  └──────┬───────┘  └────────┬────────┘  └─────────┬─────────┘  │
│         └──────────────────┬┘──────────────────────┘            │
│  ┌──────────────────────────▼────────────────────────────────┐  │
│  │                     Data Layer                             │  │
│  │  SportteryAPI → SportteryScraper → OddsAPI → APIFootball  │  │
│  │  ClubElo (free) │ football-data.co.uk (free historical)   │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                      LLM Layer                            │   │
│  │  Claude │ GPT │ Gemini │ DeepSeek │ Kimi │ GLM │ Custom  │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
          │                           │
    PostgreSQL                     DuckDB
  用户/配置/赛事/预测            快照/回测历史
  ChatSession                     prediction_snapshots
                                   backtest_results
```

## 数据流

### 每日同步流（08:00 APScheduler）

```
APScheduler.run_daily_sync()
  │
  ├─ SourceManager.get_daily_matches(date)
  │    ├─ [有 SportteryAPIKey] SportteryAPI.get_daily_matches()
  │    └─ [无 Key] SportteryScraper.get_daily_matches() [Playwright]
  │
  ├─ SourceManager.get_overseas_odds()
  │    └─ [有 OddsAPIKey] OddsAPI.get_odds_for_leagues()
  │
  ├─ sync_daily_matches(session, source_manager, snapshot)
  │    ├─ Upsert to PostgreSQL matches 表
  │    └─ Save to DuckDB match_snapshots
  │
  └─ Redis cache 写入 (matches:{date}, odds_api:latest)
```

### 每日分析流（09:00 APScheduler，Phase 3）

```
APScheduler.run_daily_analysis()
  │
  └─ DailyPipeline.run(date)
       │
       ├─ 1. 加载今日 Match 列表（PostgreSQL）
       │
       ├─ 2. Layer 1 — 统计模型
       │    ├─ ClubElo.get_match_elos(home, away)   [免费]
       │    ├─ DCParams 拟合（历史数据，懒加载）
       │    ├─ dixon_coles.predict_probs()
       │    ├─ TemperatureCalibrator.transform()
       │    ├─ remove_vig(overseas_odds, method="power")
       │    └─ PredictionFusion.fuse({dc, market, elo})
       │
       ├─ 3. Layer 2 — 情报 + LLM
       │    ├─ APIFootball.get_injuries(fixture_id)
       │    ├─ SkillsInjector.build_system_prompt(context)
       │    │    ├─ 始终：SKILL.md + factor-model.md + sporttery-output.md
       │    │    ├─ 条件：tournament-incentives.md (is_tournament)
       │    │    └─ 条件：form-context.md (has_abnormal_form)
       │    ├─ LLMClient.chat(messages, system_prompt)
       │    └─ 解析 LLM 输出 → intel_summary + risk_label + intel_adjustment
       │
       ├─ 4. Layer 3 — 票型生成
       │    └─ TicketGenerator.generate(predictions, budget)
       │         ├─ conservative: 60% 本金，高置信腿
       │         ├─ balanced:     25% 本金，主观点+防守腿
       │         ├─ high_odds:    10% 本金，含平局/冷门
       │         └─ scoreline:    5%  本金，比分覆盖
       │
       └─ 5. 写入 PostgreSQL predictions 表 + DuckDB prediction_snapshots
```

### SSE 对话流（用户发起）

```
前端 fetch('/api/chat/stream', {method:'POST'})
  │
  └─ chat.py:stream_chat()
       ├─ 加载 LLMConfig（用户默认模型）
       ├─ 加载关联 Match + Prediction（若有 match_id）
       ├─ SkillsInjector.build_system_prompt(context)
       ├─ LLMClient.chat_stream(messages, system_prompt)
       │    └─ yield AsyncGenerator[str]
       └─ StreamingResponse(text/event-stream)
            data: {"content": "..."}
            data: {"done": true, "session_id": 123}
```

## 数据库 Schema

### PostgreSQL（核心业务数据）

```sql
-- 用户
users: id, username, email, hashed_password, is_admin, created_at

-- LLM 配置（每用户可配多个）
llm_configs: id, user_id, name, provider(enum), model,
             api_key(encrypted), base_url, is_default

-- 数据源配置
datasource_configs: id, user_id, source_name, api_key,
                    use_scraper, enabled, extra_config(jsonb)

-- 赛事
matches: id, sporttery_id, home_team, away_team, league,
         kickoff_at, sale_date, available_markets(jsonb),
         sporttery_odds(jsonb), overseas_odds(jsonb), is_tournament

-- 预测
predictions: id, match_id→matches, run_id, stat_probs(jsonb),
             intel_summary, risk_label, confidence, tickets(jsonb),
             llm_provider, llm_model, created_at

-- 对话
chat_sessions: id, user_id→users, match_id→matches,
               title, messages(jsonb array), created_at, updated_at
```

### DuckDB（分析快照）

```sql
prediction_snapshots: id, match_id, run_id, observed_at, kickoff_at,
                      stat_probs(json), fused_probs(json), intel_summary,
                      risk_label, confidence, model_version

match_snapshots: id, sporttery_id, observed_at, sale_date,
                 home_team, away_team, league, sporttery_odds(json),
                 overseas_odds(json), source, raw_data(json)

backtest_results: id, match_id, run_date, predicted(json),
                  actual(H/D/A), brier, log_loss, rps
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/auth/login | JWT 登录 |
| POST | /api/auth/register | 注册 |
| GET  | /api/matches/ | 今日赛事列表（?sale_date=） |
| GET  | /api/matches/{id} | 单场详情 |
| POST | /api/matches/sync | 手动触发同步 |
| GET  | /api/predictions/{match_id} | 预测结果 |
| POST | /api/tickets/generate | 生成投注方案 |
| POST | /api/chat/stream | SSE 流式对话 |
| GET  | /api/chat/sessions | 历史会话列表 |
| GET  | /api/chat/sessions/{id} | 会话详情 |
| GET  | /api/backtest/metrics | 回测精度指标 |
| GET  | /api/backtest/history | 历史预测记录 |
| POST | /api/backtest/record | 录入实际结果 |
| GET  | /api/settings/llm | LLM 配置列表 |
| POST | /api/settings/llm | 新增 LLM 配置 |
| POST | /api/settings/llm/{id}/test | 测试连通 |
| DELETE | /api/settings/llm/{id} | 删除配置 |
| GET  | /api/settings/datasource | 数据源配置 |
| PUT  | /api/settings/datasource | 更新数据源配置 |

## 边界条件与失败处理

| 场景 | 处理方式 |
|------|---------|
| 竞彩 API 返回空 | 自动降级 Playwright 爬虫，失败时返回空列表 |
| Playwright 爬虫失效 | 返回 Redis 缓存（最长 4h），前端标注数据时效 |
| LLM API 超时/错误 | 仅返回统计层结果，intel_summary 为 null |
| Dixon-Coles 无训练数据 | 降级 `predict_from_features(elo, xg)` |
| DuckDB 写失败 | 记录日志，不影响主流程 |
| PostgreSQL 连接失败 | 返回 503，前端显示"服务暂时不可用" |

## 安全考虑

- API Key 存储：PostgreSQL `api_key` 字段应加密（Phase 5 完善）
- JWT：7 天有效期，secret_key 通过 env 注入
- 爬虫 User-Agent：模拟真实浏览器，避免被封
- LLM 输出：不直接渲染 HTML（防 XSS），统一 `whitespace-pre-wrap` 纯文本

## 性能目标

| 指标 | 目标值 |
|------|-------|
| 赛事列表加载 | < 200ms（Redis 缓存命中） |
| 单场详情 | < 500ms |
| LLM 首 token | < 3s |
| 投注方案生成 | < 10s（含 LLM 调用） |
| Dixon-Coles 拟合 | < 30s（5 赛季数据，~15k 场次） |
| 每日同步任务 | < 5min |
