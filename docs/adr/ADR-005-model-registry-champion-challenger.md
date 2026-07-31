# ADR-005: Champion/Challenger 模型注册与晋升门控

**状态：** 已采用
**日期：** 2026-07-31

## 决策

新训练的 Dixon-Coles 模型版本通过 `backend/core/modeling/model_registry.py` 注册到 DuckDB，采用 Champion/Challenger 双轨机制：只有当 Challenger 在 Brier score 和 Log-loss 均改善 ≥ 0.001 时，才自动晋升为新 Champion；否则 Challenger 保留观察期，不替换生产模型。

## 背景

Dixon-Coles 模型会随新赛季数据定期重训，直接替换会引入回退风险（过拟合新数据、样本量不足时指标反而变差）。需要一套轻量的 A/B 门控，让模型更新可验证、可回滚，同时不引入独立的 ML 平台依赖（项目已有 DuckDB，天然适合存储模型快照和指标历史）。

## 后果

- 模型元数据（版本号、训练日期、Brier/Log-loss/RPS/ECE/样本量）存入 DuckDB `model_versions` 表，由 `snapshot.py` 管理连接
- 晋升门控写死在 `model_registry.py`：`Brier_reduction ≥ 0.001 AND log_loss_reduction ≥ 0.001`（来自 football-prediction-skill 阈值）
- Champion 版本以 `is_champion=True` 标记，`pipeline.py` 总是加载当前 Champion 做预测
- Challenger 版本可在回测报告页（`/api/backtest/`）单独对比，不影响生产预测
- 若需手动强制晋升，调用 `ModelRegistry.promote(version_id)`，写入审计日志
- 禁止将模型权重文件存入 PostgreSQL（二进制大对象影响 OLTP 性能）；权重序列化为 JSON 存 DuckDB 或落盘为 `.pkl` 文件并在 DuckDB 记录路径
