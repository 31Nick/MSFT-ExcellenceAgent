"""Tests for excellence_agent.analysis.resource_mapper.ResourceMapper."""

from __future__ import annotations

import pandas as pd
import pytest

from excellence_agent.analysis.resource_mapper import ResourceMapper
from excellence_agent.ingest.schema import COL_RESOURCE_TYPE


class TestMapResourceType:
    def test_case_insensitive_matching(self, resource_mapper: ResourceMapper) -> None:
        assert resource_mapper.map_resource_type("Microsoft.Network/virtualNetworks") == "Networking"
        assert resource_mapper.map_resource_type("MICROSOFT.NETWORK/VIRTUALNETWORKS") == "Networking"
        assert resource_mapper.map_resource_type("microsoft.network/virtualnetworks") == "Networking"

    def test_prefix_matching(self, resource_mapper: ResourceMapper) -> None:
        # "microsoft.documentdb/" is a prefix pattern — anything under it should match
        assert resource_mapper.map_resource_type("microsoft.documentdb/databaseaccounts") == "Data"
        assert resource_mapper.map_resource_type("microsoft.storage/storageaccounts") == "Data"

    def test_unmapped_goes_to_default(self, resource_mapper: ResourceMapper) -> None:
        assert resource_mapper.map_resource_type("microsoft.web/sites") == "Uncategorised"
        assert resource_mapper.map_resource_type("completely.unknown/type") == "Uncategorised"


class TestMapDataframe:
    def test_adds_matrix_category_column(self, resource_mapper: ResourceMapper) -> None:
        df = pd.DataFrame(
            {
                COL_RESOURCE_TYPE: [
                    "microsoft.network/virtualnetworks",
                    "microsoft.documentdb/databaseaccounts",
                    "microsoft.insights/components",
                    "microsoft.web/sites",
                ]
            }
        )
        result = resource_mapper.map_dataframe(df)
        assert "MatrixCategory" in result.columns
        categories = result["MatrixCategory"].tolist()
        assert categories == ["Networking", "Data", "Observability", "Uncategorised"]
