"""Runtime configuration from environment variables (see /.env.example)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(ROOT / ".env", ".env"), extra="ignore")

    # --- app
    touchline_mode: Literal["local", "azure"] = "local"
    demo_speed: float = 8.0  # replay speed multiplier for live matches
    cache_dir: Path = ROOT / ".cache"
    allowed_origins: str = "*"
    log_level: str = "INFO"
    public_base_url: str = "http://localhost:8000"

    # --- LLM provider: auto picks foundry > azure_openai > openai > offline
    llm_provider: Literal["auto", "offline", "foundry", "azure_openai", "openai"] = "auto"
    foundry_project_endpoint: str | None = None
    foundry_model_fast: str = "gpt-4.1-mini"
    foundry_model_reasoning: str = "gpt-4.1"
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_api_version: str = "2024-10-21"
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    llm_timeout_s: float = 12.0
    # Use the versioned prompt agents published to Foundry (python -m touchline.foundry_ops register)
    foundry_hosted_agents: bool = False
    # Enterprise controls
    max_cost_per_match_usd: float = (
        2.0  # model spend cap per match; agents fall back to verified templates beyond it
    )
    control_api_key: str | None = None  # when set, control actions require header x-touchline-key
    ask_rate_per_minute: int = 20
    chat_min_interval_s: float = 1.0
    # USD per 1K tokens, used for the cost-per-match readout in the Control Room
    price_fast_in: float = 0.0004
    price_fast_out: float = 0.0016
    price_reasoning_in: float = 0.002
    price_reasoning_out: float = 0.008

    # --- Azure data plane (all optional; local fallbacks are used when unset)
    eventhub_connection: str | None = None
    eventhub_fqdn: str | None = None  # use with managed identity
    eventhub_name: str = "match-events"
    cosmos_endpoint: str | None = None
    cosmos_key: str | None = None
    cosmos_db: str = "touchline"
    webpubsub_connection: str | None = None
    webpubsub_endpoint: str | None = None
    webpubsub_hub: str = "touchline"
    translator_key: str | None = None
    translator_region: str | None = None
    translator_endpoint: str = "https://api.cognitive.microsofttranslator.com"
    content_safety_endpoint: str | None = None
    content_safety_key: str | None = None
    search_endpoint: str | None = None
    search_key: str | None = None
    search_index: str = "touchline-memory"
    applicationinsights_connection_string: str | None = None
    logic_app_recap_url: str | None = None  # HTTP trigger that distributes recaps

    # --- personalization defaults
    languages: str = "en,es,fr,pt,ar,ja"

    @property
    def language_list(self) -> list[str]:
        return [x.strip() for x in self.languages.split(",") if x.strip()]

    @property
    def resolved_llm_provider(self) -> str:
        if self.llm_provider != "auto":
            return self.llm_provider
        if self.foundry_project_endpoint:
            return "foundry"
        if self.azure_openai_endpoint:
            return "azure_openai"
        if self.openai_api_key:
            return "openai"
        return "offline"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.cache_dir.mkdir(parents=True, exist_ok=True)
    return s
