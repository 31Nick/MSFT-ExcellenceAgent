"""Tests for excellence_agent.ado.customer_config."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from excellence_agent.ado.customer_config import (
    CustomerConfig,
    CustomerConfigError,
    list_customer_configs,
    load_customer_config,
)


@pytest.fixture()
def tmp_customers(tmp_path: Path) -> Path:
    """Create a temp customers directory with test configs."""
    customers = tmp_path / "customers"
    customers.mkdir()

    (customers / "acme.yaml").write_text(
        """
customer_name: "Acme Corp"
ado:
  organization: "acme-org"
  project: "CloudReliability"
  team: "SRE Team"
  area_path: "CloudReliability\\\\SRE"
  iteration_path: "CloudReliability\\\\Sprint 1"
work_items:
  type_mapping:
    epic: "Epic"
    feature: "Feature"
    story: "User Story"
    task: "Task"
""",
        encoding="utf-8",
    )

    (customers / "minimal.yaml").write_text(
        """
ado:
  organization: "min-org"
  project: "MinProject"
""",
        encoding="utf-8",
    )

    (customers / "bad-no-org.yaml").write_text(
        """
ado:
  project: "SomeProject"
""",
        encoding="utf-8",
    )

    (customers / "example.yaml").write_text(
        """
customer_name: "Example Corp"
ado:
  organization: "example-org"
  project: "Infrastructure"
""",
        encoding="utf-8",
    )

    return customers


class TestLoadCustomerConfig:
    def test_full_config(self, tmp_customers: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ADO_PAT_ACME", "secret-pat-acme")
        cfg = load_customer_config("acme", customers_dir=tmp_customers)
        assert cfg.slug == "acme"
        assert cfg.customer_name == "Acme Corp"
        assert cfg.organization == "acme-org"
        assert cfg.project == "CloudReliability"
        assert cfg.team == "SRE Team"
        assert cfg.pat == "secret-pat-acme"
        assert cfg.type_mapping.story == "User Story"
        assert cfg.organization_url == "https://dev.azure.com/acme-org"

    def test_minimal_config_defaults(self, tmp_customers: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ADO_PAT", "global-pat")
        cfg = load_customer_config("minimal", customers_dir=tmp_customers)
        assert cfg.slug == "minimal"
        assert cfg.customer_name == "minimal"  # falls back to slug
        assert cfg.organization == "min-org"
        assert cfg.team == ""
        assert cfg.type_mapping.epic == "Epic"
        assert cfg.pat == "global-pat"

    def test_customer_specific_pat_overrides_global(
        self, tmp_customers: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ADO_PAT", "global-pat")
        monkeypatch.setenv("ADO_PAT_ACME", "specific-pat")
        cfg = load_customer_config("acme", customers_dir=tmp_customers)
        assert cfg.pat == "specific-pat"

    def test_global_pat_fallback(self, tmp_customers: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ADO_PAT_ACME", raising=False)
        monkeypatch.setenv("ADO_PAT", "fallback-pat")
        cfg = load_customer_config("acme", customers_dir=tmp_customers)
        assert cfg.pat == "fallback-pat"

    def test_missing_pat_raises(self, tmp_customers: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ADO_PAT", raising=False)
        monkeypatch.delenv("ADO_PAT_ACME", raising=False)
        with pytest.raises(CustomerConfigError, match="No PAT found"):
            load_customer_config("acme", customers_dir=tmp_customers)

    def test_missing_file_raises(self, tmp_customers: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ADO_PAT", "x")
        with pytest.raises(CustomerConfigError, match="not found"):
            load_customer_config("nonexistent", customers_dir=tmp_customers)

    def test_missing_organization_raises(self, tmp_customers: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ADO_PAT", "x")
        with pytest.raises(CustomerConfigError, match="ado.organization"):
            load_customer_config("bad-no-org", customers_dir=tmp_customers)


class TestListCustomerConfigs:
    def test_excludes_example(self, tmp_customers: Path) -> None:
        configs = list_customer_configs(customers_dir=tmp_customers)
        slugs = [c["slug"] for c in configs]
        assert "example" not in slugs

    def test_lists_real_configs(self, tmp_customers: Path) -> None:
        configs = list_customer_configs(customers_dir=tmp_customers)
        slugs = [c["slug"] for c in configs]
        assert "acme" in slugs
        assert "minimal" in slugs

    def test_empty_dir(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty_customers"
        empty.mkdir()
        assert list_customer_configs(customers_dir=empty) == []

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        assert list_customer_configs(customers_dir=tmp_path / "nope") == []
