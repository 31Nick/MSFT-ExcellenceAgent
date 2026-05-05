"""Processing ledger — tracks which recommendations have been processed.

Extends the existing sync SQLite database (.state/sync.db) with tables
for deduplication across incremental pipeline runs and per-resource-type
run numbering.

Tables:
    processed_recommendations — one row per (app, guid, resource_id)
    resource_type_runs — per (app, resource_type) run counter

Note: The `customer` column is retained in the schema for backward
compatibility but defaults to '_default' (single-customer mode).
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, List, Optional, Set, Tuple

_DEFAULT_STATE_DIR = Path(__file__).parent.parent.parent / ".state"
_DEFAULT_CUSTOMER = "_default"

_LEDGER_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS processed_recommendations (
    customer TEXT NOT NULL,
    app_name TEXT NOT NULL,
    recommendation_guid TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    source_file TEXT DEFAULT '',
    processed_at TEXT NOT NULL,
    run_number INTEGER NOT NULL,
    story_stable_key TEXT DEFAULT '',
    PRIMARY KEY (customer, app_name, recommendation_guid, resource_id)
);

CREATE TABLE IF NOT EXISTS resource_type_runs (
    customer TEXT NOT NULL,
    app_name TEXT NOT NULL,
    resource_type_norm TEXT NOT NULL,
    run_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (customer, app_name, resource_type_norm)
);

CREATE INDEX IF NOT EXISTS idx_processed_recs_customer_app
    ON processed_recommendations (customer, app_name);

CREATE INDEX IF NOT EXISTS idx_processed_recs_run
    ON processed_recommendations (customer, app_name, run_number);
"""


class ProcessingLedger:
    """SQLite-backed ledger for tracking processed recommendations.

    Shares the same database file as SyncStateStore (.state/sync.db)
    but uses separate tables.
    """

    def __init__(self, state_dir: Optional[Path] = None) -> None:
        self._state_dir = state_dir or _DEFAULT_STATE_DIR
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._state_dir / "sync.db"
        self._init_tables()

    def _init_tables(self) -> None:
        with self._connect() as conn:
            conn.executescript(_LEDGER_SCHEMA_SQL)

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Query methods ─────────────────────────────────────────────────

    def is_already_processed(
        self,
        customer: str = _DEFAULT_CUSTOMER,
        app_name: str = "",
        recommendation_guid: str = "",
        resource_id: str = "",
    ) -> bool:
        """Check if a specific (guid, resource_id) has been processed before."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT 1 FROM processed_recommendations
                   WHERE customer = ? AND app_name = ?
                   AND recommendation_guid = ? AND resource_id = ?""",
                (customer, app_name, recommendation_guid, resource_id),
            ).fetchone()
        return row is not None

    def get_already_processed_keys(
        self,
        customer: str = _DEFAULT_CUSTOMER,
        app_name: str = "",
    ) -> Set[Tuple[str, str]]:
        """Return all (recommendation_guid, resource_id) pairs already processed."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT recommendation_guid, resource_id
                   FROM processed_recommendations
                   WHERE customer = ? AND app_name = ?""",
                (customer, app_name),
            ).fetchall()
        return {(r["recommendation_guid"], r["resource_id"]) for r in rows}

    def get_next_run_number(
        self,
        customer: str = _DEFAULT_CUSTOMER,
        app_name: str = "",
        resource_type_norm: str = "",
    ) -> int:
        """Get the next run number for a (customer, app, resource_type).

        Increments the counter and returns the new value.
        """
        with self._connect() as conn:
            row = conn.execute(
                """SELECT run_count FROM resource_type_runs
                   WHERE customer = ? AND app_name = ? AND resource_type_norm = ?""",
                (customer, app_name, resource_type_norm),
            ).fetchone()

            if row is None:
                new_count = 1
                conn.execute(
                    """INSERT INTO resource_type_runs
                       (customer, app_name, resource_type_norm, run_count)
                       VALUES (?, ?, ?, ?)""",
                    (customer, app_name, resource_type_norm, new_count),
                )
            else:
                new_count = row["run_count"] + 1
                conn.execute(
                    """UPDATE resource_type_runs SET run_count = ?
                       WHERE customer = ? AND app_name = ? AND resource_type_norm = ?""",
                    (new_count, customer, app_name, resource_type_norm),
                )

        return new_count

    def peek_next_run_number(
        self,
        customer: str = _DEFAULT_CUSTOMER,
        app_name: str = "",
        resource_type_norm: str = "",
    ) -> int:
        """Preview the next run number WITHOUT incrementing."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT run_count FROM resource_type_runs
                   WHERE customer = ? AND app_name = ? AND resource_type_norm = ?""",
                (customer, app_name, resource_type_norm),
            ).fetchone()
        return (row["run_count"] + 1) if row else 1

    def get_current_run_count(
        self,
        customer: str = _DEFAULT_CUSTOMER,
        app_name: str = "",
        resource_type_norm: str = "",
    ) -> int:
        """Get current run count (0 if never processed)."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT run_count FROM resource_type_runs
                   WHERE customer = ? AND app_name = ? AND resource_type_norm = ?""",
                (customer, app_name, resource_type_norm),
            ).fetchone()
        return row["run_count"] if row else 0

    # ── Record methods ────────────────────────────────────────────────

    def record_processed(
        self,
        customer: str = _DEFAULT_CUSTOMER,
        app_name: str = "",
        recommendation_guid: str = "",
        resource_id: str = "",
        run_number: int = 1,
        *,
        source_file: str = "",
        story_stable_key: str = "",
    ) -> None:
        """Record a single recommendation+resource as processed."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO processed_recommendations
                   (customer, app_name, recommendation_guid, resource_id,
                    source_file, processed_at, run_number, story_stable_key)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    customer, app_name, recommendation_guid, resource_id,
                    source_file, now, run_number, story_stable_key,
                ),
            )

    def record_processed_batch(
        self,
        customer: str = _DEFAULT_CUSTOMER,
        app_name: str = "",
        items: List[Tuple[str, str]] = None,  # (recommendation_guid, resource_id)
        run_number: int = 1,
        *,
        source_file: str = "",
        story_stable_key: str = "",
    ) -> int:
        """Record multiple items as processed in a single transaction.

        Returns the number of newly inserted records (ignores duplicates).
        """
        if items is None:
            items = []
        now = datetime.now(timezone.utc).isoformat()
        inserted = 0
        with self._connect() as conn:
            for guid, resource_id in items:
                cursor = conn.execute(
                    """INSERT OR IGNORE INTO processed_recommendations
                       (customer, app_name, recommendation_guid, resource_id,
                        source_file, processed_at, run_number, story_stable_key)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        customer, app_name, guid, resource_id,
                        source_file, now, run_number, story_stable_key,
                    ),
                )
                inserted += cursor.rowcount
        return inserted

    # ── Stats ─────────────────────────────────────────────────────────

    def get_stats(self, customer: str, app_name: Optional[str] = None) -> dict:
        """Get processing statistics."""
        with self._connect() as conn:
            if app_name:
                total = conn.execute(
                    "SELECT COUNT(*) as c FROM processed_recommendations WHERE customer = ? AND app_name = ?",
                    (customer, app_name),
                ).fetchone()["c"]
                runs = conn.execute(
                    "SELECT SUM(run_count) as c FROM resource_type_runs WHERE customer = ? AND app_name = ?",
                    (customer, app_name),
                ).fetchone()["c"] or 0
            else:
                total = conn.execute(
                    "SELECT COUNT(*) as c FROM processed_recommendations WHERE customer = ?",
                    (customer,),
                ).fetchone()["c"]
                runs = conn.execute(
                    "SELECT SUM(run_count) as c FROM resource_type_runs WHERE customer = ?",
                    (customer,),
                ).fetchone()["c"] or 0

        return {
            "total_processed": total,
            "total_runs": runs,
        }

    def reset(self, customer: str, app_name: Optional[str] = None) -> None:
        """Reset ledger data. Use with caution."""
        with self._connect() as conn:
            if app_name:
                conn.execute(
                    "DELETE FROM processed_recommendations WHERE customer = ? AND app_name = ?",
                    (customer, app_name),
                )
                conn.execute(
                    "DELETE FROM resource_type_runs WHERE customer = ? AND app_name = ?",
                    (customer, app_name),
                )
            else:
                conn.execute(
                    "DELETE FROM processed_recommendations WHERE customer = ?",
                    (customer,),
                )
                conn.execute(
                    "DELETE FROM resource_type_runs WHERE customer = ?",
                    (customer,),
                )
