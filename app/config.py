"""All settings come from environment variables / the .env file."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_api_key: str = "change-me"
    default_provider: str = "openai"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"

    local_base_url: str = "http://localhost:11434/v1"
    local_model: str = "qwen2.5-coder:7b"
    local_api_key: str = "ollama"  # Ollama ignores it, the SDK just needs something

    max_rows: int = 1000
    max_tables_in_prompt: int = 12
    max_repair_attempts: int = 2
    request_timeout: int = 120
    enforce_table_whitelist: bool = True

    schema_file: str = "schema/schema.json"
    examples_file: str = "schema/examples.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
