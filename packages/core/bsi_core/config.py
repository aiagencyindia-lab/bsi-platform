"""Settings, read once from the environment (and .env)."""

from datetime import UTC, datetime
from functools import lru_cache
from typing import Literal

from pydantic import AwareDatetime
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOCAL = "postgresql+psycopg://{u}:{p}@localhost:5433/bsi"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = _LOCAL.format(u="bsi_app", p="app")
    owner_database_url: str = _LOCAL.format(u="bsi_owner", p="owner")
    engine_model: str = "gemini-3.8-flash"
    extract_model: str = "gemini-3.5-flash-lite"
    embed_model: str = "gemini-embedding-001"
    judge_mode: Literal["batched", "isolated"] = "batched"
    raw_store_dir: str = "./data"
    # Stays true until the chosen judge mode passes the slice-2 bar (§5.3).
    rec_rate_experimental: bool = True
    # Slice-2 live-spend guard (spec §7): the cap covers ledger entries plus
    # observations created at or after spend_since (after slice 1's run).
    spend_cap_usd: float = 15.0
    spend_since: AwareDatetime = datetime(2026, 9, 19, 10, 0, tzinfo=UTC)
    # Slice 3: per-organization daily cap on scheduled runs (spec §3).
    daily_budget_usd: float = 2.0
    obs_cost_estimate_micros: int = 50_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
