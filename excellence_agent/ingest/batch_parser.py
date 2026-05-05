"""Batch directory parser — traverses APRL batch assessment output structure.

Handles:
- Multi-file input from the directory structure produced by Invoke-APRLBatchAssessment.ps1:
    Root/AppName/Prod|Other envs/SubscriptionName/Expert-Analysis*.xlsx
- Review status filtering (only "Reviewed" items)
- Environment filtering (Prod, OtherEnvs, All)
- Metadata enrichment (app_name, environment, subscription_name, source_file)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import pandas as pd

from excellence_agent.ingest.excel_parser import APRLParser
from excellence_agent.ingest.schema import COL_REVIEW_STATUS, COL_RESOURCE_TYPE

logger = logging.getLogger(__name__)

# Metadata columns added by batch parsing
COL_APP_NAME = "_app_name"
COL_ENVIRONMENT = "_environment"
COL_SUBSCRIPTION_NAME = "_subscription_name"
COL_SOURCE_FILE = "_source_file"


@dataclass
class BatchParseResult:
    """Result of parsing a batch assessment directory."""

    impacted_resources: pd.DataFrame
    files_processed: int = 0
    files_skipped: int = 0
    files_errored: int = 0
    apps_found: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def filter_reviewed(df: pd.DataFrame) -> pd.DataFrame:
    """Filter DataFrame to only rows where REVIEW STATUS is 'Reviewed'.

    Case-insensitive, trimmed comparison. Rows with blank or other statuses
    are excluded.
    """
    if COL_REVIEW_STATUS not in df.columns:
        logger.warning(
            "Column '%s' not found in DataFrame — cannot filter by review status. "
            "Returning all rows.",
            COL_REVIEW_STATUS,
        )
        return df

    mask = (
        df[COL_REVIEW_STATUS]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
        .eq("reviewed")
    )
    filtered = df[mask].reset_index(drop=True)
    excluded = len(df) - len(filtered)
    logger.info(
        "Review status filter: %d reviewed, %d excluded (total %d)",
        len(filtered),
        excluded,
        len(df),
    )
    return filtered


def _classify_environment(folder_name: str) -> str:
    """Classify a folder name as 'Prod' or 'Other Envs'."""
    if folder_name.lower().strip() == "prod":
        return "Prod"
    return "Other Envs"


def _matches_env_filter(env: str, env_filter: str) -> bool:
    """Check if an environment matches the filter."""
    if env_filter.lower() == "all":
        return True
    if env_filter.lower() == "prod":
        return env == "Prod"
    if env_filter.lower() in ("otherenvs", "other envs", "other_envs"):
        return env == "Other Envs"
    return True


def parse_batch_directory(
    input_dir: str | Path,
    *,
    reviewed_only: bool = True,
    env_filter: str = "All",
) -> BatchParseResult:
    """Parse all Expert Analysis files in a batch assessment directory structure.

    Expected structure:
        input_dir/AppName/Prod|Other envs/SubscriptionName/Expert-Analysis*.xlsx

    Parameters
    ----------
    input_dir
        Root directory containing app-based folder structure.
    reviewed_only
        If True, only include rows with REVIEW STATUS == "Reviewed".
    env_filter
        Filter by environment: "All", "Prod", or "OtherEnvs".

    Returns
    -------
    BatchParseResult
        Combined DataFrame with metadata columns and parse statistics.
    """
    input_path = Path(input_dir)
    if not input_path.is_dir():
        raise FileNotFoundError(f"Batch input directory not found: {input_dir}")

    all_frames: List[pd.DataFrame] = []
    files_processed = 0
    files_skipped = 0
    files_errored = 0
    apps_found: set[str] = set()
    errors: List[str] = []

    # Find all Expert-Analysis Excel files
    excel_files = list(input_path.rglob("Expert-Analysis*.xlsx"))

    if not excel_files:
        logger.warning("No Expert-Analysis*.xlsx files found under '%s'", input_dir)
        return BatchParseResult(
            impacted_resources=pd.DataFrame(),
            apps_found=[],
        )

    logger.info("Found %d Expert Analysis file(s) in '%s'", len(excel_files), input_dir)

    for file_path in excel_files:
        # Determine app/env/sub from path structure
        # Expected: input_dir / AppName / Env / SubName / file.xlsx
        try:
            relative = file_path.relative_to(input_path)
            parts = relative.parts  # (AppName, Env, SubName, filename)
        except ValueError:
            parts = ()

        if len(parts) >= 4:
            app_name = parts[0]
            env_folder = parts[1]
            sub_name = parts[2]
        elif len(parts) >= 3:
            app_name = parts[0]
            env_folder = parts[1]
            sub_name = "Unknown"
        elif len(parts) >= 2:
            app_name = parts[0]
            env_folder = "Unknown"
            sub_name = "Unknown"
        else:
            app_name = "Unknown"
            env_folder = "Unknown"
            sub_name = "Unknown"

        environment = _classify_environment(env_folder)

        # Apply environment filter
        if not _matches_env_filter(environment, env_filter):
            files_skipped += 1
            continue

        # Parse the file
        try:
            parser = APRLParser(str(file_path))
            report = parser.parse()
            df = report.impacted_resources

            if df.empty:
                files_skipped += 1
                continue

            # Add metadata columns
            df = df.copy()
            df[COL_APP_NAME] = app_name
            df[COL_ENVIRONMENT] = environment
            df[COL_SUBSCRIPTION_NAME] = sub_name
            df[COL_SOURCE_FILE] = str(file_path)

            all_frames.append(df)
            files_processed += 1
            apps_found.add(app_name)

        except Exception as e:
            files_errored += 1
            error_msg = f"Error parsing '{file_path}': {e}"
            errors.append(error_msg)
            logger.error(error_msg)

    # Combine all DataFrames
    if all_frames:
        combined = pd.concat(all_frames, ignore_index=True)
    else:
        combined = pd.DataFrame()

    # Apply review status filter
    if reviewed_only and not combined.empty:
        combined = filter_reviewed(combined)

    logger.info(
        "Batch parse complete: %d files processed, %d skipped, %d errors, %d apps, %d rows",
        files_processed,
        files_skipped,
        files_errored,
        len(apps_found),
        len(combined),
    )

    return BatchParseResult(
        impacted_resources=combined,
        files_processed=files_processed,
        files_skipped=files_skipped,
        files_errored=files_errored,
        apps_found=sorted(apps_found),
        errors=errors,
    )


def parse_single_file(
    file_path: str | Path,
    *,
    reviewed_only: bool = True,
    app_name: Optional[str] = None,
    environment: str = "Unknown",
    subscription_name: str = "Unknown",
) -> BatchParseResult:
    """Parse a single Expert Analysis file with optional review filtering.

    Parameters
    ----------
    file_path
        Path to the Expert Analysis Excel file.
    reviewed_only
        If True, only include rows with REVIEW STATUS == "Reviewed".
    app_name
        Application name to assign. If None, derived from parent folder name.
    environment
        Environment label (default "Unknown").
    subscription_name
        Subscription name (default "Unknown").
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    if app_name is None:
        # Try to derive from parent folder structure
        app_name = path.parent.parent.parent.name if len(path.parts) > 3 else "Unknown"

    parser = APRLParser(str(path))
    report = parser.parse()
    df = report.impacted_resources

    if df.empty:
        return BatchParseResult(
            impacted_resources=pd.DataFrame(),
            files_processed=1,
            apps_found=[app_name] if app_name != "Unknown" else [],
        )

    # Add metadata
    df = df.copy()
    df[COL_APP_NAME] = app_name
    df[COL_ENVIRONMENT] = environment
    df[COL_SUBSCRIPTION_NAME] = subscription_name
    df[COL_SOURCE_FILE] = str(path)

    # Apply review filter
    if reviewed_only:
        df = filter_reviewed(df)

    return BatchParseResult(
        impacted_resources=df,
        files_processed=1,
        apps_found=[app_name] if app_name != "Unknown" else [],
    )
