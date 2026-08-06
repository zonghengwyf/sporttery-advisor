# Contract: LLM 全局决策指令

**Type**: Internal Python API (module-level function)
**File**: `backend/core/tickets/global_decision.py`

---

## Public API

```python
async def make_global_decision(
    enriched_preds: list[dict],
    llm_client: LLMClient,
) -> TicketStructureDirective | None:
    """
    在所有单场分析完成后，调用 LLM 做全局票型结构决策。

    enriched_preds: 每项 {match, prediction, ensemble_votes}
    llm_client: 已初始化的 LLMClient（从调用方复用，不新建连接）

    返回 TicketStructureDirective，或 None（LLM 调用失败时降级）。
    """
```

---

## LLM Prompt 结构

### System Prompt

```
[SkillsInjector 竞彩规则知识（SKILL.md + factor-model.md + sporttery-output.md）]

---

## 全局方案结构决策

你是竞彩足球投注方案设计师。以下是今日所有场次的分析摘要。

你的任务是：基于各场次的统计概率、风险标签和置信度，
决定哪几场进入稳健串关，哪几场进入均衡串关，哪几场进入博高赔，
并判断是否需要容错方案。

**决策原则（宪法约束）**：
1. 你的决策 MUST 以统计概率和 risk_label 为依据，MUST NOT 仅凭情报印象
2. 容错方案仅在存在明显不确定性的场次时使用，MUST NOT 机械地给所有方案加容错
3. 若今日场次质量整体低，应给出"无推荐方案"而非强行凑数
4. 每个方案的理由说明 MUST 包含"为什么选这几场合串"的判断依据

**输出要求**：最后输出以下 JSON 代码块：

```json
{
  "conservative": {
    "match_ids": [1, 3, 5],
    "rationale": "三场均为 mainline 标签，置信度均高于65%，统计主胜概率>55%，串关预期价值正向",
    "cover": null
  },
  "balanced": {
    "match_ids": [1, 2],
    "rationale": "两场均衡配置，含平局保护，整体中奖率可接受",
    "cover": {
      "trigger_match_id": 2,
      "rationale": "第2场模型共识仅1/2，存在分歧，加容错保底以防单腿失误"
    }
  },
  "high_odds": {
    "match_ids": [4],
    "rationale": "第4场客队赔率偏高，统计EV正向，小额博高赔"
  },
  "excluded": [
    {"match_id": 6, "reason": "置信度仅32%，risk_label=avoid，不纳入任何方案"}
  ],
  "no_recommendation": false
}
```

**注意**：
- match_ids 中的数字必须来自下面的赛事列表
- 每个 rationale 必须解释"为什么"，不少于15个中文字
- 如果某个方案不适合（如今日没有高置信场次），将该 key 设为 null
- 容错 cover 的 trigger_match_id 必须在对应方案的 match_ids 中
- 如今日整体质量差，设 "no_recommendation": true，conservative/balanced/high_odds 全为 null
```

### User Message 结构

```
今日竞彩赛事分析摘要（{n} 场）：

场次 ID {match_id}：{home_team} vs {away_team}（{league}）
  统计概率：主胜 {home:.0%} / 平 {draw:.0%} / 客胜 {away:.0%}
  EV：主胜 {ev_home:+.3f} / 平 {ev_draw:+.3f} / 客胜 {ev_away:+.3f}
  风险标签：{risk_label} | 置信度：{confidence:.0%}
  AI 分析摘要：{intel_summary}
  模型共识：{model_votes.agree}/{model_votes.total}
  稳健腿推荐：{conservative_pick.pick}（{conservative_pick.market}）
  均衡腿推荐：{balanced_pick.pick}（{balanced_pick.market}）
  博高赔腿推荐：{high_odds_pick.pick}（{high_odds_pick.market}）

... [每场重复]

请完成全局方案结构决策并输出要求的 JSON 代码块。
```

---

## 输出解析

```python
def _parse_directive(text: str, valid_ids: set[int]) -> TicketStructureDirective:
    """解析 LLM 输出，过滤无效 match_id，校验必填字段。"""
```

解析失败时返回 `None`（调用方降级到 Python 规则）。

---

## 调用方集成示例

```python
# api/tickets.py 中的调用点（3 处统一提取为辅助函数）
async def _make_global_decision_safe(enriched_preds, llm_client) -> TicketStructureDirective | None:
    try:
        from core.tickets.global_decision import make_global_decision
        return await make_global_decision(enriched_preds, llm_client)
    except Exception as e:
        logger.warning("全局决策失败，降级 Python 规则: %s", e)
        return None
```

---

## 错误行为

| 场景 | 行为 |
|------|------|
| LLM 调用超时/网络错误 | 返回 `None`（降级） |
| JSON 解析失败 | 返回 `None`（降级） |
| match_ids 包含不存在 ID | 静默过滤无效 ID |
| cover 注数 > 5 注 | Python 层截断为普通 n串1 |
| rationale 长度 < 10 字 | 替换为默认文本 |
| `no_recommendation=true` | `generate_parlay_plans` 返回空 plans（触发现有 `_empty_plans_reason` 逻辑） |
