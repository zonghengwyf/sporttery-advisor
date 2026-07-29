"""API-Football 数据提供者 — 需要 API Key（RapidAPI 或官方）。

文档：https://www.api-football.com/documentation-v3
提供：伤停名单、联赛积分榜。
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

_BASE_URL = "https://v3.football.api-sports.io"

# 竞彩联赛中文名 → API-Football league_id
_LEAGUE_IDS: dict[str, int] = {
    "英超": 39,
    "西甲": 140,
    "德甲": 78,
    "意甲": 135,
    "法甲": 61,
    "荷甲": 88,
    "葡超": 94,
    "苏超": 179,
    "比甲": 144,
    "土超": 203,
    "欧冠": 2,
    "欧联": 3,
    "欧联大会杯": 848,
    "世界杯": 1,
    "欧洲杯": 4,
    "亚洲杯": 30,
}


class APIFootballProvider:
    def __init__(self, api_key: str):
        self._api_key = api_key
        self._headers = {
            "x-apisports-key": api_key,
            "Accept": "application/json",
        }

    # ── 伤停 ─────────────────────────────────────────────────────────────────

    async def get_injuries(self, fixture_id: str | int) -> list[dict]:
        """获取指定赛事的伤停名单。
        返回：[{team, player, reason, status}]
        """
        data = await asyncio.to_thread(
            self._get, "/injuries", {"fixture": str(fixture_id)}
        )
        if not data:
            return []
        results = []
        for item in data.get("response", []):
            player = item.get("player", {})
            team = item.get("team", {})
            results.append({
                "team": team.get("name", ""),
                "player": player.get("name", ""),
                "reason": item.get("reason", ""),
                "status": "Injured",
            })
        return results

    async def get_injuries_by_teams(
        self, home_team: str, away_team: str, match_date: date
    ) -> list[dict]:
        """通过球队名 + 日期搜索赛事，再获取伤停（API Key 精度限制时的降级方案）。"""
        fixture_id = await asyncio.to_thread(
            self._find_fixture, home_team, away_team, match_date
        )
        if not fixture_id:
            return []
        return await self.get_injuries(fixture_id)

    # ── 积分榜 ────────────────────────────────────────────────────────────────

    async def get_standings(self, league_cn: str, season: int | None = None) -> list[dict]:
        """获取联赛积分榜。
        返回：[{rank, team, played, won, drawn, lost, gf, ga, gd, points, form}]
        """
        league_id = _LEAGUE_IDS.get(league_cn)
        if not league_id:
            return []
        if season is None:
            # 当前赛季年份（欧洲赛季按开始年算）
            today = date.today()
            season = today.year if today.month >= 7 else today.year - 1

        data = await asyncio.to_thread(
            self._get, "/standings", {"league": str(league_id), "season": str(season)}
        )
        if not data:
            return []

        rows: list[dict] = []
        for group in data.get("response", []):
            for league_info in group.get("league", {}).get("standings", [[]]):
                for entry in league_info:
                    team = entry.get("team", {})
                    all_stats = entry.get("all", {})
                    goals = all_stats.get("goals", {})
                    rows.append({
                        "rank": entry.get("rank"),
                        "team": team.get("name", ""),
                        "played": all_stats.get("played"),
                        "won": all_stats.get("win"),
                        "drawn": all_stats.get("draw"),
                        "lost": all_stats.get("lose"),
                        "gf": goals.get("for"),
                        "ga": goals.get("against"),
                        "gd": entry.get("goalsDiff"),
                        "points": entry.get("points"),
                        "form": entry.get("form", ""),  # 如 "WWDLW"
                    })
        return rows

    # ── 内部 ─────────────────────────────────────────────────────────────────

    def _get(self, path: str, params: dict) -> dict:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{_BASE_URL}{path}?{query}"
        req = urllib.request.Request(url, headers=self._headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except Exception as exc:
            logger.debug("API-Football %s 失败：%s", path, exc)
            return {}

    def _find_fixture(
        self, home_team: str, away_team: str, match_date: date
    ) -> int | None:
        data = self._get("/fixtures", {"date": match_date.isoformat()})
        for item in data.get("response", []):
            teams = item.get("teams", {})
            h = teams.get("home", {}).get("name", "").lower()
            a = teams.get("away", {}).get("name", "").lower()
            if home_team.lower() in h and away_team.lower() in a:
                return item.get("fixture", {}).get("id")
        return None
