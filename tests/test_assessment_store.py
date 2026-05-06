"""Tests for multi-assessment persistence: AssessmentStore, from_dict round-trip, API endpoints."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from excellence_agent.ado.assessment_store import AssessmentStore, AssessmentSummary
from excellence_agent.models import AffectedResource, Recommendation
from excellence_agent.models_v2 import (
    EpicV2,
    FeatureV2,
    UserStoryV2,
    WorkItemHierarchyV2,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_state_dir(tmp_path):
    return tmp_path / "state"


@pytest.fixture
def store(tmp_state_dir):
    return AssessmentStore(state_dir=tmp_state_dir)


def _build_sample_hierarchy() -> WorkItemHierarchyV2:
    ar = AffectedResource(
        resource_name="vm-prod-01",
        resource_id="/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm-prod-01",
        resource_group="rg1",
        subscription_id="sub1",
        location="eastus",
        validation_status="Validated",
        notes="Needs resize",
        check_name="UseAvailabilityZones",
        custom_fields={"env": "prod"},
    )
    rec = Recommendation(
        title="Enable Availability Zones",
        recommendation_guid="guid-001",
        impact="High",
        recommendation_control="AZ-01",
        potential_benefit="Improved uptime",
        learn_more_link="https://example.com",
        long_description="Long desc here",
        waf_pillar="Reliability",
        category="Compute",
        source="APRL",
        advisor_metadata={"score": "95"},
        affected_resources=[ar],
    )
    story = UserStoryV2(
        title="Virtual Machines - Recommendations 1",
        resource_type="microsoft.compute/virtualmachines",
        resource_type_display="Virtual Machines",
        run_number=1,
        impact="High",
        category="Compute",
        source="APRL",
        waf_pillars={"Reliability", "Performance Efficiency"},
        resource_count=1,
        recommendations=[rec],
    )
    feat = FeatureV2(
        category_key="compute",
        category_name="Compute",
        description="Compute resources",
        resource_types={"microsoft.compute/virtualmachines"},
        resource_groups={"rg1"},
        subscriptions={"sub1"},
        resource_count=1,
    )
    feat.add_user_story(story)
    epic = EpicV2(
        app_name="TestApp",
        description="Test application",
        total_resource_count=1,
        waf_pillars={"Reliability"},
        impact_summary={"High": 1},
        environments={"Production"},
    )
    epic.add_feature(feat)
    hierarchy = WorkItemHierarchyV2()
    hierarchy.add_epic(epic)
    return hierarchy


# ---------------------------------------------------------------------------
# from_dict round-trip tests
# ---------------------------------------------------------------------------


class TestFromDict:
    def test_affected_resource_round_trip(self):
        ar = AffectedResource(
            resource_name="vm1", resource_id="/sub/rg/vm1",
            resource_group="rg", subscription_id="sub",
            location="westus", validation_status="OK",
            notes="note", check_name="chk",
            custom_fields={"k": "v"},
        )
        d = ar.to_dict()
        ar2 = AffectedResource.from_dict(d)
        assert ar2.resource_name == "vm1"
        assert ar2.custom_fields == {"k": "v"}

    def test_recommendation_round_trip(self):
        ar = AffectedResource(resource_name="r1", resource_id="id1", resource_group="rg", subscription_id="s", location="l")
        rec = Recommendation(
            title="Rec", recommendation_guid="g1", impact="High",
            recommendation_control="c1", potential_benefit="benefit",
            affected_resources=[ar],
        )
        d = rec.to_dict()
        rec2 = Recommendation.from_dict(d)
        assert rec2.title == "Rec"
        assert len(rec2.affected_resources) == 1
        assert rec2.affected_resources[0].resource_name == "r1"

    def test_user_story_v2_round_trip(self):
        rec = Recommendation(title="R", recommendation_guid="g", impact="Medium", recommendation_control="c")
        story = UserStoryV2(
            title="S1", resource_type="microsoft.compute/virtualmachines",
            resource_type_display="VMs", run_number=3, impact="Medium",
            category="Compute", source="APRL", waf_pillars={"Reliability"},
            resource_count=5, recommendations=[rec],
        )
        d = story.to_dict()
        s2 = UserStoryV2.from_dict(d)
        assert s2.title == "S1"
        assert s2.run_number == 3
        assert s2.waf_pillars == {"Reliability"}
        assert s2.priority == 2  # Medium -> 2

    def test_feature_v2_round_trip(self):
        story = UserStoryV2(
            title="S", resource_type="t", resource_type_display="T",
            run_number=1, impact="Low", category="C", source="APRL",
            waf_pillars=set(), resource_count=0, recommendations=[],
        )
        feat = FeatureV2(
            category_key="k", category_name="N",
            resource_types={"t"}, resource_groups={"rg1", "rg2"},
            subscriptions={"s1"}, resource_count=2,
        )
        feat.add_user_story(story)
        d = feat.to_dict()
        f2 = FeatureV2.from_dict(d)
        assert f2.category_key == "k"
        assert len(f2.user_stories) == 1
        assert f2.resource_groups == {"rg1", "rg2"}

    def test_epic_v2_round_trip(self):
        feat = FeatureV2(category_key="k", category_name="N")
        epic = EpicV2(
            app_name="MyApp", description="desc",
            total_resource_count=10, waf_pillars={"Reliability", "Security"},
            impact_summary={"High": 5, "Medium": 5},
            environments={"Prod", "Dev"},
        )
        epic.add_feature(feat)
        d = epic.to_dict()
        e2 = EpicV2.from_dict(d)
        assert e2.app_name == "MyApp"
        assert e2.waf_pillars == {"Reliability", "Security"}
        assert len(e2.features) == 1

    def test_full_hierarchy_round_trip(self):
        h = _build_sample_hierarchy()
        d = h.to_dict()
        h2 = WorkItemHierarchyV2.from_dict(d)
        assert len(h2.epics) == 1
        assert h2.epics[0].app_name == "TestApp"
        assert len(h2.all_features()) == 1
        assert len(h2.all_stories()) == 1
        story = h2.all_stories()[0]
        assert story.title == "Virtual Machines - Recommendations 1"
        assert story.run_number == 1
        assert len(story.recommendations) == 1
        rec = story.recommendations[0]
        assert rec.title == "Enable Availability Zones"
        assert rec.advisor_metadata == {"score": "95"}
        assert len(rec.affected_resources) == 1
        ar = rec.affected_resources[0]
        assert ar.resource_name == "vm-prod-01"
        assert ar.custom_fields == {"env": "prod"}


# ---------------------------------------------------------------------------
# AssessmentStore CRUD tests
# ---------------------------------------------------------------------------


class TestAssessmentStore:
    def test_save_and_load(self, store):
        h = _build_sample_hierarchy()
        aid = store.save("App1", h.to_dict(), h.summary_stats(), source_filename="f.xlsx", items_processed=5)
        assert aid == 1

        loaded = store.load_hierarchy_dict(aid)
        assert loaded is not None
        h2 = WorkItemHierarchyV2.from_dict(loaded)
        assert h2.epics[0].app_name == "TestApp"

    def test_list_and_filter(self, store):
        store.save("App1", {"epics": []}, {})
        store.save("App2", {"epics": []}, {})
        store.save("App1", {"epics": []}, {})

        all_a = store.list_assessments()
        assert len(all_a) == 3

        app1_only = store.list_assessments(app_name="App1")
        assert len(app1_only) == 2
        assert all(a.app_name == "App1" for a in app1_only)

    def test_get_latest(self, store):
        store.save("App1", {"epics": []}, {}, items_processed=1)
        store.save("App2", {"epics": []}, {}, items_processed=2)
        store.save("App1", {"epics": []}, {}, items_processed=3)

        latest = store.get_latest()
        assert latest is not None
        assert latest.items_processed == 3

        latest_app2 = store.get_latest(app_name="App2")
        assert latest_app2 is not None
        assert latest_app2.items_processed == 2

    def test_delete(self, store):
        aid = store.save("App1", {"epics": []}, {})
        assert store.delete(aid) is True
        assert store.delete(aid) is False  # already deleted
        assert store.load_hierarchy_dict(aid) is None

    def test_summary_fields(self, store):
        aid = store.save(
            "TestApp", {"epics": []}, {"user_stories": 5},
            source_filename="report.xlsx", reviewed_only=False,
            items_processed=10, items_skipped=3,
        )
        summary = store.get_summary(aid)
        assert summary is not None
        assert summary.app_name == "TestApp"
        assert summary.source_filename == "report.xlsx"
        assert summary.reviewed_only is False
        assert summary.stats == {"user_stories": 5}
        assert summary.items_processed == 10
        assert summary.items_skipped == 3

    def test_nonexistent_returns_none(self, store):
        assert store.load_hierarchy_dict(999) is None
        assert store.get_summary(999) is None
        assert store.get_latest() is None


# ---------------------------------------------------------------------------
# Web API integration tests
# ---------------------------------------------------------------------------


class TestAssessmentAPI:
    @pytest.fixture
    def client(self, tmp_state_dir):
        from excellence_agent.config import Config
        from excellence_agent.web.app import create_app

        config = Config.from_env()
        app = create_app(config)
        app.config["EA_ASSESSMENT_STORE"] = AssessmentStore(state_dir=tmp_state_dir)
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c

    def test_list_empty(self, client):
        resp = client.get("/api/assessments")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["assessments"] == []

    def test_save_and_list(self, client):
        # Upload triggers save — simulate by saving directly
        store = AssessmentStore(state_dir=Path(client.application.config["EA_ASSESSMENT_STORE"]._state_dir))
        aid = store.save("App1", {"epics": []}, {"user_stories": 2}, items_processed=5)

        resp = client.get("/api/assessments")
        data = resp.get_json()
        assert len(data["assessments"]) == 1
        assert data["assessments"][0]["app_name"] == "App1"

    def test_load_assessment(self, client):
        h = _build_sample_hierarchy()
        store = client.application.config["EA_ASSESSMENT_STORE"]
        aid = store.save("TestApp", h.to_dict(), h.summary_stats(), items_processed=1)

        resp = client.get(f"/api/assessments/{aid}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["app_name"] == "TestApp"
        assert client.application.config["EA_ACTIVE_ASSESSMENT_ID"] == aid

    def test_load_nonexistent(self, client):
        resp = client.get("/api/assessments/999")
        assert resp.status_code == 404

    def test_delete_assessment(self, client):
        store = client.application.config["EA_ASSESSMENT_STORE"]
        aid = store.save("App1", {"epics": []}, {})
        client.application.config["EA_ACTIVE_ASSESSMENT_ID"] = aid

        resp = client.delete(f"/api/assessments/{aid}")
        assert resp.status_code == 200
        assert client.application.config["EA_ACTIVE_ASSESSMENT_ID"] is None

    def test_active_assessment_endpoint(self, client):
        resp = client.get("/api/assessments/active")
        data = resp.get_json()
        assert data["active"] is None

        store = client.application.config["EA_ASSESSMENT_STORE"]
        aid = store.save("App1", {"epics": []}, {"user_stories": 0})
        client.application.config["EA_ACTIVE_ASSESSMENT_ID"] = aid

        resp = client.get("/api/assessments/active")
        data = resp.get_json()
        assert data["active"]["app_name"] == "App1"
