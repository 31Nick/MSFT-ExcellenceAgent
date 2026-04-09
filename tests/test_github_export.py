"""Tests for excellence_agent.export.github_export.GitHubExporter."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from excellence_agent.config import GitHubConfig
from excellence_agent.export.github_content import GitHubContentGenerator
from excellence_agent.export.github_export import GitHubExporter
from excellence_agent.models import (
    Epic,
    Feature,
    Task,
    UserStory,
    WorkItemHierarchy,
)


@pytest.fixture()
def github_config() -> GitHubConfig:
    return GitHubConfig(
        repo="myorg/myrepo",
        milestone="Sprint 1",
        assignee="octocat",
    )


@pytest.fixture()
def github_content_generator() -> GitHubContentGenerator:
    return GitHubContentGenerator()


@pytest.fixture()
def github_exporter(github_config: GitHubConfig, github_content_generator: GitHubContentGenerator) -> GitHubExporter:
    return GitHubExporter(github_config, github_content_generator)


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
        source="APRL",
    )
    task = Task(
        resource_name="cosmos-db-01",
        resource_id="/subscriptions/sub/rg/cosmos-db-01",
        resource_group="rg-data",
        subscription_id="sub-001",
        location="uksouth",
        source="APRL",
    )
    story.add_task(task)
    feat.add_user_story(story)
    epic.add_feature(feat)
    h.add_epic(epic)
    return h


def _build_multi_hierarchy() -> WorkItemHierarchy:
    """Two Epics with multiple levels for more thorough testing."""
    h = WorkItemHierarchy()

    # Epic 1: Data
    epic1 = Epic(name="Data", description="Data services")
    feat1 = Feature(name="Cosmos DB", resource_type="microsoft.documentdb/databaseaccounts")
    story1 = UserStory(
        title="Enable automatic failover",
        recommendation_guid="aaaa-1111",
        impact="High",
        recommendation_control="Automated",
        waf_pillar="Reliability",
        category="Availability",
        source="APRL",
    )
    task1 = Task(
        resource_name="cosmos-db-01",
        resource_id="/subscriptions/sub/rg/cosmos-db-01",
        resource_group="rg-data",
        subscription_id="sub-001",
        location="uksouth",
        source="APRL",
    )
    task2 = Task(
        resource_name="cosmos-db-02",
        resource_id="/subscriptions/sub/rg/cosmos-db-02",
        resource_group="rg-data",
        subscription_id="sub-001",
        location="ukwest",
        source="APRL",
    )
    story1.add_task(task1)
    story1.add_task(task2)
    feat1.add_user_story(story1)
    epic1.add_feature(feat1)
    h.add_epic(epic1)

    # Epic 2: Networking
    epic2 = Epic(name="Networking", description="Network resources")
    feat2 = Feature(name="Virtual Networks", resource_type="microsoft.network/virtualnetworks")
    story2 = UserStory(
        title="Configure DDoS protection",
        recommendation_guid="bbbb-2222",
        impact="Medium",
        recommendation_control="Personalized",
        waf_pillar="Security",
        category="Network Security",
        source="Advisor",
    )
    task3 = Task(
        resource_name="vnet-hub",
        resource_id="/subscriptions/sub/rg/vnet-hub",
        resource_group="rg-network",
        subscription_id="sub-001",
        location="eastus",
        source="Advisor",
    )
    story2.add_task(task3)
    feat2.add_user_story(story2)
    epic2.add_feature(feat2)
    h.add_epic(epic2)

    return h


class TestGitHubExporter:
    def test_export_creates_both_files(self, github_exporter: GitHubExporter, tmp_path: Path) -> None:
        paths = github_exporter.export(_build_small_hierarchy(), str(tmp_path))
        assert os.path.exists(paths["json_path"])
        assert os.path.exists(paths["markdown_path"])
        assert paths["json_path"].endswith("github_issues.json")
        assert paths["markdown_path"].endswith("github_issues.md")

    def test_json_structure(self, github_exporter: GitHubExporter, tmp_path: Path) -> None:
        paths = github_exporter.export(_build_small_hierarchy(), str(tmp_path))
        with open(paths["json_path"], encoding="utf-8") as fh:
            data = json.load(fh)

        assert data["repo"] == "myorg/myrepo"
        assert data["milestone"] == "Sprint 1"
        assert data["default_assignee"] == "octocat"
        assert "label_definitions" in data
        assert "issues" in data
        assert "summary" in data

    def test_json_issue_count(self, github_exporter: GitHubExporter, tmp_path: Path) -> None:
        """Small hierarchy: 1 epic + 1 feature + 1 story + 1 task = 4 issues."""
        paths = github_exporter.export(_build_small_hierarchy(), str(tmp_path))
        with open(paths["json_path"], encoding="utf-8") as fh:
            data = json.load(fh)

        assert data["summary"]["total_issues"] == 4
        assert data["summary"]["epics"] == 1
        assert data["summary"]["features"] == 1
        assert data["summary"]["user_stories"] == 1
        assert data["summary"]["tasks"] == 1
        assert len(data["issues"]) == 4

    def test_json_issue_types(self, github_exporter: GitHubExporter, tmp_path: Path) -> None:
        paths = github_exporter.export(_build_small_hierarchy(), str(tmp_path))
        with open(paths["json_path"], encoding="utf-8") as fh:
            data = json.load(fh)

        types = [issue["issue_type"] for issue in data["issues"]]
        assert "epic" in types
        assert "feature" in types
        assert "user-story" in types
        assert "task" in types

    def test_type_labels(self, github_exporter: GitHubExporter, tmp_path: Path) -> None:
        paths = github_exporter.export(_build_small_hierarchy(), str(tmp_path))
        with open(paths["json_path"], encoding="utf-8") as fh:
            data = json.load(fh)

        for issue in data["issues"]:
            type_label = f"type:{issue['issue_type']}"
            assert type_label in issue["labels"], f"Missing {type_label} in {issue['title']}"

    def test_epic_title_prefix(self, github_exporter: GitHubExporter, tmp_path: Path) -> None:
        paths = github_exporter.export(_build_small_hierarchy(), str(tmp_path))
        with open(paths["json_path"], encoding="utf-8") as fh:
            data = json.load(fh)

        epics = [i for i in data["issues"] if i["issue_type"] == "epic"]
        assert len(epics) == 1
        assert epics[0]["title"].startswith("[Epic]")

    def test_feature_title_prefix(self, github_exporter: GitHubExporter, tmp_path: Path) -> None:
        paths = github_exporter.export(_build_small_hierarchy(), str(tmp_path))
        with open(paths["json_path"], encoding="utf-8") as fh:
            data = json.load(fh)

        features = [i for i in data["issues"] if i["issue_type"] == "feature"]
        assert len(features) == 1
        assert features[0]["title"].startswith("[Feature]")

    def test_task_title_prefix(self, github_exporter: GitHubExporter, tmp_path: Path) -> None:
        paths = github_exporter.export(_build_small_hierarchy(), str(tmp_path))
        with open(paths["json_path"], encoding="utf-8") as fh:
            data = json.load(fh)

        tasks = [i for i in data["issues"] if i["issue_type"] == "task"]
        assert len(tasks) == 1
        assert tasks[0]["title"].startswith("Remediate:")

    def test_parent_child_references(self, github_exporter: GitHubExporter, tmp_path: Path) -> None:
        paths = github_exporter.export(_build_small_hierarchy(), str(tmp_path))
        with open(paths["json_path"], encoding="utf-8") as fh:
            data = json.load(fh)

        issues_by_id = {i["id"]: i for i in data["issues"]}

        # Epic has no parent, has feature as child
        epic = [i for i in data["issues"] if i["issue_type"] == "epic"][0]
        assert epic["parent_id"] is None
        assert len(epic["children_ids"]) > 0

        # Feature has epic as parent, story as child
        feature = [i for i in data["issues"] if i["issue_type"] == "feature"][0]
        assert feature["parent_id"] is not None
        assert len(feature["children_ids"]) > 0

        # Task has story as parent, no children
        task = [i for i in data["issues"] if i["issue_type"] == "task"][0]
        assert task["parent_id"] is not None
        assert len(task["children_ids"]) == 0

    def test_impact_labels(self, github_exporter: GitHubExporter, tmp_path: Path) -> None:
        paths = github_exporter.export(_build_small_hierarchy(), str(tmp_path))
        with open(paths["json_path"], encoding="utf-8") as fh:
            data = json.load(fh)

        stories = [i for i in data["issues"] if i["issue_type"] == "user-story"]
        assert "impact:high" in stories[0]["labels"]

    def test_priority_labels(self, github_exporter: GitHubExporter, tmp_path: Path) -> None:
        paths = github_exporter.export(_build_small_hierarchy(), str(tmp_path))
        with open(paths["json_path"], encoding="utf-8") as fh:
            data = json.load(fh)

        # High impact = priority 1
        stories = [i for i in data["issues"] if i["issue_type"] == "user-story"]
        assert "priority:1" in stories[0]["labels"]

    def test_waf_labels(self, github_exporter: GitHubExporter, tmp_path: Path) -> None:
        paths = github_exporter.export(_build_small_hierarchy(), str(tmp_path))
        with open(paths["json_path"], encoding="utf-8") as fh:
            data = json.load(fh)

        stories = [i for i in data["issues"] if i["issue_type"] == "user-story"]
        assert "waf:reliability" in stories[0]["labels"]

    def test_location_labels_on_tasks(self, github_exporter: GitHubExporter, tmp_path: Path) -> None:
        paths = github_exporter.export(_build_small_hierarchy(), str(tmp_path))
        with open(paths["json_path"], encoding="utf-8") as fh:
            data = json.load(fh)

        tasks = [i for i in data["issues"] if i["issue_type"] == "task"]
        assert "location:uksouth" in tasks[0]["labels"]

    def test_assignee_from_config(self, github_exporter: GitHubExporter, tmp_path: Path) -> None:
        paths = github_exporter.export(_build_small_hierarchy(), str(tmp_path))
        with open(paths["json_path"], encoding="utf-8") as fh:
            data = json.load(fh)

        for issue in data["issues"]:
            assert issue.get("assignee") == "octocat"

    def test_milestone_from_config(self, github_exporter: GitHubExporter, tmp_path: Path) -> None:
        paths = github_exporter.export(_build_small_hierarchy(), str(tmp_path))
        with open(paths["json_path"], encoding="utf-8") as fh:
            data = json.load(fh)

        for issue in data["issues"]:
            assert issue.get("milestone") == "Sprint 1"

    def test_empty_hierarchy(self, github_exporter: GitHubExporter, tmp_path: Path) -> None:
        paths = github_exporter.export(WorkItemHierarchy(), str(tmp_path))
        with open(paths["json_path"], encoding="utf-8") as fh:
            data = json.load(fh)

        assert data["summary"]["total_issues"] == 0
        assert len(data["issues"]) == 0

    def test_label_definitions_generated(self, github_exporter: GitHubExporter, tmp_path: Path) -> None:
        paths = github_exporter.export(_build_small_hierarchy(), str(tmp_path))
        with open(paths["json_path"], encoding="utf-8") as fh:
            data = json.load(fh)

        label_names = [d["name"] for d in data["label_definitions"]]
        assert "type:epic" in label_names
        assert "type:feature" in label_names
        assert "type:user-story" in label_names
        assert "type:task" in label_names

    def test_label_definitions_have_colors(self, github_exporter: GitHubExporter, tmp_path: Path) -> None:
        paths = github_exporter.export(_build_small_hierarchy(), str(tmp_path))
        with open(paths["json_path"], encoding="utf-8") as fh:
            data = json.load(fh)

        for defn in data["label_definitions"]:
            assert "name" in defn
            assert "color" in defn
            assert len(defn["color"]) == 6  # hex color without #

    def test_markdown_output_contains_title(self, github_exporter: GitHubExporter, tmp_path: Path) -> None:
        paths = github_exporter.export(_build_small_hierarchy(), str(tmp_path))
        with open(paths["markdown_path"], encoding="utf-8") as fh:
            content = fh.read()

        assert "myorg/myrepo" in content
        assert "Data" in content
        assert "Enable automatic failover" in content

    def test_markdown_contains_all_issue_types(self, github_exporter: GitHubExporter, tmp_path: Path) -> None:
        paths = github_exporter.export(_build_small_hierarchy(), str(tmp_path))
        with open(paths["markdown_path"], encoding="utf-8") as fh:
            content = fh.read()

        assert "[Epic]" in content
        assert "[Feature]" in content
        assert "Remediate:" in content

    def test_multi_hierarchy_issue_count(self, github_exporter: GitHubExporter, tmp_path: Path) -> None:
        """Multi hierarchy: 2 epics + 2 features + 2 stories + 3 tasks = 9 issues."""
        paths = github_exporter.export(_build_multi_hierarchy(), str(tmp_path))
        with open(paths["json_path"], encoding="utf-8") as fh:
            data = json.load(fh)

        assert data["summary"]["total_issues"] == 9
        assert data["summary"]["epics"] == 2
        assert data["summary"]["features"] == 2
        assert data["summary"]["user_stories"] == 2
        assert data["summary"]["tasks"] == 3

    def test_no_optional_fields_when_empty(self, tmp_path: Path) -> None:
        """Config without milestone/assignee should not include those fields."""
        config = GitHubConfig(repo="org/repo")
        gen = GitHubContentGenerator()
        exporter = GitHubExporter(config, gen)

        paths = exporter.export(_build_small_hierarchy(), str(tmp_path))
        with open(paths["json_path"], encoding="utf-8") as fh:
            data = json.load(fh)

        assert "milestone" not in data
        assert "default_assignee" not in data
        for issue in data["issues"]:
            assert "assignee" not in issue
            assert "milestone" not in issue

    def test_extra_labels_applied(self, tmp_path: Path) -> None:
        """Extra labels from config should be applied to all issues."""
        config = GitHubConfig(repo="org/repo", extra_labels=["azure", "aprl"])
        gen = GitHubContentGenerator()
        exporter = GitHubExporter(config, gen)

        paths = exporter.export(_build_small_hierarchy(), str(tmp_path))
        with open(paths["json_path"], encoding="utf-8") as fh:
            data = json.load(fh)

        for issue in data["issues"]:
            assert "azure" in issue["labels"]
            assert "aprl" in issue["labels"]

    def test_issue_bodies_are_markdown(self, github_exporter: GitHubExporter, tmp_path: Path) -> None:
        """Issue bodies should be Markdown, not HTML."""
        paths = github_exporter.export(_build_small_hierarchy(), str(tmp_path))
        with open(paths["json_path"], encoding="utf-8") as fh:
            data = json.load(fh)

        for issue in data["issues"]:
            body = issue["body"]
            # Should contain Markdown headings
            assert "#" in body
            # Should NOT contain HTML tags (our templates use pure Markdown)
            assert "<h1>" not in body
            assert "<ul>" not in body
