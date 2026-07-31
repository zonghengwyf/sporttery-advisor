# 自动追踪功能设计文档

## 一句话定位

系统每天自动生成投注方案、赛后自动同步结果，产生一条可回溯的「AI 推荐 → 实际赛果 → 盈亏」的时间线，用于评估系统实用性和准确率。

---

## 菜单位置决策

**结论：新增独立菜单「追踪」**，插入在「方案」和「战绩」之间。

| 菜单 | 意图 | 行为主体 |
|------|------|---------|
| 方案 | 生成本次投注建议 | 用户主动触发 |
| **追踪** | 查看系统历史推荐 & 准确率 | 系统自动 |
| 战绩 | 记录用户实际下注结果 | 用户主动记录 |
| 回测 | 统计模型的 Brier/RPS 精度 | 技术指标 |

「追踪」和「回测」的区别：回测看的是概率模型的校准度，追踪看的是完整链路（出票→赛果→盈亏）的实用价值。两者都重要，但受众不同：追踪是日常使用者看的，回测是调参时看的。

PC 端侧边栏增加一项。移动端底导航从 5 项扩到 6 项时过密 — 建议将「回测」移入「设置」或合并为二级页（回测本身使用频率低），腾出底导航位置给「追踪」。

---

## 核心数据模型

### AutoTicketRun（新表）

```python
class AutoTicketRun(Base):
    __tablename__ = "auto_ticket_runs"

    id          = Column(Integer, primary_key=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False)
    run_date    = Column(Date, nullable=False)           # 出票日期
    trigger     = Column(String, default="scheduled")    # scheduled / manual
    model_info  = Column(JSON)   # {llms: ["claude-3-5", "deepseek-v3"], type: "ensemble"|"single", consensus_ratio: 0.8}
    match_ids   = Column(JSON)   # 出票时用到的 match_id 列表
    tickets_json = Column(JSON)  # 完整票型 JSON（同 BettingTickets 响应格式）
    sync_status  = Column(String, default="pending")     # pending / synced / failed / partial
    sync_error   = Column(Text)  # 失败原因（可能是部分场次的）
    results_json = Column(JSON)  # 赛后结果补填，{match_id: {actual: "H", score: "2-0"}}
    created_at  = Column(DateTime, default=datetime.utcnow)
    synced_at   = Column(DateTime)
```

---

## 功能模块

### 1. 自动出票调度

APScheduler 新增 job（在现有 09:00 分析之后）：

```
08:00  sync_matches_job        — 赛单同步（现有）
09:00  run_analysis_job        — AI 分析（现有）
09:30  auto_ticket_job         — 自动出票（新增，可配置）
```

自动出票逻辑：
1. 查当日 pending 分析的赛事（已有 Prediction）
2. 调用与「方案」页相同的票型生成逻辑（无 force，复用缓存分析）
3. 如果配置了多 LLM，标记 type=ensemble，记录 consensus_ratio
4. 写入 AutoTicketRun，trigger=scheduled

### 2. 赛果自动同步

比赛结束后（kickoff_at + 2h 触发）或凌晨统一 sync：
- 查当日 AutoTicketRun 中 sync_status=pending 的记录
- 对其每个 match_id 读取 Match.actual_result / actual_score
- 如果所有比赛有结果 → sync_status=synced，填 results_json
- 如果部分有结果 → sync_status=partial，记录已同步场次
- 如果读取失败 → sync_status=failed，sync_error 记录原因

失败原因分类：
- `no_result_yet` — 比赛尚未结束（正常情况）
- `score_missing` — 比赛结束但比分未录入（通知用户手动录入）
- `match_not_found` — match_id 在数据库中找不到
- `api_error: {message}` — 数据源请求失败

### 3. 中奖计算

复用 `bets.py` 的 `_evaluate_legs` 和 `_hhad_result_from_score` 逻辑，每个方案独立计算：
- 串关全中 → won
- 任一腿未中 → lost  
- 有腿尚无结果 → pending
- 有腿 void → 按剩余腿计算

---

## 页面信息架构

### 追踪页（/track）

```
┌────────────────────────────────────────────┐
│  系统追踪  [本月] [近3月] [全部]  [手动触发] │
├────────────────────────────────────────────┤
│  统计概览条                                  │
│  共 N 次出票  中奖 X 注  命中率 X%  ROI X%  │
├────────────────────────────────────────────┤
│  ── 2026-07-28 ──────────────────────────  │
│  [🤖 自动] [多角色集成] [3模型·85%共识]       │
│  3 场赛事  4 份方案  ✓ 已同步                │
│                                            │
│  ▸ 稳健票  2关  赔率×2.4  [待结算]          │
│  ▸ 均衡票  3关  赔率×3.8  [✓ 中奖 +¥14.4]  │
│  ▸ 高赔票  4关  赔率×8.2  [✗ 未中 -¥5]     │
│                                            │
│  ── 2026-07-27 ──────────────────────────  │
│  [🤖 自动] [单模型: DeepSeek-v3]            │
│  2 场赛事  3 份方案  ⚠️ 部分同步             │
│  ↳ match#123 比分未录入，请手动核对          │
└────────────────────────────────────────────┘
```

### 方案详情展开

点击方案卡展开：
```
均衡票  3关串1  投注¥10
├─ 曼城 vs 阿森纳   主胜(3)  赔率1.72  ✓ 主胜(2-0)
├─ 皇马 vs 巴萨     平局(1)  赔率3.50  ✓ 平局(1-1)
└─ 拜仁 vs 多特     让球主胜 -1(3)  赔率2.05  ✓ 主胜(3-1)
预计回报¥30.8  实际¥30.8  净盈¥20.8

分析来源: Claude 3.5 Sonnet / DeepSeek v3 / Kimi k1.5
共识结果: 3/3 均推荐均衡路线
```

---

## 标签系统

| 标签 | 含义 | 样式 |
|------|------|------|
| 🤖 自动 | APScheduler 触发 | 蓝色 chip |
| 🖱️ 手动 | 用户在追踪页点「立即运行」 | 灰色 chip |
| 多角色集成 | 多 LLM Ensemble | 紫色 chip |
| 单模型: {name} | 只有一个 LLM | 默认 chip |
| N模型·X%共识 | 投票来源 | 文本标注 |
| ✓ 已同步 | 所有赛果已录入 | 绿色 |
| ⏳ 同步中 | 部分或等待 | 黄色 |
| ⚠️ 部分同步 | 有场次缺结果 | 橙色 |
| ✗ 同步失败 | 全部失败 | 红色 |
| ✓ 中奖 +¥N | 串关全中 | 绿色 |
| ✗ 未中 -¥N | 串关未中 | 红色 |
| ⏳ 待结算 | 有腿尚无结果 | 灰色 |

---

## 设置页扩展

「设置」→「自动出票」新增区块：

```
自动出票
├── 开启自动出票  [开关]
├── 每日出票时间  [09:30]  （需在分析完成后，建议 09:15~12:00）
├── 出票投注额    [¥10]   （每份方案的参考金额，仅用于盈亏计算）
└── 赛果同步时间  [凌晨 02:00]  （自动同步前一日赛果）
```

出票时间验证：若早于当日分析完成时间（09:00 + 分析耗时），给出警告，不阻止保存。

---

## API 端点规划

```
GET  /api/track/runs            — 历史出票列表（分页）
GET  /api/track/runs/{id}       — 单次出票详情
POST /api/track/runs            — 手动触发出票（trigger=manual）
POST /api/track/runs/{id}/sync  — 手动触发该次赛果同步
GET  /api/track/summary         — 统计概览（命中率、ROI、总次数）
```

---

## 实现优先级

| 优先级 | 模块 | 工作量 |
|--------|------|--------|
| P0 | AutoTicketRun 数据模型 + migration | 0.5h |
| P0 | auto_ticket_job + 赛果 sync job（APScheduler） | 1h |
| P0 | `/api/track/` 端点（CRUD + summary） | 1h |
| P1 | 追踪页前端（timeline + 方案卡 + 标签） | 2h |
| P1 | 设置页「自动出票」区块 | 0.5h |
| P2 | 手动触发按钮 + 单次 sync 触发 | 0.5h |
| P2 | 同步失败原因分类 + 展示 | 0.5h |
