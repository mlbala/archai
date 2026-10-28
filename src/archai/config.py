from __future__ import annotations

import os
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROLE_KEYS = ("requirements", "cloud", "api", "security", "verifier")
PROVIDER_NAMES = ("openai", "anthropic", "gemini", "deepseek")


def user_config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / "archai"


def user_env_file() -> Path:
    return user_config_dir() / ".env"


def _env_files() -> tuple[Path, ...]:
    """Configuration files in increasing priority: user config, then the working directory."""
    return (user_env_file(), Path(".env"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ARCHAI_", env_file=".env", extra="ignore")

    output_dir: Path = Path("output")
    architect_provider: str = "openai"
    architect_model: str | None = None
    role_models: str | None = None
    gemini_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("ARCHAI_GEMINI_API_KEY", "GEMINI_API_KEY")
    )
    openai_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("ARCHAI_OPENAI_API_KEY", "OPENAI_API_KEY")
    )
    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ARCHAI_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    )
    deepseek_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ARCHAI_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"),
    )
    deepseek_base_url: str = "https://api.deepseek.com"
    # Claude: effort for architecture work ("" sends none) and server-side refusal fallbacks.
    anthropic_effort: str = "high"
    anthropic_fallbacks: bool = True
    max_generation_calls: int = 16
    max_generation_tokens: int = 400_000
    request_timeout_seconds: int = 300


def load_settings() -> Settings:
    """Load settings from the environment plus the user and working-directory .env files."""
    files = tuple(str(path) for path in _env_files())
    return Settings(_env_file=files or None)


def parse_role_models(value: str | None) -> dict[str, tuple[str, str | None]]:
    """Parse ``role=provider[:model]`` pairs separated by commas or newlines."""
    result: dict[str, tuple[str, str | None]] = {}
    if not value:
        return result
    for raw in value.replace("\n", ",").split(","):
        item = raw.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(f"role model {item!r} must look like role=provider[:model]")
        role, target = (part.strip() for part in item.split("=", 1))
        role = role.lower()
        if role not in ROLE_KEYS:
            raise ValueError(f"unknown architect role {role!r}; choose from {', '.join(ROLE_KEYS)}")
        provider, _, model = target.partition(":")
        provider = provider.strip().lower()
        if provider not in PROVIDER_NAMES:
            raise ValueError(f"role {role}: provider must be one of {', '.join(PROVIDER_NAMES)}")
        result[role] = (provider, model.strip() or None)
    return result
