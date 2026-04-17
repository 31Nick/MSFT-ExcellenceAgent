"""Tests for the sync-related web API endpoints."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from excellence_agent.web.app import create_app
from excellence_agent.config import Config


@pytest.fixture
def tmp_customers_dir(tmp_path):
    cust_dir = tmp_path / "customers"
    cust_dir.mkdir()
    config_yaml = cust_dir / "testcorp.yaml"
    config_yaml.write_text(
        "customer_name: TestCorp\n"
        "ado:\n"
        "  organization: test-org\n"
        "  project: test-project\n"
    )
    return cust_dir


@pytest.fixture
def app(tmp_path):
    config = Config(output_dir=str(tmp_path / "output"))
    app = create_app(config)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Customer endpoints
# ---------------------------------------------------------------------------

class TestListCustomers:
    def test_returns_list(self, client, tmp_customers_dir):
        with patch("excellence_agent.ado.customer_config._CUSTOMERS_DIR", tmp_customers_dir):
            resp = client.get("/api/customers")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["slug"] == "testcorp"

    def test_empty(self, client, tmp_path):
        empty = tmp_path / "empty_customers"
        empty.mkdir()
        with patch("excellence_agent.ado.customer_config._CUSTOMERS_DIR", empty):
            resp = client.get("/api/customers")
        assert resp.status_code == 200
        assert resp.get_json() == []


class TestGetCustomer:
    def test_returns_details(self, client, tmp_customers_dir):
        with (
            patch("excellence_agent.ado.customer_config._CUSTOMERS_DIR", tmp_customers_dir),
            patch.dict(os.environ, {"ADO_PAT": "secret-pat-value"}),
        ):
            resp = client.get("/api/customers/testcorp")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["slug"] == "testcorp"
        assert data["organization"] == "test-org"
        assert data["pat_configured"] is True
        assert "secret" not in json.dumps(data)

    def test_not_found(self, client, tmp_path):
        empty = tmp_path / "empty_customers"
        empty.mkdir()
        with patch("excellence_agent.ado.customer_config._CUSTOMERS_DIR", empty):
            resp = client.get("/api/customers/nope")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Sync endpoints
# ---------------------------------------------------------------------------

class TestSyncPlan:
    def test_missing_customer(self, client):
        resp = client.post("/api/sync/plan", json={})
        assert resp.status_code == 400

    def test_no_hierarchy(self, client):
        resp = client.post("/api/sync/plan", json={"customer": "test"})
        assert resp.status_code == 404
        assert "hierarchy" in resp.get_json()["error"].lower()

    def test_returns_plan(self, client, app, tmp_customers_dir):
        from excellence_agent.ado.sync_service import SyncPlan, PlannedItem

        mock_hierarchy = MagicMock()
        app.config["EA_HIERARCHY"] = mock_hierarchy

        mock_plan = SyncPlan(customer="testcorp")
        mock_plan.to_create.append(PlannedItem(
            stable_key="epic:net", work_item_type="Epic",
            title="Networking", action="create", content_hash="abc",
        ))

        with (
            patch("excellence_agent.ado.customer_config._CUSTOMERS_DIR", tmp_customers_dir),
            patch.dict(os.environ, {"ADO_PAT": "test-pat"}),
            patch("excellence_agent.ado.sync_service.AdoSyncService.plan", return_value=mock_plan),
        ):
            resp = client.post("/api/sync/plan", json={"customer": "testcorp"})

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["summary"]["create"] == 1
        assert len(data["to_create"]) == 1
        assert data["to_create"][0]["title"] == "Networking"


class TestSyncStatus:
    def test_returns_status(self, client, tmp_customers_dir):
        from excellence_agent.ado.state_store import SyncItem, SyncRun

        items = [
            SyncItem(stable_key="epic:a", customer="testcorp",
                     work_item_type="Epic", title="A", sync_status="created"),
        ]
        runs = [
            SyncRun(id=1, customer="testcorp", started_at="2026-01-01T00:00:00",
                    status="completed", items_created=1),
        ]

        with (
            patch("excellence_agent.ado.customer_config._CUSTOMERS_DIR", tmp_customers_dir),
            patch.dict(os.environ, {"ADO_PAT": "test-pat"}),
            patch("excellence_agent.ado.state_store.SyncStateStore.get_items_by_customer", return_value=items),
            patch("excellence_agent.ado.state_store.SyncStateStore.get_runs", return_value=runs),
        ):
            resp = client.get("/api/sync/status/testcorp")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total_items"] == 1
        assert data["status_counts"]["created"] == 1
        assert data["latest_run"]["id"] == 1


class TestSyncHistory:
    def test_returns_runs(self, client):
        from excellence_agent.ado.state_store import SyncRun

        runs = [
            SyncRun(id=2, customer="testcorp", started_at="2026-01-02T00:00:00",
                    status="completed", items_created=5),
            SyncRun(id=1, customer="testcorp", started_at="2026-01-01T00:00:00",
                    status="failed", items_failed=2),
        ]
        with patch("excellence_agent.ado.state_store.SyncStateStore.get_runs", return_value=runs):
            resp = client.get("/api/sync/history/testcorp")

        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 2
        assert data[0]["id"] == 2
        assert data[1]["status"] == "failed"


class TestSyncRetry:
    def test_missing_customer(self, client):
        resp = client.post("/api/sync/retry", json={})
        assert resp.status_code == 400

    def test_no_failed_items(self, client, tmp_customers_dir, app):
        app.config["EA_HIERARCHY"] = MagicMock()
        with (
            patch("excellence_agent.ado.customer_config._CUSTOMERS_DIR", tmp_customers_dir),
            patch.dict(os.environ, {"ADO_PAT": "test-pat"}),
            patch("excellence_agent.ado.state_store.SyncStateStore.get_items_for_retry", return_value=[]),
        ):
            resp = client.post("/api/sync/retry", json={"customer": "testcorp"})

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "No failed" in data["message"]
