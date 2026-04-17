"""Tests for excellence_agent.ado.sync_service (plan + push + retry)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from excellence_agent.ado.customer_config import CustomerConfig, WorkItemTypeMapping
from excellence_agent.ado.mcp_client import ADOMCPClient, MCPClientError, WorkItem
from excellence_agent.ado.state_store import SyncItem, SyncStateStore
from excellence_agent.ado.sync_service import AdoSyncService, SyncPlan
from excellence_agent.export.content_generator import ContentGenerator
from excellence_agent.models import Epic, Feature, Task, UserStory, WorkItemHierarchy


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture()
def config() -> CustomerConfig:
    return CustomerConfig(
        slug="test-customer",
        customer_name="Test Corp",
        organization="test-org",
        project="TestProject",
        pat="fake-pat",
        type_mapping=WorkItemTypeMapping(),
    )


@pytest.fixture()
def store(tmp_path: Path) -> SyncStateStore:
    return SyncStateStore(state_dir=tmp_path / ".state")


@pytest.fixture()
def cg() -> ContentGenerator:
    return ContentGenerator()


@pytest.fixture()
def service(store: SyncStateStore, cg: ContentGenerator, config: CustomerConfig) -> AdoSyncService:
    return AdoSyncService(state_store=store, content_generator=cg, config=config)


@pytest.fixture()
def small_hierarchy() -> WorkItemHierarchy:
    """Build a minimal hierarchy: 1 Epic → 1 Feature → 1 Story → 1 Task."""
    h = WorkItemHierarchy()
    epic = Epic(name="Networking", description="Network resources")
    feat = Feature(name="VNets", resource_type="microsoft.network/virtualnetworks")
    epic.add_feature(feat)
    story = UserStory(
        title="Enable DDoS protection",
        recommendation_guid="guid-001",
        impact="High",
        recommendation_control="Automated",
        long_description="Enable DDoS on all VNets.",
        waf_pillar="Security",
        learn_more_link="https://aka.ms/ddos",
    )
    feat.add_user_story(story)
    task = Task(
        resource_name="vnet-hub",
        resource_id="/subscriptions/sub-1/resourceGroups/rg-net/providers/Microsoft.Network/virtualNetworks/vnet-hub",
        resource_group="rg-net",
        subscription_id="sub-1",
        location="uksouth",
        check_name="check-ddos",
    )
    story.add_task(task)
    h.add_epic(epic)
    return h


@pytest.fixture()
def mock_mcp() -> AsyncMock:
    """Mock ADOMCPClient with auto-incrementing IDs."""
    client = AsyncMock(spec=ADOMCPClient)
    _counter = {"id": 100}

    async def _create_work_item(work_item_type, fields, **kw):
        _counter["id"] += 1
        return _counter["id"]

    async def _update_work_item(wi_id, fields):
        return 2  # rev

    async def _link_work_items(source_id, target_id, link_type=""):
        return True

    client.create_work_item = AsyncMock(side_effect=_create_work_item)
    client.update_work_item = AsyncMock(side_effect=_update_work_item)
    client.link_work_items = AsyncMock(side_effect=_link_work_items)
    return client


# ── Plan tests ────────────────────────────────────────────────────────────


class TestPlan:
    def test_first_run_all_creates(
        self, service: AdoSyncService, small_hierarchy: WorkItemHierarchy
    ) -> None:
        plan = service.plan(small_hierarchy)
        assert len(plan.to_create) == 4  # Epic + Feature + Story + Task
        assert len(plan.to_update) == 0
        assert len(plan.unchanged) == 0
        assert len(plan.orphaned) == 0

        types = [pi.work_item_type for pi in plan.to_create]
        assert "Epic" in types
        assert "Feature" in types
        assert "User Story" in types
        assert "Task" in types

    def test_second_run_unchanged(
        self, service: AdoSyncService, store: SyncStateStore,
        small_hierarchy: WorkItemHierarchy, config: CustomerConfig,
    ) -> None:
        # First plan → all creates
        plan1 = service.plan(small_hierarchy)
        assert len(plan1.to_create) == 4

        # Simulate that they were synced (save state with correct hashes)
        for pi in plan1.to_create:
            store.upsert_item(SyncItem(
                stable_key=pi.stable_key,
                customer=config.slug,
                ado_work_item_id=999,
                work_item_type=pi.work_item_type,
                title=pi.title,
                content_hash=pi.content_hash,
                parent_stable_key=pi.parent_stable_key,
                sync_status="created",
            ))

        # Second plan → all unchanged
        plan2 = service.plan(small_hierarchy)
        assert len(plan2.to_create) == 0
        assert len(plan2.to_update) == 0
        assert len(plan2.unchanged) == 4

    def test_change_triggers_update(
        self, service: AdoSyncService, store: SyncStateStore,
        small_hierarchy: WorkItemHierarchy, config: CustomerConfig,
    ) -> None:
        plan1 = service.plan(small_hierarchy)
        # Save items with WRONG hash to trigger update
        for pi in plan1.to_create:
            store.upsert_item(SyncItem(
                stable_key=pi.stable_key,
                customer=config.slug,
                ado_work_item_id=500,
                work_item_type=pi.work_item_type,
                title=pi.title,
                content_hash="stale-hash",
                parent_stable_key=pi.parent_stable_key,
                sync_status="created",
            ))

        plan2 = service.plan(small_hierarchy)
        assert len(plan2.to_update) == 4
        assert len(plan2.to_create) == 0

    def test_orphan_detection(
        self, service: AdoSyncService, store: SyncStateStore,
        config: CustomerConfig,
    ) -> None:
        # Pre-populate state with an item that doesn't exist in hierarchy
        store.upsert_item(SyncItem(
            stable_key="epic:deleted-category",
            customer=config.slug,
            ado_work_item_id=777,
            work_item_type="Epic",
            title="Deleted Category",
            content_hash="old-hash",
            sync_status="created",
        ))

        # Plan against empty hierarchy
        plan = service.plan(WorkItemHierarchy())
        assert len(plan.orphaned) == 1
        assert plan.orphaned[0].stable_key == "epic:deleted-category"

    def test_plan_summary(
        self, service: AdoSyncService, small_hierarchy: WorkItemHierarchy
    ) -> None:
        plan = service.plan(small_hierarchy)
        s = plan.summary()
        assert s["create"] == 4
        assert s["total"] == 4


# ── Push tests ────────────────────────────────────────────────────────────


class TestPush:
    @pytest.mark.asyncio
    async def test_push_creates_all_items(
        self, service: AdoSyncService, store: SyncStateStore,
        small_hierarchy: WorkItemHierarchy, mock_mcp: AsyncMock,
    ) -> None:
        plan = service.plan(small_hierarchy)
        result = await service.push(plan, mock_mcp)

        assert result.success
        assert result.run.items_created == 4
        assert result.run.items_failed == 0
        assert result.run.status == "completed"

        # Verify state store was updated
        items = store.get_items_by_customer("test-customer")
        assert len(items) == 4
        assert all(i.ado_work_item_id is not None for i in items)
        assert all(i.sync_status == "created" for i in items)

    @pytest.mark.asyncio
    async def test_push_links_children_to_parents(
        self, service: AdoSyncService, small_hierarchy: WorkItemHierarchy,
        mock_mcp: AsyncMock,
    ) -> None:
        plan = service.plan(small_hierarchy)
        await service.push(plan, mock_mcp)

        # Feature, Story, Task should each trigger a link call (3 children)
        assert mock_mcp.link_work_items.await_count == 3

    @pytest.mark.asyncio
    async def test_push_handles_partial_failure(
        self, service: AdoSyncService, store: SyncStateStore,
        small_hierarchy: WorkItemHierarchy, mock_mcp: AsyncMock,
    ) -> None:
        call_count = {"n": 0}
        async def _failing_create(work_item_type, fields, **kw):
            call_count["n"] += 1
            if call_count["n"] == 3:  # Third create fails
                raise MCPClientError("Simulated failure")
            return 200 + call_count["n"]

        mock_mcp.create_work_item = AsyncMock(side_effect=_failing_create)

        plan = service.plan(small_hierarchy)
        result = await service.push(plan, mock_mcp)

        assert not result.success
        assert result.run.items_created == 3
        assert result.run.items_failed == 1
        assert result.run.status == "failed"
        assert len(result.errors) == 1

        # Failed item is in state store with status 'failed'
        failed = store.get_items_for_retry("test-customer")
        assert len(failed) == 1

    @pytest.mark.asyncio
    async def test_push_updates_existing(
        self, service: AdoSyncService, store: SyncStateStore,
        small_hierarchy: WorkItemHierarchy, mock_mcp: AsyncMock,
        config: CustomerConfig,
    ) -> None:
        # Pre-populate state with stale hashes to force updates
        plan1 = service.plan(small_hierarchy)
        for pi in plan1.to_create:
            store.upsert_item(SyncItem(
                stable_key=pi.stable_key,
                customer=config.slug,
                ado_work_item_id=500,
                work_item_type=pi.work_item_type,
                title=pi.title,
                content_hash="stale-hash",
                parent_stable_key=pi.parent_stable_key,
                sync_status="created",
            ))

        plan2 = service.plan(small_hierarchy)
        assert len(plan2.to_update) == 4

        result = await service.push(plan2, mock_mcp)
        assert result.success
        assert result.run.items_updated == 4

    @pytest.mark.asyncio
    async def test_push_marks_orphans(
        self, service: AdoSyncService, store: SyncStateStore,
        mock_mcp: AsyncMock, config: CustomerConfig,
    ) -> None:
        store.upsert_item(SyncItem(
            stable_key="epic:old",
            customer=config.slug,
            ado_work_item_id=888,
            work_item_type="Epic",
            title="Old Epic",
            content_hash="hash",
            sync_status="created",
        ))

        plan = service.plan(WorkItemHierarchy())
        assert len(plan.orphaned) == 1

        result = await service.push(plan, mock_mcp)
        assert result.run.items_orphaned == 1

        orphaned = store.get_item("epic:old", config.slug)
        assert orphaned is not None
        assert orphaned.sync_status == "orphaned"


# ── Retry tests ───────────────────────────────────────────────────────────


class TestRetry:
    @pytest.mark.asyncio
    async def test_retry_reprocesses_failed(
        self, service: AdoSyncService, store: SyncStateStore,
        mock_mcp: AsyncMock, config: CustomerConfig,
    ) -> None:
        # Pre-populate a failed item
        store.upsert_item(SyncItem(
            stable_key="epic:retry-me",
            customer=config.slug,
            work_item_type="Epic",
            title="Retry Epic",
            content_hash="hash",
            sync_status="failed",
            error_message="previous error",
            run_id=1,
        ))

        result = await service.retry_failed(mock_mcp, run_id=1)
        assert result.run.items_created == 1

    @pytest.mark.asyncio
    async def test_retry_no_failed_items(
        self, service: AdoSyncService, mock_mcp: AsyncMock,
    ) -> None:
        result = await service.retry_failed(mock_mcp)
        assert result.run.status == "completed"
        assert result.run.items_created == 0
