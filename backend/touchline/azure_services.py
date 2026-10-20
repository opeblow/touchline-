"""Thin async clients for Azure AI services used by the agents.

All are optional. When not configured, callers use local fallbacks.
  * Azure AI Translator  — any-language localisation, player/club names protected.
  * Azure AI Content Safety — screen every published text.
  * Azure AI Search      — season memory lookups.
"""

from __future__ import annotations

import html
import logging
import re
from typing import Any

import httpx

from touchline.config import Settings

log = logging.getLogger(__name__)


class Translator:
    def __init__(self, settings: Settings) -> None:
        self.key = settings.translator_key
        self.region = settings.translator_region
        self.endpoint = settings.translator_endpoint.rstrip("/")
        self.enabled = bool(self.key)

    async def translate(self, text: str, to_lang: str, protect: list[str]) -> str:
        """Translate `text`, keeping every string in `protect` (names) untouched."""
        if not self.enabled:
            raise RuntimeError("Translator not configured")
        marked = html.escape(text)
        for name in sorted(set(filter(None, protect)), key=len, reverse=True):
            esc = html.escape(name)
            marked = re.sub(rf"\b{re.escape(esc)}\b", f'<span class="notranslate">{esc}</span>', marked)
        headers = {"Ocp-Apim-Subscription-Key": self.key, "Content-Type": "application/json"}
        if self.region:
            headers["Ocp-Apim-Subscription-Region"] = self.region
        params = {"api-version": "3.0", "to": to_lang, "textType": "html"}
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.post(
                f"{self.endpoint}/translate", params=params, headers=headers, json=[{"Text": marked}]
            )
            r.raise_for_status()
            out = r.json()[0]["translations"][0]["text"]
        out = re.sub(r'<span class="notranslate">(.*?)</span>', r"\1", out)
        return html.unescape(out)


class ContentSafety:
    def __init__(self, settings: Settings) -> None:
        self.endpoint = (settings.content_safety_endpoint or "").rstrip("/")
        self.key = settings.content_safety_key
        self.enabled = bool(self.endpoint)

    async def screen(self, text: str, threshold: int = 4) -> tuple[bool, list[str]]:
        """Returns (safe, flagged_categories)."""
        if not self.enabled:
            return True, []
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Ocp-Apim-Subscription-Key"] = self.key
        else:  # managed identity
            from azure.identity.aio import DefaultAzureCredential

            async with DefaultAzureCredential() as cred:
                token = await cred.get_token("https://cognitiveservices.azure.com/.default")
                headers["Authorization"] = f"Bearer {token.token}"
        body = {
            "text": text[:1000],
            "categories": ["Hate", "Violence", "Sexual", "SelfHarm"],
            "outputType": "FourSeverityLevels",
        }
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.post(
                    f"{self.endpoint}/contentsafety/text:analyze",
                    params={"api-version": "2024-09-01"},
                    headers=headers,
                    json=body,
                )
                r.raise_for_status()
                flagged = [
                    c["category"]
                    for c in r.json().get("categoriesAnalysis", [])
                    if c.get("severity", 0) >= threshold
                ]
                return not flagged, flagged
        except Exception as exc:  # fail open on transport errors; local rules still apply
            log.warning("Content Safety unavailable: %s", exc)
            return True, []


class SearchMemory:
    """Azure AI Search index of season facts (player and team profiles)."""

    def __init__(self, settings: Settings) -> None:
        self.endpoint = settings.search_endpoint
        self.key = settings.search_key
        self.index = settings.search_index
        self.enabled = bool(self.endpoint)

    async def lookup(self, doc_id: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        headers = {"api-key": self.key} if self.key else {}
        if not self.key:
            from azure.identity.aio import DefaultAzureCredential

            async with DefaultAzureCredential() as cred:
                token = await cred.get_token("https://search.azure.com/.default")
                headers["Authorization"] = f"Bearer {token.token}"
        try:
            async with httpx.AsyncClient(timeout=4) as client:
                r = await client.get(
                    f"{self.endpoint}/indexes/{self.index}/docs/{doc_id}",
                    params={"api-version": "2024-07-01"},
                    headers=headers,
                )
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                return r.json()
        except Exception as exc:
            log.warning("AI Search lookup failed: %s", exc)
            return None
