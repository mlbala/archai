from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ARCHAI_", env_file=".env", extra="ignore")

    output_dir: Path = Path("output")
    architect_provider: str = "gemini"
    architect_model: str | None = None
    gemini_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("ARCHAI_GEMINI_API_KEY", "GEMINI_API_KEY")
    )
    openai_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("ARCHAI_OPENAI_API_KEY", "OPENAI_API_KEY")
    )
    max_generation_calls: int = 12
    max_generation_tokens: int = 120_000
