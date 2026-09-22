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
    # 2.5 searched in 80 of 80 answers; 3.8 in about 1 in 4, so most of its
    # answers had no citations (findings-slice2 §7, findings-slice5 §1).
    engine_model: str = "gemini-2.5-flash"
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
    # Slice 6: days either side of a task's done_at that impact compares.
    # Copied onto the task when it is marked done, so changing it never
    # moves a window that is already open.
    impact_window_days: int = 14


@lru_cache
def get_settings() -> Settings:
    return Settings()
