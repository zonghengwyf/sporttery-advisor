# Tasks: LLM 驱动的票型方案决策层

**Input**: Design documents from `specs/001-llm-ticket-decision/`

**Prerequisites**: plan.md ✅ spec.md ✅ research.md ✅ data-model.md ✅ contracts/ ✅

**Organization**: Tasks grouped by user story for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no conflicting edits)
- **[Story]**: Which user story this task belongs to

---

## Phase 1: Setup — 无需（复用现有项目结构）

本功能不引入新的依赖包、无迁移、无新路由注册，直接进入 Foundational 阶段。

---

## Phase 2: Foundational（所有 User Story 的阻塞前提）

**Purpose**: 建立核心数据结构和新模块骨架，US1/US2/US3 均依赖此阶段

**⚠️ CRITICAL**: 此阶段完成前不能开始任何 User Story 工作

- [ ] T001 在 `backend/core/tickets/generator.py` 的 `ParlayPlan` dataclass 中增加 `ai_rationale: str = ""` 和 `ai_excluded: list[dict] = field(default_factory=list)` 字段，并在 `to_dict()` 中输出
- [ ] T002 创建 `backend/core/tickets/global_decision.py`：定义 `CoverDirective`、`SchemeDirective`、`ExcludedMatch`、`TicketStructureDirective` 四个 dataclass（见 data-model.md），不含任何业务逻辑

**Checkpoint**: `generator.py` 中的 `ParlayPlan.to_dict()` 输出包含 `ai_rationale`；`global_decision.py` 可以被 import 无报错

---

## Phase 3: User Story 1 — AI 决定当天串关组合（Priority: P1）🎯 MVP

**Goal**: AI 全局决策替代 Python `_RISK_WEIGHT` 阈值分桶，决定哪几场进入每个方案；博高赔改为单选腿

**Independent Test**: 选 4 场已分析赛事（含 1 场 risk_label=avoid）→ 生成方案 → 稳健/均衡方案不包含 avoid 场次；后端 log 中出现"全局决策调用"记录；`ai_rationale` 字段非空

### Implementation for User Story 1

- [ ] T003 [US1] 在 `backend/core/tickets/global_decision.py` 中实现 `_build_prompt(enriched_preds)` 函数：构建 system prompt（读取 skills 目录中 SKILL.md + factor-model.md + sporttery-output.md 并拼接全局决策指令）和 user message（每场摘要：match_id、队名、统计概率、EV、risk_label、confidence、intel_summary、model_votes、各腿推荐）。参考 `contracts/global-decision-directive.md` 中的完整 prompt 模板。
- [ ] T004 [US1] 在 `backend/core/tickets/global_decision.py` 中实现 `_parse_directive(text, valid_ids)` 函数：从 LLM 输出提取 ```json 代码块（复用 `pipeline._parse_llm_response` 模式），将解析结果映射为 `TicketStructureDirective`；过滤不在 `valid_ids` 中的 match_id；rationale 长度 < 10 字时替换为默认文本；解析失败时返回 None
- [ ] T005 [US1] 在 `backend/core/tickets/global_decision.py` 中实现 `async def make_global_decision(enriched_preds, llm_client) -> TicketStructureDirective | None`：调用 `_build_prompt`、`llm_client.chat()`（`max_tokens=1024`）、`_parse_directive`；记录 `logger.info` 调用入口和结果摘要；任何异常 catch 后 return None（降级）
- [ ] T006 [US1] 修改 `backend/core/tickets/generator.py` 中的 `generate_parlay_plans()` 签名，增加 `directive: TicketStructureDirective | None = None` 参数；当 `directive` 非 None 时，对每个方案（conservative/balanced/high_odds）将 `enriched_predictions` 过滤为 `directive.{plan}.match_ids` 中的场次（替代 `_RISK_WEIGHT` 阈值判断）；当 `directive.no_recommendation` 为 True 时提前返回空 plans；保持 `directive=None` 时现有行为不变（向后兼容）
- [ ] T007 [US1] 修改 `backend/core/tickets/generator.py` 第 462 行：将 `_make_leg(ho)` 改为 `_make_leg(ho, max_picks=1)` 并更新同行注释（博高赔改为单选，删除"允许多选覆盖"说明）
- [ ] T008 [US1] 在 `backend/api/tickets.py` 中新增辅助函数 `async def _make_global_decision_safe(enriched_preds, llm_client) -> TicketStructureDirective | None`：try/except 包裹 `make_global_decision()`，异常时 `logger.warning("全局决策失败，降级 Python 规则: %s", e)` 并 return None
- [ ] T009 [US1] 修改 `backend/api/tickets.py` 中的 `generate_tickets()` 函数：在 `enriched_preds` 汇总完成、调用 `generator.generate_parlay_plans()` 之前，调用 `_make_global_decision_safe(enriched_preds, <active_llm_client>)` 获取 `directive`，并将其传入 `generate_parlay_plans()`；`<active_llm_client>` 在 force（Ensemble）路径取 `llm_configs[0]` 的 client，非 force 路径取 `_get_user_llm_client(db, current_user.id)` 结果（已有引用复用）
- [ ] T010 [US1] 修改 `backend/api/tickets.py` 中的 `stream_tickets()` 内部 `_generate()` 函数：在 `gen.generate_parlay_plans()` 调用前注入全局决策调用（与 T009 相同逻辑），并在 SSE 事件流中推送 `_sse("step", step="global_decision", msg="AI 全局方案结构决策…", index=2, total=5)`（将现有 index=2,3 调整为 3,4，total 改为 5）
- [ ] T011 [US1] 修改 `backend/api/tickets.py` 中的 `_run_ticket_task()` 函数：在 `gen.generate_parlay_plans()` 调用前注入全局决策调用（与 T009 相同逻辑），并 `await push("step", step="global_decision", msg="AI 全局方案结构决策…", index=2, total=5)`

**Checkpoint**: 生成方案时后端 log 出现"全局决策"记录；稳健方案只含 AI 指定场次；博高赔每条腿 `num_picks==1`

---

## Phase 4: User Story 2 — AI 决定容错方案（Priority: P2）

**Goal**: AI 判断是否需要容错及针对哪条腿容错，替代机械式 `range(2, n+1)` 全子组合；Python 层强制注数 ≤5

**Independent Test**: 准备 3 场赛事（第 2 场 confidence 低）→ 生成方案 → 稳健容错方案只替换第 2 腿而非生成 3串4（4注）；全票共识时无任何 `_cover` 方案

### Implementation for User Story 2

- [ ] T012 [US2] 修改 `backend/core/tickets/generator.py` 中 `generate_parlay_plans()` 的容错生成逻辑（当前位于 line 492-501）：当 `directive` 非 None 时，仅当 `directive.{plan_id}.cover` 非 None 时生成容错方案；生成前校验：`list(range(2, n+1))` 产生的 num_combos > 5 时，截断为 `combo_sizes=[n-1, n]`（仅保留最小两级子组合）使注数 ≤5，日志 warning；当 `directive` 为 None 时保持现有行为（向后兼容）
- [ ] T013 [US2] 在 `backend/core/tickets/generator.py` 的容错方案 `ParlayPlan` 构建处，将 `directive.{plan_id}.cover.rationale` 写入 `cover_plan.ai_rationale`（格式："[容错说明] " + cover.rationale）

**Checkpoint**: 全票共识场次不产生任何 `_cover` key；意见分歧场次产生容错且 `num_combos ≤ 5`；`ai_rationale` 包含容错理由

---

## Phase 5: User Story 3 — AI 给出方案结构的理由（Priority: P2）

**Goal**: 每个方案 card 展示 AI 撰写的串关结构说明（≥30 字，与单腿 rationale 不重叠）；被排除场次在 UI 可见但标注原因

**Independent Test**: 生成方案后，`GET /api/tickets/generate` 响应中每个主方案的 `ai_rationale` 长度 ≥ 30 字；前端方案 card 中能看到方案级说明文字；被排除场次（`ai_excluded`）信息展示在方案卡底部

### Implementation for User Story 3（Backend）

- [ ] T014 [P] [US3] 修改 `backend/core/tickets/generator.py` 中 `generate_parlay_plans()`：当 `directive` 非 None 时，将 `directive.{plan_id}.rationale` 写入对应 `ParlayPlan.ai_rationale`；将 `directive.excluded` 写入各 `ParlayPlan.ai_excluded`（所有方案共享排除列表）

### Implementation for User Story 3（Frontend）

- [ ] T015 [P] [US3] 修改 `frontend/src/views/BettingTickets.vue`：在 `activeScheme` 计算属性或 scheme 展示区增加对 `scheme.ai_rationale` 字段的读取；在方案 card 头部（stars 评分行下方）新增 `ai-rationale` 折叠区块：默认折叠，点击展开显示 `scheme.ai_rationale` 全文（样式：`text-xs text-muted`，前缀图标：robot/brain 简单 SVG 或无图标）；仅当 `scheme.ai_rationale` 非空时显示
- [ ] T016 [US3] 修改 `frontend/src/views/BettingTickets.vue`：读取 `activeScheme.ai_excluded` 数组；当数组非空时，在方案 card 底部（容错卡上方）渲染 `ai-excluded-banner`，格式："本场未纳入方案：{home} vs {away} — {reason}"（每项一行），样式使用 `text-xs text-muted` 带左边框 `border-l-2 border-yellow-400`；`ai_excluded` 通过 match_id 对应到 `enriched_preds` 获取队名（后端 `_build_schemes` 已有 `mid_to_league` 映射，需扩展为包含队名的 `mid_to_match_info`）
- [ ] T017 [US3] 修改 `backend/api/tickets.py` 中 `_build_schemes()` 函数：将 `mid_to_league` 扩展为 `mid_to_info` dict（包含 `league`、`home_team`、`away_team`），并在每个 scheme 的 legs 处使用；同时将 `plan.ai_excluded` 中的 match_id 解析为 `{match_id, home_team, away_team, reason}` 格式输出（而非仅含 ID）

**Checkpoint**: 前端方案 card 展示 AI 结构说明；被排除场次信息可见；说明文字与单腿 rationale 内容不重叠

---

## Phase 6: Polish & Cross-Cutting

**Purpose**: 可观测性、LLM 用量追踪、验收

- [ ] T018 [P] 在 `backend/core/tickets/global_decision.py` 的 `make_global_decision()` 中，LLM 调用后异步调用 `record_llm_usage(llm_client.db_config_id, llm_client.last_usage)`（复用 `pipeline._layer2_llm` 中的模式），将全局决策 token 计入 LLM 用量统计
- [ ] T019 [P] 在 `backend/core/tickets/global_decision.py` 中补充 `logger.info` 输出：调用前记录输入场次数，解析成功后记录各方案 match_ids 数量和是否 no_recommendation
- [ ] T020 按 `specs/001-llm-ticket-decision/quickstart.md` 中的 6 个场景手动验收：全局决策生效、无需容错时不生成、容错 ≤5 注、降级、博高赔单选、耗时 ≤+15s

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundational (Phase 2)**: 无前置，立即开始；T001 和 T002 可并行
- **Phase 3 (US1)**: 依赖 T001 + T002 完成；T003-T005 可并行；T006 依赖 T003-T005；T007 独立；T008-T011 依赖 T006
- **Phase 4 (US2)**: 依赖 T006（已 accept directive param）；T012 依赖 T006，T013 依赖 T012
- **Phase 5 (US3)**: 依赖 T006 + T014（backend）；T014-T015 并行；T016-T017 依赖 T015/T014
- **Phase 6 (Polish)**: 依赖所有前置 Story 完成

### User Story Dependencies

- **US1 (P1)**: 依赖 Foundational 完成 → 唯一 MVP 交付单元
- **US2 (P2)**: 依赖 US1 完成（使用 directive 参数）→ 增强层
- **US3 (P2)**: 依赖 US1 完成（需要 ai_rationale 字段）→ 可与 US2 并行

### Parallel Opportunities

- T001 ‖ T002（Foundational 内）
- T003 ‖ T004 ‖ T007（US1 内，不同函数）
- T009 ‖ T010 ‖ T011（US1 内，3 个注入点，同文件但不同函数）
- T014 ‖ T015（US3 内，backend + frontend 并行）
- T018 ‖ T019（Polish 内）

---

## Parallel Example: User Story 1

```text
# 第一批（Foundational 完成后立即并行）：
Task T003: _build_prompt() in global_decision.py
Task T004: _parse_directive() in global_decision.py
Task T007: 博高赔 max_picks=1 in generator.py

# 第二批（T003+T004 完成后）：
Task T005: make_global_decision() in global_decision.py

# 第三批（T005+T006 完成后，3 个调用点并行）：
Task T009: generate_tickets() injection
Task T010: stream_tickets() injection
Task T011: _run_ticket_task() injection
```

---

## Implementation Strategy

### MVP（仅 User Story 1）

1. 完成 Foundational（T001, T002）
2. 完成 US1（T003-T011）
3. **停止验收**：后端 log 确认全局决策生效；博高赔单选；API 响应含 `ai_rationale` 字段
4. 可选继续 US2/US3

### 完整交付顺序

1. Foundational → US1 → **验收 MVP**
2. US2（容错 AI 化）→ **验收容错行为**
3. US3（前端展示 rationale）→ **验收 UI**
4. Polish（用量追踪 + 完整 quickstart 验收）

---

## Notes

- [P] = 不同函数/文件，无未完成任务的依赖，可并行执行
- T006 是最关键的改动（`generate_parlay_plans` 接受 directive），其他任务均依赖它或与它无关
- 博高赔多选清除（T007）是独立的单行修改，可随时先做
- 所有改动对 `directive=None` 保持完全向后兼容，降级路径天然存在
- 不需要 DB migration，不需要新 API 路由
- 总任务数：20 个（T001-T020）
