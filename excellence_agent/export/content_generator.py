"""
Content generator for ADO work-item descriptions and acceptance criteria.

Uses Jinja2 templates to produce rich Markdown that Azure DevOps renders in
description fields.  Acceptance criteria are generated programmatically so they
stay specific, testable, and traceable back to APRL checks.
"""

from __future__ import annotations

import logging
import os
from collections import Counter
from typing import TYPE_CHECKING

from jinja2 import Environment, FileSystemLoader

if TYPE_CHECKING:
    pass

from excellence_agent.models import Epic, Feature, Task, UserStory

logger = logging.getLogger(__name__)

_DEFAULT_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")


class ContentGenerator:
    """Render work-item descriptions and acceptance criteria for every hierarchy level."""

    def __init__(self, template_dir: str | None = None) -> None:
        """Initialise the Jinja2 environment.

        Parameters
        ----------
        template_dir:
            Path to the directory containing ``*.md.j2`` templates.
            Defaults to the ``templates/`` sub-package next to this file.
        """
        self._template_dir = template_dir or _DEFAULT_TEMPLATE_DIR
        self._env = Environment(
            loader=FileSystemLoader(self._template_dir),
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        logger.debug("ContentGenerator initialised with templates from %s", self._template_dir)

    # ------------------------------------------------------------------
    # Epic
    # ------------------------------------------------------------------

    def generate_epic_description(self, epic: Epic) -> str:
        """Render the Epic description from *epic.md.j2*."""
        all_subs: set[str] = set()
        for feat in epic.features:
            all_subs.update(feat.subscriptions)

        template = self._env.get_template("epic.md.j2")
        rendered = template.render(
            epic_name=epic.name,
            description=epic.description or f"Azure Excellence recommendations for the {epic.name} domain.",
            waf_pillars=sorted(epic.waf_pillars) if epic.waf_pillars else ["N/A"],
            feature_count=len(epic.features),
            story_count=epic.total_stories(),
            resource_count=epic.total_resource_count,
            subscriptions=sorted(all_subs) if all_subs else ["N/A"],
            impact_summary=epic.impact_summary or {},
            features=epic.features,
        )
        logger.debug("Generated Epic description for '%s'", epic.name)
        return rendered

    def generate_epic_acceptance_criteria(self, epic: Epic) -> str:
        """Generate acceptance criteria for an Epic."""
        lines: list[str] = [
            "<p>All Features within this Epic are completed and verified.</p>",
        ]
        if epic.features:
            lines.append("<p><strong>Features to complete:</strong></p>")
            lines.append("<ul>")
            for feat in epic.features:
                lines.append(
                    f"<li>{feat.name} ({feat.resource_type}) &mdash; "
                    f"{len(feat.user_stories)} recommendation(s), "
                    f"{feat.total_tasks()} resource(s)</li>"
                )
            lines.append("</ul>")
        logger.debug("Generated Epic acceptance criteria for '%s'", epic.name)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Feature
    # ------------------------------------------------------------------

    def generate_feature_description(self, feature: Feature) -> str:
        """Render the Feature description from *feature.md.j2*."""
        epic_name = feature.epic.name if feature.epic else "Unknown"

        impact_counter: Counter[str] = Counter()
        locations: set[str] = set()
        all_tasks = []
        for story in feature.user_stories:
            for task in story.tasks:
                impact_counter[task.impact] += 1
                for res in task.affected_resources:
                    locations.add(res.location)
                all_tasks.append(task)

        template = self._env.get_template("feature.md.j2")
        rendered = template.render(
            feature_name=feature.name,
            resource_type=feature.resource_type,
            epic_name=epic_name,
            recommendation_count=len(all_tasks),
            resource_count=feature.resource_count,
            resource_groups=sorted(feature.resource_groups) if feature.resource_groups else ["N/A"],
            subscriptions=sorted(feature.subscriptions) if feature.subscriptions else ["N/A"],
            locations=sorted(locations) if locations else ["N/A"],
            impact_summary=dict(impact_counter),
            recommendation_tasks=all_tasks,
        )
        logger.debug("Generated Feature description for '%s'", feature.name)
        return rendered

    def generate_feature_acceptance_criteria(self, feature: Feature) -> str:
        """Generate acceptance criteria for a Feature."""
        all_tasks = [t for s in feature.user_stories for t in s.tasks]
        lines: list[str] = [
            f"<p>All recommendations for <strong>{feature.resource_type}</strong> are completed. "
            "Resources validated against APRL checks.</p>",
        ]
        if all_tasks:
            lines.append("<p><strong>Recommendations to complete:</strong></p>")
            lines.append("<ul>")
            for task in all_tasks:
                lines.append(
                    f"<li>{task.title} [{task.impact}] &mdash; "
                    f"{len(task.affected_resources)} resource(s)</li>"
                )
            lines.append("</ul>")
        logger.debug("Generated Feature acceptance criteria for '%s'", feature.name)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # User Story
    # ------------------------------------------------------------------

    def generate_story_description(self, story: UserStory) -> str:
        """Render the consolidated User Story description from *user_story.md.j2*."""
        resource_type = story.feature.resource_type if story.feature else "Unknown"
        template = self._env.get_template("user_story.md.j2")
        rendered = template.render(
            title=story.title,
            resource_type=resource_type,
            impact=story.impact,
            waf_pillars=sorted(story.waf_pillars) if story.waf_pillars else ["N/A"],
            source=story.source or "APRL",
            resource_count=story.resource_count,
            tasks=story.tasks,
        )
        logger.debug("Generated UserStory description for '%s'", story.title)
        return rendered

    def generate_story_acceptance_criteria(self, story: UserStory) -> str:
        """Generate acceptance criteria for a consolidated User Story."""
        lines: list[str] = [
            "<ul>",
            f"<li>All {len(story.tasks)} recommendation(s) have been implemented</li>",
            f"<li>All {story.resource_count} affected resource(s) pass APRL compliance checks</li>",
        ]

        if story.tasks:
            lines.append("</ul>")
            lines.append("<p><strong>Per-recommendation verification:</strong></p>")
            lines.append("<ul>")
            for task in story.tasks:
                lines.append(
                    f"<li><strong>{task.title}</strong> [{task.impact}] &mdash; "
                    f"{len(task.affected_resources)} resource(s) remediated"
                    f" (GUID: <code>{task.recommendation_guid}</code>)</li>"
                )

        lines.append("</ul>")
        logger.debug("Generated UserStory acceptance criteria for '%s'", story.title)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Task
    # ------------------------------------------------------------------

    def generate_task_description(self, task: Task) -> str:
        """Render the Task (recommendation) description from *task.md.j2*."""
        template = self._env.get_template("task.md.j2")
        rendered = template.render(
            title=task.title,
            long_description=task.long_description or "No detailed description available.",
            impact=task.impact,
            waf_pillar=task.waf_pillar or "N/A",
            recommendation_control=task.recommendation_control,
            potential_benefit=task.potential_benefit or "N/A",
            source=task.source or "APRL",
            recommendation_guid=task.recommendation_guid,
            learn_more_link=task.learn_more_link or "N/A",
            advisor_metadata=task.advisor_metadata,
            affected_resources=task.affected_resources,
        )
        logger.debug("Generated Task description for '%s'", task.title)
        return rendered

    def generate_task_acceptance_criteria(self, task: Task) -> str:
        """Generate acceptance criteria for a Task (recommendation)."""
        lines: list[str] = [
            "<ul>",
            f"<li>All {len(task.affected_resources)} resource(s) have been remediated "
            f"for recommendation <strong>{task.title}</strong></li>",
            f"<li>APRL check <code>{task.recommendation_guid}</code> passes for all resources</li>",
        ]

        if task.affected_resources:
            lines.append("</ul>")
            lines.append("<p><strong>Per-resource verification:</strong></p>")
            lines.append("<ul>")
            for res in task.affected_resources:
                lines.append(
                    f"<li>Resource <strong>{res.resource_name}</strong> in "
                    f"<code>{res.resource_group}</code> is compliant</li>"
                )

        if task.learn_more_link:
            lines.append(
                f"<li>Changes verified via <a href=\"{task.learn_more_link}\">{task.learn_more_link}</a></li>"
            )

        if task.source and task.source != "APRL":
            lines.append(f"<li>Source: <strong>{task.source}</strong></li>")

        advisor_meta = task.advisor_metadata or {}
        if advisor_meta.get("advisor_retirement_date"):
            lines.append(
                f"<li>⚠️ Retirement date: <strong>{advisor_meta['advisor_retirement_date']}</strong></li>"
            )
        if advisor_meta.get("advisor_retiring_feature"):
            lines.append(
                f"<li>Retiring feature: {advisor_meta['advisor_retiring_feature']}</li>"
            )

        lines.append("</ul>")
        logger.debug("Generated Task acceptance criteria for '%s'", task.title)
        return "\n".join(lines)
