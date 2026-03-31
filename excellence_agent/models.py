"""
Dataclass models for the ExcellenceAgent ADO work-item hierarchy.

Hierarchy: Epic → Feature → UserStory → Task

Data sourced from APRL v2 (Azure Proactive Resiliency Library) Excel reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class Task:
    """An individual Azure resource that needs remediation."""

    resource_name: str
    resource_id: str  # full ARM ID
    resource_group: str
    subscription_id: str
    location: str
    validation_status: str = ""
    custom_fields: Dict[str, str] = field(default_factory=dict)
    notes: str = ""
    check_name: str = ""
    source: str = ""  # "APRL", "Advisor", or "APRL & Advisor"
    advisor_metadata: Dict[str, str] = field(default_factory=dict)  # retirement_date, retiring_feature, etc.

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource_name": self.resource_name,
            "resource_id": self.resource_id,
            "resource_group": self.resource_group,
            "subscription_id": self.subscription_id,
            "location": self.location,
            "validation_status": self.validation_status,
            "custom_fields": dict(self.custom_fields),
            "notes": self.notes,
            "check_name": self.check_name,
            "source": self.source,
            "advisor_metadata": dict(self.advisor_metadata),
        }


@dataclass
class UserStory:
    """A deduplicated APRL recommendation."""

    title: str
    recommendation_guid: str
    impact: str  # High / Medium / Low
    recommendation_control: str
    potential_benefit: str = ""
    learn_more_link: str = ""
    long_description: str = ""
    waf_pillar: str = ""
    category: str = ""
    source: str = ""
    advisor_metadata: Dict[str, str] = field(default_factory=dict)
    feature: Optional[Feature] = field(default=None, repr=False)
    tasks: List[Task] = field(default_factory=list)

    @property
    def priority(self) -> int:
        """Map Impact to integer: High=1, Medium=2, Low=3."""
        return {"High": 1, "Medium": 2, "Low": 3}.get(self.impact, 3)

    def add_task(self, task: Task) -> None:
        self.tasks.append(task)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "recommendation_guid": self.recommendation_guid,
            "impact": self.impact,
            "priority": self.priority,
            "recommendation_control": self.recommendation_control,
            "potential_benefit": self.potential_benefit,
            "learn_more_link": self.learn_more_link,
            "long_description": self.long_description,
            "waf_pillar": self.waf_pillar,
            "category": self.category,
            "source": self.source,
            "advisor_metadata": dict(self.advisor_metadata),
            "tasks": [t.to_dict() for t in self.tasks],
        }


@dataclass
class Feature:
    """An Azure resource type within an Epic (e.g. 'microsoft.network/networkwatchers')."""

    name: str
    resource_type: str
    epic: Optional[Epic] = field(default=None, repr=False)
    user_stories: List[UserStory] = field(default_factory=list)
    resource_groups: Set[str] = field(default_factory=set)
    subscriptions: Set[str] = field(default_factory=set)
    resource_count: int = 0

    def add_user_story(self, story: UserStory) -> None:
        story.feature = self
        self.user_stories.append(story)

    def total_tasks(self) -> int:
        return sum(len(s.tasks) for s in self.user_stories)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "resource_type": self.resource_type,
            "resource_groups": sorted(self.resource_groups),
            "subscriptions": sorted(self.subscriptions),
            "resource_count": self.resource_count,
            "user_stories": [s.to_dict() for s in self.user_stories],
            "total_tasks": self.total_tasks(),
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

    def add_feature(self, feature: Feature) -> None:
        feature.epic = self
        self.features.append(feature)

    def total_stories(self) -> int:
        return sum(len(f.user_stories) for f in self.features)

    def total_tasks(self) -> int:
        return sum(f.total_tasks() for f in self.features)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "total_resource_count": self.total_resource_count,
            "waf_pillars": sorted(self.waf_pillars),
            "impact_summary": dict(self.impact_summary),
            "features": [f.to_dict() for f in self.features],
            "total_stories": self.total_stories(),
            "total_tasks": self.total_tasks(),
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

    def all_tasks(self) -> List[Task]:
        return [t for s in self.all_stories() for t in s.tasks]

    def summary_stats(self) -> Dict[str, int]:
        return {
            "epics": len(self.epics),
            "features": len(self.all_features()),
            "user_stories": len(self.all_stories()),
            "tasks": len(self.all_tasks()),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "epics": [e.to_dict() for e in self.epics],
            "summary": self.summary_stats(),
        }
