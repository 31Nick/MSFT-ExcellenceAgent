"""Hierarchy builder — groups a mapped APRL DataFrame into the Epic→Feature→UserStory→Task tree."""

from __future__ import annotations

import logging
from collections import Counter
from typing import Dict, Optional, Set

import pandas as pd

from excellence_agent.ingest.schema import (
    COL_CATEGORY,
    COL_CHECK_NAME,
    COL_CUSTOM1,
    COL_CUSTOM2,
    COL_CUSTOM3,
    COL_CUSTOM4,
    COL_CUSTOM5,
    COL_GUID,
    COL_ID,
    COL_IMPACT,
    COL_LEARN_MORE_LINK,
    COL_LOCATION,
    COL_LONG_DESCRIPTION,
    COL_NAME,
    COL_NOTES,
    COL_POTENTIAL_BENEFIT,
    COL_RECOMMENDATION_CONTROL,
    COL_RECOMMENDATION_TITLE,
    COL_RESOURCE_GROUP,
    COL_RESOURCE_TYPE,
    COL_REVIEW_STATUS,
    COL_SOURCE,
    COL_SUBSCRIPTION_ID,
    COL_WAF_PILLAR,
)
from excellence_agent.models import (
    Epic,
    Feature,
    Task,
    UserStory,
    WorkItemHierarchy,
)

logger = logging.getLogger(__name__)

# Column added by ResourceMapper — not part of the raw APRL schema.
COL_MATRIX_CATEGORY = "MatrixCategory"

# Impact ordering for sorting (High first).
_IMPACT_ORDER = {"High": 1, "Medium": 2, "Low": 3}


def _safe_str(val: object) -> str:
    """Return *val* as a stripped string, or ``""`` if NaN/None."""
    if pd.isna(val):
        return ""
    return str(val).strip()


def _friendly_resource_name(resource_type: str) -> str:
    """Turn an ARM resource type into a human-friendly name.

    ``"microsoft.network/networkwatchers"`` → ``"Network Watchers"``
    """
    if not resource_type:
        return "Unknown Resource"
    # Take the segment after the last '/'
    segment = resource_type.rsplit("/", 1)[-1]
    # Insert spaces before uppercase letters, then title-case
    spaced = ""
    for i, ch in enumerate(segment):
        if ch.isupper() and i > 0 and segment[i - 1].islower():
            spaced += " "
        spaced += ch
    return spaced.replace("_", " ").title()


class HierarchyBuilder:
    """Builds the Epic→Feature→UserStory→Task tree from a mapped DataFrame."""

    def __init__(
        self,
        category_descriptions: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        Args:
            category_descriptions: mapping of category name → description
                                   (from resource_matrix.yaml).
        """
        self._category_descriptions = category_descriptions or {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self, df: pd.DataFrame) -> WorkItemHierarchy:
        """Build the full hierarchy from the mapped DataFrame.

        The DataFrame **must** have a ``MatrixCategory`` column (added by
        :class:`ResourceMapper`).

        Grouping logic:

        1. Group rows by *MatrixCategory* → creates **Epics**.
        2. Within each Epic, group by *Resource Type* → creates **Features**.
        3. Within each Feature, group by *(Recommendation Title, Guid)* →
           creates **UserStories** (deduplication!).
        4. Each row becomes a **Task** under its UserStory.
        """
        if COL_MATRIX_CATEGORY not in df.columns:
            raise ValueError(
                f"DataFrame is missing the '{COL_MATRIX_CATEGORY}' column. "
                "Run ResourceMapper before building the hierarchy."
            )

        hierarchy = WorkItemHierarchy()

        for category, category_df in df.groupby(COL_MATRIX_CATEGORY, sort=False):
            epic = self._build_epic(str(category), category_df)
            hierarchy.add_epic(epic)

        # Sort Epics alphabetically by name.
        hierarchy.epics.sort(key=lambda e: e.name.lower())

        logger.info(
            "Built hierarchy: %d epics, %d features, %d stories, %d tasks",
            len(hierarchy.epics),
            len(hierarchy.all_features()),
            len(hierarchy.all_stories()),
            len(hierarchy.all_tasks()),
        )
        return hierarchy

    # ------------------------------------------------------------------
    # Internal builders
    # ------------------------------------------------------------------

    def _build_epic(self, category: str, category_df: pd.DataFrame) -> Epic:
        epic = Epic(
            name=category,
            description=self._category_descriptions.get(category, ""),
        )

        impact_counter: Counter[str] = Counter()
        waf_pillars: Set[str] = set()
        total_resources = 0

        for resource_type, rt_df in category_df.groupby(COL_RESOURCE_TYPE, sort=False):
            feature = self._build_feature(str(resource_type), rt_df)
            epic.add_feature(feature)
            total_resources += feature.resource_count

            for story in feature.user_stories:
                impact_counter[story.impact] += 1
                if story.waf_pillar:
                    waf_pillars.add(story.waf_pillar)

        epic.total_resource_count = total_resources
        epic.impact_summary = dict(impact_counter)
        epic.waf_pillars = waf_pillars

        # Sort Features by resource count descending.
        epic.features.sort(key=lambda f: f.resource_count, reverse=True)

        return epic

    def _build_feature(self, resource_type: str, rt_df: pd.DataFrame) -> Feature:
        feature = Feature(
            name=_friendly_resource_name(resource_type),
            resource_type=resource_type,
        )

        resource_groups: Set[str] = set()
        subscriptions: Set[str] = set()

        for (rec_title, guid), story_df in rt_df.groupby(
            [COL_RECOMMENDATION_TITLE, COL_GUID], sort=False
        ):
            story = self._build_user_story(
                _safe_str(rec_title), _safe_str(guid), story_df
            )
            feature.add_user_story(story)

            for _, row in story_df.iterrows():
                rg = _safe_str(row.get(COL_RESOURCE_GROUP))
                sub = _safe_str(row.get(COL_SUBSCRIPTION_ID))
                if rg:
                    resource_groups.add(rg)
                if sub:
                    subscriptions.add(sub)

        feature.resource_groups = resource_groups
        feature.subscriptions = subscriptions
        feature.resource_count = len(rt_df)

        # Sort UserStories by priority (High first).
        feature.user_stories.sort(key=lambda s: _IMPACT_ORDER.get(s.impact, 99))

        return feature

    def _build_user_story(
        self, rec_title: str, guid: str, story_df: pd.DataFrame
    ) -> UserStory:
        first_row = story_df.iloc[0]

        # Use _Source from cross-referencer if available, else fallback to APRL Source column
        source_val = _safe_str(first_row.get("_Source")) or _safe_str(first_row.get(COL_SOURCE))

        advisor_metadata: Dict[str, str] = {}
        for col_name in (
            "advisor_retirement_date",
            "advisor_retiring_feature",
            "advisor_subscription_name",
            "advisor_updated_date",
            "advisor_cost_implications",
        ):
            val = _safe_str(first_row.get(col_name))
            if val:
                advisor_metadata[col_name] = val

        story = UserStory(
            title=rec_title,
            recommendation_guid=guid,
            impact=_safe_str(first_row.get(COL_IMPACT)),
            recommendation_control=_safe_str(first_row.get(COL_RECOMMENDATION_CONTROL)),
            potential_benefit=_safe_str(first_row.get(COL_POTENTIAL_BENEFIT)),
            learn_more_link=_safe_str(first_row.get(COL_LEARN_MORE_LINK)),
            long_description=_safe_str(first_row.get(COL_LONG_DESCRIPTION)),
            waf_pillar=_safe_str(first_row.get(COL_WAF_PILLAR)),
            category=_safe_str(first_row.get(COL_CATEGORY)),
            source=source_val,
            advisor_metadata=advisor_metadata,
        )

        for _, row in story_df.iterrows():
            task = self._build_task(row)
            story.add_task(task)

        return story

    def _build_task(self, row: pd.Series) -> Task:
        custom_fields: Dict[str, str] = {}
        for col in (COL_CUSTOM1, COL_CUSTOM2, COL_CUSTOM3, COL_CUSTOM4, COL_CUSTOM5):
            val = _safe_str(row.get(col))
            if val:
                custom_fields[col] = val

        source_val = _safe_str(row.get("_Source")) or _safe_str(row.get(COL_SOURCE))

        advisor_metadata: Dict[str, str] = {}
        for col_name in (
            "advisor_retirement_date",
            "advisor_retiring_feature",
            "advisor_subscription_name",
            "advisor_updated_date",
            "advisor_cost_implications",
        ):
            val = _safe_str(row.get(col_name))
            if val:
                advisor_metadata[col_name] = val

        return Task(
            resource_name=_safe_str(row.get(COL_NAME)),
            resource_id=_safe_str(row.get(COL_ID)),
            resource_group=_safe_str(row.get(COL_RESOURCE_GROUP)),
            subscription_id=_safe_str(row.get(COL_SUBSCRIPTION_ID)),
            location=_safe_str(row.get(COL_LOCATION)),
            validation_status=_safe_str(row.get(COL_REVIEW_STATUS)),
            custom_fields=custom_fields,
            notes=_safe_str(row.get(COL_NOTES)),
            check_name=_safe_str(row.get(COL_CHECK_NAME)),
            source=source_val,
            advisor_metadata=advisor_metadata,
        )
