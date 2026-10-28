from __future__ import annotations

from dataclasses import dataclass

from archai.architect_providers.base import ArchitectProvider
from archai.config import PROVIDER_NAMES, ROLE_KEYS, Settings, parse_role_models
from archai.errors import ProviderError


@dataclass(frozen=True)
class ProviderInfo:
    name: str
    label: str
    default_model: str
    key_envs: tuple[str, ...]
    suggested: tuple[str, ...]
    notes: str


PROVIDERS: dict[str, ProviderInfo] = {
    "openai": ProviderInfo(
        "openai",
        "OpenAI",
        "gpt-6-sol",
        ("ARCHAI_OPENAI_API_KEY", "OPENAI_API_KEY"),
        ("gpt-6-sol", "gpt-6-luna", "gpt-6-astra", "gpt-5.5"),
        "Responses API with strict structured outputs.",
    ),
    "anthropic": ProviderInfo(
        "anthropic",
        "Anthropic Claude",
        "claude-opus-5-5",
        ("ARCHAI_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
        ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"),
        "Messages API with JSON-schema output, effort=high, refusal fallbacks on.",
    ),
    "gemini": ProviderInfo(
        "gemini",
        "Google Gemini",
        "gemini-3.1-pro-preview",
        ("ARCHAI_GEMINI_API_KEY", "GEMINI_API_KEY"),
        ("gemini-3.1-pro-preview",),
        "JSON-schema output; Pro preview models need a paid tier. See --remote for others.",
    ),
    "deepseek": ProviderInfo(
        "deepseek",
        "DeepSeek",
        "deepseek-v4-pro",
        ("ARCHAI_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"),
        ("deepseek-v4-pro", "deepseek-flash"),
        "OpenAI-compatible JSON mode; schema enforced locally with repair.",
    ),
}
assert tuple(PROVIDERS) == PROVIDER_NAMES
DEFAULT_MODELS = {name: info.default_model for name, info in PROVIDERS.items()}


@dataclass(frozen=True)
class RoleBinding:
    provider: str
    model: str


def check_provider(name: str) -> str:
    provider = name.strip().lower()
    if provider not in PROVIDERS:
        raise ProviderError(
            f"Unsupported architect provider {provider!r}; choose {', '.join(PROVIDERS)}",
            kind="configuration",
        )
    return provider


def selected_model(settings: Settings, provider: str, explicit_model: str | None) -> str:
    if explicit_model:
        return explicit_model
    if settings.architect_provider.lower() == provider and settings.architect_model:
        return settings.architect_model
    return DEFAULT_MODELS[provider]


def api_key_for(settings: Settings, provider: str) -> str | None:
    value = getattr(settings, f"{provider}_api_key", None)
    return value if isinstance(value, str) and value else None


def create_provider(settings: Settings, name: str | None, model: str | None) -> ArchitectProvider:
    provider = check_provider(name or settings.architect_provider)
    model_id = selected_model(settings, provider, model)
    key = api_key_for(settings, provider)
    if not key:
        raise ProviderError(
            f"{provider} API key is missing. Set {PROVIDERS[provider].key_envs[0]}, run "
            f"`archai model use {provider} --key`, or run `archai setup`.",
            kind="configuration",
        )
    timeout = settings.request_timeout_seconds
    if provider == "openai":
        from archai.architect_providers.openai import OpenAIArchitectProvider

        return OpenAIArchitectProvider(key, model_id, timeout_seconds=timeout)
    if provider == "anthropic":
        from archai.architect_providers.anthropic import AnthropicArchitectProvider

        return AnthropicArchitectProvider(
            key,
            model_id,
            timeout_seconds=timeout,
            effort=settings.anthropic_effort or None,
            fallbacks=settings.anthropic_fallbacks,
        )
    if provider == "deepseek":
        from archai.architect_providers.deepseek import DeepSeekArchitectProvider

        return DeepSeekArchitectProvider(
            key, model_id, timeout_seconds=timeout, base_url=settings.deepseek_base_url
        )
    from archai.architect_providers.gemini import GeminiArchitectProvider

    return GeminiArchitectProvider(key, model_id, timeout_seconds=timeout)


def resolve_role_bindings(
    settings: Settings,
    provider: str | None,
    model: str | None,
    role_models: list[str] | None = None,
) -> dict[str, RoleBinding]:
    """Map each specialist role to a provider/model, honouring per-role overrides."""
    default_provider = check_provider(provider or settings.architect_provider)
    overrides = parse_role_models(settings.role_models)
    overrides.update(parse_role_models(",".join(role_models or [])))
    bindings: dict[str, RoleBinding] = {}
    for role in ROLE_KEYS:
        role_provider, role_model = overrides.get(role, (default_provider, None))
        chosen_model = role_model or (
            model if role_provider == default_provider and model else None
        )
        bindings[role] = RoleBinding(
            role_provider, selected_model(settings, role_provider, chosen_model)
        )
    return bindings


def list_remote_models(settings: Settings, provider: str) -> list[str]:
    """Model IDs the configured key can use (a free listing call; no generation)."""
    provider = check_provider(provider)
    key = api_key_for(settings, provider)
    if not key:
        raise ProviderError(f"No {provider} API key configured", kind="configuration")
    try:
        if provider in {"openai", "deepseek"}:
            import openai

            client = openai.OpenAI(
                api_key=key,
                base_url=settings.deepseek_base_url if provider == "deepseek" else None,
                max_retries=0,
                timeout=30,
            )
            return sorted(model.id for model in client.models.list())
        if provider == "anthropic":
            import anthropic

            return sorted(model.id for model in anthropic.Anthropic(api_key=key).models.list())
        from google import genai

        names = []
        gemini = genai.Client(api_key=key)  # keep a reference: the pager reuses its connection
        for item in gemini.models.list():
            actions = getattr(item, "supported_actions", None) or []
            if not actions or "generateContent" in actions:
                names.append(str(item.name).removeprefix("models/"))
        return sorted(names)
    except ProviderError:
        raise
    except Exception as exc:  # provider SDK errors differ; report them uniformly
        raise ProviderError(
            f"Could not list {provider} models: {type(exc).__name__}", kind="provider_error"
        ) from exc
