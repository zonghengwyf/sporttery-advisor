from __future__ import annotations

import asyncio
import json
import logging
import math
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class SnapshotManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # 初始化表结构（同步，单次连接）
        self._init_tables()

    def _init_tables(self):
        from core.modeling.model_registry import ModelRegistry
        ModelRegistry(self.db_path).init_table()

        import duckdb
        con = duckdb.connect(self.db_path)
        try:
            con.execute("CREATE SEQUENCE IF NOT EXISTS backtest_seq START 1")
            con.execute("CREATE SEQUENCE IF NOT EXISTS prediction_seq START 1")
            con.execute("""
                CREATE TABLE IF NOT EXISTS prediction_snapshots (
                    id           INTEGER DEFAULT nextval('prediction_seq') PRIMARY KEY,
                    match_id     INTEGER   NOT NULL,
                    run_id       TEXT      NOT NULL,
                    kickoff_at   TEXT,
                    stat_probs   TEXT,
                    fused_probs  TEXT,
                    intel_summary TEXT,
                    risk_label   TEXT,
                    confidence   FLOAT,
                    recorded_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS backtest_results (
                    id           INTEGER DEFAULT nextval('backtest_seq') PRIMARY KEY,
                    match_id     INTEGER   NOT NULL,
                    user_id      INTEGER   NOT NULL DEFAULT 0,
                    p_home       FLOAT     NOT NULL,
                    p_draw       FLOAT     NOT NULL,
                    p_away       FLOAT     NOT NULL,
                    actual       VARCHAR(1) NOT NULL,
                    home_odds    FLOAT,
                    draw_odds    FLOAT,
                    away_odds    FLOAT,
                    observed_at  TIMESTAMP,
                    as_of        TIMESTAMP,
                    kickoff_at   TIMESTAMP,
                    recorded_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Forward-compatible migration: add columns to existing tables
            for col, typedef in [
                ("observed_at", "TIMESTAMP"),
                ("as_of",       "TIMESTAMP"),
                ("kickoff_at",  "TIMESTAMP"),
                ("home_odds",   "FLOAT"),
                ("draw_odds",   "FLOAT"),
                ("away_odds",   "FLOAT"),
                ("pick",        "VARCHAR(1)"),   # ADR-006 CLV 追踪
                ("entry_odds",  "FLOAT"),
                ("close_odds",  "FLOAT"),
                ("clv",         "FLOAT"),
            ]:
                try:
                    con.execute(
                        f"ALTER TABLE backtest_results ADD COLUMN {col} {typedef}"
                    )
                except Exception:
                    pass  # column already exists
            try:
                con.execute(
                    "ALTER TABLE prediction_snapshots ADD COLUMN market_odds TEXT"
                )
            except Exception:
                pass  # column already exists
        finally:
            con.close()

    # ── 预测快照 ──────────────────────────────────────────────────────────────

    async def save_prediction(
        self,
        match_id: int,
        run_id: str,
        kickoff_at: str,
        stat_probs: dict,
        fused_probs: dict,
        intel_summary: str,
        risk_label: str,
        confidence: float,
        market_odds: dict | None = None,
    ) -> None:
        db_path = self.db_path
        stat_json   = json.dumps(stat_probs)
        fused_json  = json.dumps(fused_probs)
        odds_json   = json.dumps(market_odds) if market_odds else None

        def _insert():
            import duckdb
            con = duckdb.connect(db_path)
            try:
                con.execute(
                    """
                    INSERT INTO prediction_snapshots
                        (match_id, run_id, kickoff_at, stat_probs, fused_probs,
                         intel_summary, risk_label, confidence, market_odds)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [match_id, run_id, kickoff_at,
                     stat_json, fused_json,
                     intel_summary, risk_label, confidence, odds_json],
                )
            finally:
                con.close()

        await asyncio.to_thread(_insert)

    async def get_latest_prediction_odds(self, match_id: int) -> dict | None:
        """返回某场比赛最近一次预测快照中的赔率（预测时刻 entry 价，ADR-006）。"""
        db_path = self.db_path

        def _query():
            import duckdb
            con = duckdb.connect(db_path, read_only=True)
            try:
                row = con.execute(
                    """
                    SELECT market_odds FROM prediction_snapshots
                    WHERE match_id = ? AND market_odds IS NOT NULL
                    ORDER BY id DESC LIMIT 1
                    """,
                    [match_id],
                ).fetchone()
                return json.loads(row[0]) if row and row[0] else None
            finally:
                con.close()

        try:
            return await asyncio.to_thread(_query)
        except Exception:
            return None

    # ── 时间约束验证 ──────────────────────────────────────────────────────────

    @staticmethod
    def validate_event_time(
        observed_at: datetime | None,
        as_of: datetime | None,
        kickoff_at: datetime | None,
    ) -> None:
        """
        Enforce: observed_at ≤ as_of < kickoff_at.
        Prevents future data from leaking into predictions (look-ahead bias).
        Skips validation when any timestamp is None.
        """
        if observed_at and as_of and observed_at > as_of:
            raise ValueError(
                f"observed_at ({observed_at}) must be ≤ as_of ({as_of})"
            )
        if as_of and kickoff_at and as_of >= kickoff_at:
            raise ValueError(
                f"as_of ({as_of}) must be < kickoff_at ({kickoff_at})"
            )

    # ── 写入 ──────────────────────────────────────────────────────────────────

    async def save_backtest_result(
        self,
        match_id: int,
        predicted: dict,
        actual: str,
        user_id: int = 0,
        observed_at: datetime | None = None,
        as_of: datetime | None = None,
        kickoff_at: datetime | None = None,
        market_odds: dict | None = None,
        pick: str | None = None,
        entry_odds: float | None = None,
        close_odds: float | None = None,
        clv: float | None = None,
    ) -> None:
        self.validate_event_time(observed_at, as_of, kickoff_at)

        p_home = float(predicted.get("home", 0.33))
        p_draw = float(predicted.get("draw", 0.33))
        p_away = float(predicted.get("away", 0.34))
        total = max(p_home + p_draw + p_away, 1e-9)
        p_home, p_draw, p_away = p_home / total, p_draw / total, p_away / total

        h_odds = float(market_odds["home"]) if market_odds and market_odds.get("home") else None
        d_odds = float(market_odds["draw"]) if market_odds and market_odds.get("draw") else None
        a_odds = float(market_odds["away"]) if market_odds and market_odds.get("away") else None

        db_path = self.db_path

        def _insert():
            import duckdb
            con = duckdb.connect(db_path)
            try:
                # 幂等：同一场比赛同一用户只保留最新一条
                con.execute(
                    "DELETE FROM backtest_results WHERE match_id = ? AND user_id = ?",
                    [match_id, user_id],
                )
                con.execute(
                    "INSERT INTO backtest_results"
                    " (match_id, user_id, p_home, p_draw, p_away, actual,"
                    "  home_odds, draw_odds, away_odds,"
                    "  pick, entry_odds, close_odds, clv,"
                    "  observed_at, as_of, kickoff_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [match_id, user_id, p_home, p_draw, p_away, actual,
                     h_odds, d_odds, a_odds,
                     pick, entry_odds, close_odds, clv,
                     observed_at, as_of, kickoff_at],
                )
            finally:
                con.close()

        await asyncio.to_thread(_insert)

    # ── 读取指标 ──────────────────────────────────────────────────────────────

    async def get_backtest_metrics(self, days: int = 30, user_id: int = 0) -> dict | None:
        db_path = self.db_path
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(days=int(days))

        def _compute():
            import duckdb
            con = duckdb.connect(db_path, read_only=True)
            try:
                rows = con.execute(
                    """
                    SELECT p_home, p_draw, p_away, actual
                    FROM backtest_results
                    WHERE user_id = ?
                      AND recorded_at >= ?
                    """,
                    [user_id, cutoff],
                ).fetchall()
                if not rows:
                    return None
                metrics = _calc_metrics(rows)
                # CLV 聚合（ADR-006）：仅统计有完整买入/收盘价的记录
                try:
                    clv_rows = con.execute(
                        """
                        SELECT clv FROM backtest_results
                        WHERE user_id = ? AND recorded_at >= ? AND clv IS NOT NULL
                        """,
                        [user_id, cutoff],
                    ).fetchall()
                except Exception:
                    clv_rows = []
                if clv_rows:
                    clvs = [r[0] for r in clv_rows]
                    metrics["avg_clv"] = round(sum(clvs) / len(clvs), 4)
                    metrics["clv_positive_ratio"] = round(
                        sum(1 for c in clvs if c > 0) / len(clvs), 4
                    )
                    metrics["n_with_clv"] = len(clvs)
                else:
                    metrics["avg_clv"] = None
                    metrics["clv_positive_ratio"] = None
                    metrics["n_with_clv"] = 0
                return metrics
            finally:
                con.close()

        return await asyncio.to_thread(_compute)

    async def get_chart_data(self, days: int = 30, user_id: int = 0) -> dict:
        db_path = self.db_path
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(days=int(days))

        def _compute():
            import duckdb
            con = duckdb.connect(db_path, read_only=True)
            try:
                rows = con.execute(
                    """
                    SELECT date_trunc('day', recorded_at) AS day,
                           p_home, p_draw, p_away, actual
                    FROM backtest_results
                    WHERE user_id = ?
                      AND recorded_at >= ?
                    ORDER BY day
                    """,
                    [user_id, cutoff],
                ).fetchall()
            finally:
                con.close()

            by_date: dict[str, list] = {}
            for row in rows:
                key = str(row[0])[:10]
                by_date.setdefault(key, []).append(row[1:])

            dates, brier_series, baseline_series = [], [], []
            for d in sorted(by_date):
                group = by_date[d]
                dates.append(d)
                brier_series.append(round(_brier_score(group), 4))
                baseline_series.append(0.222)  # 三类等概随机基线 = 2/9

            return {"dates": dates, "brier_series": brier_series, "baseline_series": baseline_series}

        return await asyncio.to_thread(_compute)

    async def get_devig_historical(self, limit: int = 60) -> list[dict]:
        """
        返回最近 N 条含赔率的回测记录，供 select_devig_method() 选择最优去水差方法。
        """
        db_path = self.db_path

        def _query():
            import duckdb
            con = duckdb.connect(db_path, read_only=True)
            try:
                rows = con.execute(
                    """
                    SELECT home_odds, draw_odds, away_odds, actual
                    FROM backtest_results
                    WHERE home_odds IS NOT NULL
                      AND draw_odds IS NOT NULL
                      AND away_odds IS NOT NULL
                    ORDER BY recorded_at DESC
                    LIMIT ?
                    """,
                    [int(limit)],
                ).fetchall()
            finally:
                con.close()
            return [
                {"home_odds": r[0], "draw_odds": r[1], "away_odds": r[2], "actual": r[3]}
                for r in rows
            ]

        return await asyncio.to_thread(_query)

    def close(self):
        pass  # 连接已在每次操作后关闭，无需集中释放


# ── 指标计算 ──────────────────────────────────────────────────────────────────

def _outcome_vec(actual: str) -> tuple[float, float, float]:
    return (
        (1.0, 0.0, 0.0) if actual == "H" else
        (0.0, 1.0, 0.0) if actual == "D" else
        (0.0, 0.0, 1.0)
    )


def _brier_score(rows: list) -> float:
    total = 0.0
    for p_home, p_draw, p_away, actual in rows:
        i_h, i_d, i_a = _outcome_vec(actual)
        total += (p_home - i_h) ** 2 + (p_draw - i_d) ** 2 + (p_away - i_a) ** 2
    return total / len(rows)


# ── CLV 共享计算（ADR-006） ─────────────────────────────────────────────────

async def compute_clv_fields(
    snap,
    match_id: int,
    predicted: dict,
    close_all: dict | None,
    recommended: str | None = None,
) -> tuple[str | None, float | None, float | None, float | None]:
    """计算 (pick, entry_odds, close_odds, clv)。
    pick 优先取实际推荐方向（tickets.final_outcome），否则 argmax 概率；
    entry 为预测时刻快照赔率，close 为封盘赔率。数据不足时相应字段为 None。
    供 workers/tasks._auto_save_backtest 与 api/backtest.record 复用。"""
    if not predicted:
        return None, None, None, None
    p_map = {
        "H": predicted.get("home", 0),
        "D": predicted.get("draw", 0),
        "A": predicted.get("away", 0),
    }
    if not any(p_map.values()):
        return None, None, None, None
    pick = recommended if recommended in ("H", "D", "A") else max(p_map, key=p_map.__getitem__)
    key = {"H": "home", "D": "draw", "A": "away"}[pick]

    entry_all = await snap.get_latest_prediction_odds(match_id)
    entry_odds = float(entry_all[key]) if entry_all and entry_all.get(key) else None
    close_odds = float(close_all[key]) if close_all and close_all.get(key) else None
    clv = round(entry_odds / close_odds - 1, 4) if entry_odds and close_odds and close_odds > 0 else None
    return pick, entry_odds, close_odds, clv


def _calc_metrics(rows: list) -> dict:
    from core.modeling.metrics import rps as _rps

    n = len(rows)
    brier_sum = log_loss_sum = rps_sum = 0.0
    buckets: dict[int, list] = {i: [] for i in range(10)}
    eps = 1e-7

    for p_home, p_draw, p_away, actual in rows:
        probs = [p_home, p_draw, p_away]
        i_h, i_d, i_a = _outcome_vec(actual)
        indicators = [i_h, i_d, i_a]

        brier_sum += sum((p - i) ** 2 for p, i in zip(probs, indicators))
        log_loss_sum += -sum(i * math.log(max(p, eps)) for p, i in zip(probs, indicators))
        rps_sum += _rps(probs, indicators.index(1.0))

        max_p = max(probs)
        max_idx = probs.index(max_p)
        correct = 1.0 if indicators[max_idx] == 1.0 else 0.0
        buckets[min(int(max_p * 10), 9)].append((max_p, correct))

    ece = 0.0
    for bucket in buckets.values():
        if not bucket:
            continue
        avg_conf = sum(x[0] for x in bucket) / len(bucket)
        avg_acc = sum(x[1] for x in bucket) / len(bucket)
        ece += (len(bucket) / n) * abs(avg_conf - avg_acc)

    return {
        "brier":    round(brier_sum / n, 4),
        "log_loss": round(log_loss_sum / n, 4),
        "rps":      round(rps_sum / n, 4),
        "ece":      round(ece, 4),
        "n":        n,
    }
