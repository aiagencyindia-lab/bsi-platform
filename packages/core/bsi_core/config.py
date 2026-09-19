"""Settings, read once from the environment (and .env)."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

_LOCAL = "postgresql+psycopg://{u}:{p}@localhost:5433/bsi"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = _LOCAL.format(u="bsi_app", p="app")
    owner_database_url: str = _LOCAL.format(u="bsi_owner", p="owner")
    engine_model: str = "gemini-3.8-flash"
    extract_model: str = "gemini-3.5-flash-lite"
    judge_mode: Literal["batched", "isolated"] = "batched"
    raw_store_dir: str = "./data"


@lru_cache
def get_settings() -> Settings:
    return Settings()
