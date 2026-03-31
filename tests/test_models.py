"""Tests for excellence_agent.models data classes."""

from __future__ import annotations

import pytest

from excellence_agent.models import (
    Epic,
    Feature,
    Task,
    UserStory,
    WorkItemHierarchy,
)


# ── Task ──────────────────────────────────────────────────────────────────


class TestTask:
    def test_to_dict_contains_all_fields(self) -> None:
        task = Task(
            resource_name="vm-01",
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-01",
            resource_group="rg",
            subscription_id="sub",
            location="uksouth",
            validation_status="Pending",
            custom_fields={"custom1": "val1"},
            notes="Some note",
            check_name="check-abc",
        )
        d = task.to_dict()
        assert d["resource_name"] == "vm-01"
        assert d["resource_id"].endswith("vm-01")
        assert d["resource_group"] == "rg"
        assert d["subscription_id"] == "sub"
        assert d["location"] == "uksouth"
        assert d["validation_status"] == "Pending"
        assert d["custom_fields"] == {"custom1": "val1"}
        assert d["notes"] == "Some note"
        assert d["check_name"] == "check-abc"

    def test_to_dict_custom_fields_is_copy(self) -> None:
        original = {"custom1": "a"}
        task = Task("n", "id", "rg", "sub", "loc", custom_fields=original)
        d = task.to_dict()
        d["custom_fields"]["custom1"] = "changed"
        assert task.custom_fields["custom1"] == "a"


# ── UserStory ─────────────────────────────────────────────────────────────


class TestUserStory:
    @pytest.mark.parametrize(
        "impact, expected",
        [("High", 1), ("Medium", 2), ("Low", 3)],
    )
    def test_priority_mapping(self, impact: str, expected: int) -> None:
        story = UserStory(
            title="rec",
            recommendation_guid="guid",
            impact=impact,
            recommendation_control="Automated",
        )
        assert story.priority == expected

    def test_priority_unknown_defaults_to_3(self) -> None:
        story = UserStory(
            title="rec",
            recommendation_guid="guid",
            impact="Unknown",
            recommendation_control="Automated",
        )
        assert story.priority == 3

    def test_add_task(self) -> None:
        story = UserStory(
            title="rec",
            recommendation_guid="guid",
            impact="High",
            recommendation_control="Automated",
        )
        task = Task("vm-01", "id", "rg", "sub", "loc")
        story.add_task(task)
        assert len(story.tasks) == 1
        assert story.tasks[0] is task


# ── Feature ───────────────────────────────────────────────────────────────


class TestFeature:
    def _make_feature(self) -> Feature:
        return Feature(name="Cosmos DB", resource_type="microsoft.documentdb/databaseaccounts")

    def test_add_user_story_sets_backref(self) -> None:
        feat = self._make_feature()
        story = UserStory("rec", "guid", "High", "Automated")
        feat.add_user_story(story)
        assert story.feature is feat
        assert len(feat.user_stories) == 1

    def test_total_tasks(self) -> None:
        feat = self._make_feature()
        story1 = UserStory("rec1", "g1", "High", "Automated")
        story1.add_task(Task("r1", "id1", "rg", "sub", "loc"))
        story1.add_task(Task("r2", "id2", "rg", "sub", "loc"))
        story2 = UserStory("rec2", "g2", "Medium", "Automated")
        story2.add_task(Task("r3", "id3", "rg", "sub", "loc"))
        feat.add_user_story(story1)
        feat.add_user_story(story2)
        assert feat.total_tasks() == 3


# ── Epic ──────────────────────────────────────────────────────────────────


class TestEpic:
    def _make_epic(self) -> Epic:
        epic = Epic(name="Data", description="Data services")
        feat = Feature(name="Cosmos DB", resource_type="microsoft.documentdb/databaseaccounts")
        story = UserStory("rec1", "g1", "High", "Automated")
        story.add_task(Task("r1", "id1", "rg", "sub", "loc"))
        story.add_task(Task("r2", "id2", "rg", "sub", "loc"))
        feat.add_user_story(story)
        epic.add_feature(feat)
        return epic

    def test_add_feature_sets_backref(self) -> None:
        epic = Epic(name="Data")
        feat = Feature(name="Cosmos", resource_type="type")
        epic.add_feature(feat)
        assert feat.epic is epic
        assert len(epic.features) == 1

    def test_total_stories(self) -> None:
        epic = self._make_epic()
        assert epic.total_stories() == 1

    def test_total_tasks(self) -> None:
        epic = self._make_epic()
        assert epic.total_tasks() == 2


# ── WorkItemHierarchy ─────────────────────────────────────────────────────


class TestWorkItemHierarchy:
    def test_summary_stats(self, sample_hierarchy: WorkItemHierarchy) -> None:
        stats = sample_hierarchy.summary_stats()
        assert set(stats.keys()) == {"epics", "features", "user_stories", "tasks"}
        # 10 rows → 10 tasks
        assert stats["tasks"] == 10
        assert stats["epics"] > 0
        assert stats["features"] > 0
        assert stats["user_stories"] > 0

    def test_summary_stats_empty(self) -> None:
        h = WorkItemHierarchy()
        assert h.summary_stats() == {
            "epics": 0,
            "features": 0,
            "user_stories": 0,
            "tasks": 0,
        }
