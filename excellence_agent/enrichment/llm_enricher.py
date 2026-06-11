"""
Optional Azure OpenAI enrichment for the ExcellenceAgent.

Entirely opt-in — the agent works fully without it.  When configured,
LLMEnricher can generate richer acceptance criteria, remediation steps,
and semantic grouping suggestions via the Azure OpenAI chat completions API.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from openai import AzureOpenAI, APIError, APITimeoutError, RateLimitError

from excellence_agent.config import AzureOpenAIConfig
from excellence_agent.models import Recommendation, UserStory, WorkItemHierarchy

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an Azure cloud engineer specializing in WAF (Well-Architected Framework) "
    "alignment and Azure proactive resiliency best practices. You produce clear, "
    "actionable, and technically precise output."
)

ACCEPTANCE_CRITERIA_PROMPT = """\
Given the following Azure recommendation, generate detailed and testable acceptance \
criteria in checkbox markdown format (- [ ] …).

**Recommendation:** {title}
**Description:** {long_description}
**Recommendation Control:** {recommendation_control}
**Learn More:** {learn_more_link}

Requirements for the acceptance criteria:
- Each criterion must be independently verifiable.
- Include specific Azure resource settings, CLI commands, or portal paths where possible.
- Cover both the positive case (resource is compliant) and any edge cases.
- Keep the list concise (5-10 items).
"""

REMEDIATION_STEPS_PROMPT = """\
Provide step-by-step remediation instructions for the following non-compliant Azure \
resource.

**Resource Name:** {resource_name}
**ARM Resource ID:** {resource_id}
**Resource Type:** {resource_type}
**Location:** {location}
**Recommendation:** {recommendation_title}
**Recommendation Description:** {long_description}
**Recommendation Control:** {recommendation_control}

Instructions:
- Number each step.
- Include Azure CLI / PowerShell commands or portal navigation paths.
- Note any prerequisites (permissions, dependencies).
- Warn about potential downtime or breaking changes.
"""

SEMANTIC_GROUPING_PROMPT = """\
Analyse the following list of Azure recommendation titles and descriptions. Suggest \
non-obvious semantic groupings that go beyond simple resource-type matching.

{stories_block}

Return a JSON array where each element has:
- "group_name": short descriptive name
- "description": one-sentence explanation of the grouping rationale
- "story_titles": list of story titles that belong to this group

Focus on cross-cutting concerns such as encryption-at-rest, network isolation, \
monitoring gaps, identity hardening, or cost optimisation patterns.
"""


class LLMEnricher:
    """Azure OpenAI enrichment for work-item hierarchies."""

    def __init__(self, config: AzureOpenAIConfig, *, rate_limit_delay: float = 0.5):
        """Initialise the Azure OpenAI client.

        Parameters
        ----------
        config:
            An ``AzureOpenAIConfig`` instance with endpoint, api_key, and deployment.
        rate_limit_delay:
            Seconds to sleep between API calls to avoid throttling.

        Raises
        ------
        ValueError
            If ``config`` is missing required fields (endpoint, api_key, deployment).
        """
        if not config.is_configured:
            raise ValueError(
                "AzureOpenAIConfig is incomplete — endpoint, api_key, and deployment "
                "are all required."
            )

        self._client = AzureOpenAI(
            azure_endpoint=config.endpoint,
            api_key=config.api_key,
            api_version=config.api_version,
        )
        self._deployment = config.deployment
        self._rate_limit_delay = rate_limit_delay
        self._configured = True

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_available(self) -> bool:
        """Return True when the client is configured and ready."""
        return self._configured

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _chat(self, user_prompt: str, *, temperature: float = 0.3) -> Optional[str]:
        """Send a chat completion request and return the assistant response text.

        Returns ``None`` on any API error so callers never crash.
        """
        try:
            response = self._client.chat.completions.create(
                model=self._deployment,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
            )
            time.sleep(self._rate_limit_delay)
            return response.choices[0].message.content
        except (APIError, APITimeoutError, RateLimitError) as exc:
            logger.warning("Azure OpenAI API error: %s", exc)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Unexpected error during LLM call: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Public enrichment methods
    # ------------------------------------------------------------------

    def enrich_story_acceptance_criteria(self, story: UserStory) -> Optional[str]:
        """Generate detailed, testable acceptance criteria for a consolidated *UserStory*.

        Uses the story's recommendations to build the prompt.

        Returns
        -------
        str or None
            Markdown-formatted acceptance criteria, or ``None`` on failure.
        """
        rec_summaries = []
        for rec in story.recommendations:
            rec_summaries.append(f"- {rec.title} [{rec.impact}]: {rec.long_description or 'N/A'}")
        recs_text = "\n".join(rec_summaries) if rec_summaries else "N/A"

        prompt = ACCEPTANCE_CRITERIA_PROMPT.format(
            title=story.title,
            long_description=recs_text,
            recommendation_control="Mixed",
            learn_more_link="See individual recommendations",
        )
        return self._chat(prompt)

    def enrich_recommendation_remediation_steps(
        self, rec: Recommendation, resource_type: str = ""
    ) -> Optional[str]:
        """Generate step-by-step remediation instructions for a recommendation.

        Parameters
        ----------
        rec:
            The ``Recommendation`` with its affected resources.
        resource_type:
            ARM resource type for context.

        Returns
        -------
        str or None
            Numbered remediation steps, or ``None`` on failure.
        """
        resource_names = ", ".join(r.resource_name for r in rec.affected_resources[:5])
        if len(rec.affected_resources) > 5:
            resource_names += f" (+{len(rec.affected_resources) - 5} more)"

        prompt = REMEDIATION_STEPS_PROMPT.format(
            resource_name=resource_names,
            resource_id=resource_type,
            resource_type=resource_type,
            location="multiple",
            recommendation_title=rec.title,
            long_description=rec.long_description or "N/A",
            recommendation_control=rec.recommendation_control or "N/A",
        )
        return self._chat(prompt)

    def suggest_semantic_groups(
        self, stories: list[UserStory]
    ) -> list[dict[str, Any]]:
        """Analyse stories for non-obvious semantic groupings.

        Returns
        -------
        list[dict]
            Each dict contains ``group_name``, ``description``, and
            ``story_titles``.  Returns an empty list on failure.
        """
        if not stories:
            return []

        lines: list[str] = []
        for idx, s in enumerate(stories, 1):
            rec_titles = ", ".join(r.title for r in s.recommendations[:3])
            lines.append(f"{idx}. **{s.title}** — {rec_titles}")

        prompt = SEMANTIC_GROUPING_PROMPT.format(stories_block="\n".join(lines))
        raw = self._chat(prompt, temperature=0.5)
        if raw is None:
            return []

        import json

        # The model may wrap the JSON in a markdown code fence; strip it.
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()

        try:
            result = json.loads(cleaned)
            if isinstance(result, list):
                return result
            logger.warning("LLM returned non-list JSON for semantic groups.")
            return []
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse LLM semantic grouping response: %s", exc)
            return []

    def enrich_hierarchy(self, hierarchy: WorkItemHierarchy) -> WorkItemHierarchy:
        """Enrich an entire hierarchy in-place.

        Iterates over all stories and tasks, enriching acceptance criteria and
        remediation notes.  Progress is logged at INFO level.

        Returns the same ``hierarchy`` instance for chaining convenience.
        """
        all_stories = hierarchy.all_stories()
        total_stories = len(all_stories)
        logger.info("Starting LLM enrichment for %d stories …", total_stories)

        for idx, story in enumerate(all_stories, 1):
            logger.info(
                "[%d/%d] Enriching story: %s", idx, total_stories, story.title
            )

            resource_type = story.feature.resource_type if story.feature else ""
            for rec in story.recommendations:
                steps = self.enrich_recommendation_remediation_steps(rec, resource_type)
                if steps:
                    rec.long_description = (
                        f"{rec.long_description}\n\n"
                        f"## Remediation Steps (LLM-generated)\n{steps}"
                    ).strip()

        logger.info("LLM enrichment complete for %d stories.", total_stories)
        return hierarchy
