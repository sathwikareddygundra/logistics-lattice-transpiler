import os
import sys
from enum import StrEnum
from functools import lru_cache

from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    dev = "dev"
    staging = "staging"
    prod = "prod"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file_encoding="utf-8", extra="ignore")

    environment: Environment = Environment.dev
    groq_api_key: str
    log_level: str = "INFO"

    # Filled in for real once T-9 inventories each plant's database
    mcw_db_url: str | None = None
    ycw_db_url: str | None = None
    vgu_db_url: str | None = None


@lru_cache
def get_settings() -> Settings:
    env = os.environ.get("ENVIRONMENT", "dev")
    env_file = f".env.{env}"
    try:
        return Settings(_env_file=env_file)  # type: ignore[call-arg]
    except ValidationError as e:
        print(f"FATAL: invalid or missing configuration for environment '{env}':", file=sys.stderr)
        print(e, file=sys.stderr)
        sys.exit(1)
