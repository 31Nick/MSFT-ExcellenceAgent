"""Cross-reference engine: merge APRL and Advisor DataFrames by resource."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from excellence_agent.analysis.similarity import SimilarityMatcher
from excellence_agent.ingest.advisor_schema import (
    COL_ADV_BUSINESS_IMPACT,
    COL_ADV_COST_IMPLICATIONS,
    COL_ADV_DESCRIPTION_CHANGES,
    COL_ADV_POTENTIAL_BENEFITS,
    COL_ADV_RECOMMENDATION,
    COL_ADV_RESOURCE_GROUP,
    COL_ADV_RESOURCE_NAME,
    COL_ADV_RETIREMENT_DATE,
    COL_ADV_RETIRING_FEATURE,
    COL_ADV_SUBSCRIPTION_ID,
    COL_ADV_SUBSCRIPTION_NAME,
    COL_ADV_TYPE,
    COL_ADV_UPDATED_DATE,
)
from excellence_agent.ingest.schema import (
    COL_CATEGORY,
    COL_GUID,
    COL_IMPACT,
    COL_LONG_DESCRIPTION,
    COL_NAME,
    COL_NOTES,
    COL_POTENTIAL_BENEFIT,
    COL_RECOMMENDATION_CONTROL,
    COL_RECOMMENDATION_TITLE,
    COL_RESOURCE_GROUP,
    COL_RESOURCE_TYPE,
    COL_SOURCE,
    COL_SUBSCRIPTION_ID,
    COL_WAF_PILLAR,
    IMPACTED_RESOURCES_COLUMNS,
)

logger = logging.getLogger(__name__)

# Source tag values
_SRC_APRL = "APRL"
_SRC_ADVISOR = "Advisor"
_SRC_BOTH = "APRL & Advisor"
_SOURCE_COL = "_Source"

# Advisor-specific columns preserved in the merged output
_ADVISOR_EXTRA_COLS = [
    "advisor_retirement_date",
    "advisor_retiring_feature",
    "advisor_subscription_name",
    "advisor_updated_date",
    "advisor_cost_implications",
]


# ---------------------------------------------------------------------------
# Column mapping: Advisor → APRL-compatible names
# ---------------------------------------------------------------------------
_ADVISOR_TO_APRL_MAP: dict[str, str] = {
    COL_ADV_BUSINESS_IMPACT: COL_IMPACT,
    COL_ADV_RECOMMENDATION: COL_RECOMMENDATION_TITLE,
    COL_ADV_SUBSCRIPTION_ID: COL_SUBSCRIPTION_ID,
    COL_ADV_RESOURCE_GROUP: COL_RESOURCE_GROUP,
    COL_ADV_RESOURCE_NAME: COL_NAME,
    COL_ADV_TYPE: COL_RESOURCE_TYPE,
    COL_ADV_POTENTIAL_BENEFITS: COL_POTENTIAL_BENEFIT,
    COL_ADV_DESCRIPTION_CHANGES: COL_LONG_DESCRIPTION,
}

# Advisor columns renamed to advisor_* prefixed extras
_ADVISOR_EXTRA_MAP: dict[str, str] = {
    COL_ADV_RETIREMENT_DATE: "advisor_retirement_date",
    COL_ADV_RETIRING_FEATURE: "advisor_retiring_feature",
    COL_ADV_SUBSCRIPTION_NAME: "advisor_subscription_name",
    COL_ADV_UPDATED_DATE: "advisor_updated_date",
    COL_ADV_COST_IMPLICATIONS: "advisor_cost_implications",
}


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------
@dataclass
class CrossReferenceReport:
    """Summary of cross-referencing results."""

    total_aprl_rows: int = 0
    total_advisor_rows: int = 0
    total_merged_rows: int = 0
    matched_resources: list[str] = field(default_factory=list)
    aprl_only_resources: list[str] = field(default_factory=list)
    advisor_only_resources: list[str] = field(default_factory=list)
    duplicate_recommendations: list[dict[str, Any]] = field(default_factory=list)

    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """Serialise the report to a plain dictionary."""
        return {
            "total_aprl_rows": self.total_aprl_rows,
            "total_advisor_rows": self.total_advisor_rows,
            "total_merged_rows": self.total_merged_rows,
            "matched_resources_count": len(self.matched_resources),
            "aprl_only_resources_count": len(self.aprl_only_resources),
            "advisor_only_resources_count": len(self.advisor_only_resources),
            "duplicate_recommendations_count": len(self.duplicate_recommendations),
            "matched_resources": self.matched_resources,
            "aprl_only_resources": self.aprl_only_resources,
            "advisor_only_resources": self.advisor_only_resources,
            "duplicate_recommendations": self.duplicate_recommendations,
        }

    def summary(self) -> str:
        """Return a human-readable summary."""
        lines = [
            "=== Cross-Reference Report ===",
            f"APRL rows:         {self.total_aprl_rows}",
            f"Advisor rows:      {self.total_advisor_rows}",
            f"Merged rows:       {self.total_merged_rows}",
            f"Matched resources: {len(self.matched_resources)}",
            f"APRL-only:         {len(self.aprl_only_resources)}",
            f"Advisor-only:      {len(self.advisor_only_resources)}",
            f"Duplicate recs:    {len(self.duplicate_recommendations)}",
        ]
        if self.matched_resources:
            lines.append("")
            lines.append("--- Matched resources (first 20) ---")
            for name in self.matched_resources[:20]:
                lines.append(f"  • {name}")
            if len(self.matched_resources) > 20:
                lines.append(f"  … and {len(self.matched_resources) - 20} more")
        if self.duplicate_recommendations:
            lines.append("")
            lines.append("--- Duplicate recommendations (first 10) ---")
            for dup in self.duplicate_recommendations[:10]:
                lines.append(
                    f"  [{dup['resource']}] "
                    f"APRL: \"{dup['aprl_title']}\" ↔ "
                    f"Advisor: \"{dup['advisor_title']}\" "
                    f"(score={dup['similarity_score']:.3f})"
                )
            if len(self.duplicate_recommendations) > 10:
                lines.append(
                    f"  … and {len(self.duplicate_recommendations) - 10} more"
                )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
class CrossReferencer:
    """Merge APRL and Advisor DataFrames, cross-referencing by resource."""

    def __init__(self, similarity_threshold: float = 0.3) -> None:
        self._matcher = SimilarityMatcher(threshold=similarity_threshold)
        self._threshold = similarity_threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def merge(
        self,
        aprl_df: pd.DataFrame,
        advisor_df: pd.DataFrame,
    ) -> tuple[pd.DataFrame, CrossReferenceReport]:
        """Merge APRL and Advisor DataFrames into a unified DataFrame.

        Strategy:
        1. Normalise Advisor columns to match APRL column names.
        2. Match resources by Resource Name (case-insensitive, primary key),
           confirmed with Resource Group + Subscription ID.
        3. For matched resources, compare recommendations via SimilarityMatcher:
           - Similar → tag "APRL & Advisor", keep APRL data, append Advisor
             recommendation text to Notes.
           - Different → keep both, tagged by source.
        4. Append Advisor-only rows (resources not in APRL).
        5. All APRL-only rows keep source "APRL".

        Returns:
            (merged_df, report)
        """
        logger.info(
            "Starting cross-reference: %d APRL rows, %d Advisor rows",
            len(aprl_df),
            len(advisor_df),
        )

        # Work on copies so we don't mutate the caller's data.
        aprl = aprl_df.copy()
        advisor_norm = self._normalise_advisor(advisor_df.copy())

        # Ensure _Source column on APRL rows.
        if _SOURCE_COL not in aprl.columns:
            aprl[_SOURCE_COL] = _SRC_APRL
        else:
            aprl[_SOURCE_COL] = aprl[_SOURCE_COL].fillna(_SRC_APRL)

        # Ensure advisor extra columns exist on APRL frame (empty).
        for col in _ADVISOR_EXTRA_COLS:
            if col not in aprl.columns:
                aprl[col] = ""

        # Match resources across sources.
        matches = self._match_resources(aprl, advisor_norm)

        report = CrossReferenceReport(
            total_aprl_rows=len(aprl_df),
            total_advisor_rows=len(advisor_df),
        )

        # Collect all row indices of APRL rows that become "APRL & Advisor".
        aprl_merged_indices: set[int] = set()
        advisor_consumed_indices: set[int] = set()
        all_duplicates: list[dict[str, Any]] = []

        # ----- Process matched resources -----
        for aprl_idxs, adv_idxs, resource_name in matches["matched"]:
            report.matched_resources.append(resource_name)

            aprl_rows = aprl.loc[aprl_idxs]
            adv_rows = advisor_norm.loc[adv_idxs]

            duplicates = self._detect_recommendation_overlaps(aprl_rows, adv_rows)
            all_duplicates.extend(duplicates)

            # Build sets of advisor indices consumed by overlap matches.
            dup_adv_titles = {d["advisor_title"] for d in duplicates}
            dup_aprl_titles = {d["aprl_title"] for d in duplicates}

            # Tag overlapping APRL rows as "APRL & Advisor" and append note.
            for dup in duplicates:
                # Find the APRL row index matching this duplicate.
                mask = (
                    aprl.loc[aprl_idxs, COL_RECOMMENDATION_TITLE]
                    .astype(str)
                    .str.strip()
                    .str.lower()
                    == str(dup["aprl_title"]).strip().lower()
                )
                matched_aprl_idxs = [i for i in aprl_idxs if mask.get(i, False)]

                for idx in matched_aprl_idxs:
                    aprl.at[idx, _SOURCE_COL] = _SRC_BOTH
                    if COL_NOTES in aprl.columns:
                        existing_note = str(aprl.at[idx, COL_NOTES]) if pd.notna(aprl.at[idx, COL_NOTES]) else ""
                    else:
                        existing_note = ""
                    advisor_note = f"[Advisor] {dup['advisor_title']}"
                    if COL_NOTES in aprl.columns:
                        if existing_note:
                            aprl.at[idx, COL_NOTES] = f"{existing_note} | {advisor_note}"
                        else:
                            aprl.at[idx, COL_NOTES] = advisor_note
                    aprl_merged_indices.add(idx)

            # Mark advisor rows consumed by duplicates.
            for idx in adv_idxs:
                title = str(advisor_norm.at[idx, COL_RECOMMENDATION_TITLE]).strip().lower()
                if title in {t.strip().lower() for t in dup_adv_titles}:
                    advisor_consumed_indices.add(idx)

            # Advisor rows for this resource that were NOT duplicates —
            # these are unique Advisor recommendations for a matched resource.
            # They go into the merged frame tagged as "Advisor".
            for idx in adv_idxs:
                if idx not in advisor_consumed_indices:
                    advisor_consumed_indices.add(idx)
                    # Row already has _Source = "Advisor" from normalisation.

        # ----- Advisor-only resources -----
        advisor_only_indices: list[int] = []
        for adv_idxs, resource_name in matches["advisor_only"]:
            report.advisor_only_resources.append(resource_name)
            advisor_only_indices.extend(adv_idxs)

        # ----- APRL-only resources -----
        for aprl_idxs, resource_name in matches["aprl_only"]:
            report.aprl_only_resources.append(resource_name)

        report.duplicate_recommendations = all_duplicates

        # ----- Assemble merged DataFrame -----
        # 1. All APRL rows (some now tagged "APRL & Advisor").
        parts: list[pd.DataFrame] = [aprl]

        # 2. Advisor rows for matched resources that weren't duplicates.
        matched_advisor_not_dup = [
            idx
            for aprl_idxs, adv_idxs, _ in matches["matched"]
            for idx in adv_idxs
            if idx not in {
                i
                for d in all_duplicates
                for i in adv_idxs
                if str(advisor_norm.at[i, COL_RECOMMENDATION_TITLE]).strip().lower()
                == str(d["advisor_title"]).strip().lower()
            }
        ]
        if matched_advisor_not_dup:
            parts.append(advisor_norm.loc[matched_advisor_not_dup])

        # 3. Advisor-only rows.
        if advisor_only_indices:
            parts.append(advisor_norm.loc[advisor_only_indices])

        merged = pd.concat(parts, ignore_index=True)

        # Ensure every expected APRL column exists.
        for col in IMPACTED_RESOURCES_COLUMNS:
            if col not in merged.columns:
                merged[col] = ""
        # Ensure extra advisor columns exist.
        for col in _ADVISOR_EXTRA_COLS:
            if col not in merged.columns:
                merged[col] = ""

        report.total_merged_rows = len(merged)

        logger.info(
            "Cross-reference complete: %d merged rows "
            "(%d matched resources, %d APRL-only, %d Advisor-only, %d duplicate recs)",
            report.total_merged_rows,
            len(report.matched_resources),
            len(report.aprl_only_resources),
            len(report.advisor_only_resources),
            len(report.duplicate_recommendations),
        )

        return merged, report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _normalise_advisor(self, advisor_df: pd.DataFrame) -> pd.DataFrame:
        """Map Advisor columns to APRL-compatible column names.

        Column mapping:
            Business Impact       → Impact
            Recommendation        → Recommendation Title
            Subscription ID       → subscriptionId
            Resource Group        → resourceGroup
            Resource Name         → name
            Type                  → Resource Type
            Potential benefits    → Potential Benefit
            Description of changes → Long Description

        Default values for APRL-specific columns Advisor lacks:
            Source → "Advisor", WAF Pillar → "", Category → "Azure Service",
            Guid → "", Recommendation Control → "".

        Advisor-specific columns are preserved with an ``advisor_`` prefix.
        """
        df = advisor_df.copy()

        # Rename advisor extras → advisor_* first (before main rename).
        extra_rename: dict[str, str] = {}
        for adv_col, target in _ADVISOR_EXTRA_MAP.items():
            if adv_col in df.columns:
                extra_rename[adv_col] = target
        if extra_rename:
            df = df.rename(columns=extra_rename)

        # Main rename: Advisor → APRL column names.
        main_rename: dict[str, str] = {}
        for adv_col, aprl_col in _ADVISOR_TO_APRL_MAP.items():
            if adv_col in df.columns:
                main_rename[adv_col] = aprl_col
        if main_rename:
            df = df.rename(columns=main_rename)

        # Default values for APRL-only columns.
        defaults: dict[str, str] = {
            COL_SOURCE: _SRC_ADVISOR,
            COL_WAF_PILLAR: "",
            COL_CATEGORY: "Azure Service",
            COL_GUID: "",
            COL_RECOMMENDATION_CONTROL: "",
        }
        for col, default_val in defaults.items():
            if col not in df.columns:
                df[col] = default_val

        # Ensure _Source tag.
        df[_SOURCE_COL] = _SRC_ADVISOR

        # Drop the old _Source from AdvisorParser if it was already present
        # (we just set the canonical one above).

        logger.debug(
            "Normalised Advisor columns: %d columns, %d rows",
            len(df.columns),
            len(df),
        )
        return df

    def _match_resources(
        self,
        aprl_df: pd.DataFrame,
        advisor_df: pd.DataFrame,
    ) -> dict[str, list]:
        """Match resources by name across sources.

        Primary key:  resource name (case-insensitive).
        Confirmation: resource_group + subscription_id match when available.

        Returns::

            {
                'matched':      [(aprl_indices, advisor_indices, resource_name), ...],
                'aprl_only':    [(aprl_indices, resource_name), ...],
                'advisor_only': [(advisor_indices, resource_name), ...],
            }
        """
        def _normalise_key(val: Any) -> str:
            if pd.isna(val):
                return ""
            return str(val).strip().lower()

        # Build resource-name → row-indices lookup for each source.
        aprl_groups: dict[str, list[int]] = {}
        for idx, row in aprl_df.iterrows():
            key = _normalise_key(row.get(COL_NAME, ""))
            if key:
                aprl_groups.setdefault(key, []).append(idx)

        adv_groups: dict[str, list[int]] = {}
        for idx, row in advisor_df.iterrows():
            key = _normalise_key(row.get(COL_NAME, ""))
            if key:
                adv_groups.setdefault(key, []).append(idx)

        matched: list[tuple[list[int], list[int], str]] = []
        aprl_only: list[tuple[list[int], str]] = []
        advisor_only: list[tuple[list[int], str]] = []

        # Track which advisor resource keys were matched.
        matched_adv_keys: set[str] = set()

        for key, aprl_idxs in aprl_groups.items():
            if key in adv_groups:
                adv_idxs = adv_groups[key]

                # Confirm match: check that at least one pair shares
                # resource_group + subscription_id (if available).
                confirmed = self._confirm_match(aprl_df, advisor_df, aprl_idxs, adv_idxs)

                if confirmed:
                    # Use original-cased name from first APRL row.
                    original_name = str(aprl_df.at[aprl_idxs[0], COL_NAME])
                    matched.append((aprl_idxs, adv_idxs, original_name))
                    matched_adv_keys.add(key)
                else:
                    # Name matched but resource group / subscription didn't.
                    # Treat as separate resources.
                    original_name = str(aprl_df.at[aprl_idxs[0], COL_NAME])
                    aprl_only.append((aprl_idxs, original_name))
                    adv_name = str(advisor_df.at[adv_idxs[0], COL_NAME])
                    advisor_only.append((adv_idxs, adv_name))
                    matched_adv_keys.add(key)
            else:
                original_name = str(aprl_df.at[aprl_idxs[0], COL_NAME])
                aprl_only.append((aprl_idxs, original_name))

        # Advisor resources not matched at all.
        for key, adv_idxs in adv_groups.items():
            if key not in matched_adv_keys and key not in {
                k for k in aprl_groups
            }:
                adv_name = str(advisor_df.at[adv_idxs[0], COL_NAME])
                advisor_only.append((adv_idxs, adv_name))

        logger.info(
            "Resource matching: %d matched, %d APRL-only, %d Advisor-only",
            len(matched),
            len(aprl_only),
            len(advisor_only),
        )
        return {
            "matched": matched,
            "aprl_only": aprl_only,
            "advisor_only": advisor_only,
        }

    def _confirm_match(
        self,
        aprl_df: pd.DataFrame,
        advisor_df: pd.DataFrame,
        aprl_idxs: list[int],
        adv_idxs: list[int],
    ) -> bool:
        """Confirm a resource-name match by checking resource group + subscription.

        Returns ``True`` when at least one APRL row and one Advisor row share
        the same (resource_group, subscription_id) pair, or when the confirming
        columns are missing / empty (benefit of the doubt).
        """
        def _norm(val: Any) -> str:
            if pd.isna(val):
                return ""
            return str(val).strip().lower()

        aprl_pairs: set[tuple[str, str]] = set()
        for idx in aprl_idxs:
            rg = _norm(aprl_df.at[idx, COL_RESOURCE_GROUP]) if COL_RESOURCE_GROUP in aprl_df.columns else ""
            sub = _norm(aprl_df.at[idx, COL_SUBSCRIPTION_ID]) if COL_SUBSCRIPTION_ID in aprl_df.columns else ""
            aprl_pairs.add((rg, sub))

        adv_pairs: set[tuple[str, str]] = set()
        for idx in adv_idxs:
            rg = _norm(advisor_df.at[idx, COL_RESOURCE_GROUP]) if COL_RESOURCE_GROUP in advisor_df.columns else ""
            sub = _norm(advisor_df.at[idx, COL_SUBSCRIPTION_ID]) if COL_SUBSCRIPTION_ID in advisor_df.columns else ""
            adv_pairs.add((rg, sub))

        # If either side has only empty pairs, give benefit of the doubt.
        if aprl_pairs == {("", "")} or adv_pairs == {("", "")}:
            return True

        return bool(aprl_pairs & adv_pairs)

    def _detect_recommendation_overlaps(
        self,
        aprl_rows: pd.DataFrame,
        advisor_rows: pd.DataFrame,
    ) -> list[dict[str, Any]]:
        """For matched resources, find similar recommendations via SimilarityMatcher."""
        aprl_titles = (
            aprl_rows[COL_RECOMMENDATION_TITLE]
            .dropna()
            .astype(str)
            .str.strip()
            .tolist()
        )
        adv_titles = (
            advisor_rows[COL_RECOMMENDATION_TITLE]
            .dropna()
            .astype(str)
            .str.strip()
            .tolist()
        )

        if not aprl_titles or not adv_titles:
            return []

        similarity_matches = self._matcher.find_matches(aprl_titles, adv_titles)

        duplicates: list[dict[str, Any]] = []
        resource_name = str(
            aprl_rows.iloc[0][COL_NAME]
            if COL_NAME in aprl_rows.columns
            else "unknown"
        )
        for aprl_title, adv_title, score in similarity_matches:
            duplicates.append(
                {
                    "resource": resource_name,
                    "aprl_title": aprl_title,
                    "advisor_title": adv_title,
                    "similarity_score": round(score, 4),
                }
            )

        return duplicates
