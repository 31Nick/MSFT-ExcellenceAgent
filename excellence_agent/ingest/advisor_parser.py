"""Parser for Azure Advisor CSV exports."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from excellence_agent.ingest.advisor_schema import (
    ADVISOR_COLUMNS,
    ADVISOR_REQUIRED_COLUMNS,
    COL_ADV_RESOURCE_NAME,
    COL_ADV_TYPE,
    validate_advisor_columns,
)

logger = logging.getLogger(__name__)


@dataclass
class AdvisorReport:
    """Container for the parsed Advisor CSV data."""

    recommendations: pd.DataFrame
    metadata: dict[str, Any] = field(default_factory=dict)


class AdvisorParser:
    """Read an Azure Advisor CSV export and return a clean DataFrame."""

    def __init__(
        self,
        file_path: str,
        type_mapping: dict[str, str] | None = None,
    ) -> None:
        self.file_path = file_path
        self.type_mapping = type_mapping or {}
        if not os.path.isfile(self.file_path):
            raise FileNotFoundError(
                f"Advisor CSV not found: {self.file_path}"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self) -> AdvisorReport:
        """Parse the Advisor CSV into a normalised :class:`AdvisorReport`."""
        df = pd.read_csv(self.file_path, encoding="utf-8-sig")

        # Normalise header whitespace.
        df.columns = [str(c).strip() for c in df.columns]

        # Validate expected columns.
        is_valid, missing = validate_advisor_columns(
            list(df.columns), ADVISOR_COLUMNS
        )
        if not is_valid:
            logger.warning("Advisor CSV is missing expected columns: %s", missing)

        # Validate required columns (stricter).
        req_valid, req_missing = validate_advisor_columns(
            list(df.columns), ADVISOR_REQUIRED_COLUMNS
        )
        if not req_valid:
            raise ValueError(
                f"Advisor CSV is missing REQUIRED columns: {req_missing}"
            )

        # Strip whitespace from all string columns.
        str_cols = df.select_dtypes(include=["object"]).columns
        df[str_cols] = df[str_cols].apply(lambda col: col.str.strip())

        # Filter out rows with empty Resource Name.
        if COL_ADV_RESOURCE_NAME in df.columns:
            before = len(df)
            df = df[
                df[COL_ADV_RESOURCE_NAME].notna()
                & (df[COL_ADV_RESOURCE_NAME].astype(str).str.strip() != "")
            ]
            dropped = before - len(df)
            if dropped:
                logger.debug(
                    "Filtered %d rows with empty Resource Name", dropped
                )

        # Map friendly type names to ARM resource types.
        if COL_ADV_TYPE in df.columns:
            df[COL_ADV_TYPE] = df[COL_ADV_TYPE].apply(self._map_type)

        # Tag every row with source.
        df["_Source"] = "Advisor"

        df = df.reset_index(drop=True)

        unique_types = (
            sorted(df[COL_ADV_TYPE].dropna().unique().tolist())
            if COL_ADV_TYPE in df.columns
            else []
        )
        metadata: dict[str, Any] = {
            "row_count": len(df),
            "unique_resource_types": unique_types,
            "source_file": os.path.basename(self.file_path),
        }
        logger.info("Parsed Advisor CSV: %d recommendation rows", len(df))
        return AdvisorReport(recommendations=df, metadata=metadata)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _map_type(self, friendly_name: str | float) -> str:
        """Resolve a friendly type name to an ARM resource type."""
        if pd.isna(friendly_name):
            return str(friendly_name)

        name = str(friendly_name).strip()

        # Exact match.
        if name in self.type_mapping:
            return self.type_mapping[name]

        # Case-insensitive best-effort match.
        lower = name.lower()
        for key, value in self.type_mapping.items():
            if key.lower() == lower:
                return value

        # No mapping found — keep the original friendly name.
        return name
