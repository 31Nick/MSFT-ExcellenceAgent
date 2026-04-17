"""Shared pipeline helper: parse → cross-ref → map → build hierarchy.

Used by CLI commands (export, sync) and the web upload endpoint to avoid
duplicating the ingest-to-hierarchy logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from excellence_agent.analysis import (
    CrossReferencer,
    Deduplicator,
    HierarchyBuilder,
    PatternDetector,
    ResourceMapper,
)
from excellence_agent.ingest import APRLParser
from excellence_agent.models import WorkItemHierarchy


def load_resource_matrix(matrix_path: str) -> dict:
    """Load a resource matrix YAML file."""
    import yaml

    with open(matrix_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_hierarchy(
    report_path: str,
    matrix_path: str,
    *,
    advisor_path: Optional[str] = None,
) -> Tuple[WorkItemHierarchy, dict]:
    """Run the full pipeline and return ``(hierarchy, stats)``.

    Parameters
    ----------
    report_path
        Path to the APRL v2 Excel report.
    matrix_path
        Path to ``resource_matrix.yaml``.
    advisor_path
        Optional path to an Azure Advisor CSV export.

    Returns
    -------
    tuple
        ``(WorkItemHierarchy, summary_stats_dict)``
    """
    aprl = APRLParser(report_path).parse()
    df = aprl.impacted_resources

    matrix = load_resource_matrix(matrix_path)

    if advisor_path:
        from excellence_agent.ingest import AdvisorParser

        type_mapping = matrix.get("advisor_type_mapping", {})
        advisor_report = AdvisorParser(advisor_path, type_mapping=type_mapping).parse()
        xref = CrossReferencer()
        df, _xref_report = xref.merge(df, advisor_report.recommendations)

    mapper = ResourceMapper(matrix)
    mapped_df = mapper.map_dataframe(df)

    descriptions = {
        cat: info.get("description", "")
        for cat, info in matrix.get("categories", {}).items()
    }
    hierarchy = HierarchyBuilder(category_descriptions=descriptions).build(mapped_df)
    return hierarchy, hierarchy.summary_stats()
