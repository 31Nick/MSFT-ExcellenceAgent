"""Tests for stable_key properties on model classes."""

from __future__ import annotations

import pytest

from excellence_agent.models import Epic, Feature, Task, UserStory


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
        story = UserStory(
            title="Enable failover",
            recommendation_guid="AAAA-1111-BBBB-2222",
            impact="High",
            recommendation_control="Automated",
        )
        feat.add_user_story(story)
        assert story.stable_key == "story:aaaa-1111-bbbb-2222:microsoft.documentdb/databaseaccounts"

    def test_raises_without_parent(self) -> None:
        story = UserStory(
            title="rec",
            recommendation_guid="guid",
            impact="High",
            recommendation_control="Automated",
        )
        with pytest.raises(ValueError, match="parent Feature"):
            _ = story.stable_key


class TestTaskStableKey:
    def test_basic(self) -> None:
        epic = Epic(name="Networking")
        feat = Feature(name="VNets", resource_type="microsoft.network/virtualNetworks")
        epic.add_feature(feat)
        story = UserStory(
            title="Enable DDoS",
            recommendation_guid="GUID-001",
            impact="High",
            recommendation_control="Automated",
        )
        feat.add_user_story(story)
        task = Task(
            resource_name="vnet-hub",
            resource_id="/subscriptions/SUB/resourceGroups/RG/providers/Microsoft.Network/virtualNetworks/vnet-hub",
            resource_group="RG",
            subscription_id="SUB",
            location="uksouth",
        )
        story.add_task(task)
        expected = "task:guid-001:/subscriptions/sub/resourcegroups/rg/providers/microsoft.network/virtualnetworks/vnet-hub"
        assert task.stable_key == expected

    def test_raises_without_parent(self) -> None:
        task = Task("n", "id", "rg", "sub", "loc")
        with pytest.raises(ValueError, match="parent UserStory"):
            _ = task.stable_key

    def test_same_resource_different_stories_no_collision(self) -> None:
        """Same resource_id under two different recommendations yields distinct keys."""
        epic = Epic(name="Net")
        feat = Feature(name="VNets", resource_type="type")
        epic.add_feature(feat)

        story_a = UserStory("rec-A", "GUID-A", "High", "Automated")
        story_b = UserStory("rec-B", "GUID-B", "Medium", "Automated")
        feat.add_user_story(story_a)
        feat.add_user_story(story_b)

        task_a = Task("vm", "/subs/x/vm-01", "rg", "sub", "loc")
        task_b = Task("vm", "/subs/x/vm-01", "rg", "sub", "loc")
        story_a.add_task(task_a)
        story_b.add_task(task_b)

        assert task_a.stable_key != task_b.stable_key

    def test_add_task_sets_backref(self) -> None:
        story = UserStory("rec", "guid", "High", "Automated")
        task = Task("n", "id", "rg", "sub", "loc")
        story.add_task(task)
        assert task.user_story is story
