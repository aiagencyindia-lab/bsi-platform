"""Settings, read once from the environment (and .env)."""

from datetime import UTC, datetime
from functools import lru_cache
from typing import Literal

from pydantic import AwareDatetime, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOCAL = "postgresql+psycopg://{u}:{p}@localhost:5433/bsi"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = _LOCAL.format(u="bsi_app", p="app")
    owner_database_url: str = _LOCAL.format(u="bsi_owner", p="owner")
    # gemini-2.5-flash retires 2026-10-20. Slice 56's probe on the 20 Run 1
    # prompts (2026-10-08): 3.5-flash-lite searched 20 of 20 at a mean
    # $0.0300 per observation; 3.1-flash-lite 20 of 20 at $0.0537;
    # 3.8-flash 6 of 20 (findings-slice56).
    engine_model: str = "gemini-3.5-flash-lite"
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
    # Slice 56: max(50,000, the next multiple of 10,000 above the engine's
    # measured mean (30,039.5 micros, gemini-3.5-flash-lite in the probe)
    # plus 2,000 for extraction) = max(50,000, 40,000).
    obs_cost_estimate_micros: int = 50_000
    # Slice 6: days either side of a task's done_at that impact compares.
    # Copied onto the task when it is marked done, so changing it never
    # moves a window that is already open.
    impact_window_days: int = 14
    # Slice 37: the SERP provider's API login and password (the dashboard's
    # API Access tab). Empty = the Brand SERP audit is not configured.
    dataforseo_login: str = ""
    dataforseo_password: SecretStr = SecretStr("")


@lru_cache
def get_settings() -> Settings:
    return Settings()
