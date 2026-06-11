"""Tests for excellence_agent.ado.state_store."""

from __future__ import annotations

from pathlib import Path

import pytest

from excellence_agent.ado.state_store import (
    SyncItem,
    SyncRun,
    SyncStateStore,
    compute_content_hash,
)


@pytest.fixture()
def store(tmp_path: Path) -> SyncStateStore:
    """Return a SyncStateStore backed by a temp directory."""
    return SyncStateStore(state_dir=tmp_path / ".state")


# ── compute_content_hash ──────────────────────────────────────────────────


class TestContentHash:
    def test_deterministic(self) -> None:
        fields = {"title": "Enable DDoS", "type": "Epic", "area_path": "Infra"}
        assert compute_content_hash(fields) == compute_content_hash(fields)

    def test_order_independent(self) -> None:
        a = compute_content_hash({"b": "2", "a": "1"})
        b = compute_content_hash({"a": "1", "b": "2"})
        assert a == b

    def test_different_values_differ(self) -> None:
        a = compute_content_hash({"title": "A"})
        b = compute_content_hash({"title": "B"})
        assert a != b

    def test_change_type_changes_hash(self) -> None:
        a = compute_content_hash({"title": "X", "work_item_type": "Epic"})
        b = compute_content_hash({"title": "X", "work_item_type": "Feature"})
        assert a != b

    def test_change_area_path_changes_hash(self) -> None:
        a = compute_content_hash({"title": "X", "area_path": "A"})
        b = compute_content_hash({"title": "X", "area_path": "B"})
        assert a != b


# ── SyncItem CRUD ─────────────────────────────────────────────────────────


class TestSyncItemCRUD:
    def test_upsert_and_get(self, store: SyncStateStore) -> None:
        item = SyncItem(
            stable_key="epic:networking",
            customer="acme",
            work_item_type="Epic",
            title="Networking",
            content_hash="abc123",
        )
        store.upsert_item(item)
        got = store.get_item("epic:networking", "acme")
        assert got is not None
        assert got.stable_key == "epic:networking"
        assert got.title == "Networking"
        assert got.sync_status == "pending"

    def test_upsert_updates_existing(self, store: SyncStateStore) -> None:
        item = SyncItem(stable_key="epic:data", customer="acme", title="Data v1")
        store.upsert_item(item)

        item.title = "Data v2"
        item.ado_work_item_id = 42
        item.sync_status = "created"
        store.upsert_item(item)

        got = store.get_item("epic:data", "acme")
        assert got is not None
        assert got.title == "Data v2"
        assert got.ado_work_item_id == 42
        assert got.sync_status == "created"

    def test_get_nonexistent_returns_none(self, store: SyncStateStore) -> None:
        assert store.get_item("epic:nope", "acme") is None

    def test_items_isolated_by_customer(self, store: SyncStateStore) -> None:
        store.upsert_item(SyncItem(stable_key="epic:net", customer="alpha", title="Alpha Net"))
        store.upsert_item(SyncItem(stable_key="epic:net", customer="beta", title="Beta Net"))

        alpha = store.get_item("epic:net", "alpha")
        beta = store.get_item("epic:net", "beta")
        assert alpha is not None and beta is not None
        assert alpha.title == "Alpha Net"
        assert beta.title == "Beta Net"

    def test_get_items_by_customer(self, store: SyncStateStore) -> None:
        store.upsert_item(SyncItem(stable_key="epic:a", customer="acme"))
        store.upsert_item(SyncItem(stable_key="epic:b", customer="acme"))
        store.upsert_item(SyncItem(stable_key="epic:c", customer="other"))

        items = store.get_items_by_customer("acme")
        assert len(items) == 2
        assert {i.stable_key for i in items} == {"epic:a", "epic:b"}

    def test_get_items_for_retry(self, store: SyncStateStore) -> None:
        store.upsert_item(SyncItem(stable_key="a", customer="c", sync_status="failed", run_id=1))
        store.upsert_item(SyncItem(stable_key="b", customer="c", sync_status="created", run_id=1))
        store.upsert_item(SyncItem(stable_key="c", customer="c", sync_status="failed", run_id=2))

        all_failed = store.get_items_for_retry("c")
        assert len(all_failed) == 2

        run1_failed = store.get_items_for_retry("c", run_id=1)
        assert len(run1_failed) == 1
        assert run1_failed[0].stable_key == "a"


# ── Orphan detection ──────────────────────────────────────────────────────


class TestOrphanDetection:
    def test_mark_orphaned(self, store: SyncStateStore) -> None:
        store.upsert_item(SyncItem(stable_key="epic:a", customer="acme", sync_status="created"))
        store.upsert_item(SyncItem(stable_key="epic:b", customer="acme", sync_status="created"))
        store.upsert_item(SyncItem(stable_key="epic:c", customer="acme", sync_status="created"))

        count = store.mark_orphaned("acme", {"epic:a", "epic:b"}, run_id=5)
        assert count == 1

        orphaned = store.get_item("epic:c", "acme")
        assert orphaned is not None
        assert orphaned.sync_status == "orphaned"

    def test_pending_items_not_orphaned(self, store: SyncStateStore) -> None:
        store.upsert_item(SyncItem(stable_key="epic:x", customer="acme", sync_status="pending"))

        count = store.mark_orphaned("acme", {"epic:other"}, run_id=1)
        assert count == 0


# ── SyncRun ───────────────────────────────────────────────────────────────


class TestSyncRun:
    def test_create_and_update_run(self, store: SyncStateStore) -> None:
        run = store.create_run("acme")
        assert run.id is not None
        assert run.status == "running"
        assert run.customer == "acme"

        run.status = "completed"
        run.items_created = 10
        run.items_updated = 3
        run.completed_at = "2026-01-01T00:00:00Z"
        store.update_run(run)

        runs = store.get_runs("acme")
        assert len(runs) == 1
        assert runs[0].status == "completed"
        assert runs[0].items_created == 10

    def test_get_runs_ordered_by_newest(self, store: SyncStateStore) -> None:
        store.create_run("acme")
        store.create_run("acme")
        store.create_run("acme")

        runs = store.get_runs("acme")
        assert len(runs) == 3
        assert runs[0].id > runs[1].id > runs[2].id  # type: ignore

    def test_runs_isolated_by_customer(self, store: SyncStateStore) -> None:
        store.create_run("alpha")
        store.create_run("beta")

        assert len(store.get_runs("alpha")) == 1
        assert len(store.get_runs("beta")) == 1


# ── Customer lock ─────────────────────────────────────────────────────────


class TestCustomerLock:
    def test_lock_acquires_and_releases(self, store: SyncStateStore) -> None:
        with store.customer_lock("acme"):
            store.upsert_item(SyncItem(stable_key="epic:locked", customer="acme"))
        got = store.get_item("epic:locked", "acme")
        assert got is not None
