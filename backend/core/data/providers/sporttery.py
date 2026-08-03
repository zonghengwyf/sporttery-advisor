"""竞彩官方数据源 — 无需 API Key，直连 webapi.sporttery.cn。"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from typing import Any

OFFICIAL_URL = "https://webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry"
# 赛果专用接口（已完赛比赛会从在售接口消失，必须用此接口查赛果）
RESULT_URL = "https://webapi.sporttery.cn/gateway/jc/football/getMatchResultV1.qry"
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


# 竞彩赛果编码映射（matchResult 字段值 → H/D/A）
_RESULT_CODE_MAP: dict[str, str] = {
    "1": "H", "胜": "H",
    "0": "D", "平": "D",
    "3": "A", "负": "A",
}


def _parse_result(item: dict[str, Any]) -> tuple[str | None, str | None]:
    """从 API 响应项提取赛果和比分。返回 (H/D/A | None, "2-1" | None)。
    兼容在售接口（getMatchCalculatorV1）与赛果接口（getMatchResultV1）的字段差异。"""
    result_code: str | None = None
    score: str | None = None

    # 结果字段（多候选键）
    for key in ("matchResult", "matchResultHAD", "result", "winLostResult"):
        mr = str(item.get(key) or "").strip()
        if mr in _RESULT_CODE_MAP:
            result_code = _RESULT_CODE_MAP[mr]
            break

    # 比分字段：优先 homeScore/awayScore 拆分键，其次 "2-1"/"2:1" 合并键
    try:
        hs = item.get("homeScore")
        as_ = item.get("awayScore")
        if hs is not None and as_ is not None:
            h_int, a_int = int(hs), int(as_)
            score = f"{h_int}-{a_int}"
            if result_code is None:
                if h_int > a_int:
                    result_code = "H"
                elif h_int < a_int:
                    result_code = "A"
                else:
                    result_code = "D"
    except (TypeError, ValueError):
        pass

    if score is None:
        for key in ("score", "sectionsNo1Score", "fullScore"):
            raw = str(item.get(key) or "").strip()
            if not raw:
                continue
            for sep in ("-", ":", "："):
                if sep in raw:
                    try:
                        h_int, a_int = (int(x) for x in raw.split(sep)[:2])
                    except ValueError:
                        continue
                    score = f"{h_int}-{a_int}"
                    if result_code is None:
                        result_code = "H" if h_int > a_int else ("A" if h_int < a_int else "D")
                    break
            if score is not None:
                break

    return result_code, score


def _get_json(url: str, referer: str = "https://m.sporttery.cn/") -> dict:
    """带代理降级链的 GET JSON。失败抛 ProviderError。"""
    headers = {
        "User-Agent": _UA,
        "Referer": referer,
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers)
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
    return payload


def _fetch_raw_items() -> list[dict]:
    """拉取竞彩官方接口全量数据项（不按日期过滤）。在 asyncio.to_thread 中调用。"""
    payload = _get_json(OFFICIAL_URL + "?poolCode=had,hhad,crs,ttg,hafu&channel=c")
    groups = (payload.get("value") or {}).get("matchInfoList")
    if not isinstance(groups, list):
        raise ProviderError("竞彩官方响应结构已变化（缺少 value.matchInfoList）")
    items: list[dict] = []
    for group in groups:
        for item in group.get("subMatchList") or []:
            items.append(item)
    return items


def fetch_results_between(begin: date, end: date) -> dict[str, tuple[str | None, str | None]]:
    """批量拉取赛果（getMatchResultV1，按日期范围分页）。
    返回 {matchId: (H/D/A | None, score | None)}。接口不可达时抛 ProviderError。"""
    out: dict[str, tuple[str | None, str | None]] = {}
    page = 1
    while page <= 20:  # 安全上限
        url = (
            f"{RESULT_URL}?matchPage={page}"
            f"&matchBeginDate={begin.isoformat()}&matchEndDate={end.isoformat()}"
            f"&leagueId=&pageSize=100&isFix=0&pcOrWap=1"
        )
        payload = _get_json(url, referer="https://www.sporttery.cn/")
        data = payload.get("data") or {}
        items = data.get("matchResultList") or []
        for item in items:
            mid = str(item.get("matchId") or "")
            if mid:
                out[mid] = _parse_result(item)
        try:
            total = int(data.get("totalRecord") or 0)
        except (TypeError, ValueError):
            total = 0
        if not items or page * 100 >= total:
            break
        page += 1
    return out


def fetch_result_by_id(sporttery_id: str, match_date: date | None = None) -> tuple[str | None, str | None]:
    """按 sporttery_id 查询赛果，返回 (H/D/A | None, score | None)。在 asyncio.to_thread 中调用。
    优先走赛果专用接口（按比赛日期 ±1 天）；失败降级在售接口（仅对当天完赛有效）。"""
    if match_date is not None:
        from datetime import timedelta
        try:
            results = fetch_results_between(match_date - timedelta(days=1), match_date + timedelta(days=1))
            if sporttery_id in results:
                return results[sporttery_id]
        except ProviderError:
            pass  # 降级在售接口
    try:
        items = _fetch_raw_items()
    except ProviderError:
        return None, None
    for item in items:
        if str(item.get("matchId") or "") == sporttery_id:
            return _parse_result(item)
    return None, None


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
            actual_result, actual_score = _parse_result(item)
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
                "actual_result": actual_result,
                "actual_score": actual_score,
            })
    return result
