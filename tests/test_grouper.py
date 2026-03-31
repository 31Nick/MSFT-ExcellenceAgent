"""Tests for excellence_agent.analysis.grouper (HierarchyBuilder)."""

from __future__ import annotations

import pandas as pd
import pytest

from excellence_agent.analysis.grouper import HierarchyBuilder, _friendly_resource_name
from excellence_agent.analysis.resource_mapper import ResourceMapper
from excellence_agent.models import WorkItemHierarchy


class TestHierarchyBuilderBuild:
    """Tests for HierarchyBuilder.build()."""

    def test_creates_correct_number_of_epics(
        self, sample_hierarchy: WorkItemHierarchy
    ) -> None:
        # Data, Networking, Observability (alphabetical)
        epic_names = [e.name for e in sample_hierarchy.epics]
        assert sorted(epic_names) == epic_names  # alphabetical order
        assert set(epic_names) == {"Data", "Networking", "Observability"}

    def test_dedup_cosmosdb_same_guid_one_story_two_tasks(
        self, sample_hierarchy: WorkItemHierarchy
    ) -> None:
        """2 CosmosDB rows with the same Guid → 1 UserStory, 2 Tasks."""
        data_epic = next(e for e in sample_hierarchy.epics if e.name == "Data")
        cosmos_feature = next(
            f for f in data_epic.features
            if "documentdb" in f.resource_type.lower()
        )
        # Exactly 1 user story for the shared Guid
        assert len(cosmos_feature.user_stories) == 1
        # Both rows become tasks under that story
        assert len(cosmos_feature.user_stories[0].tasks) == 2

    def test_feature_sorting_by_resource_count_desc(
        self, sample_hierarchy: WorkItemHierarchy
    ) -> None:
        net_epic = next(e for e in sample_hierarchy.epics if e.name == "Networking")
        counts = [f.resource_count for f in net_epic.features]
        assert counts == sorted(counts, reverse=True)

    def test_user_story_sorting_by_impact_priority(
        self, sample_hierarchy: WorkItemHierarchy
    ) -> None:
        net_epic = next(e for e in sample_hierarchy.epics if e.name == "Networking")
        for feature in net_epic.features:
            priorities = [s.priority for s in feature.user_stories]
            assert priorities == sorted(priorities)

    def test_error_when_matrix_category_missing(self) -> None:
        df = pd.DataFrame({"Resource Type": ["microsoft.compute/virtualMachines"]})
        builder = HierarchyBuilder()
        with pytest.raises(ValueError, match="MatrixCategory"):
            builder.build(df)


class TestFriendlyResourceName:
    @pytest.mark.parametrize(
        "input_val, expected",
        [
            ("microsoft.network/networkwatchers", "Networkwatchers"),
            ("microsoft.network/virtualNetworks", "Virtual Networks"),
            ("microsoft.documentdb/databaseaccounts", "Databaseaccounts"),
            ("", "Unknown Resource"),
        ],
    )
    def test_conversion(self, input_val: str, expected: str) -> None:
        assert _friendly_resource_name(input_val) == expected
