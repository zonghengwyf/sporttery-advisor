"""LLM 全局票型方案决策层

在所有单场分析完成后，调用 LLM 做一次全局结构决策：
  - 哪几场进入稳健/均衡/博高赔方案
  - 是否需要容错方案及针对哪条腿
  - 每个方案的串关结构说明（ai_rationale）

make_global_decision() 是唯一公开接口，失败时返回 None（调用方降级到 Python 规则）。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"

# ── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class CoverDirective:
    trigger_match_id: int
    rationale: str


@dataclass
class SchemeDirective:
    match_ids: list[int]
    rationale: str
    cover: CoverDirective | None = None


@dataclass
class ExcludedMatch:
    match_id: int
    reason: str


@dataclass
class TicketStructureDirective:
    conservative: SchemeDirective | None
    balanced: SchemeDirective | None
    high_odds: SchemeDirective | None
    excluded: list[ExcludedMatch] = field(default_factory=list)
    no_recommendation: bool = False
    raw_text: str = ""


# ── Prompt 构建 ───────────────────────────────────────────────────────────────

def _load_skills_text() -> str:
    skill_files = ["SKILL.md", "factor-model.md", "sporttery-output.md"]
    parts: list[str] = []
    for fname in skill_files:
        p = _SKILLS_DIR / fname
        if p.exists():
            try:
                parts.append(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    return "\n\n---\n\n".join(parts)


_GLOBAL_DECISION_INSTRUCTION = """
---

## 全局方案结构决策任务

你是竞彩足球投注方案设计师。以下是今日所有场次的分析摘要。

你的任务：基于各场次的统计概率、风险标签和置信度，决定哪几场进入稳健串关，哪几场进入均衡串关，哪几场进入博高赔，并判断是否需要容错方案。

**决策原则（宪法约束）**：
1. 你的决策 MUST 以统计概率和 risk_label 为依据，MUST NOT 仅凭情报印象调整方案结构
2. 容错方案仅在存在明显不确定性的场次时使用，MUST NOT 机械地给所有方案加容错
3. 若今日场次质量整体低，应给出"无推荐方案"而非强行凑数
4. 每个方案的 rationale MUST 包含"为什么选这几场合串"的判断依据，不少于15个中文字
5. 如果某个方案不适合（如今日没有高置信场次），将该 key 设为 null

**串关最低要求**：每个方案至少 2 场才能构成串关。单场不串关。

**输出格式**：完成分析后，在回复最后输出以下 JSON 代码块（勿省略）：

```json
{
  "conservative": {
    "match_ids": [1, 3],
    "rationale": "两场均为 mainline 标签，主胜概率均超55%，统计EV正向，串关中奖率可接受",
    "cover": null
  },
  "balanced": {
    "match_ids": [1, 2],
    "rationale": "均衡配置含平局保护，两场整体风险可控",
    "cover": {
      "trigger_match_id": 2,
      "rationale": "第2场模型共识仅1/2，存在分歧，容错保底防单腿失误"
    }
  },
  "high_odds": {
    "match_ids": [4],
    "rationale": "第4场客队赔率高于统计价值，小额博高赔"
  },
  "excluded": [
    {"match_id": 6, "reason": "置信度仅32%，risk_label=avoid，不纳入任何方案"}
  ],
  "no_recommendation": false
}
```

注意：match_ids 中的数字必须来自下面的赛事列表；如今日整体质量差，设 "no_recommendation": true 并将其他方案 key 设为 null。
"""


def _build_prompt(enriched_preds: list[dict]) -> tuple[str, str]:
    system = _load_skills_text() + _GLOBAL_DECISION_INSTRUCTION

    lines = [f"今日竞彩赛事分析摘要（{len(enriched_preds)} 场）：\n"]
    for item in enriched_preds:
        match = item["match"]
        pred = item["prediction"]
        votes = item.get("ensemble_votes", [])

        fp = (pred.fused_probs or pred.stat_probs or {}) if pred else {}
        h = fp.get("home", 0.33)
        d = fp.get("draw", 0.28)
        a = fp.get("away", 0.39)
        ev_h = fp.get("ev_home", 0.0)
        ev_d = fp.get("ev_draw", 0.0)
        ev_a = fp.get("ev_away", 0.0)

        risk = (pred.risk_label or "guarded") if pred else "guarded"
        conf = (pred.confidence or 0.5) if pred else 0.5
        intel = (pred.intel_summary or "") if pred else ""

        tickets = (pred.tickets or {}) if pred else {}
        cons_pick = (tickets.get("conservative_leg") or {})
        bal_pick = (tickets.get("balanced_leg") or {})
        ho_pick = (tickets.get("high_odds_leg") or {})

        agree = sum(1 for v in votes if v.get("outcome") == _pick_to_outcome(cons_pick.get("pick", "")))
        total_votes = len(votes)
        votes_str = f"{agree}/{total_votes}" if total_votes else "N/A"

        lines.append(
            f"场次 ID {match.id}：{match.home_team} vs {match.away_team}（{match.league or ''}）\n"
            f"  统计概率：主胜 {h:.0%} / 平 {d:.0%} / 客胜 {a:.0%}\n"
            f"  EV：主胜 {ev_h:+.3f} / 平 {ev_d:+.3f} / 客胜 {ev_a:+.3f}\n"
            f"  风险标签：{risk} | 置信度：{conf:.0%}\n"
            f"  AI 分析摘要：{intel[:60] if intel else '无'}\n"
            f"  模型共识：{votes_str}\n"
            f"  稳健腿推荐：{cons_pick.get('pick', '—')}（{cons_pick.get('market', '胜平负')}）\n"
            f"  均衡腿推荐：{bal_pick.get('pick', '—')}（{bal_pick.get('market', '胜平负')}）\n"
            f"  博高赔腿推荐：{ho_pick.get('pick', ho_pick.get('picks', '—'))}（{ho_pick.get('market', '胜平负')}）\n"
        )

    lines.append("\n请完成全局方案结构决策并输出要求的 JSON 代码块。")
    return system, "\n".join(lines)


def _pick_to_outcome(pick: str) -> str:
    return {"主胜": "H", "平局": "D", "客胜": "A"}.get(pick, "")


# ── 解析 ──────────────────────────────────────────────────────────────────────

def _parse_directive(text: str, valid_ids: set[int]) -> TicketStructureDirective | None:
    decoder = json.JSONDecoder()
    raw: dict | None = None

    # 1. 优先匹配 ```json ... ``` 代码块
    for m in re.finditer(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL):
        try:
            raw = json.loads(m.group(1))
            break
        except json.JSONDecodeError:
            pass

    # 2. 从尾部反向找 {
    if raw is None:
        for i in range(len(text) - 1, -1, -1):
            if text[i] == "{":
                try:
                    obj, _ = decoder.raw_decode(text[i:])
                    if isinstance(obj, dict) and ("conservative" in obj or "no_recommendation" in obj):
                        raw = obj
                        break
                except json.JSONDecodeError:
                    continue

    if raw is None:
        logger.warning("全局决策：无法从 LLM 输出提取 JSON")
        return None

    no_rec = bool(raw.get("no_recommendation", False))

    _KEY_CN = {"conservative": "稳健串关", "balanced": "均衡串关", "high_odds": "博高赔"}

    def _parse_scheme(key: str) -> SchemeDirective | None:
        s = raw.get(key)
        if not s or not isinstance(s, dict):
            return None
        ids = [i for i in (s.get("match_ids") or []) if isinstance(i, int) and i in valid_ids]
        if len(ids) < 2:
            return None
        rationale = str(s.get("rationale") or "")
        if len(rationale) < 30:
            rationale = f"AI 全局结构决策：依据各场统计概率与风险标签，将以上场次纳入{_KEY_CN.get(key, key)}方案"

        cover_raw = s.get("cover")
        cover: CoverDirective | None = None
        if cover_raw and isinstance(cover_raw, dict):
            tid = cover_raw.get("trigger_match_id")
            if isinstance(tid, int) and tid in valid_ids and tid in ids:
                cover = CoverDirective(
                    trigger_match_id=tid,
                    rationale=str(cover_raw.get("rationale") or "AI 决定容错保底"),
                )

        return SchemeDirective(match_ids=ids, rationale=rationale, cover=cover)

    excluded_raw = raw.get("excluded") or []
    excluded: list[ExcludedMatch] = []
    for ex in excluded_raw:
        if isinstance(ex, dict):
            mid = ex.get("match_id")
            if isinstance(mid, int) and mid in valid_ids:
                excluded.append(ExcludedMatch(match_id=mid, reason=str(ex.get("reason") or "")))

    return TicketStructureDirective(
        conservative=_parse_scheme("conservative"),
        balanced=_parse_scheme("balanced"),
        high_odds=_parse_scheme("high_odds"),
        excluded=excluded,
        no_recommendation=no_rec,
        raw_text=text,
    )


# ── 公开接口 ──────────────────────────────────────────────────────────────────

async def make_global_decision(
    enriched_preds: list[dict],
    llm_client,
) -> TicketStructureDirective | None:
    if not enriched_preds:
        return None

    valid_ids = {item["match"].id for item in enriched_preds}
    logger.info("全局决策：开始调用，输入 %d 场，match_ids=%s", len(enriched_preds), sorted(valid_ids))

    system_prompt, user_message = _build_prompt(enriched_preds)

    raw_text = await llm_client.chat(
        messages=[{"role": "user", "content": user_message}],
        system=system_prompt,
        max_tokens=1024,
    )

    try:
        from core.llm.usage import record_llm_usage
        await record_llm_usage(llm_client.db_config_id, llm_client.last_usage)
    except Exception as _ue:
        logger.debug("全局决策：用量记录失败（非致命）: %s", _ue)

    directive = _parse_directive(raw_text, valid_ids)
    if directive is None:
        return None

    if directive.no_recommendation:
        logger.info("全局决策：AI 判断今日无推荐方案")
    else:
        summary = {
            k: len(getattr(directive, k).match_ids) if getattr(directive, k) else 0
            for k in ("conservative", "balanced", "high_odds")
        }
        logger.info("全局决策完成：%s，排除 %d 场", summary, len(directive.excluded))

    return directive
