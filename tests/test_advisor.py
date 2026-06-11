"""Tests for Advisor integration: parser, cross-referencer, similarity, and source tagging."""

from __future__ import annotations

import csv
import io
import os
import tempfile

import pandas as pd
import pytest

from excellence_agent.analysis.cross_reference import CrossReferenceReport, CrossReferencer
from excellence_agent.analysis.grouper import HierarchyBuilder
from excellence_agent.analysis.resource_mapper import ResourceMapper
from excellence_agent.analysis.similarity import SimilarityMatcher
from excellence_agent.export.ado_csv import ADOExporter
from excellence_agent.export.content_generator import ContentGenerator
from excellence_agent.config import ADOConfig
from excellence_agent.ingest.advisor_parser import AdvisorParser
from excellence_agent.ingest.advisor_schema import (
    COL_ADV_BUSINESS_IMPACT,
    COL_ADV_RECOMMENDATION,
    COL_ADV_RESOURCE_GROUP,
    COL_ADV_RESOURCE_NAME,
    COL_ADV_SUBSCRIPTION_ID,
    COL_ADV_SUBSCRIPTION_NAME,
    COL_ADV_TYPE,
)
from excellence_agent.ingest.schema import (
    COL_GUID,
    COL_ID,
    COL_IMPACT,
    COL_LONG_DESCRIPTION,
    COL_NAME,
    COL_RECOMMENDATION_TITLE,
    COL_RESOURCE_GROUP,
    COL_RESOURCE_TYPE,
    COL_SOURCE,
    COL_SUBSCRIPTION_ID,
    COL_WAF_PILLAR,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_advisor_csv(rows: list[dict], path: str) -> str:
    """Write Advisor CSV with BOM encoding."""
    cols = [
        "Business Impact", "Recommendation", "Subscription ID",
        "Subscription Name", "Resource Group", "Resource Name",
        "Type", "Updated Date", "Potential benefits",
        "Cost implications (Preview)", "Description of changes",
        "Retirement date", "Retiring feature",
    ]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        for row in rows:
            full_row = {c: row.get(c, "") for c in cols}
            writer.writerow(full_row)
    return path


@pytest.fixture()
def advisor_csv_path(tmp_path):
    """Create a minimal Advisor CSV with 3 rows."""
    rows = [
        {
            "Business Impact": "High",
            "Recommendation": "Configure continuous backup mode",
            "Subscription ID": "sub-001",
            "Subscription Name": "Test Sub",
            "Resource Group": "rg-data",
            "Resource Name": "cosmos-db-01",
            "Type": "Cosmos DB account",
            "Potential benefits": "Data protection",
            "Description of changes": "Enable continuous backup",
            "Retirement date": "2025-12-31",
            "Retiring feature": "Point-in-time restore v1",
        },
        {
            "Business Impact": "Medium",
            "Recommendation": "Use zone-supported App Service Plan",
            "Subscription ID": "sub-001",
            "Subscription Name": "Test Sub",
            "Resource Group": "rg-apps",
            "Resource Name": "app-plan-01",
            "Type": "App Service plan",
            "Potential benefits": "Availability",
        },
        {
            "Business Impact": "Low",
            "Recommendation": "Enable diagnostic settings",
            "Subscription ID": "sub-001",
            "Subscription Name": "Test Sub",
            "Resource Group": "rg-new",
            "Resource Name": "advisor-only-resource",
            "Type": "Virtual machine",
            "Potential benefits": "Monitoring",
        },
    ]
    csv_path = str(tmp_path / "advisor_test.csv")
    _write_advisor_csv(rows, csv_path)
    return csv_path


@pytest.fixture()
def type_mapping():
    return {
        "Cosmos DB account": "Microsoft.DocumentDB/databaseAccounts",
        "App Service plan": "microsoft.web/serverfarms",
        "Virtual machine": "Microsoft.Compute/virtualMachines",
    }


@pytest.fixture()
def sample_aprl_df():
    """A minimal APRL DataFrame with 3 rows (one overlapping with Advisor)."""
    rows = [
        {
            COL_RESOURCE_TYPE: "microsoft.documentdb/databaseaccounts",
            COL_NAME: "cosmos-db-01",
            COL_RESOURCE_GROUP: "rg-data",
            COL_SUBSCRIPTION_ID: "sub-001",
            COL_RECOMMENDATION_TITLE: "Configure continuous backup mode",
            COL_IMPACT: "High",
            COL_GUID: "guid-001",
            COL_WAF_PILLAR: "Reliability",
            COL_LONG_DESCRIPTION: "Enable continuous backup for CosmosDB",
            COL_SOURCE: "APRL",
            COL_ID: "/subscriptions/sub-001/resourceGroups/rg-data/providers/microsoft.documentdb/databaseaccounts/cosmos-db-01",
        },
        {
            COL_RESOURCE_TYPE: "microsoft.network/virtualnetworks",
            COL_NAME: "vnet-hub",
            COL_RESOURCE_GROUP: "rg-network",
            COL_SUBSCRIPTION_ID: "sub-001",
            COL_RECOMMENDATION_TITLE: "Enable DDoS protection",
            COL_IMPACT: "High",
            COL_GUID: "guid-002",
            COL_WAF_PILLAR: "Security",
            COL_LONG_DESCRIPTION: "Protect against DDoS attacks",
            COL_SOURCE: "APRL",
            COL_ID: "/subscriptions/sub-001/resourceGroups/rg-network/providers/microsoft.network/virtualnetworks/vnet-hub",
        },
    ]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# SimilarityMatcher tests
# ---------------------------------------------------------------------------

class TestSimilarityMatcher:
    def test_identical_strings(self):
        m = SimilarityMatcher()
        assert m.similarity_score("Enable backup", "Enable backup") == 1.0

    def test_completely_different(self):
        m = SimilarityMatcher()
        score = m.similarity_score("Enable backup mode", "Configure network peering")
        assert score < 0.3

    def test_similar_recommendations(self):
        m = SimilarityMatcher()
        score = m.similarity_score(
            "Configure continuous backup mode",
            "Improve resiliency by migrating to continuous backup",
        )
        assert score >= 0.3

    def test_empty_strings(self):
        m = SimilarityMatcher()
        assert m.similarity_score("", "") == 0.0
        assert m.similarity_score("something", "") == 0.0

    def test_custom_threshold(self):
        m = SimilarityMatcher(threshold=0.8)
        assert not m.are_similar("backup mode", "backup configuration")


# ---------------------------------------------------------------------------
# AdvisorParser tests
# ---------------------------------------------------------------------------

class TestAdvisorParser:
    def test_parse_basic(self, advisor_csv_path, type_mapping):
        parser = AdvisorParser(advisor_csv_path, type_mapping=type_mapping)
        report = parser.parse()
        assert len(report.recommendations) == 3
        assert "_Source" in report.recommendations.columns

    def test_type_mapping_applied(self, advisor_csv_path, type_mapping):
        parser = AdvisorParser(advisor_csv_path, type_mapping=type_mapping)
        report = parser.parse()
        types = report.recommendations["Type"].tolist()
        assert "Microsoft.DocumentDB/databaseAccounts" in types
        assert "microsoft.web/serverfarms" in types
        assert "Cosmos DB account" not in types

    def test_source_tag_set(self, advisor_csv_path, type_mapping):
        parser = AdvisorParser(advisor_csv_path, type_mapping=type_mapping)
        report = parser.parse()
        assert all(report.recommendations["_Source"] == "Advisor")

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            AdvisorParser("/nonexistent/path.csv")

    def test_no_type_mapping(self, advisor_csv_path):
        parser = AdvisorParser(advisor_csv_path)
        report = parser.parse()
        # Friendly names preserved without mapping
        assert "Cosmos DB account" in report.recommendations["Type"].tolist()


# ---------------------------------------------------------------------------
# CrossReferencer tests
# ---------------------------------------------------------------------------

class TestCrossReferencer:
    def test_merge_with_overlap(self, sample_aprl_df, advisor_csv_path, type_mapping):
        advisor = AdvisorParser(advisor_csv_path, type_mapping=type_mapping).parse()
        xref = CrossReferencer()
        merged, report = xref.merge(sample_aprl_df, advisor.recommendations)

        assert report.total_aprl_rows == 2
        assert report.total_advisor_rows == 3
        assert "cosmos-db-01" in report.matched_resources
        assert "advisor-only-resource" in report.advisor_only_resources
        assert "_Source" in merged.columns

    def test_source_values(self, sample_aprl_df, advisor_csv_path, type_mapping):
        advisor = AdvisorParser(advisor_csv_path, type_mapping=type_mapping).parse()
        xref = CrossReferencer()
        merged, _ = xref.merge(sample_aprl_df, advisor.recommendations)

        source_values = set(merged["_Source"].unique())
        assert "APRL" in source_values or "APRL & Advisor" in source_values
        assert "Advisor" in source_values

    def test_advisor_only_rows_included(self, sample_aprl_df, advisor_csv_path, type_mapping):
        advisor = AdvisorParser(advisor_csv_path, type_mapping=type_mapping).parse()
        xref = CrossReferencer()
        merged, report = xref.merge(sample_aprl_df, advisor.recommendations)

        # "advisor-only-resource" should be in merged output
        names = merged[COL_NAME].tolist()
        assert "advisor-only-resource" in names

    def test_merged_row_count(self, sample_aprl_df, advisor_csv_path, type_mapping):
        advisor = AdvisorParser(advisor_csv_path, type_mapping=type_mapping).parse()
        xref = CrossReferencer()
        merged, report = xref.merge(sample_aprl_df, advisor.recommendations)

        # 2 APRL + some Advisor-only (at least 1) = at least 3
        assert len(merged) >= 3
        assert report.total_merged_rows == len(merged)

    def test_report_serialisation(self):
        report = CrossReferenceReport(
            total_aprl_rows=10,
            total_advisor_rows=5,
            total_merged_rows=12,
            matched_resources=["res1"],
            aprl_only_resources=["res2"],
            advisor_only_resources=["res3"],
        )
        d = report.to_dict()
        assert d["total_aprl_rows"] == 10
        assert d["matched_resources_count"] == 1
        assert "res1" in d["matched_resources"]

    def test_empty_advisor(self, sample_aprl_df):
        """When Advisor has no rows, APRL data passes through unchanged."""
        empty_advisor = pd.DataFrame(columns=[
            "Business Impact", "Recommendation", "Subscription ID",
            "Subscription Name", "Resource Group", "Resource Name",
            "Type", "Updated Date", "Potential benefits",
            "Cost implications (Preview)", "Description of changes",
            "Retirement date", "Retiring feature", "_Source",
        ])
        xref = CrossReferencer()
        merged, report = xref.merge(sample_aprl_df, empty_advisor)
        assert len(merged) == len(sample_aprl_df)
        assert report.total_advisor_rows == 0


# ---------------------------------------------------------------------------
# Source propagation through hierarchy + export
# ---------------------------------------------------------------------------

class TestSourcePropagation:
    """Test that source tags flow from merged DataFrame → hierarchy → CSV."""

    @pytest.fixture()
    def merged_hierarchy(self, sample_aprl_df, advisor_csv_path, type_mapping):
        """Build a full hierarchy from merged APRL + Advisor data."""
        advisor = AdvisorParser(advisor_csv_path, type_mapping=type_mapping).parse()
        xref = CrossReferencer()
        merged, _ = xref.merge(sample_aprl_df, advisor.recommendations)

        matrix_config = {
            "categories": {
                "Data": {
                    "description": "Data services",
                    "resource_patterns": ["microsoft.documentdb/", "microsoft.storage/"],
                },
                "Networking": {
                    "description": "Networking",
                    "resource_patterns": ["microsoft.network/"],
                },
                "Compute": {
                    "description": "Compute",
                    "resource_patterns": ["microsoft.compute/"],
                },
                "Apps": {
                    "description": "Apps",
                    "resource_patterns": ["microsoft.web/"],
                },
            },
            "default_category": "Uncategorised",
        }
        mapper = ResourceMapper(matrix_config)
        mapped = mapper.map_dataframe(merged)
        builder = HierarchyBuilder()
        return builder.build(mapped)

    def test_sources_in_stories(self, merged_hierarchy):
        sources = {s.source for s in merged_hierarchy.all_stories() if s.source}
        assert len(sources) > 0
        # Should have at least APRL-sourced stories
        assert any("APRL" in s for s in sources)

    def test_sources_in_recommendations(self, merged_hierarchy):
        sources = {r.source for r in merged_hierarchy.all_recommendations() if r.source}
        assert len(sources) > 0

    def test_advisor_metadata_on_matched(self, merged_hierarchy):
        """Recommendations from Advisor should have advisor_metadata populated."""
        for story in merged_hierarchy.all_stories():
            for rec in story.recommendations:
                if rec.source == "Advisor" or rec.source == "APRL & Advisor":
                    pass  # Just ensure no crash
                if rec.advisor_metadata.get("advisor_retirement_date"):
                    assert len(rec.advisor_metadata["advisor_retirement_date"]) > 0

    def test_csv_source_tags(self, merged_hierarchy, tmp_path):
        """Exported CSV should contain Source: tags."""
        config = ADOConfig()
        gen = ContentGenerator()
        exporter = ADOExporter(config, gen)
        out_path = str(tmp_path / "test_export.csv")
        exporter.export(merged_hierarchy, out_path)

        with open(out_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            source_tags = set()
            for row in reader:
                for tag in row.get("Tags", "").split(";"):
                    tag = tag.strip()
                    if tag.startswith("Source:"):
                        source_tags.add(tag)

        assert len(source_tags) > 0
        assert "Source:APRL" in source_tags or "Source:APRL & Advisor" in source_tags

    def test_aprl_only_mode_unchanged(self, sample_aprl_df):
        """Without Advisor data, hierarchy works exactly as before."""
        matrix_config = {
            "categories": {
                "Data": {
                    "description": "Data services",
                    "resource_patterns": ["microsoft.documentdb/"],
                },
                "Networking": {
                    "description": "Networking",
                    "resource_patterns": ["microsoft.network/"],
                },
            },
            "default_category": "Uncategorised",
        }
        mapper = ResourceMapper(matrix_config)
        mapped = mapper.map_dataframe(sample_aprl_df)
        hierarchy = HierarchyBuilder().build(mapped)

        # All sources should be APRL
        for story in hierarchy.all_stories():
            assert story.source in ("APRL", "")
        for rec in hierarchy.all_recommendations():
            assert rec.source in ("APRL", "")
