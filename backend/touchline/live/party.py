"""Watch party: fans watching the same live match together.

Members sign in with a Microsoft account (Entra ID via MSAL in the browser) or join
as guests. They chat, send reactions, and predict who scores next; predictions are
settled automatically by the live event feed. Chat passes the same safety screen
as agent output (local blocklist + Azure AI Content Safety when configured).
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from touchline.agents.guardian_rules import BLOCKLIST

REACTIONS = {"GOAL", "WOW", "CLAP", "COME ON", "NOOO", "HAHA", "UNREAL", "REF!"}
POINTS_CORRECT = 10


@dataclass
class Member:
    member_id: str
    name: str
    provider: str  # "microsoft" | "guest"
    avatar: str
    club: str | None = None
    points: int = 0
    joined: float = field(default_factory=time.time)
    connections: int = 1

    def public(self) -> dict[str, Any]:
        return {
            "id": self.member_id,
            "name": self.name,
            "provider": self.provider,
            "avatar": self.avatar,
            "club": self.club,
            "points": self.points,
        }


class Party:
    def __init__(self) -> None:
        self.members: dict[str, Member] = {}
        self.chat: list[dict[str, Any]] = []
        self.round = 1
        self.picks: dict[str, str] = {}  # member_id -> "home" | "away" | "none"
        self.history: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ membership

    def join(self, name: str, provider: str, member_id: str | None, club: str | None) -> Member:
        clean = re.sub(r"[^\w .'-]", "", name, flags=re.UNICODE).strip()[:28] or "Guest"
        mid = member_id or uuid.uuid4().hex[:10]
        if mid in self.members:
            m = self.members[mid]
            m.connections += 1
            m.name, m.club = clean, club or m.club
            return m
        initials = "".join(w[0] for w in clean.split()[:2]).upper() or "G"
        m = Member(mid, clean, "microsoft" if provider == "microsoft" else "guest", initials, club)
        self.members[mid] = m
        return m

    def leave(self, member_id: str) -> None:
        m = self.members.get(member_id)
        if m:
            m.connections -= 1
            if m.connections <= 0:
                self.members.pop(member_id, None)
                self.picks.pop(member_id, None)

    # ------------------------------------------------------------------ chat & reactions

    @staticmethod
    def screen(text: str) -> tuple[bool, str]:
        text = text.strip()[:240]
        low = text.lower()
        if not text:
            return False, "empty"
        if any(re.search(rf"\b{w}\b", low) for w in BLOCKLIST):
            return False, "Message blocked by the safety screen"
        return True, text

    def add_chat(self, member: Member, text: str, minute: int) -> dict[str, Any]:
        msg = {
            "id": uuid.uuid4().hex[:8],
            "member": member.public(),
            "text": text,
            "minute": minute,
            "ts": time.time(),
        }
        self.chat = (self.chat + [msg])[-200:]
        return msg

    # ------------------------------------------------------------------ predictions

    def predict(self, member: Member, pick: str) -> None:
        if pick in {"home", "away", "none"}:
            self.picks[member.member_id] = pick

    def tally(self) -> dict[str, int]:
        out = {"home": 0, "away": 0, "none": 0}
        for p in self.picks.values():
            out[p] += 1
        return out

    def settle(self, outcome: str, minute: int, label: str) -> dict[str, Any]:
        """outcome: home | away (a goal) or none (full time with no further goal)."""
        winners = [mid for mid, p in self.picks.items() if p == outcome]
        for mid in winners:
            if mid in self.members:
                self.members[mid].points += POINTS_CORRECT
        result = {
            "round": self.round,
            "outcome": outcome,
            "minute": minute,
            "label": label,
            "winners": [self.members[m].name for m in winners if m in self.members],
            "tally": self.tally(),
        }
        self.history.append(result)
        self.round += 1
        self.picks = {}
        return result

    def leaderboard(self) -> list[dict[str, Any]]:
        return [m.public() for m in sorted(self.members.values(), key=lambda m: (-m.points, m.joined))]

    def state(self, member_id: str | None = None) -> dict[str, Any]:
        return {
            "members": self.leaderboard(),
            "chat": self.chat[-60:],
            "round": self.round,
            "tally": self.tally(),
            "my_pick": self.picks.get(member_id) if member_id else None,
            "history": self.history[-10:],
        }
