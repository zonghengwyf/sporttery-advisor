"""football-data.co.uk 数据提供者 — 免费，无需 API Key。

提供：近期战绩（get_recent_form）、历史交锋（get_h2h）。
CSV 格式文档：https://www.football-data.co.uk/notes.txt
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import time
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from core.data.team_names import fuzzy_match_english, resolve_to_english

logger = logging.getLogger(__name__)

_CACHE_DIR = Path("/tmp/sporttery_cache")

# 联赛 → (football-data 代码, 赛季 CSV 路径模板)
_LEAGUE_MAP: dict[str, str] = {
    "英超": "E0",
    "英冠": "E1",
    "西甲": "SP1",
    "西乙": "SP2",
    "德甲": "D1",
    "德乙": "D2",
    "意甲": "I1",
    "意乙": "I2",
    "法甲": "F1",
    "法乙": "F2",
    "荷甲": "N1",
    "葡超": "P1",
    "比甲": "B1",
    "苏超": "SC0",
    "土超": "T1",
    "希腊超": "G1",
}

_BASE_URL = "https://www.football-data.co.uk/mmz4281"


def _season_codes(n_seasons: int = 2) -> list[str]:
    """生成最近 N 个赛季代码，如 '2425', '2324'。"""
    current_year = date.today().year
    current_month = date.today().month
    # 欧洲赛季通常 7 月开始
    if current_month >= 7:
        start_year = current_year
    else:
        start_year = current_year - 1

    codes = []
    for i in range(n_seasons):
        y = start_year - i
        codes.append(f"{y % 100:02d}{(y + 1) % 100:02d}")
    return codes


class FootballDataProvider:
    def __init__(self):
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ── 公开接口 ─────────────────────────────────────────────────────────────

    async def get_recent_form(
        self, team_cn: str, league_cn: str, n: int = 6
    ) -> list[dict]:
        """返回球队最近 n 场比赛，按时间倒序。
        每条记录：{date, opponent, home_away, gf, ga, result, xg, xga}
        """
        rows = await asyncio.to_thread(self._load_league_data, league_cn)
        if not rows:
            return []

        team_names = _collect_team_names(rows)
        team_en = fuzzy_match_english(team_cn, team_names)
        if not team_en:
            logger.debug("recent_form: 找不到球队 %s（联赛 %s）", team_cn, league_cn)
            return []

        matches = []
        for row in rows:
            if row.get("HomeTeam") == team_en:
                matches.append(_build_form_entry(row, team_en, "H"))
            elif row.get("AwayTeam") == team_en:
                matches.append(_build_form_entry(row, team_en, "A"))

        # 按日期倒序
        matches.sort(key=lambda x: x["date"], reverse=True)
        return matches[:n]

    async def get_h2h(
        self, home_cn: str, away_cn: str, league_cn: str, n: int = 6
    ) -> list[dict]:
        """返回两队历史交锋最近 n 场，不限主客场。"""
        rows = await asyncio.to_thread(self._load_league_data, league_cn)
        if not rows:
            return []

        team_names = _collect_team_names(rows)
        home_en = fuzzy_match_english(home_cn, team_names)
        away_en = fuzzy_match_english(away_cn, team_names)
        if not home_en or not away_en:
            return []

        results = []
        for row in rows:
            ht = row.get("HomeTeam", "")
            at = row.get("AwayTeam", "")
            if (ht == home_en and at == away_en) or (ht == away_en and at == home_en):
                results.append({
                    "date": _parse_date(row.get("Date", "")),
                    "home_team": ht,
                    "away_team": at,
                    "home_goals": _safe_int(row.get("FTHG")),
                    "away_goals": _safe_int(row.get("FTAG")),
                    "result": row.get("FTR", ""),  # H/D/A
                    "xg_home": _safe_float(row.get("xg") or row.get("HxG")),
                    "xg_away": _safe_float(row.get("xga") or row.get("AxG")),
                })

        results.sort(key=lambda x: x["date"], reverse=True)
        return results[:n]

    # ── 内部实现 ─────────────────────────────────────────────────────────────

    def _load_league_data(self, league_cn: str) -> list[dict]:
        """加载联赛数据（最近 2 赛季合并），结果按日期排序。"""
        league_code = _LEAGUE_MAP.get(league_cn)
        if not league_code:
            # 尝试模糊匹配联赛名
            for k, v in _LEAGUE_MAP.items():
                if k in league_cn or league_cn in k:
                    league_code = v
                    break
        if not league_code:
            logger.debug("football_data: 不支持联赛 %s", league_cn)
            return []

        all_rows: list[dict] = []
        for season in _season_codes(2):
            rows = self._fetch_season(league_code, season)
            all_rows.extend(rows)

        all_rows.sort(key=lambda r: _parse_date(r.get("Date", "")))
        return all_rows

    def _fetch_season(self, league_code: str, season: str) -> list[dict]:
        """下载单赛季 CSV，带本地缓存（当前赛季 6 小时 TTL，历史赛季永久缓存）。"""
        cache_path = _CACHE_DIR / f"fd_{league_code}_{season}.csv"
        current_seasons = _season_codes(1)
        is_current = season in current_seasons
        _SIX_HOURS = 6 * 3600
        cache_valid = (
            cache_path.exists()
            and cache_path.stat().st_size > 0
            and (not is_current or time.time() - cache_path.stat().st_mtime < _SIX_HOURS)
        )
        if cache_valid:
            return _parse_csv(cache_path.read_text(encoding="utf-8-sig", errors="replace"))

        url = f"{_BASE_URL}/{season}/{league_code}.csv"
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                text = resp.read().decode("utf-8-sig", errors="replace")
            cache_path.write_text(text, encoding="utf-8")
            return _parse_csv(text)
        except Exception as exc:
            logger.debug("football_data %s %s 下载失败：%s", league_code, season, exc)
            return []


# ── 历史数据批量获取（供模型训练） ─────────────────────────────────────────

def fetch_seasons(n_seasons: int = 3) -> list[dict]:
    """下载最近 N 个赛季多联赛历史数据，返回标准化字典列表。
    每条记录：{date, home_team, away_team, home_goals, away_goals}
    """
    provider = FootballDataProvider()
    all_matches: list[dict] = []
    seasons = _season_codes(n_seasons)

    for league_code in _LEAGUE_MAP.values():
        for season in seasons:
            rows = provider._fetch_season(league_code, season)
            for row in rows:
                hg = _safe_int(row.get("FTHG"))
                ag = _safe_int(row.get("FTAG"))
                if hg is None or ag is None:
                    continue
                all_matches.append({
                    "date": _parse_date(row.get("Date", "")),
                    "home_team": row.get("HomeTeam", ""),
                    "away_team": row.get("AwayTeam", ""),
                    "home_goals": hg,
                    "away_goals": ag,
                })
    logger.info("fetch_seasons: %d 场历史比赛", len(all_matches))
    return all_matches


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def _parse_csv(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for row in reader:
        # 过滤空行（Date 为空）
        if row.get("Date", "").strip():
            rows.append(row)
    return rows


def _collect_team_names(rows: list[dict]) -> list[str]:
    names: set[str] = set()
    for row in rows:
        if row.get("HomeTeam"):
            names.add(row["HomeTeam"])
        if row.get("AwayTeam"):
            names.add(row["AwayTeam"])
    return list(names)


def _parse_date(raw: str) -> str:
    """将 DD/MM/YY 或 DD/MM/YYYY 等格式统一为 YYYY-MM-DD。"""
    raw = (raw or "").strip()
    for fmt in ("%d/%m/%y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass
    return raw


def _build_form_entry(row: dict, team: str, side: str) -> dict:
    """从 CSV 行构建单场战绩记录。side='H'=主场, 'A'=客场。"""
    if side == "H":
        opponent = row.get("AwayTeam", "")
        gf = _safe_int(row.get("FTHG"))
        ga = _safe_int(row.get("FTAG"))
        xg = _safe_float(row.get("HxG") or row.get("home_xg"))
        xga = _safe_float(row.get("AxG") or row.get("away_xg"))
        raw_result = row.get("FTR", "")
        result = "W" if raw_result == "H" else ("D" if raw_result == "D" else "L")
    else:
        opponent = row.get("HomeTeam", "")
        gf = _safe_int(row.get("FTAG"))
        ga = _safe_int(row.get("FTHG"))
        xg = _safe_float(row.get("AxG") or row.get("away_xg"))
        xga = _safe_float(row.get("HxG") or row.get("home_xg"))
        raw_result = row.get("FTR", "")
        result = "W" if raw_result == "A" else ("D" if raw_result == "D" else "L")

    return {
        "date": _parse_date(row.get("Date", "")),
        "opponent": opponent,
        "home_away": side,
        "gf": gf,
        "ga": ga,
        "result": result,
        "xg": xg,
        "xga": xga,
    }


def _safe_int(val) -> int | None:
    try:
        return int(float(val)) if val not in (None, "", "NA") else None
    except (TypeError, ValueError):
        return None


def _safe_float(val) -> float | None:
    try:
        return round(float(val), 2) if val not in (None, "", "NA") else None
    except (TypeError, ValueError):
        return None
