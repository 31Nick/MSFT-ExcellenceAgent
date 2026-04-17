"""
Dataclass models for the ExcellenceAgent ADO work-item hierarchy.

Hierarchy: Epic → Feature → UserStory (consolidated per resource type)

Each UserStory contains Recommendation objects (data-only, not ADO work items)
which in turn reference AffectedResource objects.

Data sourced from APRL v2 (Azure Proactive Resiliency Library) Excel reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


def normalize_resource_type(raw: str) -> str:
    """Canonical resource type key — lowercase, trimmed, slashes collapsed."""
    s = raw.strip().lower()
    while "//" in s:
        s = s.replace("//", "/")
    return s.rstrip("/")


@dataclass
class AffectedResource:
    """A single Azure resource affected by a recommendation."""

    resource_name: str
    resource_id: str
    resource_group: str
    subscription_id: str
    location: str
    validation_status: str = ""
    notes: str = ""
    check_name: str = ""
    custom_fields: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource_name": self.resource_name,
            "resource_id": self.resource_id,
            "resource_group": self.resource_group,
            "subscription_id": self.subscription_id,
            "location": self.location,
            "validation_status": self.validation_status,
            "notes": self.notes,
            "check_name": self.check_name,
            "custom_fields": dict(self.custom_fields),
        }


@dataclass
class Recommendation:
    """A specific APRL recommendation (data-only, not an ADO work item)."""

    title: str
    recommendation_guid: str
    impact: str  # High / Medium / Low
    recommendation_control: str
    potential_benefit: str = ""
    learn_more_link: str = ""
    long_description: str = ""
    waf_pillar: str = ""
    category: str = ""
    source: str = ""  # "APRL", "Advisor", or "APRL & Advisor"
    advisor_metadata: Dict[str, str] = field(default_factory=dict)
    affected_resources: List[AffectedResource] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "recommendation_guid": self.recommendation_guid,
            "impact": self.impact,
            "recommendation_control": self.recommendation_control,
            "potential_benefit": self.potential_benefit,
            "learn_more_link": self.learn_more_link,
            "long_description": self.long_description,
            "waf_pillar": self.waf_pillar,
            "category": self.category,
            "source": self.source,
            "advisor_metadata": dict(self.advisor_metadata),
            "affected_resources": [r.to_dict() for r in self.affected_resources],
        }


@dataclass
class UserStory:
    """Consolidated APRL recommendations for a resource type."""

    title: str
    impact: str  # Highest impact among recommendations: High / Medium / Low
    category: str = ""
    source: str = ""
    waf_pillars: Set[str] = field(default_factory=set)
    resource_count: int = 0  # unique affected resources across all recommendations
    feature: Optional[Feature] = field(default=None, repr=False)
    recommendations: List[Recommendation] = field(default_factory=list)

    @property
    def priority(self) -> int:
        """Map Impact to integer: High=1, Medium=2, Low=3."""
        return {"High": 1, "Medium": 2, "Low": 3}.get(self.impact, 3)

    @property
    def stable_key(self) -> str:
        """Identity key for sync: ``story:{epic_name}:{resource_type}``."""
        if self.feature is None:
            raise ValueError("UserStory.stable_key requires a parent Feature (set via Feature.add_user_story)")
        epic_name = self.feature.epic.name.lower() if self.feature.epic else ""
        return f"story:{epic_name}:{self.feature.resource_type.lower()}"

    def add_recommendation(self, rec: Recommendation) -> None:
        self.recommendations.append(rec)

    def total_affected_resources(self) -> int:
        """Total number of individual resources across all recommendations."""
        return sum(len(r.affected_resources) for r in self.recommendations)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "impact": self.impact,
            "priority": self.priority,
            "category": self.category,
            "source": self.source,
            "waf_pillars": sorted(self.waf_pillars),
            "resource_count": self.resource_count,
            "recommendations": [r.to_dict() for r in self.recommendations],
        }


@dataclass
class Feature:
    """An Azure resource type within an Epic (e.g. 'microsoft.network/networkwatchers')."""

    name: str
    resource_type: str  # canonical (lowercase, normalized)
    epic: Optional[Epic] = field(default=None, repr=False)
    user_stories: List[UserStory] = field(default_factory=list)
    resource_groups: Set[str] = field(default_factory=set)
    subscriptions: Set[str] = field(default_factory=set)
    resource_count: int = 0

    @property
    def stable_key(self) -> str:
        """Identity key for sync: ``feature:{category}:{resource_type}``."""
        if self.epic is None:
            raise ValueError("Feature.stable_key requires a parent Epic (set via Epic.add_feature)")
        return f"feature:{self.epic.name.lower()}:{self.resource_type.lower()}"

    def add_user_story(self, story: UserStory) -> None:
        story.feature = self
        self.user_stories.append(story)

    def total_recommendations(self) -> int:
        """Total recommendations across all stories."""
        return sum(len(s.recommendations) for s in self.user_stories)

    def total_affected_resources(self) -> int:
        """Total individual resources across all stories and recommendations."""
        return sum(s.total_affected_resources() for s in self.user_stories)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "resource_type": self.resource_type,
            "resource_groups": sorted(self.resource_groups),
            "subscriptions": sorted(self.subscriptions),
            "resource_count": self.resource_count,
            "user_stories": [s.to_dict() for s in self.user_stories],
            "total_recommendations": self.total_recommendations(),
            "total_affected_resources": self.total_affected_resources(),
        }


@dataclass
class Epic:
    """A domain category from the APRL resource matrix."""

    name: str  # Observability, Platform, Compute, Data, Networking, Apps, AI
    description: str = ""
    features: List[Feature] = field(default_factory=list)
    total_resource_count: int = 0
    waf_pillars: Set[str] = field(default_factory=set)
    impact_summary: Dict[str, int] = field(default_factory=dict)

    @property
    def stable_key(self) -> str:
        """Identity key for sync: ``epic:{name}``."""
        return f"epic:{self.name.lower()}"

    def add_feature(self, feature: Feature) -> None:
        feature.epic = self
        self.features.append(feature)

    def total_stories(self) -> int:
        return sum(len(f.user_stories) for f in self.features)

    def total_recommendations(self) -> int:
        """Total recommendations across all features."""
        return sum(f.total_recommendations() for f in self.features)

    def total_affected_resources(self) -> int:
        """Total individual resources across all features."""
        return sum(f.total_affected_resources() for f in self.features)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "total_resource_count": self.total_resource_count,
            "waf_pillars": sorted(self.waf_pillars),
            "impact_summary": dict(self.impact_summary),
            "features": [f.to_dict() for f in self.features],
            "total_stories": self.total_stories(),
            "total_recommendations": self.total_recommendations(),
        }


@dataclass
class WorkItemHierarchy:
    """Top-level container holding all Epics and providing summary accessors."""

    epics: List[Epic] = field(default_factory=list)

    def add_epic(self, epic: Epic) -> None:
        self.epics.append(epic)

    def all_features(self) -> List[Feature]:
        return [f for e in self.epics for f in e.features]

    def all_stories(self) -> List[UserStory]:
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
