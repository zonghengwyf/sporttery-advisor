"""Skills 注入系统

参考 claude-code-sourcemap-main 的实现原理：
Skills 是 Markdown 文件，在构建每次 LLM 请求时按需注入 system prompt。
实现与 Claude Code / Codex 等价的 conditional skills 激活。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from config import settings


@dataclass
class MatchContext:
    home_team: str
    away_team: str
    league: str
    is_tournament: bool = False           # 世界杯/欧洲杯等大赛
    has_abnormal_form: bool = False       # 近期有异常赛果
    stat_probs: dict | None = None        # Dixon-Coles 统计概率
    odds_data: dict | None = None         # 赔率数据
    intel_data: dict | None = None        # 情报数据（伤停/新闻）
    odds_movement: dict | None = None     # 赔率异动数据 {home_pct, draw_pct, away_pct, direction}
    extra_context: dict = field(default_factory=dict)


class SkillsInjector:
    """将 skills/ 目录下的 Markdown 文件注入 LLM system prompt"""

    def __init__(self, skills_dir: str | None = None):
        self.skills_dir = Path(skills_dir or settings.skills_dir)
        self._cache: dict[str, str] = {}

    def _load_skill(self, filename: str) -> str:
        if filename not in self._cache:
            path = self.skills_dir / filename
            if path.exists():
                self._cache[filename] = path.read_text(encoding="utf-8")
            else:
                self._cache[filename] = ""
        return self._cache[filename]

    def _format_stat_context(self, stat_probs: dict, odds_data: dict | None) -> str:
        lines = ["## 统计模型输出（Dixon-Coles + 市场融合）\n"]
        if "home_win" in stat_probs:
            lines.append(f"- 主胜概率：{stat_probs['home_win']:.1%}")
            lines.append(f"- 平局概率：{stat_probs['draw']:.1%}")
            lines.append(f"- 客胜概率：{stat_probs['away_win']:.1%}")
        if odds_data:
            lines.append("\n## 赔率数据")
            if "sporttery" in odds_data:
                s = odds_data["sporttery"]
                lines.append(f"- 竞彩赔率：主胜 {s.get('home','-')} / 平 {s.get('draw','-')} / 客胜 {s.get('away','-')}")
            if "overseas" in odds_data:
                o = odds_data["overseas"]
                lines.append(f"- 海外赔率：主胜 {o.get('home','-')} / 平 {o.get('draw','-')} / 客胜 {o.get('away','-')}")
        return "\n".join(lines)

    def _format_odds_movement(self, movement: dict) -> str:
        lines = ["## 当前赔率异动数据\n"]
        labels = {"home": "主胜", "draw": "平局", "away": "客胜"}
        for key, label in labels.items():
            pct = movement.get(f"{key}_pct")
            open_val = movement.get(f"{key}_open")
            curr_val = movement.get(f"{key}_current")
            if pct is not None:
                direction = "↓ 下降" if pct < 0 else "↑ 上升"
                lines.append(
                    f"- {label}：{open_val} → {curr_val}（{direction} {abs(pct):.1f}%）"
                )
        return "\n".join(lines)

    def build_system_prompt(self, context: MatchContext) -> str:
        """按赛事上下文条件激活 skills，构建完整 system prompt"""
        parts: list[str] = []

        # 核心工作流（始终注入）
        skill_main = self._load_skill("SKILL.md")
        if skill_main:
            parts.append(skill_main)

        # 因素权重模型（始终注入）
        factor_model = self._load_skill("factor-model.md")
        if factor_model:
            parts.append(factor_model)

        # 体彩输出格式（始终注入）
        sporttery_output = self._load_skill("sporttery-output.md")
        if sporttery_output:
            parts.append(sporttery_output)

        # 大赛激励分析（条件激活：大赛时）
        if context.is_tournament:
            tournament = self._load_skill("tournament-incentives.md")
            if tournament:
                parts.append(tournament)

        # 异常赛果诊断（条件激活：有异常形态时）
        if context.has_abnormal_form:
            form_context = self._load_skill("form-context.md")
            if form_context:
                parts.append(form_context)

        # 赔率异动分析（条件激活：有显著赔率变动时）
        if context.odds_movement and _has_significant_movement(context.odds_movement):
            odds_move_skill = self._load_skill("odds-movement.md")
            if odds_move_skill:
                parts.append(odds_move_skill)
                parts.append(self._format_odds_movement(context.odds_movement))

        # 统计概率注入（条件激活：有模型输出时）
        if context.stat_probs:
            parts.append(self._format_stat_context(context.stat_probs, context.odds_data))

        return "\n\n---\n\n".join(filter(None, parts))

    def build_analysis_prompt(self, context: MatchContext) -> str:
        """构建单场分析的用户消息"""
        lines = [
            f"请分析以下比赛并给出竞彩投注建议：",
            f"- 主队：{context.home_team}",
            f"- 客队：{context.away_team}",
            f"- 赛事：{context.league}",
        ]
        if context.intel_data:
            lines.append(f"\n已知情报：{context.intel_data}")
        lines.append("\n请按照工作流步骤输出完整分析和投注方案。")
        return "\n".join(lines)

    def build_daily_prompt(self, matches: list[MatchContext], budget: float | None = None) -> str:
        """构建今日多场分析的用户消息"""
        match_lines = []
        for i, m in enumerate(matches, 1):
            match_lines.append(f"{i}. {m.home_team} vs {m.away_team}（{m.league}）")
        budget_str = f"，总本金 {budget} 元" if budget else ""
        return (
            f"请分析今日以下 {len(matches)} 场竞彩足球比赛{budget_str}，"
            f"输出稳健票、均衡票、博高赔票、比分小注和资金分配：\n\n"
            + "\n".join(match_lines)
        )


def _has_significant_movement(movement: dict, threshold: float = 5.0) -> bool:
    """任意赔率变动幅度超过阈值（%）则认为显著。"""
    for key in ("home_pct", "draw_pct", "away_pct"):
        val = movement.get(key)
        if val is not None and abs(val) >= threshold:
            return True
    return False
