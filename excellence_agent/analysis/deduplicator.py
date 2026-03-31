"""Post-processing deduplication analysis on a built work-item hierarchy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from excellence_agent.models import WorkItemHierarchy


@dataclass
class DeduplicationReport:
    """Summary of deduplication already applied during hierarchy building."""

    total_aprl_rows: int  # original row count (== total tasks)
    total_tasks: int  # tasks in hierarchy
    total_stories: int  # deduplicated story count
    dedup_savings: int  # rows saved by deduplication
    stories_with_multiple_tasks: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_aprl_rows": self.total_aprl_rows,
            "total_tasks": self.total_tasks,
            "total_stories": self.total_stories,
            "dedup_savings": self.dedup_savings,
            "stories_with_multiple_tasks": list(self.stories_with_multiple_tasks),
        }

    def summary(self) -> str:
        """Human-readable summary of deduplication results."""
        lines = [
            "=== Deduplication Report ===",
            f"Total APRL rows:       {self.total_aprl_rows}",
            f"Tasks in hierarchy:    {self.total_tasks}",
            f"Deduplicated stories:  {self.total_stories}",
            f"Rows saved by dedup:   {self.dedup_savings}",
        ]
        if self.stories_with_multiple_tasks:
            lines.append("")
            lines.append(
                f"Stories with multiple tasks ({len(self.stories_with_multiple_tasks)}):"
            )
            for entry in self.stories_with_multiple_tasks:
                lines.append(
                    f"  • {entry['story_title']} "
                    f"[{entry['resource_type']}] — "
                    f"{entry['task_count']} tasks"
                )
        return "\n".join(lines)


class Deduplicator:
    """Analyse a hierarchy for deduplication opportunities already applied."""

    def analyse(self, hierarchy: WorkItemHierarchy) -> DeduplicationReport:
        """Return a :class:`DeduplicationReport` for *hierarchy*."""
        all_stories = hierarchy.all_stories()
        all_tasks = hierarchy.all_tasks()

        total_tasks = len(all_tasks)
        total_stories = len(all_stories)

        # Dedup savings: each story with N tasks saved (N - 1) duplicate
        # story entries compared to having one story per task.
        dedup_savings = total_tasks - total_stories

        multi_task_stories: List[Dict[str, Any]] = []
        for story in all_stories:
            if len(story.tasks) > 1:
                resource_type = ""
                if story.feature is not None:
                    resource_type = story.feature.resource_type
                multi_task_stories.append(
                    {
                        "story_title": story.title,
                        "task_count": len(story.tasks),
                        "resource_type": resource_type,
                    }
                )

        # Sort by task count descending for readability.
        multi_task_stories.sort(key=lambda e: e["task_count"], reverse=True)

        return DeduplicationReport(
            total_aprl_rows=total_tasks,
            total_tasks=total_tasks,
            total_stories=total_stories,
            dedup_savings=dedup_savings,
            stories_with_multiple_tasks=multi_task_stories,
        )
