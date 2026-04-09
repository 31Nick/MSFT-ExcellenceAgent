"""
GitHub Issues exporter for work-item hierarchy.

Generates two output files:
  1. A structured JSON file with all issues, labels, and hierarchy references.
  2. A consolidated Markdown file with all issues separated by horizontal rules.

The JSON format is designed for programmatic consumption (e.g., future GitHub
API integration), while the Markdown provides a human-readable overview.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from excellence_agent.config import GitHubConfig
from excellence_agent.export.github_content import GitHubContentGenerator
from excellence_agent.models import Epic, Feature, Task, UserStory, WorkItemHierarchy

logger = logging.getLogger(__name__)


@dataclass
class GitHubIssue:
    """Represents a single GitHub Issue to be created."""

    id: str
    issue_type: str  # epic, feature, user-story, task
    title: str
    body: str
    labels: List[str] = field(default_factory=list)
    parent_id: Optional[str] = None
    children_ids: List[str] = field(default_factory=list)
    assignee: str = ""
    milestone: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.id,
            "issue_type": self.issue_type,
            "title": self.title,
            "body": self.body,
            "labels": self.labels,
            "parent_id": self.parent_id,
            "children_ids": self.children_ids,
        }
        if self.assignee:
            d["assignee"] = self.assignee
        if self.milestone:
            d["milestone"] = self.milestone
        return d


class GitHubExporter:
    """Export a :class:`WorkItemHierarchy` to GitHub-compatible JSON and Markdown files."""

    def __init__(self, config: GitHubConfig, content_generator: GitHubContentGenerator) -> None:
        self._config = config
        self._content = content_generator

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export(self, hierarchy: WorkItemHierarchy, output_dir: str) -> Dict[str, str]:
        """Export the hierarchy to GitHub JSON and Markdown files.

        Returns a dict with keys ``json_path`` and ``markdown_path``.
        """
        issues = self._build_issues(hierarchy)
        os.makedirs(output_dir, exist_ok=True)

        json_path = os.path.join(output_dir, "github_issues.json")
        md_path = os.path.join(output_dir, "github_issues.md")

        # Build the full export payload
        label_definitions = self._collect_label_definitions(issues)
        payload: Dict[str, Any] = {
            "repo": self._config.repo,
            "label_definitions": label_definitions,
            "issues": [issue.to_dict() for issue in issues],
            "summary": {
                "total_issues": len(issues),
                "epics": sum(1 for i in issues if i.issue_type == "epic"),
                "features": sum(1 for i in issues if i.issue_type == "feature"),
                "user_stories": sum(1 for i in issues if i.issue_type == "user-story"),
                "tasks": sum(1 for i in issues if i.issue_type == "task"),
            },
        }
        if self._config.milestone:
            payload["milestone"] = self._config.milestone
        if self._config.assignee:
            payload["default_assignee"] = self._config.assignee

        # Write JSON
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)

        # Write Markdown
        with open(md_path, "w", encoding="utf-8") as fh:
            fh.write(self._render_markdown(issues, hierarchy))

        logger.info(
            "GitHub export complete — %d issue(s) to %s",
            len(issues),
            output_dir,
        )
        return {"json_path": json_path, "markdown_path": md_path}

    # ------------------------------------------------------------------
    # Issue builders
    # ------------------------------------------------------------------

    def _build_issues(self, hierarchy: WorkItemHierarchy) -> List[GitHubIssue]:
        """Build all GitHub Issues in hierarchy order."""
        issues: List[GitHubIssue] = []
        if not hierarchy.epics:
            logger.warning("Hierarchy contains no epics — export will be empty.")
            return issues

        for epic_idx, epic in enumerate(hierarchy.epics):
            epic_id = f"epic-{epic_idx}"
            feature_ids: List[str] = []

            for feat_idx, feature in enumerate(epic.features):
                feat_id = f"epic-{epic_idx}-feat-{feat_idx}"
                story_ids: List[str] = []

                for story_idx, story in enumerate(feature.user_stories):
                    story_id = f"epic-{epic_idx}-feat-{feat_idx}-story-{story_idx}"
                    task_ids: List[str] = []

                    for task_idx, task in enumerate(story.tasks):
                        task_id = f"epic-{epic_idx}-feat-{feat_idx}-story-{story_idx}-task-{task_idx}"
                        task_ids.append(task_id)
                        issues.append(self._task_issue(task_id, task, story, story_id))

                    story_ids.append(story_id)
                    issues.append(self._story_issue(story_id, story, feat_id, task_ids))

                feature_ids.append(feat_id)
                issues.append(self._feature_issue(feat_id, feature, epic_id, story_ids))

            issues.append(self._epic_issue(epic_id, epic, feature_ids))

        # Sort: epics first, then features, then stories, then tasks
        type_order = {"epic": 0, "feature": 1, "user-story": 2, "task": 3}
        issues.sort(key=lambda i: (type_order.get(i.issue_type, 99), i.id))
        return issues

    def _epic_issue(self, issue_id: str, epic: Epic, children: List[str]) -> GitHubIssue:
        labels = ["type:epic"]
        if epic.waf_pillars:
            labels.extend(f"waf:{p.lower()}" for p in sorted(epic.waf_pillars))
        labels.append(f"domain:{epic.name.lower()}")
        labels.extend(self._config.extra_labels)

        return GitHubIssue(
            id=issue_id,
            issue_type="epic",
            title=f"[Epic] {epic.name}",
            body=self._content.generate_epic_body(epic),
            labels=labels,
            children_ids=children,
            assignee=self._config.assignee,
            milestone=self._config.milestone,
        )

    def _feature_issue(
        self, issue_id: str, feature: Feature, parent_id: str, children: List[str],
    ) -> GitHubIssue:
        highest_priority = min((s.priority for s in feature.user_stories), default=2)
        labels = [
            "type:feature",
            f"priority:{highest_priority}",
        ]
        if feature.epic:
            labels.append(f"domain:{feature.epic.name.lower()}")
        labels.extend(self._config.extra_labels)

        return GitHubIssue(
            id=issue_id,
            issue_type="feature",
            title=f"[Feature] {feature.name}",
            body=self._content.generate_feature_body(feature),
            labels=labels,
            parent_id=parent_id,
            children_ids=children,
            assignee=self._config.assignee,
            milestone=self._config.milestone,
        )

    def _story_issue(
        self, issue_id: str, story: UserStory, parent_id: str, children: List[str],
    ) -> GitHubIssue:
        labels = [
            "type:user-story",
            f"impact:{story.impact.lower()}",
            f"priority:{story.priority}",
        ]
        if story.waf_pillar:
            labels.append(f"waf:{story.waf_pillar.lower()}")
        if story.category:
            labels.append(f"category:{story.category.lower()}")
        if story.source:
            labels.append(f"source:{story.source.lower()}")
        labels.extend(self._config.extra_labels)

        return GitHubIssue(
            id=issue_id,
            issue_type="user-story",
            title=story.title,
            body=self._content.generate_story_body(story),
            labels=labels,
            parent_id=parent_id,
            children_ids=children,
            assignee=self._config.assignee,
            milestone=self._config.milestone,
        )

    def _task_issue(
        self, issue_id: str, task: Task, story: UserStory, parent_id: str,
    ) -> GitHubIssue:
        source_val = getattr(task, 'source', '') or story.source
        labels = [
            "type:task",
            f"impact:{story.impact.lower()}",
            f"priority:{story.priority}",
        ]
        if task.location:
            labels.append(f"location:{task.location.lower()}")
        if source_val:
            labels.append(f"source:{source_val.lower()}")
        labels.extend(self._config.extra_labels)

        return GitHubIssue(
            id=issue_id,
            issue_type="task",
            title=f"Remediate: {task.resource_name}",
            body=self._content.generate_task_body(task, story),
            labels=labels,
            parent_id=parent_id,
            assignee=self._config.assignee,
            milestone=self._config.milestone,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_label_definitions(issues: List[GitHubIssue]) -> List[Dict[str, str]]:
        """Collect all unique labels and generate definitions with colors."""
        seen: set[str] = set()
        definitions: List[Dict[str, str]] = []

        color_map = {
            "type:epic": "6f42c1",
            "type:feature": "0075ca",
            "type:user-story": "0e8a16",
            "type:task": "fbca04",
        }
        prefix_colors = {
            "impact": "d73a4a",
            "waf": "1d76db",
            "domain": "5319e7",
            "priority": "e4e669",
            "category": "c5def5",
            "location": "bfdadc",
            "source": "f9d0c4",
        }

        for issue in issues:
            for label in issue.labels:
                if label in seen:
                    continue
                seen.add(label)
                prefix = label.split(":")[0] if ":" in label else ""
                color = color_map.get(label, prefix_colors.get(prefix, "ededed"))
                definitions.append({"name": label, "color": color})

        return sorted(definitions, key=lambda d: d["name"])

    def _render_markdown(self, issues: List[GitHubIssue], hierarchy: WorkItemHierarchy) -> str:
        """Render a consolidated Markdown document for all issues."""
        stats = hierarchy.summary_stats()
        lines: List[str] = [
            f"# GitHub Issues Export — {self._config.repo}",
            "",
            f"**Total Issues:** {len(issues)}  ",
            f"**Epics:** {stats['epics']} | "
            f"**Features:** {stats['features']} | "
            f"**User Stories:** {stats['user_stories']} | "
            f"**Tasks:** {stats['tasks']}",
            "",
        ]
        if self._config.milestone:
            lines.append(f"**Milestone:** {self._config.milestone}  ")
        if self._config.assignee:
            lines.append(f"**Assignee:** {self._config.assignee}  ")
        lines.append("")
        lines.append("---")
        lines.append("")

        for issue in issues:
            labels_str = ", ".join(f"`{l}`" for l in issue.labels)
            lines.append(f"## {issue.title}")
            lines.append("")
            lines.append(f"**Type:** {issue.issue_type} | **Labels:** {labels_str}")
            if issue.parent_id:
                lines.append(f"**Parent:** `{issue.parent_id}`")
            if issue.children_ids:
                lines.append(f"**Children:** {', '.join(f'`{c}`' for c in issue.children_ids)}")
            lines.append("")
            lines.append(issue.body)
            lines.append("")
            lines.append("---")
            lines.append("")

        return "\n".join(lines)
