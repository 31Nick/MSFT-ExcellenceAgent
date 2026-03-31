"""Tests for excellence_agent.export.ado_csv.ADOExporter."""

from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest

from excellence_agent.config import ADOConfig
from excellence_agent.export.ado_csv import ADOExporter, _CSV_COLUMNS
from excellence_agent.export.content_generator import ContentGenerator
from excellence_agent.models import (
    Epic,
    Feature,
    Task,
    UserStory,
    WorkItemHierarchy,
)


@pytest.fixture()
def ado_config() -> ADOConfig:
    return ADOConfig(
        area_path="Project\\Team",
        iteration_path="Project\\Sprint1",
    )


@pytest.fixture()
def exporter(ado_config: ADOConfig, content_generator: ContentGenerator) -> ADOExporter:
    return ADOExporter(ado_config, content_generator)


def _build_small_hierarchy() -> WorkItemHierarchy:
    """One Epic → one Feature → one Story → one Task."""
    h = WorkItemHierarchy()
    epic = Epic(name="Data", description="Data services")
    feat = Feature(name="Cosmos DB", resource_type="microsoft.documentdb/databaseaccounts")
    story = UserStory(
        title="Enable automatic failover",
        recommendation_guid="aaaa-1111",
        impact="High",
        recommendation_control="Automated",
        waf_pillar="Reliability",
        category="Availability",
    )
    task = Task(
        resource_name="cosmos-db-01",
        resource_id="/subscriptions/sub/rg/cosmos-db-01",
        resource_group="rg-data",
        subscription_id="sub-001",
        location="uksouth",
    )
    story.add_task(task)
    feat.add_user_story(story)
    epic.add_feature(feat)
    h.add_epic(epic)
    return h


class TestADOExporterCSV:
    def test_csv_correct_headers(self, exporter: ADOExporter, tmp_path: Path) -> None:
        out = str(tmp_path / "out.csv")
        exporter.export(_build_small_hierarchy(), out)

        with open(out, encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            assert list(reader.fieldnames) == _CSV_COLUMNS

    def test_hierarchy_order(self, exporter: ADOExporter, tmp_path: Path) -> None:
        out = str(tmp_path / "out.csv")
        exporter.export(_build_small_hierarchy(), out)

        with open(out, encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            types = [row["Work Item Type"] for row in reader]

        assert types == ["Epic", "Feature", "User Story", "Task"]

    def test_title_column_indentation(self, exporter: ADOExporter, tmp_path: Path) -> None:
        out = str(tmp_path / "out.csv")
        exporter.export(_build_small_hierarchy(), out)

        with open(out, encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)

        # Epic title only in Title 1
        assert rows[0]["Title 1"] != ""
        assert rows[0]["Title 2"] == ""
        assert rows[0]["Title 3"] == ""
        assert rows[0]["Title 4"] == ""

        # Feature title only in Title 2
        assert rows[1]["Title 1"] == ""
        assert rows[1]["Title 2"] != ""
        assert rows[1]["Title 3"] == ""
        assert rows[1]["Title 4"] == ""

        # Story title only in Title 3
        assert rows[2]["Title 1"] == ""
        assert rows[2]["Title 2"] == ""
        assert rows[2]["Title 3"] != ""
        assert rows[2]["Title 4"] == ""

        # Task title only in Title 4
        assert rows[3]["Title 1"] == ""
        assert rows[3]["Title 2"] == ""
        assert rows[3]["Title 3"] == ""
        assert rows[3]["Title 4"] != ""

    def test_utf8_bom_encoding(self, exporter: ADOExporter, tmp_path: Path) -> None:
        out = str(tmp_path / "out.csv")
        exporter.export(_build_small_hierarchy(), out)

        with open(out, "rb") as fh:
            first_bytes = fh.read(3)
        # UTF-8 BOM
        assert first_bytes == b"\xef\xbb\xbf"

    def test_empty_hierarchy_headers_only(self, exporter: ADOExporter, tmp_path: Path) -> None:
        out = str(tmp_path / "out.csv")
        exporter.export(WorkItemHierarchy(), out)

        with open(out, encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)

        assert len(rows) == 0
        # Re-read to verify headers exist
        with open(out, encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            assert list(reader.fieldnames) == _CSV_COLUMNS

    def test_priority_values(self, exporter: ADOExporter, tmp_path: Path) -> None:
        out = str(tmp_path / "out.csv")
        exporter.export(_build_small_hierarchy(), out)

        with open(out, encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)

        # Epic default priority = 2
        assert rows[0]["Priority"] == "2"
        # Feature inherits highest story priority (High = 1)
        assert rows[1]["Priority"] == "1"
        # Story priority: High = 1
        assert rows[2]["Priority"] == "1"
        # Task inherits story priority
        assert rows[3]["Priority"] == "1"
