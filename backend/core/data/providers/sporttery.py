"""竞彩官方数据源 — 无需 API Key，直连 webapi.sporttery.cn。"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from typing import Any

OFFICIAL_URL = "https://webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry"
POOL_CODES = ("had", "hhad", "crs", "ttg", "hafu")
POOL_LABELS = {
    "had": "胜平负",
    "hhad": "让球胜平负",
    "crs": "比分",
    "ttg": "总进球",
    "hafu": "半全场",
}

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36"


class ProviderError(RuntimeError):
    pass


def _iso_date(value: str) -> str:
    value = value.strip()
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%y%m%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            continue
    return value


def _kickoff(day: str, clock: str) -> str:
    day = _iso_date(day)
    return f"{day}T{clock or '00:00:00'}"


def _parse_had_odds(item: dict[str, Any]) -> dict | None:
    had = item.get("had") or {}
    try:
        h = float(had.get("h", 0))
        d = float(had.get("d", 0))
        a = float(had.get("a", 0))
        if h > 1 and d > 1 and a > 1:
            return {"home": h, "draw": d, "away": a}
    except (TypeError, ValueError):
        pass
    return None


def _parse_hhad_odds(item: dict[str, Any]) -> dict | None:
    hhad = item.get("hhad") or {}
    try:
        h = float(hhad.get("h", 0))
        d = float(hhad.get("d", 0))
        a = float(hhad.get("a", 0))
        if h > 1 and d > 1 and a > 1:
            raw_line = hhad.get("goalLineValue") or hhad.get("goalLine")
            line = float(raw_line) if raw_line not in (None, "") else None
            return {"home": h, "draw": d, "away": a, "handicap": line}
    except (TypeError, ValueError):
        pass
    return None


def _parse_markets(item: dict[str, Any]) -> list[str]:
    return [pool for pool in POOL_CODES if pool in item and item[pool]]


def fetch_today(business_date: date) -> list[dict]:
    """同步拉取竞彩官方赛单，返回标准化字典列表。在 asyncio.to_thread 中调用。"""
    url = (
        OFFICIAL_URL
        + "?poolCode=had,hhad,crs,ttg,hafu&channel=c"
    )
    headers = {
        "User-Agent": _UA,
        "Referer": "https://m.sporttery.cn/",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers)

    # 先尝试系统代理，被拦截时绕过代理直连
    payload: dict | None = None
    last_err: Exception | None = None
    for no_proxy in (False, True):
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if no_proxy else None
            ctx = opener.open(req, timeout=15) if opener else urllib.request.urlopen(req, timeout=15)
            with ctx as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_err = exc

    if payload is None:
        raise ProviderError(f"竞彩官方接口不可达：{last_err}")

    groups = (payload.get("value") or {}).get("matchInfoList")
    if not isinstance(groups, list):
        raise ProviderError("竞彩官方响应结构已变化（缺少 value.matchInfoList）")

    target = business_date.isoformat()
    result: list[dict] = []
    for group in groups:
        group_date = _iso_date(str(group.get("businessDate") or group.get("matchNumDate") or ""))
        for item in group.get("subMatchList") or []:
            item_date = _iso_date(
                str(item.get("businessDate") or group.get("businessDate") or group.get("matchNumDate") or "")
            )
            if item_date != target and group_date != target:
                continue
            result.append({
                "sporttery_id": str(item.get("matchId") or ""),
                "match_no": str(item.get("matchNumStr") or ""),
                "league": str(item.get("leagueAbbName") or item.get("leagueAllName") or ""),
                "home_team": str(item.get("homeTeamAbbName") or item.get("homeTeamAllName") or ""),
                "away_team": str(item.get("awayTeamAbbName") or item.get("awayTeamAllName") or ""),
                "kickoff_at": _kickoff(
                    str(item.get("matchDate") or target),
                    str(item.get("matchTime") or "00:00:00"),
                ),
                "sale_date": target,
                "sporttery_odds": _parse_had_odds(item),
                "hhad_odds": _parse_hhad_odds(item),
                "available_markets": _parse_markets(item),
            })
    return result
