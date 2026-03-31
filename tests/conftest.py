"""Shared pytest fixtures for ExcellenceAgent tests."""

from __future__ import annotations

import pandas as pd
import pytest

from excellence_agent.analysis.grouper import HierarchyBuilder
from excellence_agent.analysis.resource_mapper import ResourceMapper
from excellence_agent.export.content_generator import ContentGenerator
from excellence_agent.ingest.schema import (
    COL_CATEGORY,
    COL_CHECK_NAME,
    COL_CUSTOM1,
    COL_CUSTOM2,
    COL_CUSTOM3,
    COL_CUSTOM4,
    COL_CUSTOM5,
    COL_GUID,
    COL_ID,
    COL_IMPACT,
    COL_LEARN_MORE_LINK,
    COL_LOCATION,
    COL_LONG_DESCRIPTION,
    COL_NAME,
    COL_NOTES,
    COL_POTENTIAL_BENEFIT,
    COL_RECOMMENDATION_CONTROL,
    COL_RECOMMENDATION_TITLE,
    COL_RESOURCE_GROUP,
    COL_RESOURCE_TYPE,
    COL_REVIEW_STATUS,
    COL_SOURCE,
    COL_SUBSCRIPTION_ID,
    COL_WAF_PILLAR,
)
from excellence_agent.models import WorkItemHierarchy


def _make_row(
    resource_type: str,
    name: str,
    guid: str,
    rec_title: str,
    impact: str = "Medium",
    rg: str = "rg-default",
    sub: str = "sub-001",
    location: str = "uksouth",
    waf_pillar: str = "Reliability",
    category: str = "Monitoring and Alerting",
    rec_control: str = "Automated",
    source: str = "APRL",
) -> dict:
    """Build a single row dict matching APRL sheet 4 columns."""
    resource_id = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{resource_type}/{name}"
    return {
        COL_REVIEW_STATUS: "",
        COL_RESOURCE_TYPE: resource_type,
        COL_SUBSCRIPTION_ID: sub,
        COL_RESOURCE_GROUP: rg,
        COL_LOCATION: location,
        COL_NAME: name,
        COL_ID: resource_id,
        COL_CUSTOM1: "",
        COL_CUSTOM2: "",
        COL_CUSTOM3: "",
        COL_CUSTOM4: "",
        COL_CUSTOM5: "",
        COL_RECOMMENDATION_TITLE: rec_title,
        COL_IMPACT: impact,
        COL_RECOMMENDATION_CONTROL: rec_control,
        COL_POTENTIAL_BENEFIT: "Improved resilience",
        COL_LEARN_MORE_LINK: "https://aka.ms/aprl",
        COL_LONG_DESCRIPTION: f"Long description for {rec_title}",
        COL_GUID: guid,
        COL_CATEGORY: category,
        COL_SOURCE: source,
        COL_WAF_PILLAR: waf_pillar,
        COL_NOTES: "",
        COL_CHECK_NAME: f"check-{guid[:8]}",
    }


@pytest.fixture()
def sample_matrix_config() -> dict:
    """Return a dict matching a subset of resource_matrix.yaml (Networking, Data, Observability)."""
    return {
        "categories": {
            "Networking": {
                "description": "Virtual networks, gateways, load balancers, and connectivity",
                "resource_patterns": [
                    "microsoft.network/virtualnetworks",
                    "microsoft.network/networkwatchers",
                ],
            },
            "Data": {
                "description": "Databases, storage, and data services",
                "resource_patterns": [
                    "microsoft.documentdb/",
                    "microsoft.storage/",
                    "microsoft.cosmosdb/",
                ],
            },
            "Observability": {
                "description": "Monitoring, logging, and diagnostics resources",
                "resource_patterns": [
                    "microsoft.insights/components",
                ],
            },
        },
        "default_category": "Uncategorised",
    }


@pytest.fixture()
def sample_dataframe() -> pd.DataFrame:
    """Return a DataFrame mimicking APRL sheet 4 data with ~10 rows.

    Contents
    --------
    - 2 CosmosDB resources with the **same** recommendation Guid → dedup test
    - 3 Network Watcher resources across 2 recommendations
    - 2 VNet resources
    - 1 Storage Account
    - 2 App Insights resources
    """
    rows = [
        # --- 2 × CosmosDB, same Guid (dedup target) ---
        _make_row(
            "microsoft.documentdb/databaseaccounts", "cosmos-db-01",
            "aaaa-1111-bbbb-2222", "Enable automatic failover for CosmosDB",
            impact="High", rg="rg-data", waf_pillar="Reliability",
        ),
        _make_row(
            "microsoft.documentdb/databaseaccounts", "cosmos-db-02",
            "aaaa-1111-bbbb-2222", "Enable automatic failover for CosmosDB",
            impact="High", rg="rg-data", waf_pillar="Reliability",
        ),
        # --- 3 × Network Watcher, 2 recommendations ---
        _make_row(
            "microsoft.network/networkwatchers", "nw-uksouth",
            "cccc-3333-dddd-4444", "Enable NSG flow logs",
            impact="Medium", rg="rg-network", waf_pillar="Security",
        ),
        _make_row(
            "microsoft.network/networkwatchers", "nw-ukwest",
            "cccc-3333-dddd-4444", "Enable NSG flow logs",
            impact="Medium", rg="rg-network", waf_pillar="Security",
        ),
        _make_row(
            "microsoft.network/networkwatchers", "nw-eastus",
            "eeee-5555-ffff-6666", "Configure connection monitor",
            impact="Low", rg="rg-network-us", waf_pillar="Operational Excellence",
        ),
        # --- 2 × VNet ---
        _make_row(
            "microsoft.network/virtualnetworks", "vnet-hub",
            "1111-aaaa-2222-bbbb", "Configure DDoS protection",
            impact="High", rg="rg-network", waf_pillar="Security",
            rec_control="Personalized",
        ),
        _make_row(
            "microsoft.network/virtualnetworks", "vnet-spoke",
            "3333-cccc-4444-dddd", "Enable VNet peering monitoring",
            impact="Medium", rg="rg-network", waf_pillar="Reliability",
        ),
        # --- 1 × Storage Account ---
        _make_row(
            "microsoft.storage/storageaccounts", "stgprod001",
            "5555-eeee-6666-ffff", "Enable soft delete for blobs",
            impact="Medium", rg="rg-data", waf_pillar="Reliability",
        ),
        # --- 2 × App Insights ---
        _make_row(
            "microsoft.insights/components", "appi-web",
            "7777-aaaa-8888-bbbb", "Configure sampling rate",
            impact="Low", rg="rg-monitoring", waf_pillar="Performance Efficiency",
        ),
        _make_row(
            "microsoft.insights/components", "appi-api",
            "9999-cccc-0000-dddd", "Enable web tests",
            impact="Medium", rg="rg-monitoring", waf_pillar="Reliability",
        ),
    ]
    return pd.DataFrame(rows)


@pytest.fixture()
def resource_mapper(sample_matrix_config: dict) -> ResourceMapper:
    """Return a ResourceMapper built from the sample matrix config."""
    return ResourceMapper(sample_matrix_config)


@pytest.fixture()
def sample_hierarchy(
    sample_dataframe: pd.DataFrame,
    resource_mapper: ResourceMapper,
    sample_matrix_config: dict,
) -> WorkItemHierarchy:
    """Build a WorkItemHierarchy from the sample dataframe."""
    mapped_df = resource_mapper.map_dataframe(sample_dataframe)
    descriptions = {
        name: body["description"]
        for name, body in sample_matrix_config["categories"].items()
    }
    builder = HierarchyBuilder(category_descriptions=descriptions)
    return builder.build(mapped_df)


@pytest.fixture()
def content_generator() -> ContentGenerator:
    """Return a ContentGenerator instance (uses default templates)."""
    return ContentGenerator()
