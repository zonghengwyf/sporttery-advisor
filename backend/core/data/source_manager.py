"""数据源管理器 — 优先级降级链 + Redis 缓存。"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)


class SourceManager:
    def __init__(
        self,
        redis_client=None,
        sporttery_api_key: str | None = None,
        odds_api_key: str | None = None,
        api_football_key: str | None = None,
    ):
        self._redis = redis_client
        self._sporttery_key = sporttery_api_key
        self._odds_key = odds_api_key
        self._api_football_key = api_football_key

    # ── 赛单获取 ──────────────────────────────────────────────────────────────

    async def get_today_matches(self, target_date: date) -> list[dict]:
        """从竞彩官方接口拉取今日赛单（同步函数包装为异步）。"""
        from core.data.providers.sporttery import fetch_today
        return await asyncio.to_thread(fetch_today, target_date)

    # ── 赛果获取 ──────────────────────────────────────────────────────────────

    async def get_match_result(self, sporttery_id: str) -> str | None:
        """
        尝试从竞彩官方接口获取赛果，返回 "H" / "D" / "A" 或 None。
        实际实现需对接竞彩赛果 API；当前版本为降级桩。
        """
        try:
            result = await asyncio.to_thread(self._fetch_sporttery_result, sporttery_id)
            return result
        except Exception as exc:
            logger.debug("竞彩赛果接口失败 sporttery_id=%s: %s", sporttery_id, exc)
            return None

    def _fetch_sporttery_result(self, sporttery_id: str) -> str | None:
        """同步实现：从竞彩官方查询赛果。未接入真实 API 时返回 None。"""
        # TODO: 接入竞彩官方赛果 API（sporttery.cn/gateway/jc/football/getResult...）
        return None

    async def get_odds_api_result(self, match) -> str | None:
        """
        通过 The Odds API /scores 接口获取赛果。
        需要 odds_api_key，且仅支持已配置 sport_key 的联赛。
        """
        if not self._odds_key:
            return None
        try:
            result = await asyncio.to_thread(self._fetch_odds_api_result, match)
            return result
        except Exception as exc:
            logger.debug("The Odds API 赛果失败: %s", exc)
            return None

    def _fetch_odds_api_result(self, match) -> str | None:
        """同步实现：The Odds API /v4/sports/{sport}/scores 查询赛果。"""
        import urllib.request

        sport_key = _resolve_sport_key(match.league or "")
        if not sport_key:
            return None

        url = (
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores"
            f"?apiKey={self._odds_key}&daysFrom=3"
        )
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data: list[dict] = json.loads(resp.read())
        except Exception as exc:
            raise RuntimeError(f"The Odds API request failed: {exc}") from exc

        home_norm = _normalize_team(match.home_team)
        away_norm = _normalize_team(match.away_team)

        for game in data:
            if not game.get("completed"):
                continue
            h = _normalize_team(game.get("home_team", ""))
            a = _normalize_team(game.get("away_team", ""))
            if h != home_norm and a != away_norm:
                continue
            scores = game.get("scores") or []
            score_map = {s["name"]: int(s["score"]) for s in scores if "name" in s and "score" in s}
            if len(score_map) < 2:
                continue
            home_goals = score_map.get(game.get("home_team", ""), 0)
            away_goals = score_map.get(game.get("away_team", ""), 0)
            if home_goals > away_goals:
                return "H"
            if home_goals < away_goals:
                return "A"
            return "D"
        return None

    # ── 历史数据 ──────────────────────────────────────────────────────────────

    async def get_historical_data(self, seasons: int = 3) -> list[dict]:
        """从 football-data.co.uk 下载历史赛果，用于 Dixon-Coles 训练。"""
        try:
            from core.data.providers import football_data  # type: ignore
            return await asyncio.to_thread(football_data.fetch_seasons, seasons)
        except Exception as exc:
            logger.warning("历史数据获取失败：%s", exc)
            return []


# ── 工具函数 ───────────────────────────────────────────────────────────────────

_LEAGUE_SPORT_MAP: dict[str, str] = {
    "英超": "soccer_epl",
    "西甲": "soccer_spain_la_liga",
    "德甲": "soccer_germany_bundesliga",
    "意甲": "soccer_italy_serie_a",
    "法甲": "soccer_france_ligue_one",
    "欧冠": "soccer_uefa_champs_league",
    "欧罗巴": "soccer_uefa_europa_league",
    "荷甲": "soccer_netherlands_eredivisie",
    "葡超": "soccer_portugal_primeira_liga",
    "苏超": "soccer_scotland_premiership",
}


def _resolve_sport_key(league: str) -> str | None:
    for keyword, key in _LEAGUE_SPORT_MAP.items():
        if keyword in league:
            return key
    return None


def _normalize_team(name: str) -> str:
    return name.lower().replace(" ", "").replace("-", "")
