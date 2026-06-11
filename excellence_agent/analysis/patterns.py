"""Cross-epic pattern detection on a built work-item hierarchy."""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set

from excellence_agent.models import WorkItemHierarchy

logger = logging.getLogger(__name__)

# Threshold: a recommendation control must span at least this many epics
# to be flagged as cross-epic.
_MIN_CROSS_EPIC_COUNT = 2

# A feature/epic is "high-impact heavy" if this fraction of its stories are High.
_HIGH_IMPACT_THRESHOLD = 0.6

# A resource group must appear in at least this many features to be a hotspot.
_MIN_FEATURE_COUNT_FOR_HOTSPOT = 3

# A WAF pillar must appear in at least this many epics to be flagged.
_MIN_EPIC_COUNT_FOR_WAF = 2


@dataclass
class Pattern:
    """A detected cross-cutting pattern in the hierarchy."""

    name: str
    description: str
    affected_epics: List[str] = field(default_factory=list)
    affected_features: List[str] = field(default_factory=list)
    story_count: int = 0
    task_count: int = 0
    recommendation_control: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "affected_epics": list(self.affected_epics),
            "affected_features": list(self.affected_features),
            "story_count": self.story_count,
            "recommendation_count": self.task_count,
            "recommendation_control": self.recommendation_control,
        }


class PatternDetector:
    """Detect cross-cutting patterns across an :class:`WorkItemHierarchy`."""

    def detect(self, hierarchy: WorkItemHierarchy) -> List[Pattern]:
        """Return all detected :class:`Pattern` instances."""
        patterns: List[Pattern] = []
        patterns.extend(self._cross_epic_controls(hierarchy))
        patterns.extend(self._high_impact_clusters(hierarchy))
        patterns.extend(self._resource_group_hotspots(hierarchy))
        patterns.extend(self._waf_pillar_themes(hierarchy))

        logger.info("Detected %d patterns across hierarchy", len(patterns))
        return patterns

    # ------------------------------------------------------------------
    # 1. Cross-epic recommendation controls
    # ------------------------------------------------------------------

    def _cross_epic_controls(self, hierarchy: WorkItemHierarchy) -> List[Pattern]:
        """Same Recommendation Control appearing across multiple Epics."""
        control_epics: Dict[str, Set[str]] = defaultdict(set)
        control_features: Dict[str, Set[str]] = defaultdict(set)
        control_stories: Counter[str] = Counter()
        control_tasks: Counter[str] = Counter()

        for epic in hierarchy.epics:
            for feature in epic.features:
                for story in feature.user_stories:
                    for rec in story.recommendations:
                        ctrl = rec.recommendation_control
                        if not ctrl:
                            continue
                        control_epics[ctrl].add(epic.name)
                        control_features[ctrl].add(feature.name)
                        control_stories[ctrl] += 1
                        control_tasks[ctrl] += len(rec.affected_resources)

        patterns: List[Pattern] = []
        for ctrl, epics in sorted(control_epics.items()):
            if len(epics) >= _MIN_CROSS_EPIC_COUNT:
                patterns.append(
                    Pattern(
                        name=f"Cross-Epic Control: {ctrl}",
                        description=(
                            f"Recommendation control '{ctrl}' spans "
                            f"{len(epics)} epics — consider a shared initiative."
                        ),
                        affected_epics=sorted(epics),
                        affected_features=sorted(control_features[ctrl]),
                        story_count=control_stories[ctrl],
                        task_count=control_tasks[ctrl],
                        recommendation_control=ctrl,
                    )
                )
        return patterns

    # ------------------------------------------------------------------
    # 2. High-impact clusters
    # ------------------------------------------------------------------

    def _high_impact_clusters(self, hierarchy: WorkItemHierarchy) -> List[Pattern]:
        """Features or Epics with disproportionately many High-impact recommendations."""
        patterns: List[Pattern] = []

        for epic in hierarchy.epics:
            for feature in epic.features:
                all_recs = [r for s in feature.user_stories for r in s.recommendations]
                if not all_recs:
                    continue
                high_count = sum(1 for r in all_recs if r.impact == "High")
                ratio = high_count / len(all_recs)
                if ratio >= _HIGH_IMPACT_THRESHOLD and high_count >= 2:
                    resource_count = sum(
                        len(r.affected_resources) for r in all_recs if r.impact == "High"
                    )
                    patterns.append(
                        Pattern(
                            name=f"High-Impact Cluster: {feature.name}",
                            description=(
                                f"{high_count}/{len(all_recs)} recommendations "
                                f"({ratio:.0%}) in '{feature.name}' "
                                f"(epic '{epic.name}') are High impact."
                            ),
                            affected_epics=[epic.name],
                            affected_features=[feature.name],
                            story_count=high_count,
                            task_count=resource_count,
                            recommendation_control="",
                        )
                    )

        return patterns

    # ------------------------------------------------------------------
    # 3. Single-resource-group hotspots
    # ------------------------------------------------------------------

    def _resource_group_hotspots(self, hierarchy: WorkItemHierarchy) -> List[Pattern]:
        """Resource groups appearing across many Features."""
        rg_features: Dict[str, Set[str]] = defaultdict(set)
        rg_epics: Dict[str, Set[str]] = defaultdict(set)
        rg_stories: Counter[str] = Counter()
        rg_tasks: Counter[str] = Counter()

        for epic in hierarchy.epics:
            for feature in epic.features:
                for rg in feature.resource_groups:
                    if not rg:
                        continue
                    rg_features[rg].add(feature.name)
                    rg_epics[rg].add(epic.name)
                    rg_stories[rg] += len(feature.user_stories)
                    rg_tasks[rg] += feature.total_recommendations()

        patterns: List[Pattern] = []
        for rg, features in sorted(rg_features.items()):
            if len(features) >= _MIN_FEATURE_COUNT_FOR_HOTSPOT:
                patterns.append(
                    Pattern(
                        name=f"Resource Group Hotspot: {rg}",
                        description=(
                            f"Resource group '{rg}' appears in "
                            f"{len(features)} features across "
                            f"{len(rg_epics[rg])} epic(s) — "
                            f"centralised remediation may be more efficient."
                        ),
                        affected_epics=sorted(rg_epics[rg]),
                        affected_features=sorted(features),
                        story_count=rg_stories[rg],
                        task_count=rg_tasks[rg],
                        recommendation_control="",
                    )
                )
        return patterns

    # ------------------------------------------------------------------
    # 4. Common WAF pillar themes
    # ------------------------------------------------------------------

    def _waf_pillar_themes(self, hierarchy: WorkItemHierarchy) -> List[Pattern]:
        """WAF pillars that dominate across Epics."""
        pillar_epics: Dict[str, Set[str]] = defaultdict(set)
        pillar_features: Dict[str, Set[str]] = defaultdict(set)
        pillar_stories: Counter[str] = Counter()
        pillar_tasks: Counter[str] = Counter()

        for epic in hierarchy.epics:
            for feature in epic.features:
                for story in feature.user_stories:
                    for rec in story.recommendations:
                        pillar = rec.waf_pillar
                        if not pillar:
                            continue
                        pillar_epics[pillar].add(epic.name)
                        pillar_features[pillar].add(feature.name)
                        pillar_stories[pillar] += 1
                        pillar_tasks[pillar] += len(rec.affected_resources)

        patterns: List[Pattern] = []
        for pillar, epics in sorted(pillar_epics.items()):
            if len(epics) >= _MIN_EPIC_COUNT_FOR_WAF:
                patterns.append(
                    Pattern(
                        name=f"WAF Pillar Theme: {pillar}",
                        description=(
                            f"WAF pillar '{pillar}' appears across "
                            f"{len(epics)} epics with "
                            f"{pillar_stories[pillar]} stories — "
                            f"consider a cross-cutting {pillar.lower()} workstream."
                        ),
                        affected_epics=sorted(epics),
                        affected_features=sorted(pillar_features[pillar]),
                        story_count=pillar_stories[pillar],
                        task_count=pillar_tasks[pillar],
                        recommendation_control="",
                    )
                )
        return patterns
