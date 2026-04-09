"""
Content generator for GitHub Issue bodies.

Uses Jinja2 templates to produce GitHub Flavored Markdown for issue descriptions.
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

_DEFAULT_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates", "github")


class GitHubContentGenerator:
    """Render GitHub Issue bodies for every hierarchy level using Markdown templates."""

    def __init__(self, template_dir: str | None = None) -> None:
        self._template_dir = template_dir or _DEFAULT_TEMPLATE_DIR
        self._env = Environment(
            loader=FileSystemLoader(self._template_dir),
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        logger.debug("GitHubContentGenerator initialised with templates from %s", self._template_dir)

    # ------------------------------------------------------------------
    # Epic
    # ------------------------------------------------------------------

    def generate_epic_body(self, epic: Epic) -> str:
        """Render the Epic issue body from *epic.md.j2*."""
        all_subs: set[str] = set()
        for feat in epic.features:
            all_subs.update(feat.subscriptions)

        template = self._env.get_template("epic.md.j2")
        return template.render(
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

    # ------------------------------------------------------------------
    # Feature
    # ------------------------------------------------------------------

    def generate_feature_body(self, feature: Feature) -> str:
        """Render the Feature issue body from *feature.md.j2*."""
        epic_name = feature.epic.name if feature.epic else "Unknown"

        impact_counter: Counter[str] = Counter()
        locations: set[str] = set()
        for story in feature.user_stories:
            impact_counter[story.impact] += 1
            for task in story.tasks:
                locations.add(task.location)

        template = self._env.get_template("feature.md.j2")
        return template.render(
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

    # ------------------------------------------------------------------
    # User Story
    # ------------------------------------------------------------------

    def generate_story_body(self, story: UserStory) -> str:
        """Render the User Story issue body from *user_story.md.j2*."""
        template = self._env.get_template("user_story.md.j2")
        return template.render(
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

    # ------------------------------------------------------------------
    # Task
    # ------------------------------------------------------------------

    def generate_task_body(self, task: Task, story: UserStory) -> str:
        """Render the Task issue body from *task.md.j2*."""
        template = self._env.get_template("task.md.j2")
        return template.render(
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
