# ADR-001: Skills 注入不依赖 Claude Code 运行时

**状态：** 已采用
**日期：** 2026-07-25

## 决策

竞彩决策规则通过 `backend/core/llm/skills_injector.py` 在运行时读取 `backend/skills/` 下的 Markdown 文件，拼接到 LLM system prompt 中，不依赖 Claude Code 原生 Skills 机制。

## 背景

本项目需要将 `china-sporttery-football-advisor` 仓库的竞彩决策规则注入 AI 分析流程。可选方案有：
1. 依赖 Claude Code 运行时 Skills（只在开发环境有效，生产环境失效）
2. 在 FastAPI 后端运行时读取 Markdown，注入 system prompt（环境无关）

方案 1 导致生产部署后 Skills 失效；方案 2 在任何 LLM 调用环境下均可用。

## 后果

- `backend/skills/` 目录是运行时依赖，Docker 镜像必须包含此目录（见 Dockerfile 的 `COPY skills/ /app/skills/`）
- 注入逻辑在 `skills_injector.py` 中，条件激活规则：始终注入 3 个基础文件，`is_tournament=True` 时追加 `tournament-incentives.md`，`has_abnormal_form=True` 时追加 `form-context.md`
- 新增 Skill 文件需同步修改 `SkillsInjector` 类的激活逻辑
- `SKILLS_DIR` 环境变量指定目录路径，默认 `/app/skills`
