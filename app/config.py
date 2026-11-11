"""All settings come from environment variables / the .env file."""

from functools import lru_cache

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()  # makes every .env line readable with os.getenv (used for provider keys)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_api_key: str = "change-me"
    default_provider: str = "auto"  # "auto" = try PROVIDER_ORDER in sequence
    provider_order: str = "gemini,groq,cerebras,mistral,openrouter,local"
    # Per-provider keys/models (GEMINI_API_KEY, GROQ_MODEL ...) are read in providers.py

    max_rows: int = 1000
    max_tables_in_prompt: int = 12
    max_repair_attempts: int = 2
    request_timeout: int = 60
    enforce_table_whitelist: bool = True

    schema_file: str = "schema/schema.json"
    examples_file: str = "schema/examples.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
