"""Tests for stable_key properties on model classes."""

from __future__ import annotations

import pytest

from excellence_agent.models import (
    AffectedResource,
    Epic,
    Feature,
    Task,
    UserStory,
)


class TestEpicStableKey:
    def test_basic(self) -> None:
        epic = Epic(name="Networking")
        assert epic.stable_key == "epic:networking"

    def test_case_normalized(self) -> None:
        epic = Epic(name="Data")
        assert epic.stable_key == "epic:data"

    def test_spaces_preserved(self) -> None:
        epic = Epic(name="AI & ML")
        assert epic.stable_key == "epic:ai & ml"


class TestFeatureStableKey:
    def test_basic(self) -> None:
        epic = Epic(name="Networking")
        feat = Feature(name="VNets", resource_type="microsoft.network/virtualNetworks")
        epic.add_feature(feat)
        assert feat.stable_key == "feature:networking:microsoft.network/virtualnetworks"

    def test_raises_without_parent(self) -> None:
        feat = Feature(name="VNets", resource_type="microsoft.network/virtualNetworks")
        with pytest.raises(ValueError, match="parent Epic"):
            _ = feat.stable_key


class TestUserStoryStableKey:
    def test_basic(self) -> None:
        epic = Epic(name="Data")
        feat = Feature(name="Cosmos", resource_type="microsoft.documentdb/databaseaccounts")
        epic.add_feature(feat)
        story = UserStory(title="Databaseaccounts - Recommendations", impact="High")
        feat.add_user_story(story)
        assert story.stable_key == "story:data:microsoft.documentdb/databaseaccounts"

    def test_raises_without_parent(self) -> None:
        story = UserStory(title="Recs", impact="High")
        with pytest.raises(ValueError, match="parent Feature"):
            _ = story.stable_key


class TestTaskStableKey:
    def test_basic(self) -> None:
        epic = Epic(name="Networking")
        feat = Feature(name="VNets", resource_type="microsoft.network/virtualNetworks")
        epic.add_feature(feat)
        story = UserStory(title="Virtual Networks - Recommendations", impact="High")
        feat.add_user_story(story)
        task = Task(
            title="Enable DDoS protection",
            recommendation_guid="GUID-001",
            impact="High",
            recommendation_control="Automated",
            affected_resources=[
                AffectedResource("vnet-hub", "/subs/sub/rg/vnet-hub", "RG", "SUB", "uksouth"),
            ],
        )
        story.add_task(task)
        expected = "task:guid-001:microsoft.network/virtualnetworks"
        assert task.stable_key == expected

    def test_raises_without_parent(self) -> None:
        task = Task("rec", "guid", "High", "Automated")
        with pytest.raises(ValueError, match="parent UserStory"):
            _ = task.stable_key

    def test_different_guids_different_keys(self) -> None:
        """Tasks with different recommendation GUIDs yield distinct keys."""
        epic = Epic(name="Net")
        feat = Feature(name="VNets", resource_type="type")
        epic.add_feature(feat)
        story = UserStory(title="Recs", impact="High")
        feat.add_user_story(story)

        task_a = Task("rec-A", "GUID-A", "High", "Automated")
        task_b = Task("rec-B", "GUID-B", "Medium", "Automated")
        story.add_task(task_a)
        story.add_task(task_b)

        assert task_a.stable_key != task_b.stable_key

    def test_add_task_sets_backref(self) -> None:
        story = UserStory(title="Recs", impact="High")
        task = Task("rec", "guid", "High", "Automated")
        story.add_task(task)
        assert task.user_story is story
