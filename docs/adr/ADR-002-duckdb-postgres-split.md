# ADR-002: DuckDB 快照 vs PostgreSQL 主数据分工

**状态：** 已采用
**日期：** 2026-07-25

## 决策

PostgreSQL 存储业务主数据（用户、配置、赛事索引、对话、投注记录），DuckDB 存储分析快照（预测历史、回测结果）。两套存储职责严格分离，互不写入对方。

## 背景

预测历史和回测结果是时间序列的追加写入，查询模式是聚合分析（Brier/RPS 计算、历史精度趋势），与 OLTP 的点查和事务需求差异大。DuckDB 的列存储和向量化执行对此类聚合查询有 10-100x 性能优势，且零运维（嵌入式，无单独服务）。

## 后果

- `backend/core/data/snapshot.py` 管理 DuckDB 连接，使用 `DUCKDB_PATH` 环境变量
- DuckDB 文件路径在 `docker-compose.yml` 中通过 volume 持久化（`./data/snapshots:/app/data/snapshots`）
- **禁止用 DuckDB 存用户数据**（无法支持事务、外键约束）；**禁止用 PostgreSQL 存大量预测快照**（行存储聚合慢）
- 回测 API（`/api/backtest/*`）查 DuckDB；所有用户相关操作查 PostgreSQL
- DuckDB 写失败不影响主流程（非关键路径），只记录日志
