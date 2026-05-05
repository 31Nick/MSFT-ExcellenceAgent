"""Incremental pipeline — flexible story creation with deduplication.

Orchestrates: parse → filter reviewed → deduplicate via ledger → build
app-centric hierarchy → assign run numbers → record in ledger.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd

from excellence_agent.ado.processing_ledger import ProcessingLedger
from excellence_agent.analysis import ResourceMapper
from excellence_agent.analysis.grouper_v2 import COL_MATRIX_CATEGORY, HierarchyBuilderV2
from excellence_agent.applications import (
    AppRegistry,
    auto_detect_apps_from_directory,
    load_app_registry,
)
from excellence_agent.ingest.batch_parser import (
    COL_APP_NAME,
    COL_SOURCE_FILE,
    BatchParseResult,
    filter_reviewed,
    parse_batch_directory,
    parse_single_file,
)
from excellence_agent.ingest.schema import COL_GUID, COL_ID
from excellence_agent.models_v2 import WorkItemHierarchyV2

logger = logging.getLogger(__name__)


@dataclass
class IncrementalResult:
    """Result of an incremental pipeline run."""

    hierarchy: WorkItemHierarchyV2
    stats: Dict[str, int] = field(default_factory=dict)
    new_items_processed: int = 0
    items_skipped_duplicate: int = 0
    apps_processed: List[str] = field(default_factory=list)
    new_apps_detected: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def build_hierarchy_incremental(
    report_path: str,
    matrix_path: str,
    *,
    customer: str,
    reviewed_only: bool = True,
    env_filter: str = "All",
    app_name: Optional[str] = None,
    state_dir: Optional[str] = None,
    app_registry_path: Optional[str] = None,
    advisor_path: Optional[str] = None,
) -> IncrementalResult:
    """Run the incremental pipeline and return the hierarchy with stats.

    Parameters
    ----------
    report_path
        Path to a single Expert Analysis file OR a batch assessment directory.
    matrix_path
        Path to resource_matrix.yaml.
    customer
        Customer identifier for scoping the processing ledger.
    reviewed_only
        If True, only process rows with REVIEW STATUS == "Reviewed".
    env_filter
        Environment filter: "All", "Prod", or "OtherEnvs".
    app_name
        Application name (used for single-file mode). Auto-detected for directories.
    state_dir
        Path to state directory (default: .state/).
    app_registry_path
        Path to applications.yaml. Default: <repo_root>/applications.yaml.
    advisor_path
        Optional path to Azure Advisor CSV for cross-referencing.

    Returns
    -------
    IncrementalResult
        The built hierarchy, stats, and processing information.
    """
    state_path = Path(state_dir) if state_dir else None
    ledger = ProcessingLedger(state_dir=state_path)
    registry = load_app_registry(app_registry_path)

    result = IncrementalResult(hierarchy=WorkItemHierarchyV2())

    # ── Step 1: Parse input ──────────────────────────────────────────
    path = Path(report_path)

    if path.is_dir():
        # Auto-detect apps from directory
        new_apps = auto_detect_apps_from_directory(path, registry, save=True)
        result.new_apps_detected = new_apps

        parse_result = parse_batch_directory(
            path,
            reviewed_only=reviewed_only,
            env_filter=env_filter,
        )
    elif path.is_file():
        parse_result = parse_single_file(
            path,
            reviewed_only=reviewed_only,
            app_name=app_name,
        )
    else:
        raise FileNotFoundError(f"Report path not found: {report_path}")

    result.apps_processed = parse_result.apps_found
    result.errors = parse_result.errors

    df = parse_result.impacted_resources

    if df.empty:
        logger.info("No reviewed items found after parsing. Nothing to process.")
        result.stats = {"total_input_rows": 0, "after_dedup": 0}
        return result

    # ── Step 2: Cross-reference with Advisor (optional) ──────────────
    if advisor_path:
        from excellence_agent.analysis import CrossReferencer
        from excellence_agent.ingest import AdvisorParser
        from excellence_agent.pipeline import load_resource_matrix

        matrix = load_resource_matrix(matrix_path)
        type_mapping = matrix.get("advisor_type_mapping", {})
        advisor_report = AdvisorParser(advisor_path, type_mapping=type_mapping).parse()
        xref = CrossReferencer()
        df, _ = xref.merge(df, advisor_report.recommendations)

    # ── Step 3: Map resources to categories ──────────────────────────
    from excellence_agent.pipeline import load_resource_matrix

    matrix = load_resource_matrix(matrix_path)
    mapper = ResourceMapper(matrix)
    df = mapper.map_dataframe(df)

    # ── Step 4: Deduplicate against ledger ───────────────────────────
    total_before_dedup = len(df)
    rows_to_keep: List[bool] = []

    for app_name_val in df[COL_APP_NAME].unique():
        app_df = df[df[COL_APP_NAME] == app_name_val]
        already_processed = ledger.get_already_processed_keys(customer, str(app_name_val))

        for _, row in app_df.iterrows():
            guid = str(row.get(COL_GUID, "")).strip()
            resource_id = str(row.get(COL_ID, "")).strip()
            key = (guid, resource_id)
            rows_to_keep.append(key not in already_processed)

    df = df[rows_to_keep].reset_index(drop=True)
    items_skipped = total_before_dedup - len(df)
    result.items_skipped_duplicate = items_skipped

    if df.empty:
        logger.info(
            "All %d items already processed. Nothing new to create.",
            total_before_dedup,
        )
        result.stats = {
            "total_input_rows": total_before_dedup,
            "after_dedup": 0,
        }
        return result

    logger.info(
        "Deduplication: %d total → %d new (%d already processed)",
        total_before_dedup,
        len(df),
        items_skipped,
    )

    # ── Step 5: Determine run numbers per (app, resource_type) ───────
    from excellence_agent.models import normalize_resource_type

    run_numbers: Dict[Tuple[str, str], int] = {}

    # Get unique (app, normalized_rt) pairs
    df["_rt_norm_tmp"] = df["Resource Type"].apply(
        lambda v: normalize_resource_type(str(v)) if pd.notna(v) else ""
    )

    unique_app_rt = df[[COL_APP_NAME, "_rt_norm_tmp"]].drop_duplicates()
    for _, row in unique_app_rt.iterrows():
        app_val = str(row[COL_APP_NAME])
        rt_val = str(row["_rt_norm_tmp"])
        if (app_val, rt_val) not in run_numbers:
            run_numbers[(app_val, rt_val)] = ledger.get_next_run_number(
                customer, app_val, rt_val
            )

    df.drop(columns=["_rt_norm_tmp"], inplace=True)

    # ── Step 6: Build hierarchy ──────────────────────────────────────
    descriptions = {
        cat: info.get("description", "")
        for cat, info in matrix.get("categories", {}).items()
    }

    def run_number_fn(app: str, resource_type: str) -> int:
        return run_numbers.get((app, resource_type), 1)

    builder = HierarchyBuilderV2(
        category_descriptions=descriptions,
        run_number_fn=run_number_fn,
    )
    hierarchy = builder.build(df)
    result.hierarchy = hierarchy

    # ── Step 7: Record processed items in ledger ─────────────────────
    total_recorded = 0
    for story in hierarchy.all_stories():
        app_val = story.feature.epic.app_name if story.feature and story.feature.epic else ""
        for rec in story.recommendations:
            items_to_record = [
                (rec.recommendation_guid, ar.resource_id)
                for ar in rec.affected_resources
            ]
            if items_to_record:
                recorded = ledger.record_processed_batch(
                    customer=customer,
                    app_name=app_val,
                    items=items_to_record,
                    run_number=story.run_number,
                    story_stable_key=story.stable_key,
                )
                total_recorded += recorded

    result.new_items_processed = total_recorded
    result.stats = hierarchy.summary_stats()
    result.stats["total_input_rows"] = total_before_dedup
    result.stats["after_dedup"] = len(df)
    result.stats["items_recorded"] = total_recorded

    logger.info(
        "Incremental pipeline complete: %d new items recorded, %d stories created",
        total_recorded,
        len(hierarchy.all_stories()),
    )

    return result
