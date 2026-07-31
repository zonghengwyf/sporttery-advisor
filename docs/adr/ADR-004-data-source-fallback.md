# ADR-004: 数据源优先级降级链

**状态：** 已采用
**日期：** 2026-07-25

## 决策

数据获取通过 `backend/core/data/source_manager.py` 统一管理，按固定优先级降级：竞彩 API Key → Playwright 爬虫 → Redis 缓存 → 免费源（ClubElo / football-data.co.uk）。上层失败自动切换下层，不暴露给 API 调用方。

## 背景

竞彩官方没有公开 API，正式 API Key 难获取。爬虫会随页面结构变化失效。需要在「最准确」和「总有数据」之间建立可靠的降级路径，让系统在无任何 Key 的情况下仍能工作（用爬虫 + 免费源）。

## 后果

- **竞彩赔率**：`SportteryAPI`（Key 可用）→ `SportteryScraper`（Playwright，Key 不可用时）→ Redis 缓存（最长 4h）
- **海外赔率**：`OddsAPI`（Key 可用）→ 无降级（该数据为可选参考）
- **伤停/阵容**：`APIFootball`（Key 可用）→ 跳过（情报层标注「无伤停数据」）
- **历史数据**：`football-data.co.uk`（免费，限速）→ 本地缓存
- **Elo 评分**：`ClubElo`（免费，HTTP GET）→ 本地缓存
- Redis 缓存 TTL：赛事数据 4h，赔率数据 1h（`source_manager.py` 中配置）
- `DataSourceConfig.use_scraper` 字段控制是否允许启用 Playwright 降级（默认 True）
- 新增数据源：在 `providers/` 下实现接口，在 `SourceManager` 中注册优先级即可
