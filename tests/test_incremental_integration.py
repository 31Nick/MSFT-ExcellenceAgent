"""Integration tests for the incremental pipeline.

Verifies end-to-end behavior:
- Deduplication across runs (same items not processed twice)
- Correct run numbering (increments per app × resource type)
- Edge cases: empty reviewed set, multiple apps, overlapping data
"""

import shutil
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from excellence_agent.ado.processing_ledger import ProcessingLedger
from excellence_agent.ingest.batch_parser import (
    COL_APP_NAME,
    COL_ENVIRONMENT,
    COL_SOURCE_FILE,
    COL_SUBSCRIPTION_NAME,
)
from excellence_agent.ingest.schema import (
    COL_GUID,
    COL_ID,
    COL_IMPACT,
    COL_RECOMMENDATION_CONTROL,
    COL_RECOMMENDATION_TITLE,
    COL_RESOURCE_GROUP,
    COL_RESOURCE_TYPE,
    COL_REVIEW_STATUS,
    COL_SUBSCRIPTION_ID,
)
from excellence_agent.pipeline_v2 import build_hierarchy_incremental


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_expert_analysis_df(
    items: list[dict],
    app_name: str = "TestApp",
) -> pd.DataFrame:
    """Create a DataFrame of impacted resources from item dicts.

    Each dict should have: guid, resource_id, resource_type, review_status
    Optional: impact, recommendation_title
    """
    rows = []
    for i, item in enumerate(items):
        rt = item.get("resource_type", "microsoft.compute/virtualMachines")
        rows.append({
            COL_REVIEW_STATUS: item.get("review_status", "Reviewed"),
            COL_RESOURCE_TYPE: rt,
            COL_SUBSCRIPTION_ID: f"sub-0",
            COL_RESOURCE_GROUP: f"rg-{i}",
            "location": "eastus",
            "name": f"resource-{i}",
            COL_ID: item.get("resource_id", f"/subs/sub-0/rg/rg-{i}/providers/{rt}/res-{i}"),
            "custom1": "", "custom2": "", "custom3": "", "custom4": "", "custom5": "",
            COL_RECOMMENDATION_TITLE: item.get("recommendation_title", f"Rec-{i}"),
            COL_IMPACT: item.get("impact", "High"),
            COL_RECOMMENDATION_CONTROL: "Control",
            "Potential Benefit": "Benefit",
            "Learn More Link": "",
            "Long Description": "Description",
            COL_GUID: item.get("guid", f"guid-{i}"),
            "Category": "Compute",
            "Source": "APRL",
            "WAF Pillar": "Reliability",
            "Notes": "",
            "checkName": "",
            COL_APP_NAME: app_name,
            COL_ENVIRONMENT: "Prod",
            COL_SUBSCRIPTION_NAME: "sub-name",
            COL_SOURCE_FILE: "test.xlsx",
        })
    return pd.DataFrame(rows)


def _write_excel_for_pipeline(df: pd.DataFrame, path: Path) -> None:
    """Write DataFrame in the Expert Analysis format expected by the parser.

    The parser expects sheet '4.ImpactedResourcesAnalysis' with header at row 11.
    """
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "4.ImpactedResourcesAnalysis"

    # Rows 1-11 are "header noise" (the parser skips to row 12 for column names)
    for r in range(1, 12):
        ws.cell(row=r, column=1, value=f"Header row {r}")

    # Row 12: column headers
    columns = list(df.columns)
    for c_idx, col_name in enumerate(columns, start=1):
        ws.cell(row=12, column=c_idx, value=col_name)

    # Data rows starting at row 13
    for r_idx, (_, row) in enumerate(df.iterrows(), start=13):
        for c_idx, col_name in enumerate(columns, start=1):
            ws.cell(row=r_idx, column=c_idx, value=row[col_name])

    wb.save(path)


@pytest.fixture
def temp_workspace(tmp_path):
    """Create a temp workspace with state dir and matrix."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_dir = workspace / ".state"
    state_dir.mkdir()

    # Copy real resource_matrix.yaml
    real_matrix = Path(__file__).parent.parent / "resource_matrix.yaml"
    matrix_dest = workspace / "resource_matrix.yaml"
    shutil.copy(real_matrix, matrix_dest)

    return {
        "root": workspace,
        "state_dir": state_dir,
        "matrix_path": str(matrix_dest),
    }


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------


class TestDeduplicationAcrossRuns:
    """Verify that running the pipeline twice with overlapping data doesn't create duplicates."""

    def test_second_run_skips_already_processed(self, temp_workspace):
        """Items from the first run should be skipped in the second run."""
        items = [
            {"guid": "g1", "resource_id": "/subs/s/rg/r/p/microsoft.compute/virtualMachines/vm1"},
            {"guid": "g2", "resource_id": "/subs/s/rg/r/p/microsoft.compute/virtualMachines/vm2"},
            {"guid": "g3", "resource_id": "/subs/s/rg/r/p/microsoft.compute/virtualMachines/vm3"},
        ]
        df = _make_expert_analysis_df(items)

        report_file = temp_workspace["root"] / "Expert-Analysis-Run1.xlsx"
        _write_excel_for_pipeline(df, report_file)

        # Run 1
        result1 = build_hierarchy_incremental(
            report_path=str(report_file),
            matrix_path=temp_workspace["matrix_path"],
            customer="test-customer",
            reviewed_only=False,
            app_name="TestApp",
            state_dir=str(temp_workspace["state_dir"]),
        )

        assert result1.new_items_processed == 3
        assert result1.items_skipped_duplicate == 0
        assert len(result1.hierarchy.all_stories()) >= 1

        # Run 2 with same data
        result2 = build_hierarchy_incremental(
            report_path=str(report_file),
            matrix_path=temp_workspace["matrix_path"],
            customer="test-customer",
            reviewed_only=False,
            app_name="TestApp",
            state_dir=str(temp_workspace["state_dir"]),
        )

        assert result2.new_items_processed == 0
        assert result2.items_skipped_duplicate == 3
        assert len(result2.hierarchy.all_stories()) == 0

    def test_partial_overlap_processes_only_new(self, temp_workspace):
        """When run 2 has some overlap, only new items are processed."""
        # Run 1: items 1, 2
        items_run1 = [
            {"guid": "g1", "resource_id": "/subs/s/rg/r/p/microsoft.compute/virtualMachines/vm1"},
            {"guid": "g2", "resource_id": "/subs/s/rg/r/p/microsoft.compute/virtualMachines/vm2"},
        ]
        df1 = _make_expert_analysis_df(items_run1)
        file1 = temp_workspace["root"] / "report1.xlsx"
        _write_excel_for_pipeline(df1, file1)

        result1 = build_hierarchy_incremental(
            report_path=str(file1),
            matrix_path=temp_workspace["matrix_path"],
            customer="test-customer",
            reviewed_only=False,
            app_name="TestApp",
            state_dir=str(temp_workspace["state_dir"]),
        )
        assert result1.new_items_processed == 2

        # Run 2: items 2, 3, 4 (item 2 overlaps)
        items_run2 = [
            {"guid": "g2", "resource_id": "/subs/s/rg/r/p/microsoft.compute/virtualMachines/vm2"},
            {"guid": "g3", "resource_id": "/subs/s/rg/r/p/microsoft.compute/virtualMachines/vm3"},
            {"guid": "g4", "resource_id": "/subs/s/rg/r/p/microsoft.compute/virtualMachines/vm4"},
        ]
        df2 = _make_expert_analysis_df(items_run2)
        file2 = temp_workspace["root"] / "report2.xlsx"
        _write_excel_for_pipeline(df2, file2)

        result2 = build_hierarchy_incremental(
            report_path=str(file2),
            matrix_path=temp_workspace["matrix_path"],
            customer="test-customer",
            reviewed_only=False,
            app_name="TestApp",
            state_dir=str(temp_workspace["state_dir"]),
        )

        assert result2.items_skipped_duplicate == 1  # g2/vm2 already done
        assert result2.new_items_processed == 2  # g3/vm3 and g4/vm4 are new


class TestRunNumbering:
    """Verify run numbers increment correctly per app × resource_type."""

    def test_run_number_increments_per_resource_type(self, temp_workspace):
        """Each run for the same resource type should get a higher run number."""
        items1 = [
            {"guid": "g1", "resource_id": "/subs/s/rg/r/p/microsoft.compute/virtualMachines/vm1"},
        ]
        df1 = _make_expert_analysis_df(items1)
        file1 = temp_workspace["root"] / "r1.xlsx"
        _write_excel_for_pipeline(df1, file1)

        result1 = build_hierarchy_incremental(
            report_path=str(file1),
            matrix_path=temp_workspace["matrix_path"],
            customer="cust",
            reviewed_only=False,
            app_name="App1",
            state_dir=str(temp_workspace["state_dir"]),
        )

        stories1 = result1.hierarchy.all_stories()
        assert len(stories1) >= 1
        assert stories1[0].run_number == 1
        assert "Recommendations 1" in stories1[0].title

        # Second run with different items but same resource type
        items2 = [
            {"guid": "g2", "resource_id": "/subs/s/rg/r/p/microsoft.compute/virtualMachines/vm2"},
        ]
        df2 = _make_expert_analysis_df(items2)
        file2 = temp_workspace["root"] / "r2.xlsx"
        _write_excel_for_pipeline(df2, file2)

        result2 = build_hierarchy_incremental(
            report_path=str(file2),
            matrix_path=temp_workspace["matrix_path"],
            customer="cust",
            reviewed_only=False,
            app_name="App1",
            state_dir=str(temp_workspace["state_dir"]),
        )

        stories2 = result2.hierarchy.all_stories()
        assert len(stories2) >= 1
        assert stories2[0].run_number == 2
        assert "Recommendations 2" in stories2[0].title

    def test_different_apps_have_independent_counters(self, temp_workspace):
        """Run numbers are per-app, so App1's counter doesn't affect App2."""
        items = [
            {"guid": "g1", "resource_id": "/subs/s/rg/r/p/microsoft.compute/virtualMachines/vm1"},
        ]

        # Run for App1
        df1 = _make_expert_analysis_df(items, app_name="App1")
        file1 = temp_workspace["root"] / "a1.xlsx"
        _write_excel_for_pipeline(df1, file1)

        build_hierarchy_incremental(
            report_path=str(file1),
            matrix_path=temp_workspace["matrix_path"],
            customer="cust",
            reviewed_only=False,
            app_name="App1",
            state_dir=str(temp_workspace["state_dir"]),
        )

        # Run for App2 (same resource type) — should start at 1
        items2 = [
            {"guid": "g2", "resource_id": "/subs/s/rg/r/p/microsoft.compute/virtualMachines/vm2"},
        ]
        df2 = _make_expert_analysis_df(items2, app_name="App2")
        file2 = temp_workspace["root"] / "a2.xlsx"
        _write_excel_for_pipeline(df2, file2)

        result2 = build_hierarchy_incremental(
            report_path=str(file2),
            matrix_path=temp_workspace["matrix_path"],
            customer="cust",
            reviewed_only=False,
            app_name="App2",
            state_dir=str(temp_workspace["state_dir"]),
        )

        stories2 = result2.hierarchy.all_stories()
        assert stories2[0].run_number == 1  # Independent from App1

    def test_different_resource_types_have_independent_counters(self, temp_workspace):
        """Different resource types within same app each start at run 1."""
        items_compute = [
            {"guid": "g1", "resource_id": "/subs/s/rg/r/p/microsoft.compute/virtualMachines/vm1",
             "resource_type": "microsoft.compute/virtualMachines"},
        ]
        items_storage = [
            {"guid": "g2", "resource_id": "/subs/s/rg/r/p/microsoft.storage/storageAccounts/sa1",
             "resource_type": "microsoft.storage/storageAccounts"},
        ]

        # Run compute first
        df1 = _make_expert_analysis_df(items_compute)
        file1 = temp_workspace["root"] / "compute.xlsx"
        _write_excel_for_pipeline(df1, file1)

        r1 = build_hierarchy_incremental(
            report_path=str(file1),
            matrix_path=temp_workspace["matrix_path"],
            customer="cust",
            reviewed_only=False,
            app_name="TestApp",
            state_dir=str(temp_workspace["state_dir"]),
        )
        # Compute is run 1
        compute_stories = [s for s in r1.hierarchy.all_stories()
                          if "compute" in s.resource_type.lower()]
        assert compute_stories[0].run_number == 1

        # Now run storage — should also be run 1 (independent counter)
        df2 = _make_expert_analysis_df(items_storage)
        file2 = temp_workspace["root"] / "storage.xlsx"
        _write_excel_for_pipeline(df2, file2)

        r2 = build_hierarchy_incremental(
            report_path=str(file2),
            matrix_path=temp_workspace["matrix_path"],
            customer="cust",
            reviewed_only=False,
            app_name="TestApp",
            state_dir=str(temp_workspace["state_dir"]),
        )
        storage_stories = [s for s in r2.hierarchy.all_stories()
                          if "storage" in s.resource_type.lower()]
        assert storage_stories[0].run_number == 1


class TestEdgeCases:
    """Edge cases for the incremental pipeline."""

    def test_empty_after_reviewed_filter(self, temp_workspace):
        """If no items pass the reviewed filter, pipeline returns empty."""
        items = [
            {"guid": "g1", "resource_id": "/subs/s/rg/r/providers/microsoft.compute/virtualMachines/vm1",
             "review_status": "Not Reviewed"},
        ]
        df = _make_expert_analysis_df(items)
        report_file = temp_workspace["root"] / "unreviewed.xlsx"
        _write_excel_for_pipeline(df, report_file)

        result = build_hierarchy_incremental(
            report_path=str(report_file),
            matrix_path=temp_workspace["matrix_path"],
            customer="cust",
            reviewed_only=True,
            app_name="TestApp",
            state_dir=str(temp_workspace["state_dir"]),
        )

        assert result.new_items_processed == 0
        assert len(result.hierarchy.all_stories()) == 0

    def test_multiple_customers_isolated(self, temp_workspace):
        """Different customers have fully isolated ledgers."""
        items = [
            {"guid": "g1", "resource_id": "/subs/s/rg/r/p/microsoft.compute/virtualMachines/vm1"},
        ]
        df = _make_expert_analysis_df(items)
        report = temp_workspace["root"] / "shared.xlsx"
        _write_excel_for_pipeline(df, report)

        # Customer A processes the items
        r1 = build_hierarchy_incremental(
            report_path=str(report),
            matrix_path=temp_workspace["matrix_path"],
            customer="customer-A",
            reviewed_only=False,
            app_name="TestApp",
            state_dir=str(temp_workspace["state_dir"]),
        )
        assert r1.new_items_processed == 1

        # Customer B should also see them as new
        r2 = build_hierarchy_incremental(
            report_path=str(report),
            matrix_path=temp_workspace["matrix_path"],
            customer="customer-B",
            reviewed_only=False,
            app_name="TestApp",
            state_dir=str(temp_workspace["state_dir"]),
        )
        assert r2.new_items_processed == 1
        assert r2.items_skipped_duplicate == 0

    def test_v2_to_v1_conversion(self, temp_workspace):
        """The V2→V1 hierarchy converter produces a valid V1 hierarchy."""
        from excellence_agent.cli import _convert_v2_to_v1

        items = [
            {"guid": "g1", "resource_id": "/subs/s/rg/r/p/microsoft.compute/virtualMachines/vm1"},
            {"guid": "g2", "resource_id": "/subs/s/rg/r/p/microsoft.compute/virtualMachines/vm2"},
        ]
        df = _make_expert_analysis_df(items)
        report = temp_workspace["root"] / "convert.xlsx"
        _write_excel_for_pipeline(df, report)

        result = build_hierarchy_incremental(
            report_path=str(report),
            matrix_path=temp_workspace["matrix_path"],
            customer="cust",
            reviewed_only=False,
            app_name="TestApp",
            state_dir=str(temp_workspace["state_dir"]),
        )

        v1 = _convert_v2_to_v1(result.hierarchy)
        assert len(v1.epics) >= 1
        assert len(v1.all_stories()) >= 1
        # V1 stories should have recommendations attached
        for story in v1.all_stories():
            assert len(story.recommendations) > 0
