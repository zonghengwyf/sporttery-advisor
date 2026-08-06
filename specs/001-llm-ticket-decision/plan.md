# Implementation Plan: LLM 驱动的票型方案决策层

**Branch**: `001-llm-ticket-decision` | **Date**: 2026-08-05 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-llm-ticket-decision/spec.md`

## Summary

在完成所有单场分析（Layer 1 统计 + Layer 2 LLM）之后，增加一次 **全局 LLM 决策调用**，输出结构化的票型结构指令（TicketStructureDirective），决定每个方案纳入哪几场、是否生成容错以及容错逻辑。Python 层保留精确的赔率计算、Kelly 注额分配和 EV 验证，只有"结构决策"上移到 AI。同步清除 博高赔 多选腿逻辑（max_picks=1）和机械式 M串N 子组合生成。

## Technical Context

**Language/Version**: Python 3.11 (backend) + TypeScript / Vue 3 (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy AsyncSession (PostgreSQL), OpenAI 兼容统一 LLM 客户端 (`core/llm/client.py`), Redis (任务状态)

**Storage**: PostgreSQL `predictions.tickets` JSONB 字段（无需 schema 变更，JSON 结构灵活），Redis 任务缓存

**Testing**: Docker Compose 集成验证（无自动化测试套件），手动端到端验证

**Target Platform**: Linux Docker（FastAPI 异步服务）

**Project Type**: Web service (FastAPI backend + Vue 3 frontend)

**Performance Goals**: 全局决策 LLM 调用增量 ≤ +15s（SC-005）；与现有 per-match 分析复用同一 LLM 客户端

**Constraints**:
- 全局决策 MUST 以统计概率和 risk_label 为依据（宪法原则一）
- Kelly 分配和 EV 验算 MUST 保留在 Python（FR-004）
- 容错方案总注数 MUST NOT 超过 5 注（FR-003）
- 全局决策失败时 MUST 降级回现有 Python 规则（宪法原则六：可降级）

**Scale/Scope**: 每日通常 5-10 场赛事；全局决策为 1 次额外 LLM 调用

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 状态 | 说明 |
|------|------|------|
| 一、统计纪律高于情报直觉 | ✅ PASS | AI 全局决策 prompt 必须注入每场的 `risk_label` + `confidence` + `fused_probs`，AI 只能在统计框架内调整结构；Python 层执行 min_win_prob 门槛仍然有效 |
| 二、透明度是唯一的信任货币 | ✅ PASS | 每个方案新增 `ai_rationale` 字段（≥30字），前端展示；排除场次在 UI 可见但标注原因 |
| 三、风控优先于收益最大化 | ✅ PASS | Kelly 分配保留在 Python；容错方案 Python 层强制 ≤5 注门槛；全局决策不影响注额计算 |
| 四、竞彩规则知识是专业护城河 | ✅ PASS | 全局决策 prompt 通过 SkillsInjector 注入竞彩 Skills（同现有 per-match 分析） |
| 五、移动场景下核心信息一屏可见 | ✅ PASS | `ai_rationale` 作为折叠展开内容，不影响核心一屏信息 |
| 六、系统可用性不绑定单一外部依赖 | ✅ PASS | 全局决策失败时 `directive=None`，降级回现有 Python 规则，功能保持可用 |

## Project Structure

### Documentation (this feature)

```text
specs/001-llm-ticket-decision/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── global-decision-directive.md
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
backend/
  core/
    tickets/
      generator.py        # MODIFY: remove multi-pick in high_odds; accept directive param; add ai_rationale to ParlayPlan
      global_decision.py  # NEW: LLMGlobalDecision — builds prompt, calls LLM, parses directive
  api/
    tickets.py            # MODIFY: inject global decision call before generate_parlay_plans (3 call sites)

frontend/
  src/views/
    BettingTickets.vue    # MODIFY: render ai_rationale per scheme (already has scheme card structure)
```

**Structure Decision**: Web application (Option 2). Minimal footprint — 1 new file, 3 modified files, no schema migration.

## Complexity Tracking

No constitution violations requiring justification.
