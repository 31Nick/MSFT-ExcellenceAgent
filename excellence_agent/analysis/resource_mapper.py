"""Maps APRL resource types to user-defined matrix categories (ADO Epics).

Uses case-insensitive prefix matching against patterns defined in
``resource_matrix.yaml``.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import yaml

logger = logging.getLogger(__name__)


class ResourceMapper:
    """Map Azure resource types to matrix categories."""

    def __init__(self, matrix_config: dict[str, Any]) -> None:
        """Initialize with a loaded YAML config dict."""
        raw_categories: dict[str, Any] = matrix_config.get("categories", {})
        self._default_category: str = matrix_config.get(
            "default_category", "Uncategorised"
        )

        # Store categories preserving YAML insertion order so first-match wins.
        self._categories: dict[str, dict[str, Any]] = {}
        for name, body in raw_categories.items():
            self._categories[name] = {
                "description": body.get("description", ""),
                "patterns": [
                    p.lower() for p in body.get("resource_patterns", [])
                ],
            }

    @classmethod
    def from_yaml(cls, yaml_path: str) -> ResourceMapper:
        """Load from a YAML file path."""
        with open(yaml_path, "r", encoding="utf-8") as fh:
            config = yaml.safe_load(fh)
        return cls(config)

    def map_resource_type(self, resource_type: str) -> str:
        """Return the category name for a given Azure resource type."""
        rt_lower = resource_type.lower()
        for category, info in self._categories.items():
            for pattern in info["patterns"]:
                if rt_lower.startswith(pattern):
                    return category

        logger.warning("Unmapped resource type: %s", resource_type)
        return self._default_category

    def get_category_description(self, category: str) -> str:
        """Return the description for a category."""
        info = self._categories.get(category)
        if info is not None:
            return info["description"]
        return ""

    def map_dataframe(
        self,
        df: pd.DataFrame,
        resource_type_column: str = "Resource Type",
    ) -> pd.DataFrame:
        """Add a ``MatrixCategory`` column to the DataFrame."""
        df["MatrixCategory"] = df[resource_type_column].apply(
            self.map_resource_type
        )
        return df

    def get_mapping_summary(self) -> dict[str, Any]:
        """Return a summary of all categories and their pattern counts."""
        summary: dict[str, Any] = {}
        for category, info in self._categories.items():
            summary[category] = {
                "description": info["description"],
                "pattern_count": len(info["patterns"]),
            }
        summary[self._default_category] = {
            "description": "Fallback for unmatched resource types",
            "pattern_count": 0,
        }
        return summary
