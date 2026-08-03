# ADR-006: CLV 追踪与 RPS 晋升门控

**状态：** 已采用
**日期：** 2026-08-02

## 决策

引入两个衡量"策略是否有真实 edge"的指标层改进，不改变任何现有策略行为：

### 1. CLV（Closing Line Value）追踪

对每条回测记录，以**系统推荐方向**（预测概率 argmax）计算买入价与收盘价的差异：

- **pick**：实际推荐方向（`tickets.final_outcome`，ensemble 场景）优先，缺失时 fallback `argmax(p_home, p_draw, p_away)` → H/D/A。计算逻辑抽为共享函数 `core/data/snapshot.py::compute_clv_fields`，自动写入（赛果同步）与手动录入（`/api/backtest/record`）同口径，避免两条写入路径互相覆盖丢 CLV
- **entry_odds**：预测生成时刻的竞彩赔率（每日分析流水线写入 `prediction_snapshots.market_odds`）
- **close_odds**：赛果同步时刻 `match.sporttery_odds`（赛前最后一次同步值，竞彩封盘后不再变动，即收盘 SP）
- **CLV%** = `entry_odds / close_odds - 1`。正值表示买入后赔率下降（市场向我们的方向移动），即跑赢收盘

公式说明：竞彩 HAD 返奖率恒定，三项赔率同比例含水，multiplicative 去水不影响 CLV 的方向与大小比较，故直接用赔率比值，与 Pikkit 的 raw CLV 公式 `(1/C - 1/B)/(1/B) = B/C - 1` 一致。

CLV 字段存入 DuckDB `backtest_results`（新增 `pick / entry_odds / close_odds / clv` 列，沿用既有 `ALTER TABLE` 前向兼容迁移模式），并在 `/api/backtest/metrics` 响应中新增聚合：`avg_clv`、`clv_positive_ratio`、`n_with_clv`。

### 2. RPS 晋升门控

`retrain_model` 留出验证集（最近 100 场）计算 RPS 填入 `ModelMetrics.rps`（替换当前空挂的 0.0）；`should_promote` 增加第三道门：

```
Brier 改善 ≥ 0.001 AND log_loss 改善 ≥ 0.001 AND (champion.rps == 0 OR RPS 改善 ≥ 0.001)
```

`champion.rps == 0` 时跳过 RPS 门（向后兼容存量 champion 记录）。RPS 采用标准累积公式 `Σ(cum_p - cum_o)² / (K-1)`，K=3，与 `snapshot.py::_calc_metrics` 回测口径一致——抽取共享函数 `core/modeling/metrics.py::rps` 供两处复用，避免公式漂移。

## 背景

- **CLV 是职业投注圈公认最能预测长期盈利的先行指标**（Pinnacle 研究：+CLV 投注者几乎必然长期盈利，−CLV 几乎必然亏损，与短期运气无关）。项目已有 `sporttery_odds_open` / `sporttery_odds` 双快照与预测时赔率数据，只差计算与沉淀。
- **RPS 是 1X2 有序结果的标准 proper score**（penaltyblog、各世界杯预测开源项目的一致选择），能区分"差点对"（预测主胜实际平局）与"错得离谱"（预测主胜实际客胜），而 Brier 对两者惩罚相同。`ModelMetrics.rps` 字段自 ADR-005 起存在但从未计算，晋升决策缺少对有序误差的感知。
- 竞彩语境的特殊性：SP 在出票时锁定、封盘前可多次调整，因此"预测时刻赔率 → 封盘赔率"的变动真实反映市场信息流入，CLV 解释成立。

## 后果

- `prediction_snapshots` 新增 `market_odds TEXT` 列；`pipeline.py` 快照写入处传入 `match.sporttery_odds`
- `backtest_results` 新增 `pick / entry_odds / close_odds / clv` 列；`_auto_save_backtest`（赛果同步）负责 join 预测快照计算并写入
- 缺少预测时赔率快照的历史记录 `clv` 为 NULL，不参与聚合；`entry_odds == close_odds`（赔率未变动）时 CLV = 0，属正常情形
- `/api/backtest/metrics` 响应新增 `avg_clv / clv_positive_ratio / n_with_clv`（向后兼容，纯新增字段）
- `should_promote` 对存量 champion（rps=0）行为不变；新 champion 均有真实 RPS 后三道门同时生效
- 样本量提醒：CLV 需 200+ 注才有统计意义，前端/报告展示时应注明（本次仅 API 层输出，前端展示后续迭代）
- 明确不做：竞彩 SP 仍禁止进入融合源（防循环论证），CLV 仅作事后评估指标，不反馈进概率形成

## 补充（2026-08-02 逻辑审查）

- `_compute_run_roi`（Kelly 回撤保护的 ROI 输入）只结算 HAD/HHAD 方案：比分等市场腿（"2-1" 永不可能等于 "主胜"）与 `total_odds<=0` 的估算方案跳过，否则 ROI 系统性低估会误触发 stake 减半
- `retrain_model` 晋升指标改为**样本外验证**：数据 >150 场时用 `records[:-100]` 单独拟合评估参数、在最近 100 场计算指标；生产参数仍用全量训练。修复此前"验证集在训练集内"导致的指标乐观偏差
