"""Integration test: full config → plan → mock-push → state → re-plan cycle.

This test exercises the complete sync workflow end-to-end using mocked
MCP calls but real state store, real content generator, and real hierarchy.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from excellence_agent.ado.customer_config import CustomerConfig, WorkItemTypeMapping
from excellence_agent.ado.mcp_client import ADOMCPClient
from excellence_agent.ado.state_store import SyncStateStore
from excellence_agent.ado.sync_service import AdoSyncService
from excellence_agent.export.content_generator import ContentGenerator
from excellence_agent.models import Epic, Feature, Task, UserStory, WorkItemHierarchy


def _make_hierarchy() -> WorkItemHierarchy:
    """Build a small but realistic hierarchy: 1 Epic, 1 Feature, 1 Story, 2 Tasks."""
    epic = Epic(name="Networking", description="Network resilience")
    feat = Feature(name="Virtual Networks", resource_type="microsoft.network/virtualnetworks")
    epic.add_feature(feat)

    story = UserStory(
        title="Use Standard SKU load balancers",
        recommendation_guid="abc-123",
        impact="High",
        recommendation_control="HighAvailability",
        potential_benefit="Improved SLA",
        learn_more_link="https://example.com",
        long_description="Upgrade to Standard SKU LBs.",
        waf_pillar="Reliability",
        category="Networking",
        source="APRL",
    )
    feat.add_user_story(story)

    t1 = Task(
        resource_name="my-lb-01",
        resource_id="/subs/1/rg/net/providers/Microsoft.Network/loadBalancers/my-lb-01",
        resource_group="net-rg",
        subscription_id="sub-1",
        location="eastus",
        validation_status="Fail",
    )
    t2 = Task(
        resource_name="my-lb-02",
        resource_id="/subs/1/rg/net/providers/Microsoft.Network/loadBalancers/my-lb-02",
        resource_group="net-rg",
        subscription_id="sub-1",
        location="westus",
        validation_status="Fail",
    )
    story.add_task(t1)
    story.add_task(t2)

    return WorkItemHierarchy(epics=[epic])


@pytest.fixture
def config():
    return CustomerConfig(
        slug="integtest",
        customer_name="Integration Test Corp",
        organization="test-org",
        project="test-project",
        pat="fake-pat-for-test",
        type_mapping=WorkItemTypeMapping(),
    )


@pytest.fixture
def store(tmp_path):
    return SyncStateStore(state_dir=tmp_path / ".state")


@pytest.fixture
def service(store, config):
    cg = ContentGenerator()
    return AdoSyncService(state_store=store, content_generator=cg, config=config)


@pytest.fixture
def hierarchy():
    return _make_hierarchy()


class TestFullSyncCycle:
    """End-to-end: plan → push → re-plan → verify unchanged."""

    def test_first_plan_all_creates(self, service, hierarchy):
        plan = service.plan(hierarchy)
        assert plan.summary()["create"] == 5  # 1 epic + 1 feat + 1 story + 2 tasks
        assert plan.summary()["unchanged"] == 0

    @pytest.mark.asyncio
    async def test_push_then_replan_shows_unchanged(self, service, store, config, hierarchy):
        # Plan
        plan = service.plan(hierarchy)
        assert plan.summary()["create"] == 5

        # Mock MCP client
        ado_id_counter = [100]

        async def mock_create(work_item_type, fields, **kw):
            ado_id_counter[0] += 1
            return ado_id_counter[0]

        async def mock_link(parent_id, child_id, **kw):
            return {"ok": True}

        client = AsyncMock(spec=ADOMCPClient)
        client.create_work_item = AsyncMock(side_effect=mock_create)
        client.link_work_items = AsyncMock(side_effect=mock_link)
        client.update_work_item = AsyncMock(return_value=2)

        # Push
        result = await service.push(plan, client)
        assert result.success
        assert result.run.items_created == 5
        assert result.run.items_failed == 0

        # Re-plan should show all unchanged
        plan2 = service.plan(hierarchy)
        assert plan2.summary()["create"] == 0
        assert plan2.summary()["unchanged"] == 5

    @pytest.mark.asyncio
    async def test_partial_failure_and_retry(self, service, store, config, hierarchy):
        plan = service.plan(hierarchy)

        call_count = [0]

        async def mock_create_with_failure(work_item_type, fields, **kw):
            call_count[0] += 1
            if call_count[0] == 3:  # Fail on 3rd item (the story)
                from excellence_agent.ado.mcp_client import MCPClientError
                raise MCPClientError("Simulated timeout")
            return 100 + call_count[0]

        client = AsyncMock(spec=ADOMCPClient)
        client.create_work_item = AsyncMock(side_effect=mock_create_with_failure)
        client.link_work_items = AsyncMock(return_value={"ok": True})
        client.update_work_item = AsyncMock(return_value=2)

        # Push — 1 item should fail
        result = await service.push(plan, client)
        assert not result.success
        assert result.run.items_failed >= 1

        # Check failed items in store
        failed = store.get_items_for_retry(config.slug)
        assert len(failed) >= 1

        # Re-plan — failed items should show up as creates (since they weren't created)
        plan2 = service.plan(hierarchy)
        assert plan2.summary()["create"] >= 1

    def test_state_store_isolation(self, store, service, hierarchy, config):
        """Items for one customer don't leak to another."""
        plan = service.plan(hierarchy)
        assert plan.summary()["create"] == 5

        # Different customer should see no items
        other_items = store.get_items_by_customer("other-customer")
        assert len(other_items) == 0

    @pytest.mark.asyncio
    async def test_change_detection_after_push(self, service, store, config):
        """Modifying the hierarchy should produce update items on re-plan."""
        h1 = _make_hierarchy()
        plan1 = service.plan(h1)

        client = AsyncMock(spec=ADOMCPClient)
        ado_counter = [200]

        async def mock_create(wt, fields, **kw):
            ado_counter[0] += 1
            return ado_counter[0]

        client.create_work_item = AsyncMock(side_effect=mock_create)
        client.link_work_items = AsyncMock(return_value={"ok": True})

        await service.push(plan1, client)

        # Now build a modified hierarchy (different epic description)
        h2 = _make_hierarchy()
        h2.epics[0].description = "CHANGED: Network resilience and security"

        plan2 = service.plan(h2)
        # Epic should be update, rest unchanged
        assert plan2.summary()["update"] >= 1
        assert plan2.summary()["unchanged"] >= 3
