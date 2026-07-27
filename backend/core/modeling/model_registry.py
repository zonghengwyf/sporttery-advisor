"""
Model registry with Champion/Challenger versioning.

Stores trained model metadata in the DuckDB snapshot database.
Promotion gates follow football-prediction-skill thresholds:
  Brier reduction ≥ 0.001 AND log_loss reduction ≥ 0.001.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── 数据类 ────────────────────────────────────────────────────────────────────

@dataclass
class ModelMetrics:
    brier:    float = 0.0
    log_loss: float = 0.0
    rps:      float = 0.0
    ece:      float = 0.0
    n:        int   = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "brier": self.brier,
            "log_loss": self.log_loss,
            "rps": self.rps,
            "ece": self.ece,
            "n": self.n,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ModelMetrics":
        return cls(
            brier=float(d.get("brier", 0)),
            log_loss=float(d.get("log_loss", 0)),
            rps=float(d.get("rps", 0)),
            ece=float(d.get("ece", 0)),
            n=int(d.get("n", 0)),
        )


@dataclass
class ModelRecord:
    model_id:      str
    competition:   str
    trained_until: str          # ISO date "2026-07-01"
    metrics:       ModelMetrics
    is_champion:   bool = False
    promoted_at:   Optional[str] = None
    metadata:      dict[str, Any] = field(default_factory=dict)


# ── Promotion gate ────────────────────────────────────────────────────────────

# Thresholds from football-prediction-skill audit
_BRIER_MIN_IMPROVEMENT    = 0.001
_LOG_LOSS_MIN_IMPROVEMENT = 0.001


def should_promote(challenger: ModelMetrics, champion: ModelMetrics) -> bool:
    """True when challenger meaningfully beats the current champion."""
    return (
        (champion.brier - challenger.brier) >= _BRIER_MIN_IMPROVEMENT
        and (champion.log_loss - challenger.log_loss) >= _LOG_LOSS_MIN_IMPROVEMENT
    )


# ── ModelRegistry ─────────────────────────────────────────────────────────────

class ModelRegistry:
    """
    Stores and manages model versions in the shared DuckDB snapshot database.
    Thread-safe via asyncio.to_thread for all DuckDB calls.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path

    def init_table(self) -> None:
        """Create model_registry table if not exists. Called once at startup."""
        import duckdb
        con = duckdb.connect(self.db_path)
        try:
            con.execute("""
                CREATE TABLE IF NOT EXISTS model_registry (
                    model_id      TEXT      PRIMARY KEY,
                    competition   TEXT      NOT NULL,
                    trained_until DATE      NOT NULL,
                    brier         FLOAT     NOT NULL,
                    log_loss      FLOAT     NOT NULL,
                    rps           FLOAT     NOT NULL DEFAULT 0,
                    ece           FLOAT     NOT NULL DEFAULT 0,
                    n_samples     INTEGER   NOT NULL DEFAULT 0,
                    is_champion   BOOLEAN   NOT NULL DEFAULT FALSE,
                    promoted_at   TIMESTAMP,
                    metadata      TEXT      DEFAULT '{}'
                )
            """)
        finally:
            con.close()

    # ── Async public API ──────────────────────────────────────────────────────

    async def register(
        self,
        model_id: str,
        competition: str,
        trained_until: str,
        metrics: ModelMetrics,
        metadata: Optional[dict] = None,
    ) -> None:
        """Insert or replace a model record (not yet champion)."""
        db_path = self.db_path
        meta_json = json.dumps(metadata or {})

        def _write():
            import duckdb
            con = duckdb.connect(db_path)
            try:
                con.execute(
                    "DELETE FROM model_registry WHERE model_id = ?", [model_id]
                )
                con.execute(
                    """
                    INSERT INTO model_registry
                        (model_id, competition, trained_until,
                         brier, log_loss, rps, ece, n_samples,
                         is_champion, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, FALSE, ?)
                    """,
                    [model_id, competition, trained_until,
                     metrics.brier, metrics.log_loss, metrics.rps, metrics.ece, metrics.n,
                     meta_json],
                )
            finally:
                con.close()

        await asyncio.to_thread(_write)
        logger.info("Registered model %s for %s (Brier=%.4f)", model_id, competition, metrics.brier)

    async def promote(self, model_id: str) -> None:
        """Promote model_id to champion; demote all others in the same competition."""
        db_path = self.db_path

        def _promote():
            import duckdb
            con = duckdb.connect(db_path)
            try:
                row = con.execute(
                    "SELECT competition FROM model_registry WHERE model_id = ?", [model_id]
                ).fetchone()
                if not row:
                    raise ValueError(f"Model {model_id!r} not found in registry")
                competition = row[0]
                now = datetime.now(timezone.utc).isoformat()
                # Atomic: demote all then promote challenger
                con.execute("BEGIN")
                con.execute(
                    "UPDATE model_registry SET is_champion = FALSE WHERE competition = ?",
                    [competition],
                )
                con.execute(
                    "UPDATE model_registry SET is_champion = TRUE, promoted_at = ? WHERE model_id = ?",
                    [now, model_id],
                )
                con.execute("COMMIT")
            except Exception:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                con.close()

        await asyncio.to_thread(_promote)
        logger.info("Promoted model %s to champion", model_id)

    async def get_champion(self, competition: str) -> Optional[ModelRecord]:
        """Return the current champion for a competition, or None."""
        db_path = self.db_path

        def _query():
            import duckdb
            con = duckdb.connect(db_path, read_only=True)
            try:
                row = con.execute(
                    """
                    SELECT model_id, competition, trained_until,
                           brier, log_loss, rps, ece, n_samples,
                           is_champion, promoted_at, metadata
                    FROM model_registry
                    WHERE competition = ? AND is_champion = TRUE
                    LIMIT 1
                    """,
                    [competition],
                ).fetchone()
                return row
            finally:
                con.close()

        row = await asyncio.to_thread(_query)
        if not row:
            return None

        (model_id, comp, trained_until,
         brier, log_loss, rps, ece, n,
         is_champ, promoted_at, meta_json) = row

        return ModelRecord(
            model_id=model_id,
            competition=comp,
            trained_until=str(trained_until),
            metrics=ModelMetrics(brier=brier, log_loss=log_loss, rps=rps, ece=ece, n=n),
            is_champion=bool(is_champ),
            promoted_at=str(promoted_at) if promoted_at else None,
            metadata=json.loads(meta_json or "{}"),
        )

    async def try_auto_promote(
        self,
        model_id: str,
        competition: str,
        trained_until: str,
        metrics: ModelMetrics,
        metadata: Optional[dict] = None,
    ) -> bool:
        """
        Register challenger and auto-promote if it beats the current champion.
        Returns True when promoted.
        """
        await self.register(model_id, competition, trained_until, metrics, metadata)
        champion = await self.get_champion(competition)

        if champion is None:
            # No existing champion → auto-promote first model
            await self.promote(model_id)
            logger.info("Auto-promoted %s (first model for %s)", model_id, competition)
            return True

        if should_promote(metrics, champion.metrics):
            await self.promote(model_id)
            logger.info(
                "Auto-promoted challenger %s over champion %s "
                "(ΔBrier=%.4f, ΔLogLoss=%.4f)",
                model_id, champion.model_id,
                champion.metrics.brier - metrics.brier,
                champion.metrics.log_loss - metrics.log_loss,
            )
            return True

        logger.info(
            "Challenger %s did not beat champion %s "
            "(ΔBrier=%.4f, ΔLogLoss=%.4f — thresholds: %.3f, %.3f)",
            model_id, champion.model_id,
            champion.metrics.brier - metrics.brier,
            champion.metrics.log_loss - metrics.log_loss,
            _BRIER_MIN_IMPROVEMENT, _LOG_LOSS_MIN_IMPROVEMENT,
        )
        return False
