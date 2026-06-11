"""Assessment store — persists pipeline results for multi-assessment switching.

Stores V2 hierarchy results as JSON in SQLite so the user can switch
between different application assessments without re-uploading.

Database: .state/assessments.db
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

_DEFAULT_STATE_DIR = Path(__file__).parent.parent.parent / ".state"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    source_filename TEXT DEFAULT '',
    reviewed_only INTEGER NOT NULL DEFAULT 1,
    stats_json TEXT DEFAULT '{}',
    hierarchy_json TEXT NOT NULL,
    items_processed INTEGER DEFAULT 0,
    items_skipped INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_assessments_app_name
    ON assessments (app_name);

CREATE INDEX IF NOT EXISTS idx_assessments_created
    ON assessments (created_at DESC);
"""


@dataclass
class AssessmentSummary:
    """Lightweight summary of a stored assessment (no hierarchy blob)."""

    id: int
    app_name: str
    created_at: str
    source_filename: str
    reviewed_only: bool
    stats: Dict[str, Any]
    items_processed: int
    items_skipped: int


class AssessmentStore:
    """SQLite-backed store for persisting assessment results."""

    def __init__(self, state_dir: Optional[Path] = None) -> None:
        self._state_dir = state_dir or _DEFAULT_STATE_DIR
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._state_dir / "assessments.db"
        self._init_tables()

    def _init_tables(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA_SQL)

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def save(
        self,
        app_name: str,
        hierarchy_dict: Dict[str, Any],
        stats: Dict[str, Any],
        *,
        source_filename: str = "",
        reviewed_only: bool = True,
        items_processed: int = 0,
        items_skipped: int = 0,
    ) -> int:
        """Save an assessment and return its ID."""
        now = datetime.now(timezone.utc).isoformat()
        hierarchy_json = json.dumps(hierarchy_dict, default=str)
        stats_json = json.dumps(stats, default=str)

        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO assessments
                   (app_name, created_at, source_filename, reviewed_only,
                    stats_json, hierarchy_json, items_processed, items_skipped)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    app_name, now, source_filename, int(reviewed_only),
                    stats_json, hierarchy_json, items_processed, items_skipped,
                ),
            )
            return cursor.lastrowid

    def load_hierarchy_dict(self, assessment_id: int) -> Optional[Dict[str, Any]]:
        """Load the raw hierarchy dict for an assessment."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT hierarchy_json FROM assessments WHERE id = ?",
                (assessment_id,),
            ).fetchone()

        if row is None:
            return None
        return json.loads(row["hierarchy_json"])

    def get_summary(self, assessment_id: int) -> Optional[AssessmentSummary]:
        """Get summary info for a single assessment."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT id, app_name, created_at, source_filename,
                          reviewed_only, stats_json, items_processed, items_skipped
                   FROM assessments WHERE id = ?""",
                (assessment_id,),
            ).fetchone()

        if row is None:
            return None
        return self._row_to_summary(row)

    def list_assessments(self, app_name: Optional[str] = None) -> List[AssessmentSummary]:
        """List all assessments, optionally filtered by app name."""
        with self._connect() as conn:
            if app_name:
                rows = conn.execute(
                    """SELECT id, app_name, created_at, source_filename,
                              reviewed_only, stats_json, items_processed, items_skipped
                       FROM assessments WHERE app_name = ?
                       ORDER BY created_at DESC""",
                    (app_name,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT id, app_name, created_at, source_filename,
                              reviewed_only, stats_json, items_processed, items_skipped
                       FROM assessments ORDER BY created_at DESC""",
                ).fetchall()

        return [self._row_to_summary(r) for r in rows]

    def delete(self, assessment_id: int) -> bool:
        """Delete an assessment. Returns True if found and deleted."""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM assessments WHERE id = ?", (assessment_id,)
            )
            return cursor.rowcount > 0

    def get_latest(self, app_name: Optional[str] = None) -> Optional[AssessmentSummary]:
        """Get the most recent assessment (optionally for a specific app)."""
        with self._connect() as conn:
            if app_name:
                row = conn.execute(
                    """SELECT id, app_name, created_at, source_filename,
                              reviewed_only, stats_json, items_processed, items_skipped
                       FROM assessments WHERE app_name = ?
                       ORDER BY created_at DESC LIMIT 1""",
                    (app_name,),
                ).fetchone()
            else:
                row = conn.execute(
                    """SELECT id, app_name, created_at, source_filename,
                              reviewed_only, stats_json, items_processed, items_skipped
                       FROM assessments ORDER BY created_at DESC LIMIT 1""",
                ).fetchone()

        if row is None:
            return None
        return self._row_to_summary(row)

    def _row_to_summary(self, row: sqlite3.Row) -> AssessmentSummary:
        return AssessmentSummary(
            id=row["id"],
            app_name=row["app_name"],
            created_at=row["created_at"],
            source_filename=row["source_filename"],
            reviewed_only=bool(row["reviewed_only"]),
            stats=json.loads(row["stats_json"]),
            items_processed=row["items_processed"],
            items_skipped=row["items_skipped"],
        )
