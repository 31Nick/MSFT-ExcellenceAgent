"""Tests for flexible story creation — incremental pipeline, batch parser,
processing ledger, app registry, and v2 hierarchy.
"""

import tempfile
from pathlib import Path

import pandas as pd
import pytest

from excellence_agent.ado.processing_ledger import ProcessingLedger
from excellence_agent.applications import (
    AppRegistry,
    auto_detect_apps_from_directory,
    load_app_registry,
)
from excellence_agent.ingest.batch_parser import (
    COL_APP_NAME,
    COL_ENVIRONMENT,
    COL_SOURCE_FILE,
    COL_SUBSCRIPTION_NAME,
    filter_reviewed,
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
from excellence_agent.models import normalize_resource_type


# ── Fixtures ─────────────────────────────────────────────────────────────


def _make_sample_df(
    n_rows: int = 5,
    review_status: str = "Reviewed",
    app_name: str = "TestApp",
    resource_type: str = "microsoft.compute/virtualMachines",
) -> pd.DataFrame:
    """Create a sample DataFrame mimicking parsed APRL data."""
    rows = []
    for i in range(n_rows):
        rows.append({
            COL_REVIEW_STATUS: review_status,
            COL_RESOURCE_TYPE: resource_type,
            COL_SUBSCRIPTION_ID: f"sub-{i % 2}",
            COL_RESOURCE_GROUP: f"rg-{i}",
            "location": "eastus",
            "name": f"resource-{i}",
            COL_ID: f"/subscriptions/sub-{i % 2}/resourceGroups/rg-{i}/providers/{resource_type}/res-{i}",
            "custom1": "",
            "custom2": "",
            "custom3": "",
            "custom4": "",
            "custom5": "",
            COL_RECOMMENDATION_TITLE: f"Recommendation {i % 3}",
            COL_IMPACT: ["High", "Medium", "Low"][i % 3],
            COL_RECOMMENDATION_CONTROL: "Control",
            "Potential Benefit": "Benefit",
            "Learn More Link": "",
            "Long Description": "Description",
            COL_GUID: f"guid-{i % 3}",
            "Category": "Compute",
            "Source": "APRL",
            "WAF Pillar": "Reliability",
            "Notes": "",
            "checkName": "",
            COL_APP_NAME: app_name,
            COL_ENVIRONMENT: "Prod",
            COL_SUBSCRIPTION_NAME: "sub-name",
            COL_SOURCE_FILE: "test.xlsx",
            "MatrixCategory": "Compute",
        })
    return pd.DataFrame(rows)


# ── Review Status Filter Tests ───────────────────────────────────────────


class TestFilterReviewed:
    def test_filters_to_reviewed_only(self):
        """Only rows with 'Reviewed' status should pass."""
        df = pd.DataFrame({
            COL_REVIEW_STATUS: ["Reviewed", "Not Started", "", "Reviewed", None],
            "data": [1, 2, 3, 4, 5],
        })
        result = filter_reviewed(df)
        assert len(result) == 2
        assert list(result["data"]) == [1, 4]

    def test_case_insensitive(self):
        """Filter should be case-insensitive."""
        df = pd.DataFrame({
            COL_REVIEW_STATUS: ["REVIEWED", "reviewed", "Reviewed", "ReViEwEd"],
            "data": [1, 2, 3, 4],
        })
        result = filter_reviewed(df)
        assert len(result) == 4

    def test_trims_whitespace(self):
        """Leading/trailing whitespace should be ignored."""
        df = pd.DataFrame({
            COL_REVIEW_STATUS: ["  Reviewed  ", "Reviewed", " reviewed"],
            "data": [1, 2, 3],
        })
        result = filter_reviewed(df)
        assert len(result) == 3

    def test_empty_df_returns_empty(self):
        """Empty DataFrame should return empty."""
        df = pd.DataFrame({COL_REVIEW_STATUS: [], "data": []})
        result = filter_reviewed(df)
        assert len(result) == 0

    def test_no_reviewed_returns_empty(self):
        """If nothing is reviewed, result is empty."""
        df = pd.DataFrame({
            COL_REVIEW_STATUS: ["Not Started", "In Progress", ""],
            "data": [1, 2, 3],
        })
        result = filter_reviewed(df)
        assert len(result) == 0

    def test_missing_column_returns_all(self):
        """If the column doesn't exist, return all rows with a warning."""
        df = pd.DataFrame({"data": [1, 2, 3]})
        result = filter_reviewed(df)
        assert len(result) == 3


# ── Processing Ledger Tests ──────────────────────────────────────────────


class TestProcessingLedger:
    @pytest.fixture
    def ledger(self, tmp_path):
        return ProcessingLedger(state_dir=tmp_path)

    def test_initial_state_empty(self, ledger):
        """New ledger should have no processed items."""
        assert not ledger.is_already_processed("cust1", "app1", "guid-1", "res-1")
        assert ledger.get_already_processed_keys("cust1", "app1") == set()

    def test_record_and_check(self, ledger):
        """Recorded items should be found in subsequent checks."""
        ledger.record_processed("cust1", "app1", "guid-1", "res-1", run_number=1)
        assert ledger.is_already_processed("cust1", "app1", "guid-1", "res-1")
        assert not ledger.is_already_processed("cust1", "app1", "guid-1", "res-2")

    def test_different_app_not_shared(self, ledger):
        """Items from one app shouldn't appear in another."""
        ledger.record_processed("cust1", "app1", "guid-1", "res-1", run_number=1)
        assert not ledger.is_already_processed("cust1", "app2", "guid-1", "res-1")

    def test_batch_record(self, ledger):
        """Batch recording should insert all items."""
        items = [("guid-1", "res-1"), ("guid-2", "res-2"), ("guid-3", "res-3")]
        count = ledger.record_processed_batch("cust1", "app1", items, run_number=1)
        assert count == 3

        keys = ledger.get_already_processed_keys("cust1", "app1")
        assert len(keys) == 3
        assert ("guid-1", "res-1") in keys

    def test_batch_ignores_duplicates(self, ledger):
        """Duplicate records should be silently ignored."""
        items = [("guid-1", "res-1")]
        ledger.record_processed_batch("cust1", "app1", items, run_number=1)
        count = ledger.record_processed_batch("cust1", "app1", items, run_number=2)
        assert count == 0  # Already existed

    def test_run_number_increments(self, ledger):
        """Run numbers should increment independently per (app, rt)."""
        assert ledger.get_next_run_number("cust1", "app1", "microsoft.compute/virtualmachines") == 1
        assert ledger.get_next_run_number("cust1", "app1", "microsoft.compute/virtualmachines") == 2
        assert ledger.get_next_run_number("cust1", "app1", "microsoft.storage/storageaccounts") == 1
        assert ledger.get_next_run_number("cust1", "app2", "microsoft.compute/virtualmachines") == 1

    def test_peek_does_not_increment(self, ledger):
        """Peek should return next number without changing state."""
        assert ledger.peek_next_run_number("cust1", "app1", "rt") == 1
        assert ledger.peek_next_run_number("cust1", "app1", "rt") == 1
        ledger.get_next_run_number("cust1", "app1", "rt")
        assert ledger.peek_next_run_number("cust1", "app1", "rt") == 2

    def test_reset_clears_data(self, ledger):
        """Reset should clear all data for a customer/app."""
        ledger.record_processed("cust1", "app1", "guid-1", "res-1", run_number=1)
        ledger.get_next_run_number("cust1", "app1", "rt")
        ledger.reset("cust1", "app1")
        assert not ledger.is_already_processed("cust1", "app1", "guid-1", "res-1")
        assert ledger.peek_next_run_number("cust1", "app1", "rt") == 1

    def test_stats(self, ledger):
        """Stats should reflect current state."""
        ledger.record_processed_batch("cust1", "app1", [("g1", "r1"), ("g2", "r2")], run_number=1)
        ledger.get_next_run_number("cust1", "app1", "rt1")
        stats = ledger.get_stats("cust1", "app1")
        assert stats["total_processed"] == 2
        assert stats["total_runs"] == 1


# ── Application Registry Tests ───────────────────────────────────────────


class TestAppRegistry:
    def test_add_and_list(self):
        """Should add and retrieve apps."""
        reg = AppRegistry()
        reg.add_app("MyApp", description="Test app")
        reg.add_app("AnotherApp")
        apps = reg.list_apps()
        assert len(apps) == 2
        assert apps[0].name == "AnotherApp"  # sorted
        assert apps[1].name == "MyApp"

    def test_case_insensitive_lookup(self):
        """App lookup should be case-insensitive."""
        reg = AppRegistry()
        reg.add_app("MyApp")
        assert reg.has_app("myapp")
        assert reg.has_app("MYAPP")
        assert reg.get_app("myapp").name == "MyApp"

    def test_remove_app(self):
        """Should remove apps by name."""
        reg = AppRegistry()
        reg.add_app("MyApp")
        assert reg.remove_app("myapp")
        assert not reg.has_app("MyApp")
        assert not reg.remove_app("nonexistent")

    def test_save_and_load(self, tmp_path):
        """Should persist to YAML and reload correctly."""
        config_path = tmp_path / "applications.yaml"
        reg = AppRegistry(config_path=config_path)
        reg.add_app("App1", description="First", environments=["Prod"])
        reg.add_app("App2", subscriptions=["sub-1"])
        reg.save()

        loaded = load_app_registry(config_path)
        assert len(loaded.apps) == 2
        assert loaded.get_app("app1").description == "First"
        assert loaded.get_app("app2").subscriptions == ["sub-1"]

    def test_load_missing_file_returns_empty(self, tmp_path):
        """Loading from a nonexistent path should return empty registry."""
        reg = load_app_registry(tmp_path / "missing.yaml")
        assert len(reg.apps) == 0

    def test_auto_detect_from_directory(self, tmp_path):
        """Should detect apps from directory structure."""
        (tmp_path / "AppOne" / "Prod").mkdir(parents=True)
        (tmp_path / "AppTwo" / "Other envs").mkdir(parents=True)
        (tmp_path / ".hidden").mkdir()  # should be skipped

        reg = AppRegistry(config_path=tmp_path / "apps.yaml")
        new_apps = auto_detect_apps_from_directory(tmp_path, reg, save=False)

        assert "AppOne" in new_apps
        assert "AppTwo" in new_apps
        assert len(new_apps) == 2
        assert reg.has_app("AppOne")

    def test_auto_detect_skips_existing(self, tmp_path):
        """Already-registered apps should not be re-added."""
        (tmp_path / "AppOne").mkdir()

        reg = AppRegistry(config_path=tmp_path / "apps.yaml")
        reg.add_app("AppOne")
        new_apps = auto_detect_apps_from_directory(tmp_path, reg, save=False)
        assert new_apps == []


# ── V2 Models Tests ──────────────────────────────────────────────────────


class TestModelsV2:
    def test_stable_keys(self):
        """Stable keys should include app name and version prefix."""
        from excellence_agent.models_v2 import EpicV2, FeatureV2, UserStoryV2

        epic = EpicV2(app_name="MyApp")
        feature = FeatureV2(category_key="compute", category_name="Compute")
        epic.add_feature(feature)

        story = UserStoryV2(
            title="Virtual Machines - Recommendations 1",
            resource_type="microsoft.compute/virtualmachines",
            resource_type_display="Virtual Machines",
            run_number=1,
            impact="High",
        )
        feature.add_user_story(story)

        assert epic.stable_key == "v2:epic:myapp"
        assert feature.stable_key == "v2:feature:myapp:compute"
        assert story.stable_key == "v2:story:myapp:compute:microsoft.compute/virtualmachines:1"

    def test_hierarchy_stats(self):
        """Summary stats should be accurate."""
        from excellence_agent.models import Recommendation
        from excellence_agent.models_v2 import (
            EpicV2,
            FeatureV2,
            UserStoryV2,
            WorkItemHierarchyV2,
        )

        hierarchy = WorkItemHierarchyV2()
        epic = EpicV2(app_name="App1")
        feature = FeatureV2(category_key="compute", category_name="Compute")
        epic.add_feature(feature)

        story = UserStoryV2(
            title="VMs - Recommendations 1",
            resource_type="microsoft.compute/virtualmachines",
            resource_type_display="Virtual Machines",
            run_number=1,
            impact="High",
        )
        story.add_recommendation(Recommendation(
            title="Enable AZ",
            recommendation_guid="g1",
            impact="High",
            recommendation_control="Control",
        ))
        feature.add_user_story(story)
        hierarchy.add_epic(epic)

        stats = hierarchy.summary_stats()
        assert stats["epics"] == 1
        assert stats["features"] == 1
        assert stats["user_stories"] == 1
        assert stats["recommendations"] == 1


# ── V2 Grouper Tests ────────────────────────────────────────────────────


class TestHierarchyBuilderV2:
    def test_basic_build(self):
        """Should create app-centric hierarchy from DataFrame."""
        from excellence_agent.analysis.grouper_v2 import HierarchyBuilderV2

        df = _make_sample_df(n_rows=5, app_name="TestApp")
        builder = HierarchyBuilderV2(run_number_fn=lambda app, rt: 1)
        hierarchy = builder.build(df)

        assert len(hierarchy.epics) == 1
        assert hierarchy.epics[0].app_name == "TestApp"
        assert len(hierarchy.all_features()) == 1  # one category
        assert len(hierarchy.all_stories()) == 1  # one resource type
        story = hierarchy.all_stories()[0]
        assert "Recommendations 1" in story.title
        assert story.run_number == 1

    def test_multiple_apps(self):
        """Should create separate epics per app."""
        from excellence_agent.analysis.grouper_v2 import HierarchyBuilderV2

        df1 = _make_sample_df(n_rows=3, app_name="App1")
        df2 = _make_sample_df(n_rows=2, app_name="App2")
        df = pd.concat([df1, df2], ignore_index=True)

        builder = HierarchyBuilderV2(run_number_fn=lambda app, rt: 1)
        hierarchy = builder.build(df)

        assert len(hierarchy.epics) == 2
        app_names = {e.app_name for e in hierarchy.epics}
        assert app_names == {"App1", "App2"}

    def test_run_number_applied(self):
        """Run number from callback should appear in story title and key."""
        from excellence_agent.analysis.grouper_v2 import HierarchyBuilderV2

        df = _make_sample_df(n_rows=3, app_name="TestApp")
        builder = HierarchyBuilderV2(run_number_fn=lambda app, rt: 3)
        hierarchy = builder.build(df)

        story = hierarchy.all_stories()[0]
        assert "Recommendations 3" in story.title
        assert story.run_number == 3
        assert ":3" in story.stable_key

    def test_multiple_resource_types(self):
        """Different resource types should produce separate stories."""
        from excellence_agent.analysis.grouper_v2 import HierarchyBuilderV2

        df1 = _make_sample_df(n_rows=2, resource_type="microsoft.compute/virtualMachines")
        df2 = _make_sample_df(n_rows=2, resource_type="microsoft.storage/storageAccounts")
        df2["MatrixCategory"] = "Storage"
        df = pd.concat([df1, df2], ignore_index=True)

        builder = HierarchyBuilderV2(run_number_fn=lambda app, rt: 1)
        hierarchy = builder.build(df)

        # Should have two features (Compute, Storage) with one story each
        assert len(hierarchy.all_features()) == 2
        assert len(hierarchy.all_stories()) == 2
