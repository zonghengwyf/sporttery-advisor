"""ClubElo 数据提供者 — 免费公开接口，无需 API Key。

文档：http://clubelo.com/API
端点：GET http://api.clubelo.com/YYYY-MM-DD  → CSV，所有球队当日 Elo
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from core.data.team_names import fuzzy_match_english

logger = logging.getLogger(__name__)

_CACHE_DIR = Path("/tmp/sporttery_cache")
_BASE_URL = "http://api.clubelo.com"


class ClubEloProvider:
    def __init__(self, cache_ttl_hours: int = 24):
        self._cache_ttl_hours = cache_ttl_hours
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ── 公开接口 ─────────────────────────────────────────────────────────────

    async def get_match_elos(
        self, home_team_cn: str, away_team_cn: str, as_of: date | None = None
    ) -> dict | None:
        """返回 {home_elo, away_elo, home_name, away_name} 或 None。"""
        as_of = as_of or date.today()
        ratings = await asyncio.to_thread(self._fetch_ratings, as_of)
        if not ratings:
            return None

        team_names = list(ratings.keys())
        home_match = fuzzy_match_english(home_team_cn, team_names)
        away_match = fuzzy_match_english(away_team_cn, team_names)

        if not home_match or not away_match:
            logger.debug(
                "ClubElo 名称匹配失败 home=%s away=%s 可用=%d",
                home_team_cn, away_team_cn, len(team_names),
            )
            return None

        return {
            "home_elo": ratings[home_match],
            "away_elo": ratings[away_match],
            "home_name": home_match,
            "away_name": away_match,
        }

    # ── 内部实现 ─────────────────────────────────────────────────────────────

    def _fetch_ratings(self, as_of: date) -> dict[str, float]:
        """下载并解析指定日期的所有球队 Elo，返回 {team_name: elo}。"""
        cache_path = _CACHE_DIR / f"clubelo_{as_of.isoformat()}.json"
        if cache_path.exists():
            try:
                return json.loads(cache_path.read_text())
            except Exception:
                pass

        # ClubElo 当天数据可能未更新，最多往前找 3 天
        for delta in range(0, 4):
            target = as_of - timedelta(days=delta)
            url = f"{_BASE_URL}/{target.isoformat()}"
            try:
                with urllib.request.urlopen(url, timeout=10) as resp:
                    text = resp.read().decode("utf-8-sig")
                ratings = _parse_elo_csv(text)
                if ratings:
                    try:
                        cache_path.write_text(json.dumps(ratings))
                    except Exception:
                        pass
                    return ratings
            except Exception as exc:
                logger.debug("ClubElo %s 请求失败：%s", target, exc)

        return {}


def _parse_elo_csv(text: str) -> dict[str, float]:
    """解析 ClubElo CSV，返回 {team: elo}。"""
    reader = csv.DictReader(io.StringIO(text))
    result: dict[str, float] = {}
    for row in reader:
        club = (row.get("Club") or "").strip()
        elo_raw = row.get("Elo") or row.get("elo") or ""
        try:
            if club and elo_raw:
                result[club] = float(elo_raw)
        except ValueError:
            pass
    return result
