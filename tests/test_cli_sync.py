"""Tests for CLI customers and sync commands."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from excellence_agent.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def tmp_customers_dir(tmp_path):
    """Create a temp customers directory with a config file."""
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


# ---------------------------------------------------------------------------
# customers list
# ---------------------------------------------------------------------------

class TestCustomersList:
    def test_empty_dir(self, runner, tmp_path):
        empty = tmp_path / "customers"
        empty.mkdir()
        with patch("excellence_agent.ado.customer_config._CUSTOMERS_DIR", empty):
            result = runner.invoke(cli, ["customers", "list"])
        assert result.exit_code == 0
        assert "No customer configs" in result.output

    def test_lists_configs(self, runner, tmp_customers_dir):
        with patch("excellence_agent.ado.customer_config._CUSTOMERS_DIR", tmp_customers_dir):
            result = runner.invoke(cli, ["customers", "list"])
        assert result.exit_code == 0
        assert "testcorp" in result.output
        assert "TestCorp" in result.output


# ---------------------------------------------------------------------------
# customers validate
# ---------------------------------------------------------------------------

class TestCustomersValidate:
    def test_valid_config(self, runner, tmp_customers_dir):
        with (
            patch("excellence_agent.ado.customer_config._CUSTOMERS_DIR", tmp_customers_dir),
            patch.dict(os.environ, {"ADO_PAT": "test-pat-12345678"}),
        ):
            result = runner.invoke(cli, ["customers", "validate", "testcorp"])
        assert result.exit_code == 0
        assert "✔ Config valid" in result.output
        assert "test-org" in result.output

    def test_missing_config(self, runner, tmp_path):
        empty = tmp_path / "customers"
        empty.mkdir()
        with patch("excellence_agent.ado.customer_config._CUSTOMERS_DIR", empty):
            result = runner.invoke(cli, ["customers", "validate", "nope"])
        assert result.exit_code != 0
        assert "not found" in result.output


# ---------------------------------------------------------------------------
# sync plan
# ---------------------------------------------------------------------------

class TestSyncPlan:
    def test_plan_shows_summary(self, runner, tmp_customers_dir, tmp_path):
        """sync plan should show create/update/unchanged counts."""
        from excellence_agent.ado.sync_service import SyncPlan, PlannedItem

        mock_plan = SyncPlan(customer="testcorp")
        mock_plan.to_create.append(PlannedItem(
            stable_key="epic:test", work_item_type="Epic",
            title="Test Epic", action="create", content_hash="abc",
        ))

        # Create fake files so Click path validation passes
        report = tmp_path / "report.xlsx"
        report.write_bytes(b"fake")
        matrix = tmp_path / "matrix.yaml"
        matrix.write_text("categories: {}")

        with (
            patch("excellence_agent.ado.customer_config._CUSTOMERS_DIR", tmp_customers_dir),
            patch.dict(os.environ, {"ADO_PAT": "test-pat-12345678"}),
            patch("excellence_agent.pipeline.build_hierarchy") as mock_bh,
            patch("excellence_agent.ado.sync_service.AdoSyncService.plan", return_value=mock_plan),
        ):
            mock_bh.return_value = (MagicMock(), {"epics": 1, "features": 1, "user_stories": 2, "tasks": 3})
            result = runner.invoke(cli, [
                "sync", "plan", "testcorp", "--report", str(report),
                "--matrix", str(matrix),
            ], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Create:" in result.output


# ---------------------------------------------------------------------------
# sync status
# ---------------------------------------------------------------------------

class TestSyncStatus:
    def test_no_data(self, runner, tmp_customers_dir):
        with (
            patch("excellence_agent.ado.customer_config._CUSTOMERS_DIR", tmp_customers_dir),
            patch.dict(os.environ, {"ADO_PAT": "test-pat-12345678"}),
            patch("excellence_agent.ado.state_store.SyncStateStore.get_items_by_customer", return_value=[]),
            patch("excellence_agent.ado.state_store.SyncStateStore.get_runs", return_value=[]),
        ):
            result = runner.invoke(cli, ["sync", "status", "testcorp"])
        assert result.exit_code == 0
        assert "No sync data" in result.output

    def test_with_items(self, runner, tmp_customers_dir):
        from excellence_agent.ado.state_store import SyncItem, SyncRun

        items = [
            SyncItem(stable_key="epic:a", customer="testcorp", work_item_type="Epic",
                     title="A", sync_status="created"),
            SyncItem(stable_key="epic:b", customer="testcorp", work_item_type="Epic",
                     title="B", sync_status="failed", error_message="timeout"),
        ]
        runs = [
            SyncRun(id=1, customer="testcorp", started_at="2026-01-01T00:00:00",
                    status="failed", items_created=1, items_failed=1),
        ]
        with (
            patch("excellence_agent.ado.customer_config._CUSTOMERS_DIR", tmp_customers_dir),
            patch.dict(os.environ, {"ADO_PAT": "test-pat-12345678"}),
            patch("excellence_agent.ado.state_store.SyncStateStore.get_items_by_customer", return_value=items),
            patch("excellence_agent.ado.state_store.SyncStateStore.get_runs", return_value=runs),
        ):
            result = runner.invoke(cli, ["sync", "status", "testcorp"])
        assert result.exit_code == 0
        assert "created" in result.output
        assert "failed" in result.output
        assert "#1" in result.output
