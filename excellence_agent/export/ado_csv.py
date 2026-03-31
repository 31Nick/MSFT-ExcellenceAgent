"""
Azure DevOps CSV exporter for bulk work-item import.

Generates a CSV file using the ADO indented-title hierarchy format:
  Title 1 = Epic, Title 2 = Feature, Title 3 = User Story, Title 4 = Task.

The file is written as UTF-8 with BOM (``utf-8-sig``) because the ADO CSV
import wizard expects that encoding.
"""

from __future__ import annotations

import csv
import logging
import os
from typing import List

from excellence_agent.config import ADOConfig
from excellence_agent.export.content_generator import ContentGenerator
from excellence_agent.models import Epic, Feature, Task, UserStory, WorkItemHierarchy

logger = logging.getLogger(__name__)

_CSV_COLUMNS = [
    "Work Item Type",
    "Title 1",
    "Title 2",
    "Title 3",
    "Title 4",
    "Description",
    "Acceptance Criteria",
    "Tags",
    "Priority",
    "Area Path",
    "Iteration Path",
]


class ADOExporter:
    """Export a :class:`WorkItemHierarchy` to an Azure DevOps-compatible CSV."""

    def __init__(self, config: ADOConfig, content_generator: ContentGenerator) -> None:
        self._config = config
        self._content = content_generator

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export(self, hierarchy: WorkItemHierarchy, output_path: str) -> str:
        """Export the full hierarchy to an ADO-compatible CSV file.

        Returns the resolved output file path.
        """
        rows = self._build_rows(hierarchy)

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        with open(output_path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=_CSV_COLUMNS, quoting=csv.QUOTE_ALL,
            )
            writer.writeheader()
            writer.writerows(rows)

        epic_count = sum(1 for r in rows if r["Work Item Type"] == self._config.work_item_type_epic)
        feature_count = sum(1 for r in rows if r["Work Item Type"] == self._config.work_item_type_feature)
        story_count = sum(1 for r in rows if r["Work Item Type"] == self._config.work_item_type_story)
        task_count = sum(1 for r in rows if r["Work Item Type"] == self._config.work_item_type_task)

        logger.info(
            "ADO CSV exported to %s — %d epic(s), %d feature(s), %d story/stories, %d task(s) (%d rows total)",
            output_path,
            epic_count,
            feature_count,
            story_count,
            task_count,
            len(rows),
        )
        return output_path

    # ------------------------------------------------------------------
    # Row builders
    # ------------------------------------------------------------------

    def _build_rows(self, hierarchy: WorkItemHierarchy) -> List[dict]:
        """Build all CSV rows in strict hierarchy order."""
        rows: List[dict] = []
        if not hierarchy.epics:
            logger.warning("Hierarchy contains no epics — CSV will be empty.")
            return rows

        for epic in hierarchy.epics:
            rows.append(self._epic_row(epic))
            for feature in epic.features:
                rows.append(self._feature_row(feature))
                for story in feature.user_stories:
                    rows.append(self._story_row(story))
                    for task in story.tasks:
                        rows.append(self._task_row(task, story))
        return rows

    def _epic_row(self, epic: Epic) -> dict:
        return {
            "Work Item Type": self._config.work_item_type_epic,
            "Title 1": epic.name,
            "Title 2": "",
            "Title 3": "",
            "Title 4": "",
            "Description": self._content.generate_epic_description(epic),
            "Acceptance Criteria": self._content.generate_epic_acceptance_criteria(epic),
            "Tags": self._build_tags(
                waf_pillars=sorted(epic.waf_pillars) if epic.waf_pillars else None,
                domain=epic.name,
            ),
            "Priority": 2,
            "Area Path": self._config.area_path,
            "Iteration Path": self._config.iteration_path,
        }

    def _feature_row(self, feature: Feature) -> dict:
        highest_priority = (
            min((s.priority for s in feature.user_stories), default=2)
        )
        return {
            "Work Item Type": self._config.work_item_type_feature,
            "Title 1": "",
            "Title 2": feature.name,
            "Title 3": "",
            "Title 4": "",
            "Description": self._content.generate_feature_description(feature),
            "Acceptance Criteria": self._content.generate_feature_acceptance_criteria(feature),
            "Tags": self._build_tags(
                resource_type=feature.resource_type,
                domain=feature.epic.name if feature.epic else None,
            ),
            "Priority": highest_priority,
            "Area Path": self._config.area_path,
            "Iteration Path": self._config.iteration_path,
        }

    def _story_row(self, story: UserStory) -> dict:
        return {
            "Work Item Type": self._config.work_item_type_story,
            "Title 1": "",
            "Title 2": "",
            "Title 3": story.title,
            "Title 4": "",
            "Description": self._content.generate_story_description(story),
            "Acceptance Criteria": self._content.generate_story_acceptance_criteria(story),
            "Tags": self._build_tags(
                impact=story.impact,
                waf_pillar=story.waf_pillar or None,
                category=story.category or None,
            ),
            "Priority": story.priority,
            "Area Path": self._config.area_path,
            "Iteration Path": self._config.iteration_path,
        }

    def _task_row(self, task: Task, story: UserStory) -> dict:
        return {
            "Work Item Type": self._config.work_item_type_task,
            "Title 1": "",
            "Title 2": "",
            "Title 3": "",
            "Title 4": task.resource_name,
            "Description": self._content.generate_task_description(task, story),
            "Acceptance Criteria": self._content.generate_task_acceptance_criteria(task, story),
            "Tags": self._build_tags(
                impact=story.impact,
                location=task.location or None,
            ),
            "Priority": story.priority,
            "Area Path": self._config.area_path,
            "Iteration Path": self._config.iteration_path,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_tags(**kwargs: str | list[str] | None) -> str:
        """Build a semicolon-separated tags string.

        Accepts keyword arguments whose values are either a single string, a
        list of strings, or ``None``.  ``None`` / empty values are silently
        skipped.
        """
        parts: list[str] = []
        for value in kwargs.values():
            if value is None:
                continue
            if isinstance(value, list):
                parts.extend(v for v in value if v)
            elif value:
                parts.append(str(value))
        return "; ".join(parts)
