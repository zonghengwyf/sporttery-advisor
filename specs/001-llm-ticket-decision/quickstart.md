# Quickstart: 验证 LLM 驱动的票型方案决策层

**Prerequisites**:
- Docker Compose 正常运行（`docker-compose up -d`）
- 已在设置页配置至少 1 个 LLM 模型（API Key 有效）
- 已有今日赛事（`POST /api/matches/sync` 同步）
- 已有至少 2 场赛事的 AI 分析（`POST /api/predictions/{match_id}` 或今日分析页触发）

---

## 场景 1: AI 全局决策生效（P1 核心验证）

**Setup**: 准备 4 场赛事，其中 2 场 risk_label=mainline、1 场 risk_label=guarded、1 场 risk_label=avoid。

**Steps**:
1. 选中全部 4 场赛事 → 点击"一键生成方案"（SSE 模式）
2. 查看 SSE 事件流，确认出现 "全局决策" 步骤 log（step="global_decision"）
3. 方案生成后，检查稳健方案是否只包含 mainline 场次（avoid 场次被排除）

**Expected**:
- 稳健方案包含 2 场（mainline）而非 4 场
- 方案 card 中出现 `ai_rationale` 文本，内容说明为何选这几场合串
- 控制台 / 后端 log 中无 "全局决策失败" 降级提示

**验证 `ai_rationale` 字段**:
```bash
curl -s -X POST http://localhost:8000/api/tickets/generate \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"match_ids": [1,2,3,4], "budget": 100}' \
  | python -m json.tool | grep -A3 "ai_rationale"
```
期望：`ai_rationale` 非空，长度 ≥ 30 字。

---

## 场景 2: 无需容错时不生成容错方案（AC: User Story 1, 场景 2）

**Setup**: 4 场赛事，全部 risk_label=mainline，`model_votes.agree == model_votes.total`（全票共识）。

**Steps**:
1. 生成方案
2. 检查 API 响应中是否没有 `conservative_cover` / `balanced_cover` key

**Expected**:
- 响应 `schemes` 中没有任何 `_cover` 后缀的 key
- 无容错方案卡片在前端展示

---

## 场景 3: 容错方案注数 ≤ 5（FR-003 强制）

**Setup**: 4 场赛事，AI 全局决策返回包含 cover 的指令（可通过 mock LLM 或真实配置带不确定场次触发）。

**Expected**:
- `conservative_cover.num_combos` ≤ 5
- 前端容错卡中注数显示 ≤ 5 注

---

## 场景 4: 全局决策 LLM 失败时降级（宪法原则六）

**Setup**: 暂时设置错误的 LLM API Key（或断网）。

**Steps**:
1. 生成方案
2. 检查 backend log 是否出现 "全局决策失败，降级 Python 规则"
3. 确认前端仍然有方案（使用 Python 规则生成）
4. 方案 `ai_rationale` 应为空或显示"全局决策不可用"

**Expected**: 功能降级可用，无 500 错误。

---

## 场景 5: 博高赔单选腿验证

**Setup**: 任意有博高赔腿的场次。

**Expected**:
- `high_odds` 方案下每条 leg 的 `picks.length === 1`（`num_picks === 1`）
- 前端博高赔方案不出现"覆盖X选"标签
- 不出现赔率列表 > 1 个

---

## 场景 6: 仅 1 场赛事时生成单关（Edge Case）

**Setup**: 只选 1 场赛事。

**Expected**:
- 竞彩串关需至少 2 场，返回 422 错误（现有行为）
- AI 全局决策 prompt 正确处理 1 场输入（不崩溃）

---

## 耗时验证（SC-005）

**Setup**: 选择 5 场已分析赛事（不触发新 AI 分析）。

**Steps**:
1. 记录请求发起时间
2. `POST /api/tickets/generate` 完成
3. 计算总耗时 vs 未引入全局决策前的基线

**Expected**: 总耗时增量 ≤ 15 秒。

---

## 接口参考

- [全局决策指令 contract](contracts/global-decision-directive.md)
- [数据模型](data-model.md)
- 后端入口：`api/tickets.py` — `generate_tickets` / `stream_tickets` / `_run_ticket_task`
- 核心新模块：`core/tickets/global_decision.py`
