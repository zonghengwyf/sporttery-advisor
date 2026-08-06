# Research: LLM 驱动的票型方案决策层

**Generated**: 2026-08-05

## 决策 1: 全局决策调用点

**Decision**: 在 `api/tickets.py` 中，`enriched_preds` 汇总完成后、调用 `generate_parlay_plans` 之前注入全局决策调用。

**Rationale**: `api/tickets.py` 已经汇聚了所有场次的 `prediction`（含 `risk_label`、`confidence`、`fused_probs`、`ensemble_votes`），且 LLM 客户端在此时已可用（Ensemble 或单模型）。调用点一致且集中，3 个入口（`generate_tickets` / `stream_tickets` / `_run_ticket_task`）均可共享同一辅助函数。

**Alternatives considered**:
- 在 `DailyPipeline.run()` 末尾调用：不适用，因为前端触发的临时分析（非每日调度）走 tickets API，不经过 pipeline.run()。
- 新增独立 API 端点：增加调用复杂度，前端需两次请求。

---

## 决策 2: 结构化指令格式

**Decision**: AI 输出 JSON 代码块，Python 用正则 + `json.loads` 解析（复用 `_parse_llm_response` 模式）。

**Rationale**: 与现有 per-match LLM 解析保持一致（`pipeline._parse_llm_response`）。输出格式明确、有限，LLM 容易遵守。

**Alternatives considered**:
- Pydantic model validation directly：需要完全正确的 JSON；但 LLM 偶有格式瑕疵，先用 `json.loads` 再做 Python 校验更鲁棒。
- 纯自然语言 + NLP 提取：可靠性差，违反 FR-006（必须结构化）。

---

## 决策 3: 降级策略

**Decision**: 全局决策 LLM 调用失败时，`directive=None`，`generate_parlay_plans` 使用现有 `_RISK_WEIGHT` 规则。此时方案仍然生成，但 `ai_rationale` 留空（或标注"全局决策不可用"）。

**Rationale**: 宪法原则六要求系统可用性不依赖单一外部依赖。全局决策是增强层，不是必要层。

---

## 决策 4: 博高赔 multi-pick 清除

**Decision**: 在 `generator.py` 第 462 行将 `_make_leg(ho)` 改为 `_make_leg(ho, max_picks=1)`，同时更新注释移除"博高赔允许多选覆盖"说明。

**Rationale**: 总监评审已确认多选腿是根本性设计缺陷（赔率显示混乱、注数膨胀、方向不明）。spec Assumptions 节明确"博高赔策略改为单选腿"。

**Alternatives considered**:
- 保留 multi-pick 但在前端隐藏：治标不治本，后端仍生成错误数据。

---

## 决策 5: 容错方案上限强制点

**Decision**: 在 `generate_parlay_plans` 的容错生成处（现有 `combo_sizes=list(range(2, n+1))` 处），当 `directive` 提供且 `directive.{plan}.cover` 为 `None` 时跳过容错；当 directive 提供 cover 时，生成的 `combo_sizes` 由 Python 验证总注数 ≤5，超限则截断而非报错。

**Rationale**: FR-003 要求总注数 ≤5。Python 层做强制门槛，AI 的容错建议仅为参考，最终注数由 Python 保证。

---

## 决策 6: ai_rationale 在 Prediction 中的持久化

**Decision**: `ai_rationale` 附加在 `ParlayPlan.to_dict()` 输出中，随 `plans → schemes` 响应返回前端；不单独持久化到数据库（Prediction.tickets 已存 per-match AI 输出，全局决策是请求时生成的方案级结论）。

**Rationale**: `Prediction.tickets` 存的是单场分析结果。方案是多场组合的派生产物，每次请求可重新生成（含全局决策）。无需额外列或 schema 变更。

**Alternatives considered**:
- 存入 `Prediction.tickets` 的 `global_rationale` 字段：多场共享一个 Prediction 中不合逻辑；方案是跨场的，不属于单场预测。

---

## 决策 7: Skills 注入

**Decision**: 全局决策 prompt 使用 `SkillsInjector` 注入通用竞彩规则（不使用单场 `MatchContext`，而是构造一个 `scheme_context` dict 传入自定义 system prompt）。

**Rationale**: `SkillsInjector.build_system_prompt` 目前要求 `MatchContext`（单场），全局决策是多场场景。新建 `global_decision.py` 直接使用 `SkillsInjector._load_skill_file()` 内部方法或读取 skills 目录，拼接多场上下文 prompt。

---

## 决策 8: 缓存

**Decision**: 不缓存全局决策结果。每次用户点击"重新生成方案"都获得新的 AI 决策。

**Rationale**: 全局决策是响应式的——如果 prediction 数据未变但用户 budget 或倍数变了，方案结构应重新评估。实现缓存的 key 设计复杂（须包含 match_ids + predictions hash + budget），成本高收益低。
