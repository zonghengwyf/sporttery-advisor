"""The Odds API 海外赔率提供者 — 需要 API Key。

文档：https://the-odds-api.com/liveapi/guides/v4/
"""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.the-odds-api.com/v4"

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


class OddsAPIProvider:
    """The Odds API 海外赔率提供者。"""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def get_league_odds(self, league: str) -> list[dict]:
        """
        拉取指定联赛所有比赛的 1X2 赔率。
        返回：[{home_team, away_team, home_odds, draw_odds, away_odds, bookmaker}]
        """
        sport_key = _resolve_sport_key(league)
        if not sport_key:
            return []

        url = (
            f"{_BASE_URL}/sports/{sport_key}/odds"
            f"?apiKey={self.api_key}&regions=eu&markets=h2h&oddsFormat=decimal"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "sporttery-advisor/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data: list[dict] = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            logger.debug("The Odds API %s 拉取失败：%s", league, exc)
            return []

        results = []
        for game in data:
            if game.get("completed"):
                continue
            home = game.get("home_team", "")
            away = game.get("away_team", "")
            if not home or not away:
                continue

            # 取平均赔率（所有 bookmaker 的均值）
            home_odds_list, draw_odds_list, away_odds_list = [], [], []
            for bookmaker in game.get("bookmakers", []):
                for market in bookmaker.get("markets", []):
                    if market.get("key") != "h2h":
                        continue
                    for outcome in market.get("outcomes", []):
                        name = outcome.get("name", "")
                        price = outcome.get("price")
                        if price is None:
                            continue
                        if name == home:
                            home_odds_list.append(price)
                        elif name == away:
                            away_odds_list.append(price)
                        elif name.lower() == "draw":
                            draw_odds_list.append(price)

            if not home_odds_list or not draw_odds_list or not away_odds_list:
                continue

            results.append({
                "home_team": home,
                "away_team": away,
                "home_odds": round(sum(home_odds_list) / len(home_odds_list), 2),
                "draw_odds": round(sum(draw_odds_list) / len(draw_odds_list), 2),
                "away_odds": round(sum(away_odds_list) / len(away_odds_list), 2),
                "bookmaker_count": len(game.get("bookmakers", [])),
            })
        return results

    def match_odds(
        self,
        home_cn: str,
        away_cn: str,
        league: str,
    ) -> dict | None:
        """
        根据中文队名和联赛，返回匹配的海外赔率。
        返回：{"home": x, "draw": y, "away": z} 或 None
        """
        from core.data.team_names import fuzzy_match_english

        odds_list = self.get_league_odds(league)
        if not odds_list:
            return None

        home_en = fuzzy_match_english(home_cn, [o["home_team"] for o in odds_list])
        away_en = fuzzy_match_english(away_cn, [o["away_team"] for o in odds_list])

        if not home_en or not away_en:
            # 备用：归一化后直接匹配
            home_norm = _normalize_team(home_cn)
            away_norm = _normalize_team(away_cn)
            for o in odds_list:
                if _normalize_team(o["home_team"]) == home_norm and _normalize_team(o["away_team"]) == away_norm:
                    return {"home": o["home_odds"], "draw": o["draw_odds"], "away": o["away_odds"]}
            return None

        for o in odds_list:
            if o["home_team"] == home_en and o["away_team"] == away_en:
                return {"home": o["home_odds"], "draw": o["draw_odds"], "away": o["away_odds"]}
        return None
