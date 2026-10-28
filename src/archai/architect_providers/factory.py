from archai.architect_providers.base import ArchitectProvider
from archai.architect_providers.gemini import GeminiArchitectProvider
from archai.architect_providers.openai import OpenAIArchitectProvider
from archai.config import Settings
from archai.errors import ProviderError

DEFAULT_MODELS = {"gemini": "gemini-2.5-pro", "openai": "gpt-4o-mini"}


def selected_model(settings: Settings, provider: str, explicit_model: str | None) -> str:
    if explicit_model:
        return explicit_model
    if settings.architect_provider.lower() == provider and settings.architect_model:
        return settings.architect_model
    return DEFAULT_MODELS[provider]


def create_provider(settings: Settings, name: str | None, model: str | None) -> ArchitectProvider:
    provider = (name or settings.architect_provider).lower()
    if provider not in DEFAULT_MODELS:
        raise ProviderError(f"Unsupported architect provider {provider!r}; choose openai or gemini")
    model_id = selected_model(settings, provider, model)
    key = settings.openai_api_key if provider == "openai" else settings.gemini_api_key
    if not key:
        env_name = "OPENAI_API_KEY" if provider == "openai" else "GEMINI_API_KEY"
        raise ProviderError(f"{provider} API key is missing. Set {env_name} or run archai setup.")
    if provider == "openai":
        return OpenAIArchitectProvider(key, model_id)
    return GeminiArchitectProvider(key, model_id)
