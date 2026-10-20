"""Event bus between the feed (producer) and the intelligence pipeline (consumer).

Local: an asyncio queue. Azure: Azure Event Hubs, partitioned by match id, so the
simulator can run as its own container and any number of consumers can read.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from touchline.config import Settings
from touchline.models import MatchEvent

log = logging.getLogger(__name__)
END = "__end__"


class LocalBus:
    kind = "in-process queue"

    def __init__(self) -> None:
        self.queue: asyncio.Queue[MatchEvent | str] = asyncio.Queue()

    async def start(self) -> None:
        return None

    async def publish(self, event: MatchEvent) -> None:
        await self.queue.put(event)

    async def close(self) -> None:
        await self.queue.put(END)

    async def consume(self) -> AsyncIterator[MatchEvent]:
        while True:
            item = await self.queue.get()
            if item == END:
                return
            yield item  # type: ignore[misc]


class EventHubsBus:
    """Publishes to and consumes from Azure Event Hubs (one partition key per match)."""

    kind = "Azure Event Hubs"

    def __init__(self, settings: Settings, match_id: str) -> None:
        from azure.eventhub import EventData  # noqa: F401
        from azure.eventhub.aio import EventHubConsumerClient, EventHubProducerClient

        self.match_id = match_id
        self.local = asyncio.Queue()  # consumer side hand-off
        if settings.eventhub_connection:
            self.producer = EventHubProducerClient.from_connection_string(
                settings.eventhub_connection, eventhub_name=settings.eventhub_name
            )
            self.consumer = EventHubConsumerClient.from_connection_string(
                settings.eventhub_connection, consumer_group="$Default", eventhub_name=settings.eventhub_name
            )
        else:
            from azure.identity.aio import DefaultAzureCredential

            cred = DefaultAzureCredential()
            self.producer = EventHubProducerClient(settings.eventhub_fqdn, settings.eventhub_name, cred)
            self.consumer = EventHubConsumerClient(
                settings.eventhub_fqdn, settings.eventhub_name, "$Default", cred
            )
        self._consumer_task: asyncio.Task | None = None

    async def publish(self, event: MatchEvent) -> None:
        from azure.eventhub import EventData

        batch = await self.producer.create_batch(partition_key=self.match_id)
        batch.add(EventData(event.model_dump_json()))
        await self.producer.send_batch(batch)

    async def close(self) -> None:
        from azure.eventhub import EventData

        batch = await self.producer.create_batch(partition_key=self.match_id)
        batch.add(EventData(json.dumps({"match_id": self.match_id, "type": END})))
        await self.producer.send_batch(batch)

    async def _on_event(self, partition_context, event) -> None:
        try:
            body = json.loads(event.body_as_str())
        except Exception:
            return
        if body.get("match_id") != self.match_id:
            return
        await self.local.put(END if body.get("type") == END else MatchEvent.model_validate(body))

    async def start(self) -> None:
        """Attach the consumer before the feed starts publishing, so no event is missed."""
        from datetime import UTC, datetime, timedelta

        since = datetime.now(UTC) - timedelta(seconds=2)
        self._consumer_task = asyncio.create_task(
            self.consumer.receive(on_event=self._on_event, starting_position=since)
        )
        await asyncio.sleep(3)

    async def consume(self) -> AsyncIterator[MatchEvent]:
        if self._consumer_task is None:
            await self.start()
        try:
            while True:
                item = await self.local.get()
                if item == END:
                    return
                yield item
        finally:
            self._consumer_task.cancel()
            await self.consumer.close()
            await self.producer.close()


def make_bus(settings: Settings, match_id: str):
    if settings.eventhub_connection or settings.eventhub_fqdn:
        try:
            return EventHubsBus(settings, match_id)
        except Exception as exc:  # pragma: no cover
            log.warning("Event Hubs unavailable, using local bus: %s", exc)
    return LocalBus()
