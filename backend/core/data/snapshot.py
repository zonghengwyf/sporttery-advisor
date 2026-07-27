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
            ]:
                try:
                    con.execute(
                        f"ALTER TABLE backtest_results ADD COLUMN {col} {typedef}"
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
    ) -> None:
        db_path = self.db_path
        stat_json   = json.dumps(stat_probs)
        fused_json  = json.dumps(fused_probs)

        def _insert():
            import duckdb
            con = duckdb.connect(db_path)
            try:
                con.execute(
                    """
                    INSERT INTO prediction_snapshots
                        (match_id, run_id, kickoff_at, stat_probs, fused_probs,
                         intel_summary, risk_label, confidence)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [match_id, run_id, kickoff_at,
                     stat_json, fused_json,
                     intel_summary, risk_label, confidence],
                )
            finally:
                con.close()

        await asyncio.to_thread(_insert)

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
                    "  observed_at, as_of, kickoff_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [match_id, user_id, p_home, p_draw, p_away, actual,
                     h_odds, d_odds, a_odds,
                     observed_at, as_of, kickoff_at],
                )
            finally:
                con.close()

        await asyncio.to_thread(_insert)

    # ── 读取指标 ──────────────────────────────────────────────────────────────

    async def get_backtest_metrics(self, days: int = 30, user_id: int = 0) -> dict | None:
        db_path = self.db_path

        def _compute():
            import duckdb
            con = duckdb.connect(db_path, read_only=True)
            try:
                rows = con.execute(
                    f"""
                    SELECT p_home, p_draw, p_away, actual
                    FROM backtest_results
                    WHERE user_id = ?
                      AND recorded_at >= CURRENT_TIMESTAMP - INTERVAL '{int(days)}' DAY
                    """,
                    [user_id],
                ).fetchall()
                if not rows:
                    return None
                return _calc_metrics(rows)
            finally:
                con.close()

        return await asyncio.to_thread(_compute)

    async def get_chart_data(self, days: int = 30, user_id: int = 0) -> dict:
        db_path = self.db_path

        def _compute():
            import duckdb
            con = duckdb.connect(db_path, read_only=True)
            try:
                rows = con.execute(
                    f"""
                    SELECT date_trunc('day', recorded_at) AS day,
                           p_home, p_draw, p_away, actual
                    FROM backtest_results
                    WHERE user_id = ?
                      AND recorded_at >= CURRENT_TIMESTAMP - INTERVAL '{int(days)}' DAY
                    ORDER BY day
                    """,
                    [user_id],
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
                    f"""
                    SELECT home_odds, draw_odds, away_odds, actual
                    FROM backtest_results
                    WHERE home_odds IS NOT NULL
                      AND draw_odds IS NOT NULL
                      AND away_odds IS NOT NULL
                    ORDER BY recorded_at DESC
                    LIMIT {int(limit)}
                    """
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


def _calc_metrics(rows: list) -> dict:
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

        cum_p = [probs[0], probs[0] + probs[1], 1.0]
        cum_i = [indicators[0], indicators[0] + indicators[1], 1.0]
        rps_sum += sum((cp - ci) ** 2 for cp, ci in zip(cum_p, cum_i)) / 2

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
