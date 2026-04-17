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

    def test_one_story_per_feature(
        self, sample_hierarchy: WorkItemHierarchy
    ) -> None:
        """Each Feature has exactly ONE consolidated UserStory."""
        for epic in sample_hierarchy.epics:
            for feature in epic.features:
                assert len(feature.user_stories) == 1, (
                    f"Feature '{feature.name}' should have 1 story, got {len(feature.user_stories)}"
                )

    def test_cosmosdb_one_task_two_resources(
        self, sample_hierarchy: WorkItemHierarchy
    ) -> None:
        """2 CosmosDB rows with the same Guid → 1 Task with 2 affected resources."""
        data_epic = next(e for e in sample_hierarchy.epics if e.name == "Data")
        cosmos_feature = next(
            f for f in data_epic.features
            if "documentdb" in f.resource_type.lower()
        )
        story = cosmos_feature.user_stories[0]
        # 1 unique recommendation → 1 task
        assert len(story.tasks) == 1
        # 2 resources affected
        assert len(story.tasks[0].affected_resources) == 2

    def test_network_watchers_two_tasks(
        self, sample_hierarchy: WorkItemHierarchy
    ) -> None:
        """3 Network Watcher rows with 2 GUIDs → 2 Tasks."""
        net_epic = next(e for e in sample_hierarchy.epics if e.name == "Networking")
        nw_feature = next(
            f for f in net_epic.features
            if "networkwatchers" in f.resource_type.lower()
        )
        story = nw_feature.user_stories[0]
        assert len(story.tasks) == 2
        # First task ("Enable NSG flow logs") has 2 resources
        nsg_task = next(t for t in story.tasks if "NSG" in t.title)
        assert len(nsg_task.affected_resources) == 2

    def test_feature_sorting_by_resource_count_desc(
        self, sample_hierarchy: WorkItemHierarchy
    ) -> None:
        net_epic = next(e for e in sample_hierarchy.epics if e.name == "Networking")
        counts = [f.resource_count for f in net_epic.features]
        assert counts == sorted(counts, reverse=True)

    def test_task_sorting_by_impact_priority(
        self, sample_hierarchy: WorkItemHierarchy
    ) -> None:
        """Tasks within a story are sorted by impact (High first)."""
        net_epic = next(e for e in sample_hierarchy.epics if e.name == "Networking")
        for feature in net_epic.features:
            for story in feature.user_stories:
                impacts = [t.impact for t in story.tasks]
                impact_order = {"High": 1, "Medium": 2, "Low": 3}
                priorities = [impact_order.get(i, 99) for i in impacts]
                assert priorities == sorted(priorities)

    def test_story_title_includes_resource_type(
        self, sample_hierarchy: WorkItemHierarchy
    ) -> None:
        """Story titles should end with '- Recommendations'."""
        for story in sample_hierarchy.all_stories():
            assert story.title.endswith("- Recommendations")

    def test_unique_resource_count(
        self, sample_hierarchy: WorkItemHierarchy
    ) -> None:
        """Feature.resource_count should count unique resources, not rows."""
        data_epic = next(e for e in sample_hierarchy.epics if e.name == "Data")
        cosmos_feature = next(
            f for f in data_epic.features
            if "documentdb" in f.resource_type.lower()
        )
        # 2 unique CosmosDB resources
        assert cosmos_feature.resource_count == 2

    def test_error_when_matrix_category_missing(self) -> None:
        df = pd.DataFrame({"Resource Type": ["microsoft.compute/virtualMachines"]})
        builder = HierarchyBuilder()
        with pytest.raises(ValueError, match="MatrixCategory"):
            builder.build(df)

    def test_total_summary_stats(
        self, sample_hierarchy: WorkItemHierarchy
    ) -> None:
        stats = sample_hierarchy.summary_stats()
        assert stats["epics"] == 3
        assert stats["features"] == 5
        assert stats["user_stories"] == 5  # 1 per feature
        assert stats["tasks"] == 8  # 8 unique recommendations


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
