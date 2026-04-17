"""Sync orchestrator — diff, plan, push work items to ADO via MCP.

The sync service sits between the in-memory ``WorkItemHierarchy`` and the
ADO MCP client.  It computes a diff against the local state store, builds
a plan, and pushes changes top-down (Epic → Feature → Story → Task) so
that parent ADO IDs are available before children are created.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from excellence_agent.ado.customer_config import CustomerConfig
from excellence_agent.ado.mcp_client import ADOMCPClient, MCPClientError
from excellence_agent.ado.state_store import (
    SyncItem,
    SyncRun,
    SyncStateStore,
    compute_content_hash,
)
from excellence_agent.export.content_generator import ContentGenerator
from excellence_agent.models import Epic, Feature, Task, UserStory, WorkItemHierarchy

logger = logging.getLogger(__name__)

# ── Plan data structures ──────────────────────────────────────────────────


@dataclass
class PlannedItem:
    """A single item in the sync plan."""

    stable_key: str
    work_item_type: str
    title: str
    action: str  # create / update / relink / unchanged / orphaned
    content_hash: str
    parent_stable_key: str = ""
    fields: Dict[str, str] = field(default_factory=dict)
    existing: Optional[SyncItem] = None
    model: Any = None  # reference to Epic/Feature/UserStory/Task


@dataclass
class SyncPlan:
    """The result of diffing hierarchy against state store."""

    customer: str
    to_create: List[PlannedItem] = field(default_factory=list)
    to_update: List[PlannedItem] = field(default_factory=list)
    to_relink: List[PlannedItem] = field(default_factory=list)
    unchanged: List[PlannedItem] = field(default_factory=list)
    orphaned: List[PlannedItem] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (
            len(self.to_create) + len(self.to_update) + len(self.to_relink)
            + len(self.unchanged) + len(self.orphaned)
        )

    def summary(self) -> Dict[str, int]:
        return {
            "create": len(self.to_create),
            "update": len(self.to_update),
            "relink": len(self.to_relink),
            "unchanged": len(self.unchanged),
            "orphaned": len(self.orphaned),
            "total": self.total,
        }


@dataclass
class SyncResult:
    """Outcome of a push operation."""

    run: SyncRun
    errors: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.run.status == "completed" and self.run.items_failed == 0


# ── Sync Service ──────────────────────────────────────────────────────────


class AdoSyncService:
    """Orchestrates the diff-plan-push lifecycle for ADO work item sync."""

    def __init__(
        self,
        state_store: SyncStateStore,
        content_generator: ContentGenerator,
        config: CustomerConfig,
    ) -> None:
        self._store = state_store
        self._cg = content_generator
        self._config = config

    # ── plan ──────────────────────────────────────────────────────────

    def plan(self, hierarchy: WorkItemHierarchy) -> SyncPlan:
        """Diff *hierarchy* against the state store and produce a sync plan."""
        customer = self._config.slug
        existing = {i.stable_key: i for i in self._store.get_items_by_customer(customer)}
        active_keys: Set[str] = set()
        sp = SyncPlan(customer=customer)

        for epic in hierarchy.epics:
            self._plan_epic(epic, existing, active_keys, sp)
            for feat in epic.features:
                self._plan_feature(feat, existing, active_keys, sp)
                for story in feat.user_stories:
                    self._plan_story(story, existing, active_keys, sp)
                    for task in story.tasks:
                        self._plan_task(task, existing, active_keys, sp)

        # Orphan detection
        for key, item in existing.items():
            if key not in active_keys and item.sync_status not in ("pending", "orphaned"):
                pi = PlannedItem(
                    stable_key=key,
                    work_item_type=item.work_item_type,
                    title=item.title,
                    action="orphaned",
                    content_hash=item.content_hash,
                    existing=item,
                )
                sp.orphaned.append(pi)

        logger.info("Sync plan for %s: %s", customer, sp.summary())
        return sp

    def _plan_item(
        self,
        stable_key: str,
        work_item_type: str,
        title: str,
        fields: Dict[str, str],
        parent_stable_key: str,
        existing: Dict[str, SyncItem],
        active_keys: Set[str],
        sp: SyncPlan,
        model: Any,
    ) -> None:
        active_keys.add(stable_key)
        content_hash = compute_content_hash(fields)
        prev = existing.get(stable_key)

        pi = PlannedItem(
            stable_key=stable_key,
            work_item_type=work_item_type,
            title=title,
            action="create",
            content_hash=content_hash,
            parent_stable_key=parent_stable_key,
            fields=fields,
            existing=prev,
            model=model,
        )

        if prev is None:
            pi.action = "create"
            sp.to_create.append(pi)
        elif prev.sync_status == "failed":
            # Previously failed — retry as create or update
            pi.action = "create" if prev.ado_work_item_id is None else "update"
            (sp.to_create if pi.action == "create" else sp.to_update).append(pi)
        elif prev.content_hash != content_hash:
            pi.action = "update"
            sp.to_update.append(pi)
        elif prev.parent_stable_key != parent_stable_key:
            pi.action = "relink"
            sp.to_relink.append(pi)
        else:
            pi.action = "unchanged"
            sp.unchanged.append(pi)

    def _plan_epic(
        self, epic: Epic, existing: Dict[str, SyncItem],
        active_keys: Set[str], sp: SyncPlan,
    ) -> None:
        desc = self._cg.generate_epic_description(epic)
        ac = self._cg.generate_epic_acceptance_criteria(epic)
        fields = self._base_fields(
            self._config.type_mapping.epic, epic.name, desc, ac,
        )
        self._plan_item(
            epic.stable_key, self._config.type_mapping.epic,
            epic.name, fields, "", existing, active_keys, sp, epic,
        )

    def _plan_feature(
        self, feat: Feature, existing: Dict[str, SyncItem],
        active_keys: Set[str], sp: SyncPlan,
    ) -> None:
        desc = self._cg.generate_feature_description(feat)
        ac = self._cg.generate_feature_acceptance_criteria(feat)
        parent_key = feat.epic.stable_key if feat.epic else ""
        fields = self._base_fields(
            self._config.type_mapping.feature, feat.name, desc, ac,
        )
        self._plan_item(
            feat.stable_key, self._config.type_mapping.feature,
            feat.name, fields, parent_key, existing, active_keys, sp, feat,
        )

    def _plan_story(
        self, story: UserStory, existing: Dict[str, SyncItem],
        active_keys: Set[str], sp: SyncPlan,
    ) -> None:
        desc = self._cg.generate_story_description(story)
        ac = self._cg.generate_story_acceptance_criteria(story)
        parent_key = story.feature.stable_key if story.feature else ""
        fields = self._base_fields(
            self._config.type_mapping.story, story.title, desc, ac,
        )
        self._plan_item(
            story.stable_key, self._config.type_mapping.story,
            story.title, fields, parent_key, existing, active_keys, sp, story,
        )

    def _plan_task(
        self, task: Task, existing: Dict[str, SyncItem],
        active_keys: Set[str], sp: SyncPlan,
    ) -> None:
        desc = self._cg.generate_task_description(task)
        ac = self._cg.generate_task_acceptance_criteria(task)
        parent_key = task.user_story.stable_key if task.user_story and task.user_story.feature else ""
        fields = self._base_fields(
            self._config.type_mapping.task, task.title, desc, ac,
        )
        self._plan_item(
            task.stable_key, self._config.type_mapping.task,
            task.title, fields, parent_key, existing, active_keys, sp, task,
        )

    def _base_fields(
        self,
        work_item_type: str,
        title: str,
        description: str,
        acceptance_criteria: str,
    ) -> Dict[str, str]:
        fields: Dict[str, str] = {
            "work_item_type": work_item_type,
            "System.Title": title,
            "System.Description": description,
            "Microsoft.VSTS.Common.AcceptanceCriteria": acceptance_criteria,
        }
        if self._config.area_path:
            fields["System.AreaPath"] = self._config.area_path
        if self._config.iteration_path:
            fields["System.IterationPath"] = self._config.iteration_path
        return fields

    # ── push ──────────────────────────────────────────────────────────

    async def push(
        self,
        plan: SyncPlan,
        mcp_client: ADOMCPClient,
    ) -> SyncResult:
        """Execute the sync plan against ADO."""
        customer = self._config.slug
        run = self._store.create_run(customer)
        result = SyncResult(run=run)

        # Build a map from stable_key -> ADO ID (from existing state)
        key_to_ado_id: Dict[str, int] = {}
        for item in self._store.get_items_by_customer(customer):
            if item.ado_work_item_id:
                key_to_ado_id[item.stable_key] = item.ado_work_item_id

        # Mark unchanged items
        for pi in plan.unchanged:
            run.items_unchanged += 1

        # Process in hierarchy order: Epics, Features, Stories, Tasks
        type_order = {
            self._config.type_mapping.epic: 0,
            self._config.type_mapping.feature: 1,
            self._config.type_mapping.story: 2,
            self._config.type_mapping.task: 3,
        }

        creates = sorted(plan.to_create, key=lambda p: type_order.get(p.work_item_type, 99))
        updates = sorted(plan.to_update, key=lambda p: type_order.get(p.work_item_type, 99))

        # Creates — parent-first ordering ensures parents get ADO IDs first
        for pi in creates:
            try:
                ado_fields = {k: v for k, v in pi.fields.items() if k.startswith("System.") or k.startswith("Microsoft.")}
                ado_id = await mcp_client.create_work_item(
                    pi.work_item_type, ado_fields,
                )
                key_to_ado_id[pi.stable_key] = ado_id

                parent_ado_id = key_to_ado_id.get(pi.parent_stable_key)

                # Link to parent if parent exists
                if parent_ado_id:
                    try:
                        await mcp_client.link_work_items(parent_ado_id, ado_id)
                        run.items_linked += 1
                    except MCPClientError as link_err:
                        logger.warning("Failed to link %d -> %d: %s", parent_ado_id, ado_id, link_err)

                self._store.upsert_item(SyncItem(
                    stable_key=pi.stable_key,
                    customer=customer,
                    ado_work_item_id=ado_id,
                    work_item_type=pi.work_item_type,
                    title=pi.title,
                    content_hash=pi.content_hash,
                    parent_stable_key=pi.parent_stable_key,
                    parent_ado_id=parent_ado_id,
                    sync_status="created",
                    last_synced_at=_now(),
                    run_id=run.id,
                ))
                run.items_created += 1
                logger.debug("Created %s #%d: %s", pi.work_item_type, ado_id, pi.title)

            except MCPClientError as e:
                run.items_failed += 1
                result.errors.append(f"Create {pi.stable_key}: {e}")
                self._store.upsert_item(SyncItem(
                    stable_key=pi.stable_key,
                    customer=customer,
                    work_item_type=pi.work_item_type,
                    title=pi.title,
                    content_hash=pi.content_hash,
                    parent_stable_key=pi.parent_stable_key,
                    sync_status="failed",
                    error_message=str(e),
                    run_id=run.id,
                ))
                logger.error("Failed to create %s: %s", pi.stable_key, e)

        # Updates
        for pi in updates:
            try:
                ado_id = key_to_ado_id.get(pi.stable_key)
                if pi.existing and pi.existing.ado_work_item_id:
                    ado_id = pi.existing.ado_work_item_id

                if not ado_id:
                    logger.warning("No ADO ID for update %s — skipping", pi.stable_key)
                    run.items_failed += 1
                    continue

                ado_fields = {k: v for k, v in pi.fields.items() if k.startswith("System.") or k.startswith("Microsoft.")}
                await mcp_client.update_work_item(ado_id, ado_fields)

                self._store.upsert_item(SyncItem(
                    stable_key=pi.stable_key,
                    customer=customer,
                    ado_work_item_id=ado_id,
                    work_item_type=pi.work_item_type,
                    title=pi.title,
                    content_hash=pi.content_hash,
                    parent_stable_key=pi.parent_stable_key,
                    parent_ado_id=key_to_ado_id.get(pi.parent_stable_key),
                    sync_status="updated",
                    last_synced_at=_now(),
                    run_id=run.id,
                ))
                run.items_updated += 1
                logger.debug("Updated %s #%d: %s", pi.work_item_type, ado_id, pi.title)

            except MCPClientError as e:
                run.items_failed += 1
                result.errors.append(f"Update {pi.stable_key}: {e}")
                self._store.upsert_item(SyncItem(
                    stable_key=pi.stable_key,
                    customer=customer,
                    work_item_type=pi.work_item_type,
                    title=pi.title,
                    content_hash=pi.content_hash,
                    parent_stable_key=pi.parent_stable_key,
                    sync_status="failed",
                    error_message=str(e),
                    run_id=run.id,
                ))
                logger.error("Failed to update %s: %s", pi.stable_key, e)

        # Orphans — mark in state store, but never delete from ADO
        orphan_count = 0
        for pi in plan.orphaned:
            if pi.existing:
                self._store.upsert_item(SyncItem(
                    stable_key=pi.stable_key,
                    customer=customer,
                    ado_work_item_id=pi.existing.ado_work_item_id,
                    work_item_type=pi.work_item_type,
                    title=pi.title,
                    content_hash=pi.existing.content_hash,
                    parent_stable_key=pi.existing.parent_stable_key,
                    parent_ado_id=pi.existing.parent_ado_id,
                    sync_status="orphaned",
                    run_id=run.id,
                ))
                orphan_count += 1
        run.items_orphaned = orphan_count

        # Finalise run
        run.completed_at = _now()
        run.status = "completed" if run.items_failed == 0 else "failed"
        self._store.update_run(run)

        logger.info(
            "Sync run #%d for %s: %d created, %d updated, %d unchanged, %d failed, %d orphaned",
            run.id, customer, run.items_created, run.items_updated,
            run.items_unchanged, run.items_failed, run.items_orphaned,
        )
        return result

    # ── retry ─────────────────────────────────────────────────────────

    async def retry_failed(
        self,
        mcp_client: ADOMCPClient,
        run_id: Optional[int] = None,
    ) -> SyncResult:
        """Retry failed items from a previous run (or all failed)."""
        customer = self._config.slug
        failed = self._store.get_items_for_retry(customer, run_id)
        if not failed:
            logger.info("No failed items to retry for %s", customer)
            run = self._store.create_run(customer)
            run.status = "completed"
            run.completed_at = _now()
            self._store.update_run(run)
            return SyncResult(run=run)

        # Rebuild a mini plan from the failed items
        plan = SyncPlan(customer=customer)
        for item in failed:
            pi = PlannedItem(
                stable_key=item.stable_key,
                work_item_type=item.work_item_type,
                title=item.title,
                action="create" if item.ado_work_item_id is None else "update",
                content_hash=item.content_hash,
                parent_stable_key=item.parent_stable_key,
                fields={},  # Retry uses stored hash — fields empty for retry
                existing=item,
            )
            if pi.action == "create":
                plan.to_create.append(pi)
            else:
                plan.to_update.append(pi)

        return await self.push(plan, mcp_client)


# ── helpers ───────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
