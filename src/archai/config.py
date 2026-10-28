from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ARCHAI_", env_file=".env", extra="ignore")

    output_dir: Path = Path("output")
    architect_provider: str = "gemini"
    architect_model: str = "gemini-2.5-pro"
    gemini_api_key: str | None = None
    max_generation_calls: int = 12
    max_generation_tokens: int = 120_000
