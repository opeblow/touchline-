"""Realtime fan-out to viewers.

Local: FastAPI WebSockets. Azure: Azure Web PubSub (groups per match and per
personalisation key), so the API can scale out without sticky sessions.
Personalised messages are only delivered to viewers who asked for that variant.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

from touchline.agents.specialists import Sub
from touchline.config import Settings
from touchline.models import WireMessage

log = logging.getLogger(__name__)


@dataclass(eq=False)
class Client:
    ws: WebSocket
    sub: Sub
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=600))
    wants_frames: bool = True
    member_id: str | None = None


class LocalHub:
    kind = "WebSocket"

    def __init__(self) -> None:
        self.clients: dict[str, set[Client]] = {}
        self.remote_subs: dict[str, Counter] = {}

    def add(self, match_id: str, client: Client) -> None:
        self.clients.setdefault(match_id, set()).add(client)

    def remove(self, match_id: str, client: Client) -> None:
        self.clients.get(match_id, set()).discard(client)

    def subs(self, match_id: str) -> set[Sub]:
        out = {c.sub for c in self.clients.get(match_id, set())}
        out |= set(self.remote_subs.get(match_id, Counter()))
        return out

    def viewer_count(self, match_id: str) -> int:
        return len(self.clients.get(match_id, set())) + sum(
            self.remote_subs.get(match_id, Counter()).values()
        )

    def register_remote(self, match_id: str, sub: Sub) -> None:
        self.remote_subs.setdefault(match_id, Counter())[sub] += 1

    async def broadcast(self, msg: WireMessage) -> None:
        payload = None
        sub_key = msg.data.get("sub_key") if msg.kind == "personalized" else None
        for client in list(self.clients.get(msg.match_id, set())):
            if sub_key and client.sub.key != sub_key:
                continue
            if msg.kind == "commentary" and msg.data.get("lang") not in (client.sub.lang, None):
                continue
            if msg.kind == "frame" and not client.wants_frames:
                continue
            if payload is None:
                payload = msg.model_dump_json()
            try:
                client.queue.put_nowait(payload)
            except asyncio.QueueFull:  # slow client: drop frames first
                if msg.kind != "frame":
                    try:
                        client.queue.get_nowait()
                        client.queue.put_nowait(payload)
                    except Exception:
                        pass


class WebPubSubHub(LocalHub):
    """Sends through Azure Web PubSub as well as to any local WebSocket clients."""

    kind = "Azure Web PubSub"

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        from azure.messaging.webpubsubservice import WebPubSubServiceClient

        if settings.webpubsub_connection:
            self.service = WebPubSubServiceClient.from_connection_string(
                settings.webpubsub_connection, hub=settings.webpubsub_hub
            )
        else:
            from azure.identity import DefaultAzureCredential

            self.service = WebPubSubServiceClient(
                endpoint=settings.webpubsub_endpoint,
                hub=settings.webpubsub_hub,
                credential=DefaultAzureCredential(),
            )

    def client_url(self, match_id: str, sub: Sub, user_id: str) -> str:
        groups = [f"m.{match_id}", f"m.{match_id}.{sub.key}"]
        token = self.service.get_client_access_token(
            user_id=user_id, groups=groups, roles=[f"webpubsub.joinLeaveGroup.m.{match_id}"]
        )
        return token["url"]

    async def broadcast(self, msg: WireMessage) -> None:
        await super().broadcast(msg)
        if msg.kind == "frame":
            return  # frames are high-frequency; served from the local replica only
        group = f"m.{msg.match_id}"
        if msg.kind == "personalized" and msg.data.get("sub_key"):
            group = f"m.{msg.match_id}.{msg.data['sub_key']}"
        payload: dict[str, Any] = json.loads(msg.model_dump_json())
        try:
            await asyncio.to_thread(
                self.service.send_to_group, group, payload, content_type="application/json"
            )
        except Exception as exc:  # pragma: no cover
            log.warning("Web PubSub send failed: %s", exc)


def make_hub(settings: Settings):
    if settings.webpubsub_connection or settings.webpubsub_endpoint:
        try:
            return WebPubSubHub(settings)
        except Exception as exc:  # pragma: no cover
            log.warning("Web PubSub unavailable, using local WebSockets: %s", exc)
    return LocalHub()
