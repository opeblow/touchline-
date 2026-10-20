"""Match Blackboard: shared state every agent reads from and writes to.

Local mode keeps it in memory. Azure mode persists to Cosmos DB (container
`blackboard`, partition key `/match_id`) so any replica, the MCP server or a
post-match job sees the same state, and it doubles as the audit trail.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

from pydantic import BaseModel

log = logging.getLogger(__name__)

KINDS = (
    "moment",
    "insight",
    "personalized",
    "commentary",
    "cue",
    "trace",
    "recap",
    "tactical",
    "audit",
    "status",
)


class Blackboard:
    """In-memory implementation (also the cache in front of Cosmos)."""

    def __init__(self, match_id: str, max_per_kind: int = 5000) -> None:
        self.match_id = match_id
        self.max_per_kind = max_per_kind
        self._items: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        self._lock = asyncio.Lock()

    async def put(self, kind: str, key: str, obj: BaseModel | dict[str, Any]) -> None:
        data = obj.model_dump(mode="json") if isinstance(obj, BaseModel) else obj
        async with self._lock:
            bucket = self._items[kind]
            bucket[key] = data
            if len(bucket) > self.max_per_kind:
                bucket.pop(next(iter(bucket)))
        await self._persist(kind, key, data)

    async def get(self, kind: str, key: str) -> dict[str, Any] | None:
        return self._items.get(kind, {}).get(key)

    async def list(self, kind: str, limit: int = 200) -> list[dict[str, Any]]:
        items = list(self._items.get(kind, {}).values())
        return items[-limit:]

    async def _persist(self, kind: str, key: str, data: dict[str, Any]) -> None:  # overridden by Cosmos
        return None


class CosmosBlackboard(Blackboard):
    """Write-through to Azure Cosmos DB. Reads are served from memory."""

    def __init__(self, match_id: str, endpoint: str, database: str, key: str | None = None) -> None:
        super().__init__(match_id)
        from azure.cosmos.aio import CosmosClient

        if key:
            self._client = CosmosClient(endpoint, credential=key)
        else:
            from azure.identity.aio import DefaultAzureCredential

            self._client = CosmosClient(endpoint, credential=DefaultAzureCredential())
        self._db_name = database
        self._container = None

    async def _get_container(self):
        if self._container is None:
            from azure.cosmos import PartitionKey

            db = await self._client.create_database_if_not_exists(self._db_name)
            self._container = await db.create_container_if_not_exists(
                id="blackboard", partition_key=PartitionKey(path="/match_id")
            )
        return self._container

    async def _persist(self, kind: str, key: str, data: dict[str, Any]) -> None:
        if kind in {"cue"}:  # high-volume, ephemeral; keep out of the database
            return
        try:
            container = await self._get_container()
            await container.upsert_item(
                {"id": f"{kind}:{key}", "match_id": self.match_id, "kind": kind, "data": data}
            )
        except Exception as exc:  # pragma: no cover - cloud path
            log.warning("Cosmos write failed (%s): %s", kind, exc)


def make_blackboard(match_id: str, settings) -> Blackboard:
    if settings.cosmos_endpoint:
        try:
            return CosmosBlackboard(
                match_id, settings.cosmos_endpoint, settings.cosmos_db, settings.cosmos_key
            )
        except Exception as exc:  # pragma: no cover
            log.warning("Cosmos unavailable, using in-memory blackboard: %s", exc)
    return Blackboard(match_id)
