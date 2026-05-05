"""App-centric hierarchy builder (v2) — groups a mapped DataFrame into
the EpicV2(App) → FeatureV2(Category) → UserStoryV2(ResourceType per run) tree.

Used by the incremental pipeline for flexible story creation.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Callable, Dict, Optional, Set

import pandas as pd

from excellence_agent.ingest.batch_parser import COL_APP_NAME
from excellence_agent.ingest.schema import (
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
    AffectedResource,
    Recommendation,
    normalize_resource_type,
)
from excellence_agent.models_v2 import (
    EpicV2,
    FeatureV2,
    UserStoryV2,
    WorkItemHierarchyV2,
)

logger = logging.getLogger(__name__)

# Column added by ResourceMapper
COL_MATRIX_CATEGORY = "MatrixCategory"

# Normalised resource type column (added during build)
_COL_RT_NORM = "_rt_norm"

# Impact ordering
_IMPACT_ORDER = {"High": 1, "Medium": 2, "Low": 3}


def _safe_str(val: object) -> str:
    """Return *val* as a stripped string, or '' if NaN/None."""
    if pd.isna(val):
        return ""
    return str(val).strip()


def _friendly_resource_name(resource_type: str) -> str:
    """Turn an ARM resource type into a human-friendly name."""
    if not resource_type:
        return "Unknown Resource"
    segment = resource_type.rsplit("/", 1)[-1]
    spaced = ""
    for i, ch in enumerate(segment):
        if ch.isupper() and i > 0 and segment[i - 1].islower():
            spaced += " "
        spaced += ch
    return spaced.replace("_", " ").title()


def _best_display_variant(resource_types: pd.Series) -> str:
    """Pick the resource type variant with the most camelCase info for display."""
    variants = resource_types.dropna().unique()
    if len(variants) == 0:
        return ""
    return max(variants, key=lambda v: sum(1 for c in str(v) if c.isupper()))


class HierarchyBuilderV2:
    """Builds the app-centric hierarchy from a mapped + filtered DataFrame.

    Expected columns:
        - COL_APP_NAME (_app_name): application name
        - COL_MATRIX_CATEGORY (MatrixCategory): domain category
        - Standard APRL columns (Resource Type, Recommendation Title, etc.)

    The run_number_fn callback is used to get the run number for each
    (app_name, resource_type) combination.
    """

    def __init__(
        self,
        category_descriptions: Optional[Dict[str, str]] = None,
        run_number_fn: Optional[Callable[[str, str], int]] = None,
    ) -> None:
        """
        Parameters
        ----------
        category_descriptions
            Map from category key to description text.
        run_number_fn
            Callable(app_name, resource_type_norm) → int.
            Returns the run number to assign. If None, defaults to 1.
        """
        self._category_descriptions = category_descriptions or {}
        self._run_number_fn = run_number_fn or (lambda app, rt: 1)

    def build(self, df: pd.DataFrame) -> WorkItemHierarchyV2:
        """Build the full app-centric hierarchy.

        Grouping logic:
        1. Group by _app_name → Epics
        2. Within each app, group by MatrixCategory → Features
        3. Within each category, group by normalised Resource Type → UserStories
        4. Each UserStory gets a run number from run_number_fn
        """
        if COL_MATRIX_CATEGORY not in df.columns:
            raise ValueError(
                f"DataFrame is missing '{COL_MATRIX_CATEGORY}'. "
                "Run ResourceMapper before building the hierarchy."
            )
        if COL_APP_NAME not in df.columns:
            raise ValueError(
                f"DataFrame is missing '{COL_APP_NAME}'. "
                "Use batch_parser or add _app_name column before building."
            )

        df = df.copy()
        df[_COL_RT_NORM] = df[COL_RESOURCE_TYPE].apply(
            lambda v: normalize_resource_type(str(v)) if pd.notna(v) else ""
        )

        hierarchy = WorkItemHierarchyV2()

        for app_name, app_df in df.groupby(COL_APP_NAME, sort=False):
            epic = self._build_epic(str(app_name), app_df)
            hierarchy.add_epic(epic)

        hierarchy.epics.sort(key=lambda e: e.app_name.lower())

        logger.info(
            "Built v2 hierarchy: %d epics (apps), %d features (categories), "
            "%d stories, %d recommendations",
            len(hierarchy.epics),
            len(hierarchy.all_features()),
            len(hierarchy.all_stories()),
            len(hierarchy.all_recommendations()),
        )
        return hierarchy

    def _build_epic(self, app_name: str, app_df: pd.DataFrame) -> EpicV2:
        epic = EpicV2(app_name=app_name)

        impact_counter: Counter[str] = Counter()
        waf_pillars: Set[str] = set()
        total_resources = 0

        for category, cat_df in app_df.groupby(COL_MATRIX_CATEGORY, sort=False):
            feature = self._build_feature(str(category), cat_df, app_name)
            epic.add_feature(feature)
            total_resources += feature.resource_count

            for story in feature.user_stories:
                for rec in story.recommendations:
                    impact_counter[rec.impact] += 1
                    if rec.waf_pillar:
                        waf_pillars.add(rec.waf_pillar)

        epic.total_resource_count = total_resources
        epic.impact_summary = dict(impact_counter)
        epic.waf_pillars = waf_pillars

        # Sort Features alphabetically
        epic.features.sort(key=lambda f: f.category_name.lower())

        return epic

    def _build_feature(
        self, category: str, cat_df: pd.DataFrame, app_name: str
    ) -> FeatureV2:
        feature = FeatureV2(
            category_key=category.lower(),
            category_name=category,
            description=self._category_descriptions.get(category, ""),
        )

        resource_groups: Set[str] = set()
        subscriptions: Set[str] = set()
        resource_types: Set[str] = set()

        for _, row in cat_df.iterrows():
            rg = _safe_str(row.get(COL_RESOURCE_GROUP))
            sub = _safe_str(row.get(COL_SUBSCRIPTION_ID))
            rt = _safe_str(row.get(_COL_RT_NORM))
            if rg:
                resource_groups.add(rg)
            if sub:
                subscriptions.add(sub)
            if rt:
                resource_types.add(rt)

        feature.resource_groups = resource_groups
        feature.subscriptions = subscriptions
        feature.resource_types = resource_types

        unique_ids = cat_df[COL_ID].dropna().unique()
        feature.resource_count = len(unique_ids)

        # Build one story per resource type within this category
        for rt_norm, rt_df in cat_df.groupby(_COL_RT_NORM, sort=False):
            story = self._build_story(str(rt_norm), rt_df, app_name)
            feature.add_user_story(story)

        # Sort stories by impact then title
        feature.user_stories.sort(
            key=lambda s: (_IMPACT_ORDER.get(s.impact, 99), s.title.lower())
        )

        return feature

    def _build_story(
        self, rt_norm: str, rt_df: pd.DataFrame, app_name: str
    ) -> UserStoryV2:
        """Build a UserStory for a single resource type within a run."""
        display_variant = _best_display_variant(rt_df[COL_RESOURCE_TYPE])
        friendly = (
            _friendly_resource_name(display_variant)
            if display_variant
            else _friendly_resource_name(rt_norm)
        )

        run_number = self._run_number_fn(app_name, rt_norm)

        waf_pillars: Set[str] = set()
        highest_impact = "Low"
        categories: Set[str] = set()
        sources: Set[str] = set()
        recs: list[Recommendation] = []

        for (rec_title, guid), rec_df in rt_df.groupby(
            [COL_RECOMMENDATION_TITLE, COL_GUID], sort=False
        ):
            rec = self._build_recommendation(_safe_str(rec_title), _safe_str(guid), rec_df)
            recs.append(rec)

            if rec.waf_pillar:
                waf_pillars.add(rec.waf_pillar)
            if rec.category:
                categories.add(rec.category)
            if rec.source:
                sources.add(rec.source)
            if _IMPACT_ORDER.get(rec.impact, 99) < _IMPACT_ORDER.get(highest_impact, 99):
                highest_impact = rec.impact

        # Source label
        if sources == {"APRL"} or not sources:
            combined_source = "APRL"
        elif sources == {"Advisor"}:
            combined_source = "Advisor"
        else:
            combined_source = "APRL & Advisor"

        unique_ids = rt_df[COL_ID].dropna().unique()

        story = UserStoryV2(
            title=f"{friendly} - Recommendations {run_number}",
            resource_type=rt_norm,
            resource_type_display=friendly,
            run_number=run_number,
            impact=highest_impact,
            category=", ".join(sorted(categories)) if categories else "",
            source=combined_source,
            waf_pillars=waf_pillars,
            resource_count=len(unique_ids),
        )

        # Sort recommendations by impact then title
        recs.sort(
            key=lambda r: (
                _IMPACT_ORDER.get(r.impact, 99),
                r.title.lower(),
                r.recommendation_guid.lower(),
            )
        )
        for rec in recs:
            story.add_recommendation(rec)

        return story

    def _build_recommendation(
        self, rec_title: str, guid: str, rec_df: pd.DataFrame
    ) -> Recommendation:
        """Build a Recommendation with its affected resources."""
        first_row = rec_df.iloc[0]

        source_val = _safe_str(first_row.get("_Source")) or _safe_str(
            first_row.get(COL_SOURCE)
        )

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

        affected: list[AffectedResource] = []
        for _, row in rec_df.iterrows():
            custom_fields: Dict[str, str] = {}
            for col in (COL_CUSTOM1, COL_CUSTOM2, COL_CUSTOM3, COL_CUSTOM4, COL_CUSTOM5):
                val = _safe_str(row.get(col))
                if val:
                    custom_fields[col] = val

            affected.append(
                AffectedResource(
                    resource_name=_safe_str(row.get(COL_NAME)),
                    resource_id=_safe_str(row.get(COL_ID)),
                    resource_group=_safe_str(row.get(COL_RESOURCE_GROUP)),
                    subscription_id=_safe_str(row.get(COL_SUBSCRIPTION_ID)),
                    location=_safe_str(row.get(COL_LOCATION)),
                    validation_status=_safe_str(row.get(COL_REVIEW_STATUS)),
                    notes=_safe_str(row.get(COL_NOTES)),
                    check_name=_safe_str(row.get(COL_CHECK_NAME)),
                    custom_fields=custom_fields,
                )
            )

        affected.sort(key=lambda a: a.resource_id.lower())

        return Recommendation(
            title=rec_title,
            recommendation_guid=guid,
            impact=_safe_str(first_row.get(COL_IMPACT)),
            recommendation_control=_safe_str(first_row.get(COL_RECOMMENDATION_CONTROL)),
            potential_benefit=_safe_str(first_row.get(COL_POTENTIAL_BENEFIT)),
            learn_more_link=_safe_str(first_row.get(COL_LEARN_MORE_LINK)),
            long_description=_safe_str(first_row.get(COL_LONG_DESCRIPTION)),
            waf_pillar=_safe_str(first_row.get(COL_WAF_PILLAR)),
            category=_safe_str(first_row.get(COL_MATRIX_CATEGORY)),
            source=source_val,
            advisor_metadata=advisor_metadata,
            affected_resources=affected,
        )
