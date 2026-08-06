# Data Model: LLM 驱动的票型方案决策层

**Generated**: 2026-08-05

## 新增实体（内存，不持久化）

### TicketStructureDirective

AI 全局决策输出的结构化指令。在请求生命周期内存在，不写入数据库。

```python
@dataclass
class CoverDirective:
    trigger_match_id: int   # 触发容错的场次 ID
    rationale: str          # AI 给出的容错理由

@dataclass
class SchemeDirective:
    match_ids: list[int]    # 纳入此方案的场次 ID 列表（≥2 才能串关）
    rationale: str          # AI 对此方案结构的说明（≥30 字）
    cover: CoverDirective | None  # None = 无需容错

@dataclass
class ExcludedMatch:
    match_id: int
    reason: str             # AI 排除此场的理由

@dataclass
class TicketStructureDirective:
    conservative: SchemeDirective | None   # None = AI 判断今日无稳健方案
    balanced:     SchemeDirective | None   # None = AI 判断今日无均衡方案
    high_odds:    SchemeDirective | None   # None = AI 判断今日无博高赔腿
    excluded:     list[ExcludedMatch]      # 被主动排除的场次
    no_recommendation: bool                # True = 今日整体不推荐
    raw_text: str                          # LLM 原始响应（用于审计）
```

**验证规则（Python 强制，不依赖 AI 输出正确性）**:
- `SchemeDirective.match_ids` 中的 ID 必须在 `enriched_preds` 中存在；无效 ID 静默过滤
- `SchemeDirective.rationale` 长度 < 10 字时替换为 "AI 全局决策理由不可用"
- `CoverDirective` 生成的方案总注数 > 5 时，Python 降级为 `combo_sizes=[n]`（普通 n串1，不做容错）

---

### ParlayPlan（扩展）

在现有 `ParlayPlan` dataclass 基础上增加字段：

```python
@dataclass
class ParlayPlan:
    # ... 现有字段不变 ...
    ai_rationale: str = ""          # NEW: AI 全局决策给出的方案结构说明
    ai_excluded: list[dict] = field(default_factory=list)  # NEW: 被排除的场次 [{match_id, reason}]
```

`to_dict()` 输出中新增：
```json
{
  "ai_rationale": "三场均高置信，主场优势明显，统计概率支撑>55%，整体串关风险可控",
  "ai_excluded": [
    {"match_id": 42, "reason": "置信度仅38%，与统计先验分歧明显，建议本场不纳入串关"}
  ]
}
```

---

## 修改实体

### API 响应 `schemes` 字典

`_build_schemes()` 中每个方案 dict 新增两字段（已由 `plan.to_dict()` 提供）：

```json
{
  "conservative": {
    "name": "稳健串关",
    "ai_rationale": "...",
    "ai_excluded": [...],
    ...
  }
}
```

---

## 无 Schema 变更

- PostgreSQL `predictions` 表不变
- `Prediction.tickets` JSONB 存 per-match 分析结果，不存 global directive（理由见 research.md 决策 6）
- Redis 任务 key 格式不变

---

## 状态转换

```
用户触发方案生成
  ↓
enriched_preds 汇总完成（所有场次均有 prediction）
  ↓
[NEW] LLMGlobalDecision.make() → TicketStructureDirective
  ↓ (失败时 directive=None，降级)
generate_parlay_plans(enriched_preds, ..., directive=directive)
  ↓ directive 非 None 时：按 match_ids 过滤腿，AI rationale 写入 ParlayPlan
  ↓ directive 为 None 时：现有 _RISK_WEIGHT 规则（保持向后兼容）
  ↓
plans → _build_schemes → response（含 ai_rationale / ai_excluded）
```
