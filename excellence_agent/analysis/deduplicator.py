"""Post-processing deduplication analysis on a built work-item hierarchy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from excellence_agent.models import WorkItemHierarchy


@dataclass
class DeduplicationReport:
    """Summary of consolidation applied during hierarchy building."""

    total_aprl_rows: int  # original row count (resource × recommendation pairs)
    total_recommendations: int  # unique recommendation tasks
    total_stories: int  # consolidated story count (1 per resource type per epic)
    consolidation_savings: int  # stories saved by consolidation
    recommendations_with_multiple_resources: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_aprl_rows": self.total_aprl_rows,
            "total_recommendations": self.total_recommendations,
            "total_stories": self.total_stories,
            "consolidation_savings": self.consolidation_savings,
            "recommendations_with_multiple_resources": list(self.recommendations_with_multiple_resources),
        }

    def summary(self) -> str:
        """Human-readable summary of consolidation results."""
        lines = [
            "=== Consolidation Report ===",
            f"Total APRL rows:          {self.total_aprl_rows}",
            f"Unique recommendations:   {self.total_recommendations}",
            f"Consolidated stories:     {self.total_stories}",
            f"Stories saved:            {self.consolidation_savings}",
        ]
        if self.recommendations_with_multiple_resources:
            lines.append("")
            lines.append(
                f"Recommendations with multiple resources ({len(self.recommendations_with_multiple_resources)}):"
            )
            for entry in self.recommendations_with_multiple_resources:
                lines.append(
                    f"  • {entry['recommendation_title']} "
                    f"[{entry['resource_type']}] — "
                    f"{entry['resource_count']} resources"
                )
        return "\n".join(lines)


class Deduplicator:
    """Analyse a hierarchy for consolidation metrics."""

    def analyse(self, hierarchy: WorkItemHierarchy) -> DeduplicationReport:
        """Return a :class:`DeduplicationReport` for *hierarchy*."""
        all_stories = hierarchy.all_stories()
        all_recs = hierarchy.all_recommendations()

        total_recommendations = len(all_recs)
        total_stories = len(all_stories)
        # Total resource×recommendation pairs (original rows)
        total_rows = sum(len(r.affected_resources) for r in all_recs)

        # Consolidation savings: recommendations that would have been separate stories
        # under the old model, now consolidated per resource type
        consolidation_savings = total_recommendations - total_stories

        multi_resource_recs: List[Dict[str, Any]] = []
        for story in all_stories:
            for rec in story.recommendations:
                if len(rec.affected_resources) > 1:
                    resource_type = story.feature.resource_type if story.feature else ""
                    multi_resource_recs.append(
                        {
                            "recommendation_title": rec.title,
                            "resource_count": len(rec.affected_resources),
                            "resource_type": resource_type,
                        }
                    )

        # Sort by resource count descending.
        multi_resource_recs.sort(key=lambda e: e["resource_count"], reverse=True)

        return DeduplicationReport(
            total_aprl_rows=total_rows,
            total_recommendations=total_recommendations,
            total_stories=total_stories,
            consolidation_savings=consolidation_savings,
            recommendations_with_multiple_resources=multi_resource_recs,
        )
