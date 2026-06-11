"""Typed Python wrapper around the ADO Local MCP Server (stdio).

Launches ``@azure-devops/mcp`` via npx as a subprocess and communicates
using the MCP stdio transport.  PAT auth via the ``ADO_MCP_AUTH_TOKEN``
environment variable.

Usage::

    async with ADOMCPClient(config) as client:
        wi_id = await client.create_work_item("Epic", {"System.Title": "My Epic"})
        item  = await client.get_work_item(wi_id)
        await client.update_work_item(wi_id, {"System.Title": "Renamed"})
        child_ids = await client.add_child_work_items(wi_id, "Feature", [
            {"title": "Child 1", "description": "desc"},
        ])
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Dict, List, Optional, Type

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from excellence_agent.ado.customer_config import CustomerConfig

logger = logging.getLogger(__name__)


class MCPClientError(Exception):
    """Raised when an MCP tool call returns an error."""


@dataclass
class WorkItem:
    """Minimal representation of an ADO work item returned by MCP."""

    id: int
    rev: int
    work_item_type: str
    title: str
    state: str
    fields: Dict[str, Any]


class ADOMCPClient:
    """Async context-managed wrapper around the ADO Local MCP Server."""

    def __init__(self, config: CustomerConfig) -> None:
        self._config = config
        self._session: Optional[ClientSession] = None
        self._stdio_context = None
        self._session_context = None

    # ── context manager ───────────────────────────────────────────────

    async def __aenter__(self) -> ADOMCPClient:
        env = {**os.environ, "ADO_MCP_AUTH_TOKEN": self._config.pat}
        params = StdioServerParameters(
            command="npx",
            args=[
                "-y",
                "@azure-devops/mcp",
                self._config.organization,
                "--authentication", "envvar",
                "-d", "work-items",
            ],
            env=env,
        )
        self._stdio_context = stdio_client(params)
        read, write = await self._stdio_context.__aenter__()
        self._session_context = ClientSession(read, write)
        self._session = await self._session_context.__aenter__()
        await self._session.initialize()
        logger.info("MCP client connected to %s", self._config.organization_url)
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        if self._session_context:
            await self._session_context.__aexit__(exc_type, exc_val, exc_tb)
        if self._stdio_context:
            await self._stdio_context.__aexit__(exc_type, exc_val, exc_tb)
        self._session = None

    # ── tool helpers ──────────────────────────────────────────────────

    async def _call(self, tool: str, arguments: Dict[str, Any]) -> Any:
        """Call an MCP tool and return parsed JSON response."""
        if self._session is None:
            raise MCPClientError("Client not connected — use as async context manager")
        result = await self._session.call_tool(tool, arguments=arguments)
        if not result.content:
            raise MCPClientError(f"{tool} returned empty content")
        text = result.content[0].text
        if text.startswith("MCP error"):
            raise MCPClientError(text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    # ── create ────────────────────────────────────────────────────────

    async def create_work_item(
        self,
        work_item_type: str,
        fields: Dict[str, str],
        *,
        project: Optional[str] = None,
    ) -> int:
        """Create a work item. *fields* is ``{field_name: value}``. Returns ADO ID."""
        data = await self._call(
            "wit_create_work_item",
            {
                "project": project or self._config.project,
                "workItemType": work_item_type,
                "fields": [{"name": k, "value": v} for k, v in fields.items()],
            },
        )
        wi_id = data["id"]
        logger.debug("Created %s #%d: %s", work_item_type, wi_id, fields.get("System.Title", ""))
        return wi_id

    # ── read ──────────────────────────────────────────────────────────

    async def get_work_item(
        self,
        wi_id: int,
        *,
        project: Optional[str] = None,
        fields: Optional[List[str]] = None,
    ) -> WorkItem:
        """Retrieve a single work item by ID."""
        args: Dict[str, Any] = {
            "id": wi_id,
            "project": project or self._config.project,
        }
        if fields:
            args["fields"] = fields
        data = await self._call("wit_get_work_item", args)
        return self._parse_work_item(data)

    async def get_work_items_batch(
        self,
        ids: List[int],
        *,
        project: Optional[str] = None,
    ) -> List[WorkItem]:
        """Retrieve multiple work items by ID."""
        data = await self._call(
            "wit_get_work_items_batch_by_ids",
            {
                "ids": ids,
                "project": project or self._config.project,
            },
        )
        items = data.get("value", data) if isinstance(data, dict) else data
        return [self._parse_work_item(d) for d in items]

    # ── update ────────────────────────────────────────────────────────

    async def update_work_item(
        self,
        wi_id: int,
        fields: Dict[str, str],
    ) -> int:
        """Update a work item. *fields* is ``{field_name: new_value}``. Returns rev."""
        data = await self._call(
            "wit_update_work_item",
            {
                "id": wi_id,
                "updates": [
                    {"op": "add", "path": f"/fields/{k}", "value": v}
                    for k, v in fields.items()
                ],
            },
        )
        return data.get("rev", 0)

    async def update_work_items_batch(
        self,
        updates: List[Dict[str, Any]],
    ) -> Any:
        """Batch update work items. Each entry: ``{id, updates: [{op,path,value}]}``."""
        return await self._call("wit_update_work_items_batch", {"updates": updates})

    # ── children & links ──────────────────────────────────────────────

    async def add_child_work_items(
        self,
        parent_id: int,
        work_item_type: str,
        items: List[Dict[str, str]],
        *,
        project: Optional[str] = None,
    ) -> List[int]:
        """Create children under *parent_id*. Returns list of new ADO IDs."""
        data = await self._call(
            "wit_add_child_work_items",
            {
                "parentId": parent_id,
                "project": project or self._config.project,
                "workItemType": work_item_type,
                "items": items,
            },
        )
        child_ids = []
        for entry in data.get("value", []):
            body = entry.get("body", "{}")
            if isinstance(body, str):
                body = json.loads(body)
            child_ids.append(body["id"])
        return child_ids

    async def link_work_items(
        self,
        source_id: int,
        target_id: int,
        link_type: str = "System.LinkTypes.Hierarchy-Forward",
    ) -> Any:
        """Link two work items."""
        return await self._call(
            "wit_work_items_link",
            {
                "sourceWorkItemId": source_id,
                "targetWorkItemId": target_id,
                "linkType": link_type,
            },
        )

    async def unlink_work_item(
        self,
        wi_id: int,
        target_id: int,
        link_type: str = "System.LinkTypes.Hierarchy-Forward",
    ) -> Any:
        """Remove a link from a work item."""
        return await self._call(
            "wit_work_item_unlink",
            {
                "id": wi_id,
                "targetId": target_id,
                "linkType": link_type,
            },
        )

    # ── helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _parse_work_item(data: dict) -> WorkItem:
        fields = data.get("fields", {})
        return WorkItem(
            id=data["id"],
            rev=data.get("rev", 0),
            work_item_type=fields.get("System.WorkItemType", ""),
            title=fields.get("System.Title", ""),
            state=fields.get("System.State", ""),
            fields=fields,
        )
