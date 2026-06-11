"""SQLite-backed sync state store for ADO MCP integration.

Tracks which work items have been pushed to ADO, their content hashes
(for change detection), ADO IDs, and parent-child relationships.

The DB lives at ``.state/sync.db`` (gitignored). All data is scoped
by ``customer`` slug to prevent cross-customer contamination.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from filelock import FileLock

_DEFAULT_STATE_DIR = Path(__file__).parent.parent.parent / ".state"

# ── Data classes ──────────────────────────────────────────────────────────


@dataclass
class SyncItem:
    """One tracked work item in the state store."""

    stable_key: str
    customer: str
    ado_work_item_id: Optional[int] = None
    work_item_type: str = ""
    title: str = ""
    content_hash: str = ""
    parent_stable_key: str = ""
    parent_ado_id: Optional[int] = None
    sync_status: str = "pending"  # pending/created/linked/updated/failed/orphaned
    error_message: str = ""
    last_synced_at: Optional[str] = None
    run_id: Optional[int] = None


@dataclass
class SyncRun:
    """A single sync execution."""

    id: Optional[int] = None
    customer: str = ""
    started_at: str = ""
    completed_at: Optional[str] = None
    status: str = "running"  # running/completed/failed/cancelled
    items_created: int = 0
    items_updated: int = 0
    items_unchanged: int = 0
    items_linked: int = 0
    items_failed: int = 0
    items_orphaned: int = 0


# ── Content hashing ──────────────────────────────────────────────────────


def compute_content_hash(fields: Dict[str, Any]) -> str:
    """Compute SHA-256 hash of the canonical JSON representation of *fields*.

    *fields* should include everything that gets pushed to ADO:
    title, description, work_item_type, area_path, iteration_path,
    acceptance_criteria, tags, priority, etc.
    """
    canonical = json.dumps(fields, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── State store ──────────────────────────────────────────────────────────


class SyncStateStore:
    """SQLite-backed state store for ADO sync tracking."""

    def __init__(self, state_dir: Optional[Path] = None) -> None:
        self._state_dir = state_dir or _DEFAULT_STATE_DIR
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._state_dir / "sync.db"
        self._init_db()

    # ── lifecycle ─────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA_SQL)

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

    # ── customer lock ─────────────────────────────────────────────────

    @contextmanager
    def customer_lock(self, customer: str) -> Generator[None, None, None]:
        """Acquire a file-based lock for *customer* to prevent concurrent syncs."""
        lock_path = self._state_dir / f"{customer}.lock"
        lock = FileLock(str(lock_path), timeout=5)
        with lock:
            yield

    # ── sync items ────────────────────────────────────────────────────

    def upsert_item(self, item: SyncItem) -> None:
        """Insert or update a sync item (keyed by stable_key + customer)."""
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO sync_items (
                    stable_key, customer, ado_work_item_id, work_item_type,
                    title, content_hash, parent_stable_key, parent_ado_id,
                    sync_status, error_message, last_synced_at, run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (stable_key, customer) DO UPDATE SET
                    ado_work_item_id = excluded.ado_work_item_id,
                    work_item_type = excluded.work_item_type,
                    title = excluded.title,
                    content_hash = excluded.content_hash,
                    parent_stable_key = excluded.parent_stable_key,
                    parent_ado_id = excluded.parent_ado_id,
                    sync_status = excluded.sync_status,
                    error_message = excluded.error_message,
                    last_synced_at = excluded.last_synced_at,
                    run_id = excluded.run_id
                """,
                (
                    item.stable_key, item.customer, item.ado_work_item_id,
                    item.work_item_type, item.title, item.content_hash,
                    item.parent_stable_key, item.parent_ado_id,
                    item.sync_status, item.error_message,
                    item.last_synced_at, item.run_id,
                ),
            )

    def get_item(self, stable_key: str, customer: str) -> Optional[SyncItem]:
        """Retrieve a single sync item."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sync_items WHERE stable_key = ? AND customer = ?",
                (stable_key, customer),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_item(row)

    def get_items_by_customer(self, customer: str) -> List[SyncItem]:
        """Get all sync items for a customer."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sync_items WHERE customer = ? ORDER BY work_item_type, stable_key",
                (customer,),
            ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def get_items_for_retry(self, customer: str, run_id: Optional[int] = None) -> List[SyncItem]:
        """Get failed items eligible for retry."""
        with self._connect() as conn:
            if run_id:
                rows = conn.execute(
                    "SELECT * FROM sync_items WHERE customer = ? AND sync_status = 'failed' AND run_id = ?",
                    (customer, run_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM sync_items WHERE customer = ? AND sync_status = 'failed'",
                    (customer,),
                ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def mark_orphaned(self, customer: str, active_keys: set[str], run_id: int) -> int:
        """Mark items not in *active_keys* as orphaned. Returns count."""
        with self._connect() as conn:
            if active_keys:
                placeholders = ",".join("?" for _ in active_keys)
                cursor = conn.execute(
                    f"""UPDATE sync_items
                        SET sync_status = 'orphaned', run_id = ?
                        WHERE customer = ?
                        AND stable_key NOT IN ({placeholders})
                        AND sync_status NOT IN ('orphaned', 'pending')""",
                    [run_id, customer, *active_keys],
                )
            else:
                cursor = conn.execute(
                    """UPDATE sync_items
                        SET sync_status = 'orphaned', run_id = ?
                        WHERE customer = ?
                        AND sync_status NOT IN ('orphaned', 'pending')""",
                    [run_id, customer],
                )
            return cursor.rowcount

    # ── sync runs ─────────────────────────────────────────────────────

    def create_run(self, customer: str) -> SyncRun:
        """Start a new sync run."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO sync_runs (customer, started_at) VALUES (?, ?)",
                (customer, now),
            )
            run_id = cursor.lastrowid
        return SyncRun(id=run_id, customer=customer, started_at=now)

    def update_run(self, run: SyncRun) -> None:
        """Update a sync run with final stats."""
        with self._connect() as conn:
            conn.execute(
                """UPDATE sync_runs SET
                    completed_at = ?, status = ?,
                    items_created = ?, items_updated = ?,
                    items_unchanged = ?, items_linked = ?,
                    items_failed = ?, items_orphaned = ?
                WHERE id = ?""",
                (
                    run.completed_at, run.status,
                    run.items_created, run.items_updated,
                    run.items_unchanged, run.items_linked,
                    run.items_failed, run.items_orphaned,
                    run.id,
                ),
            )

    def get_runs(self, customer: str, limit: int = 20) -> List[SyncRun]:
        """Get recent sync runs for a customer."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sync_runs WHERE customer = ? ORDER BY id DESC LIMIT ?",
                (customer, limit),
            ).fetchall()
        return [self._row_to_run(r) for r in rows]

    # ── helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> SyncItem:
        return SyncItem(
            stable_key=row["stable_key"],
            customer=row["customer"],
            ado_work_item_id=row["ado_work_item_id"],
            work_item_type=row["work_item_type"],
            title=row["title"],
            content_hash=row["content_hash"],
            parent_stable_key=row["parent_stable_key"] or "",
            parent_ado_id=row["parent_ado_id"],
            sync_status=row["sync_status"],
            error_message=row["error_message"] or "",
            last_synced_at=row["last_synced_at"],
            run_id=row["run_id"],
        )

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> SyncRun:
        return SyncRun(
            id=row["id"],
            customer=row["customer"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            status=row["status"],
            items_created=row["items_created"],
            items_updated=row["items_updated"],
            items_unchanged=row["items_unchanged"],
            items_linked=row["items_linked"],
            items_failed=row["items_failed"],
            items_orphaned=row["items_orphaned"],
        )


# ── SQL schema ────────────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sync_items (
    stable_key      TEXT NOT NULL,
    customer        TEXT NOT NULL,
    ado_work_item_id INTEGER,
    work_item_type  TEXT NOT NULL DEFAULT '',
    title           TEXT DEFAULT '',
    content_hash    TEXT DEFAULT '',
    parent_stable_key TEXT DEFAULT '',
    parent_ado_id   INTEGER,
    sync_status     TEXT DEFAULT 'pending',
    error_message   TEXT DEFAULT '',
    last_synced_at  TEXT,
    run_id          INTEGER,
    PRIMARY KEY (stable_key, customer)
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    customer        TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    completed_at    TEXT,
    status          TEXT DEFAULT 'running',
    items_created   INTEGER DEFAULT 0,
    items_updated   INTEGER DEFAULT 0,
    items_unchanged INTEGER DEFAULT 0,
    items_linked    INTEGER DEFAULT 0,
    items_failed    INTEGER DEFAULT 0,
    items_orphaned  INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_sync_items_customer
    ON sync_items (customer);
CREATE INDEX IF NOT EXISTS idx_sync_items_status
    ON sync_items (customer, sync_status);
CREATE INDEX IF NOT EXISTS idx_sync_runs_customer
    ON sync_runs (customer);
"""
