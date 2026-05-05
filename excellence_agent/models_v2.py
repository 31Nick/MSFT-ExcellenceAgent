"""
Dataclass models for the app-centric work-item hierarchy (v2).

Hierarchy: Epic (App) → Feature (Domain Category) → UserStory (Resource Type per run)

Each UserStory contains Recommendation objects (data-only, not ADO work items)
which in turn reference AffectedResource objects.

This module coexists with the original models.py which uses:
  Epic (Category) → Feature (Resource Type) → UserStory (consolidated)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from excellence_agent.models import (
    AffectedResource,
    Recommendation,
    normalize_resource_type,
)


@dataclass
class UserStoryV2:
    """APRL recommendations for a resource type within a specific run."""

    title: str  # e.g. "Storage Accounts - Recommendations 2"
    resource_type: str  # canonical lowercase, e.g. "microsoft.storage/storageaccounts"
    resource_type_display: str  # friendly name, e.g. "Storage Accounts"
    run_number: int  # 1-based run counter for this (app, resource_type)
    impact: str  # Highest impact among recommendations: High / Medium / Low
    category: str = ""  # domain category name (parent Feature name)
    source: str = ""
    waf_pillars: Set[str] = field(default_factory=set)
    resource_count: int = 0
    feature: Optional[FeatureV2] = field(default=None, repr=False)
    recommendations: List[Recommendation] = field(default_factory=list)

    @property
    def priority(self) -> int:
        """Map Impact to integer: High=1, Medium=2, Low=3."""
        return {"High": 1, "Medium": 2, "Low": 3}.get(self.impact, 3)

    @property
    def stable_key(self) -> str:
        """Identity key: ``v2:story:{app}:{category}:{resource_type}:{run}``."""
        if self.feature is None:
            raise ValueError("UserStoryV2.stable_key requires a parent FeatureV2")
        app = self.feature.epic.app_name.lower() if self.feature.epic else ""
        cat = self.feature.category_key.lower()
        return f"v2:story:{app}:{cat}:{self.resource_type.lower()}:{self.run_number}"

    def add_recommendation(self, rec: Recommendation) -> None:
        self.recommendations.append(rec)

    def total_affected_resources(self) -> int:
        """Total number of individual resources across all recommendations."""
        return sum(len(r.affected_resources) for r in self.recommendations)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "resource_type": self.resource_type,
            "resource_type_display": self.resource_type_display,
            "run_number": self.run_number,
            "impact": self.impact,
            "priority": self.priority,
            "category": self.category,
            "source": self.source,
            "waf_pillars": sorted(self.waf_pillars),
            "resource_count": self.resource_count,
            "recommendations": [r.to_dict() for r in self.recommendations],
        }


@dataclass
class FeatureV2:
    """A domain category within an application (e.g., 'Compute', 'Storage')."""

    category_key: str  # canonical key from resource_matrix.yaml
    category_name: str  # display name
    description: str = ""
    epic: Optional[EpicV2] = field(default=None, repr=False)
    user_stories: List[UserStoryV2] = field(default_factory=list)
    resource_types: Set[str] = field(default_factory=set)
    resource_groups: Set[str] = field(default_factory=set)
    subscriptions: Set[str] = field(default_factory=set)
    resource_count: int = 0

    @property
    def stable_key(self) -> str:
        """Identity key: ``v2:feature:{app}:{category}``."""
        if self.epic is None:
            raise ValueError("FeatureV2.stable_key requires a parent EpicV2")
        return f"v2:feature:{self.epic.app_name.lower()}:{self.category_key.lower()}"

    def add_user_story(self, story: UserStoryV2) -> None:
        story.feature = self
        self.user_stories.append(story)

    def total_recommendations(self) -> int:
        return sum(len(s.recommendations) for s in self.user_stories)

    def total_affected_resources(self) -> int:
        return sum(s.total_affected_resources() for s in self.user_stories)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category_key": self.category_key,
            "category_name": self.category_name,
            "description": self.description,
            "resource_types": sorted(self.resource_types),
            "resource_groups": sorted(self.resource_groups),
            "subscriptions": sorted(self.subscriptions),
            "resource_count": self.resource_count,
            "user_stories": [s.to_dict() for s in self.user_stories],
            "total_recommendations": self.total_recommendations(),
            "total_affected_resources": self.total_affected_resources(),
        }


@dataclass
class EpicV2:
    """An application — top-level grouping for ADO work items."""

    app_name: str  # canonical application name
    description: str = ""
    features: List[FeatureV2] = field(default_factory=list)
    total_resource_count: int = 0
    waf_pillars: Set[str] = field(default_factory=set)
    impact_summary: Dict[str, int] = field(default_factory=dict)
    environments: Set[str] = field(default_factory=set)

    @property
    def stable_key(self) -> str:
        """Identity key: ``v2:epic:{app_name}``."""
        return f"v2:epic:{self.app_name.lower()}"

    def add_feature(self, feature: FeatureV2) -> None:
        feature.epic = self
        self.features.append(feature)

    def total_stories(self) -> int:
        return sum(len(f.user_stories) for f in self.features)

    def total_recommendations(self) -> int:
        return sum(f.total_recommendations() for f in self.features)

    def total_affected_resources(self) -> int:
        return sum(f.total_affected_resources() for f in self.features)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "app_name": self.app_name,
            "description": self.description,
            "total_resource_count": self.total_resource_count,
            "waf_pillars": sorted(self.waf_pillars),
            "impact_summary": dict(self.impact_summary),
            "environments": sorted(self.environments),
            "features": [f.to_dict() for f in self.features],
            "total_stories": self.total_stories(),
            "total_recommendations": self.total_recommendations(),
        }


@dataclass
class WorkItemHierarchyV2:
    """Top-level container holding all app-scoped Epics."""

    epics: List[EpicV2] = field(default_factory=list)

    def add_epic(self, epic: EpicV2) -> None:
        self.epics.append(epic)

    def all_features(self) -> List[FeatureV2]:
        return [f for e in self.epics for f in e.features]

    def all_stories(self) -> List[UserStoryV2]:
        return [s for f in self.all_features() for s in f.user_stories]

    def all_recommendations(self) -> List[Recommendation]:
        return [r for s in self.all_stories() for r in s.recommendations]

    def all_affected_resources(self) -> List[AffectedResource]:
        return [ar for r in self.all_recommendations() for ar in r.affected_resources]

    def summary_stats(self) -> Dict[str, int]:
        return {
            "epics": len(self.epics),
            "features": len(self.all_features()),
            "user_stories": len(self.all_stories()),
            "recommendations": len(self.all_recommendations()),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "epics": [e.to_dict() for e in self.epics],
            "summary": self.summary_stats(),
        }
