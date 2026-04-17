"""Tests for excellence_agent.models data classes."""

from __future__ import annotations

import pytest

from excellence_agent.models import (
    AffectedResource,
    Epic,
    Feature,
    Task,
    UserStory,
    WorkItemHierarchy,
)


# ── AffectedResource ─────────────────────────────────────────────────────


class TestAffectedResource:
    def test_to_dict_contains_all_fields(self) -> None:
        res = AffectedResource(
            resource_name="vm-01",
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/type/vm-01",
            resource_group="rg",
            subscription_id="sub",
            location="uksouth",
            validation_status="Pending",
            notes="Some note",
            check_name="check-abc",
            custom_fields={"custom1": "val1"},
        )
        d = res.to_dict()
        assert d["resource_name"] == "vm-01"
        assert d["resource_id"].endswith("vm-01")
        assert d["resource_group"] == "rg"
        assert d["subscription_id"] == "sub"
        assert d["location"] == "uksouth"
        assert d["validation_status"] == "Pending"
        assert d["notes"] == "Some note"
        assert d["check_name"] == "check-abc"
        assert d["custom_fields"] == {"custom1": "val1"}

    def test_to_dict_custom_fields_is_copy(self) -> None:
        original = {"custom1": "a"}
        res = AffectedResource("n", "id", "rg", "sub", "loc", custom_fields=original)
        d = res.to_dict()
        d["custom_fields"]["custom1"] = "changed"
        assert res.custom_fields["custom1"] == "a"


# ── Task ──────────────────────────────────────────────────────────────────


class TestTask:
    def test_to_dict_contains_all_fields(self) -> None:
        task = Task(
            title="Enable automatic failover",
            recommendation_guid="guid-123",
            impact="High",
            recommendation_control="Automated",
            potential_benefit="Improved resilience",
            learn_more_link="https://aka.ms/aprl",
            long_description="Enable failover for CosmosDB",
            waf_pillar="Reliability",
            category="Data",
            source="APRL",
            affected_resources=[
                AffectedResource("vm-01", "id-1", "rg", "sub", "uksouth"),
            ],
        )
        d = task.to_dict()
        assert d["title"] == "Enable automatic failover"
        assert d["recommendation_guid"] == "guid-123"
        assert d["impact"] == "High"
        assert d["recommendation_control"] == "Automated"
        assert d["waf_pillar"] == "Reliability"
        assert len(d["affected_resources"]) == 1
        assert d["affected_resources"][0]["resource_name"] == "vm-01"


# ── UserStory ─────────────────────────────────────────────────────────────


class TestUserStory:
    @pytest.mark.parametrize(
        "impact, expected",
        [("High", 1), ("Medium", 2), ("Low", 3)],
    )
    def test_priority_mapping(self, impact: str, expected: int) -> None:
        story = UserStory(title="Recs", impact=impact)
        assert story.priority == expected

    def test_priority_unknown_defaults_to_3(self) -> None:
        story = UserStory(title="Recs", impact="Unknown")
        assert story.priority == 3

    def test_add_task_sets_backref(self) -> None:
        story = UserStory(title="Recs", impact="High")
        task = Task("rec1", "guid-1", "High", "Automated")
        story.add_task(task)
        assert len(story.tasks) == 1
        assert story.tasks[0] is task
        assert task.user_story is story

    def test_total_affected_resources(self) -> None:
        story = UserStory(title="Recs", impact="High")
        t1 = Task("rec1", "g1", "High", "Automated", affected_resources=[
            AffectedResource("r1", "id1", "rg", "sub", "loc"),
            AffectedResource("r2", "id2", "rg", "sub", "loc"),
        ])
        t2 = Task("rec2", "g2", "Medium", "Automated", affected_resources=[
            AffectedResource("r3", "id3", "rg", "sub", "loc"),
        ])
        story.add_task(t1)
        story.add_task(t2)
        assert story.total_affected_resources() == 3


# ── Feature ───────────────────────────────────────────────────────────────


class TestFeature:
    def _make_feature(self) -> Feature:
        return Feature(name="Cosmos DB", resource_type="microsoft.documentdb/databaseaccounts")

    def test_add_user_story_sets_backref(self) -> None:
        feat = self._make_feature()
        story = UserStory(title="Recs", impact="High")
        feat.add_user_story(story)
        assert story.feature is feat
        assert len(feat.user_stories) == 1

    def test_total_tasks(self) -> None:
        feat = self._make_feature()
        story = UserStory(title="Recs", impact="High")
        story.add_task(Task("rec1", "g1", "High", "Automated"))
        story.add_task(Task("rec2", "g2", "Medium", "Automated"))
        feat.add_user_story(story)
        assert feat.total_tasks() == 2

    def test_total_affected_resources(self) -> None:
        feat = self._make_feature()
        story = UserStory(title="Recs", impact="High")
        t1 = Task("rec1", "g1", "High", "Automated", affected_resources=[
            AffectedResource("r1", "id1", "rg", "sub", "loc"),
            AffectedResource("r2", "id2", "rg", "sub", "loc"),
        ])
        story.add_task(t1)
        feat.add_user_story(story)
        assert feat.total_affected_resources() == 2


# ── Epic ──────────────────────────────────────────────────────────────────


class TestEpic:
    def _make_epic(self) -> Epic:
        epic = Epic(name="Data", description="Data services")
        feat = Feature(name="Cosmos DB", resource_type="microsoft.documentdb/databaseaccounts")
        story = UserStory(title="Recs", impact="High")
        story.add_task(Task("rec1", "g1", "High", "Automated", affected_resources=[
            AffectedResource("r1", "id1", "rg", "sub", "loc"),
            AffectedResource("r2", "id2", "rg", "sub", "loc"),
        ]))
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
        assert epic.total_tasks() == 1

    def test_total_affected_resources(self) -> None:
        epic = self._make_epic()
        assert epic.total_affected_resources() == 2


# ── WorkItemHierarchy ─────────────────────────────────────────────────────


class TestWorkItemHierarchy:
    def test_summary_stats(self, sample_hierarchy: WorkItemHierarchy) -> None:
        stats = sample_hierarchy.summary_stats()
        assert set(stats.keys()) == {"epics", "features", "user_stories", "tasks"}
        # 8 unique recommendations → 8 tasks (not 10 rows)
        assert stats["tasks"] == 8
        # 5 features, each with 1 story
        assert stats["user_stories"] == 5
        assert stats["epics"] == 3
        assert stats["features"] == 5

    def test_summary_stats_empty(self) -> None:
        h = WorkItemHierarchy()
        assert h.summary_stats() == {
            "epics": 0,
            "features": 0,
            "user_stories": 0,
            "tasks": 0,
        }

    def test_all_affected_resources(self, sample_hierarchy: WorkItemHierarchy) -> None:
        """10 input rows → 10 affected resources across all tasks."""
        assert len(sample_hierarchy.all_affected_resources()) == 10
