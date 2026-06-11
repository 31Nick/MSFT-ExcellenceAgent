"""Tests for excellence_agent.ado.mcp_client with mocked MCP sessions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from excellence_agent.ado.customer_config import CustomerConfig, WorkItemTypeMapping
from excellence_agent.ado.mcp_client import ADOMCPClient, MCPClientError, WorkItem


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture()
def config() -> CustomerConfig:
    return CustomerConfig(
        slug="test",
        customer_name="Test Corp",
        organization="test-org",
        project="TestProject",
        pat="fake-pat",
        type_mapping=WorkItemTypeMapping(),
    )


@dataclass
class FakeContent:
    text: str


@dataclass
class FakeResult:
    content: List[FakeContent]


def _make_result(data: Any) -> FakeResult:
    """Create a mock MCP tool result from a dict or string."""
    text = json.dumps(data) if isinstance(data, (dict, list)) else str(data)
    return FakeResult(content=[FakeContent(text=text)])


def _make_error_result(msg: str) -> FakeResult:
    return FakeResult(content=[FakeContent(text=f"MCP error -32602: {msg}")])


@pytest.fixture()
def mock_session() -> AsyncMock:
    session = AsyncMock()
    session.initialize = AsyncMock()
    return session


@pytest.fixture()
def client_with_session(config: CustomerConfig, mock_session: AsyncMock) -> ADOMCPClient:
    """Return an ADOMCPClient with a pre-injected mock session (no subprocess)."""
    client = ADOMCPClient(config)
    client._session = mock_session
    return client


# ── create_work_item ──────────────────────────────────────────────────────


class TestCreateWorkItem:
    @pytest.mark.asyncio
    async def test_creates_and_returns_id(
        self, client_with_session: ADOMCPClient, mock_session: AsyncMock
    ) -> None:
        mock_session.call_tool.return_value = _make_result({"id": 42, "rev": 1, "fields": {}})

        wi_id = await client_with_session.create_work_item(
            "Epic", {"System.Title": "Test Epic"}
        )
        assert wi_id == 42
        mock_session.call_tool.assert_awaited_once()
        call_args = mock_session.call_tool.call_args
        assert call_args[0][0] == "wit_create_work_item"
        args = call_args[1]["arguments"] if "arguments" in call_args[1] else call_args[0][1]
        assert args["workItemType"] == "Epic"
        assert args["project"] == "TestProject"

    @pytest.mark.asyncio
    async def test_mcp_error_raises(
        self, client_with_session: ADOMCPClient, mock_session: AsyncMock
    ) -> None:
        mock_session.call_tool.return_value = _make_error_result("Invalid arguments")
        with pytest.raises(MCPClientError, match="MCP error"):
            await client_with_session.create_work_item("Epic", {"System.Title": "X"})


# ── get_work_item ─────────────────────────────────────────────────────────


class TestGetWorkItem:
    @pytest.mark.asyncio
    async def test_returns_work_item(
        self, client_with_session: ADOMCPClient, mock_session: AsyncMock
    ) -> None:
        mock_session.call_tool.return_value = _make_result({
            "id": 99,
            "rev": 3,
            "fields": {
                "System.WorkItemType": "Feature",
                "System.Title": "My Feature",
                "System.State": "Active",
            },
        })
        item = await client_with_session.get_work_item(99)
        assert isinstance(item, WorkItem)
        assert item.id == 99
        assert item.work_item_type == "Feature"
        assert item.title == "My Feature"
        assert item.state == "Active"

    @pytest.mark.asyncio
    async def test_passes_project(
        self, client_with_session: ADOMCPClient, mock_session: AsyncMock
    ) -> None:
        mock_session.call_tool.return_value = _make_result({"id": 1, "fields": {}})
        await client_with_session.get_work_item(1)
        call_args = mock_session.call_tool.call_args
        args = call_args[1]["arguments"] if "arguments" in call_args[1] else call_args[0][1]
        assert args["project"] == "TestProject"


# ── update_work_item ──────────────────────────────────────────────────────


class TestUpdateWorkItem:
    @pytest.mark.asyncio
    async def test_updates_and_returns_rev(
        self, client_with_session: ADOMCPClient, mock_session: AsyncMock
    ) -> None:
        mock_session.call_tool.return_value = _make_result({"id": 42, "rev": 5, "fields": {}})
        rev = await client_with_session.update_work_item(
            42, {"System.Title": "Updated Title"}
        )
        assert rev == 5
        call_args = mock_session.call_tool.call_args
        args = call_args[1]["arguments"] if "arguments" in call_args[1] else call_args[0][1]
        assert args["id"] == 42
        assert args["updates"][0]["path"] == "/fields/System.Title"
        assert args["updates"][0]["op"] == "add"


# ── add_child_work_items ──────────────────────────────────────────────────


class TestAddChildWorkItems:
    @pytest.mark.asyncio
    async def test_returns_child_ids(
        self, client_with_session: ADOMCPClient, mock_session: AsyncMock
    ) -> None:
        mock_session.call_tool.return_value = _make_result({
            "count": 2,
            "value": [
                {"code": 200, "body": json.dumps({"id": 101, "rev": 1, "fields": {}})},
                {"code": 200, "body": json.dumps({"id": 102, "rev": 1, "fields": {}})},
            ],
        })
        ids = await client_with_session.add_child_work_items(
            parent_id=50,
            work_item_type="Feature",
            items=[
                {"title": "Child 1", "description": "d1"},
                {"title": "Child 2", "description": "d2"},
            ],
        )
        assert ids == [101, 102]


# ── not connected ─────────────────────────────────────────────────────────


class TestNotConnected:
    @pytest.mark.asyncio
    async def test_raises_if_not_connected(self, config: CustomerConfig) -> None:
        client = ADOMCPClient(config)
        with pytest.raises(MCPClientError, match="not connected"):
            await client.create_work_item("Epic", {"System.Title": "X"})
