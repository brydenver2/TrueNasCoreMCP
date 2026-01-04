"""Unit tests for snapshot tools."""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from truenas_mcp_server.tools.snapshots import SnapshotTools


@pytest_asyncio.fixture
async def snapshot_tools(mock_truenas_client, mock_settings):
    """Create snapshot tools instance for testing."""
    return SnapshotTools(client=mock_truenas_client, settings=mock_settings)


@pytest.mark.asyncio
async def test_list_snapshots_handles_timestamp_formats(snapshot_tools):
    """Ensure list_snapshots normalizes timestamp payloads."""
    sample_payload = [
        {
            "name": "tank/data@auto-new",
            "properties": {
                "creation": {
                    "parsed": {"$date": 1700000000000},
                    "rawvalue": "1700000000",
                },
                "referenced": {"value": "8K"},
                "used": {"value": "4K"},
            },
            "holds": [],
        },
        {
            "name": "tank/data@auto-old",
            "properties": {
                "creation": {"parsed": 1600000000, "rawvalue": "1600000000"},
                "referenced": {"value": "4K"},
                "used": {"value": "2K"},
            },
            "holds": [],
        },
    ]

    snapshot_tools.client.get = AsyncMock(return_value=sample_payload)

    result = await snapshot_tools.list_snapshots({"limit": 10})

    assert result["success"] is True
    assert result["pagination"]["total"] == 2

    snapshots = result["snapshots"]
    assert len(snapshots) == 2

    # Entries should be sorted newest-first and expose normalized timestamps
    assert snapshots[0]["name"] == "tank/data@auto-new"
    assert snapshots[0]["created"] == 1700000000
    assert snapshots[0]["created_human"] == datetime.fromtimestamp(1700000000).isoformat()

    assert snapshots[1]["name"] == "tank/data@auto-old"
    assert snapshots[1]["created"] == 1600000000
    assert snapshots[1]["created_human"] == datetime.fromtimestamp(1600000000).isoformat()

    assert result["metadata"]["by_dataset"]["tank/data"] == 2