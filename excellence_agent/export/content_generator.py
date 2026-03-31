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
        for story in feature.user_stories:
            impact_counter[story.impact] += 1
            for task in story.tasks:
                locations.add(task.location)

        template = self._env.get_template("feature.md.j2")
        rendered = template.render(
            feature_name=feature.name,
            resource_type=feature.resource_type,
            epic_name=epic_name,
            story_count=len(feature.user_stories),
            resource_count=feature.resource_count,
            resource_groups=sorted(feature.resource_groups) if feature.resource_groups else ["N/A"],
            subscriptions=sorted(feature.subscriptions) if feature.subscriptions else ["N/A"],
            locations=sorted(locations) if locations else ["N/A"],
            impact_summary=dict(impact_counter),
            user_stories=feature.user_stories,
        )
        logger.debug("Generated Feature description for '%s'", feature.name)
        return rendered

    def generate_feature_acceptance_criteria(self, feature: Feature) -> str:
        """Generate acceptance criteria for a Feature."""
        lines: list[str] = [
            f"<p>All User Stories for <strong>{feature.resource_type}</strong> are completed. "
            "Resources validated against APRL checks.</p>",
        ]
        if feature.user_stories:
            lines.append("<p><strong>User Stories to complete:</strong></p>")
            lines.append("<ul>")
            for story in feature.user_stories:
                lines.append(
                    f"<li>{story.title} [{story.impact}] &mdash; "
                    f"{len(story.tasks)} resource(s)</li>"
                )
            lines.append("</ul>")
        logger.debug("Generated Feature acceptance criteria for '%s'", feature.name)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # User Story
    # ------------------------------------------------------------------

    def generate_story_description(self, story: UserStory) -> str:
        """Render the User Story description from *user_story.md.j2*."""
        template = self._env.get_template("user_story.md.j2")
        rendered = template.render(
            title=story.title,
            long_description=story.long_description or "No detailed description available.",
            impact=story.impact,
            waf_pillar=story.waf_pillar or "N/A",
            recommendation_control=story.recommendation_control,
            potential_benefit=story.potential_benefit or "N/A",
            source=story.source or "APRL",
            advisor_metadata=getattr(story, 'advisor_metadata', {}),
            recommendation_guid=story.recommendation_guid,
            learn_more_link=story.learn_more_link or "N/A",
            tasks=story.tasks,
        )
        logger.debug("Generated UserStory description for '%s'", story.title)
        return rendered

    def generate_story_acceptance_criteria(self, story: UserStory) -> str:
        """Generate detailed, testable acceptance criteria for a User Story."""
        task_count = len(story.tasks)
        lines: list[str] = [
            "<ul>",
            f"<li>All {task_count} resource(s) have been remediated</li>",
            f"<li>APRL check <code>{story.recommendation_guid}</code> passes for all resources</li>",
        ]

        if story.tasks:
            lines.append("</ul>")
            lines.append("<p><strong>Per-resource verification:</strong></p>")
            lines.append("<ul>")
            for task in story.tasks:
                lines.append(
                    f"<li>Resource <strong>{task.resource_name}</strong> in "
                    f"<code>{task.resource_group}</code> is compliant</li>"
                )

        if story.learn_more_link:
            lines.append(
                f"<li>Changes verified via <a href=\"{story.learn_more_link}\">{story.learn_more_link}</a></li>"
            )

        if story.source and story.source != "APRL":
            lines.append(f"<li>Source: <strong>{story.source}</strong></li>")
        advisor_meta = getattr(story, 'advisor_metadata', {})
        if advisor_meta.get("advisor_retirement_date"):
            lines.append(
                f"<li>⚠️ Retirement date: <strong>{advisor_meta['advisor_retirement_date']}</strong></li>"
            )
        if advisor_meta.get("advisor_retiring_feature"):
            lines.append(
                f"<li>Retiring feature: {advisor_meta['advisor_retiring_feature']}</li>"
            )

        lines.append("</ul>")
        logger.debug("Generated UserStory acceptance criteria for '%s'", story.title)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Task
    # ------------------------------------------------------------------

    def generate_task_description(self, task: Task, story: UserStory) -> str:
        """Render the Task description from *task.md.j2*."""
        template = self._env.get_template("task.md.j2")
        rendered = template.render(
            resource_name=task.resource_name,
            resource_id=task.resource_id,
            resource_group=task.resource_group,
            subscription_id=task.subscription_id,
            location=task.location,
            check_name=task.check_name or "",
            notes=task.notes or "",
            recommendation_title=story.title,
            learn_more_link=story.learn_more_link or "",
            source=getattr(task, 'source', '') or story.source or "APRL",
            advisor_metadata=getattr(task, 'advisor_metadata', {}),
        )
        logger.debug("Generated Task description for '%s'", task.resource_name)
        return rendered

    def generate_task_acceptance_criteria(self, task: Task, story: UserStory) -> str:
        """Generate acceptance criteria for a Task."""
        check_label = task.check_name or story.title
        lines: list[str] = [
            "<ul>",
            f"<li>Resource <strong>{task.resource_name}</strong> in <code>{task.resource_group}</code> "
            f"passes APRL check <strong>{check_label}</strong></li>",
        ]

        if task.notes:
            lines.append(f"<li>Notes addressed: {task.notes}</li>")

        if story.learn_more_link:
            lines.append(
                f"<li>Verified via <a href=\"{story.learn_more_link}\">{story.learn_more_link}</a></li>"
            )

        lines.append("</ul>")
        logger.debug("Generated Task acceptance criteria for '%s'", task.resource_name)
        return "\n".join(lines)
