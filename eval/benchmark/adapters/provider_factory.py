"""Provider configuration shared by reproducible Track B runners."""
from __future__ import annotations

import os


CANDIDATES = {
    "groq": ("GROQ_API_KEY", "https://api.groq.com/openai/v1"),
    "fireworks": ("FIREWORKS_API_KEY", "https://api.fireworks.ai/inference/v1"),
    "nvidia": ("NVIDIA_API_KEY", "https://integrate.api.nvidia.com/v1"),
    "dashscope": ("DASHSCOPE_API_KEY", None),
    "mistral": ("MISTRAL_API_KEY", "https://api.mistral.ai/v1"),
    "sambanova": ("SAMBANOVA_API_KEY", "https://api.sambanova.ai/v1"),
    "openai": ("OPENAI_API_KEY", None),
    "anthropic": ("ANTHROPIC_API_KEY", None),
}


class ProviderConfigurationError(ValueError):
    pass


def provider_config_for_track(track: str, provider: str | None, model: str | None) -> dict:
    if not model:
        raise ProviderConfigurationError("--model is required for Track B")
    native = {"track_b_openai_responses": "openai", "track_b_anthropic": "anthropic"}
    if track in native:
        if provider is not None:
            raise ProviderConfigurationError(f"--provider is redundant for {track}")
        provider = native[track]
    elif track == "track_b_frontier":
        if not provider:
            raise ProviderConfigurationError("--provider is required for track_b_frontier")
    else:
        raise ProviderConfigurationError(f"unsupported Track B track: {track}")
    if provider not in CANDIDATES:
        raise ProviderConfigurationError(f"unsupported provider: {provider}")
    key_name, base_url = CANDIDATES[provider]
    if provider == "dashscope":
        base_url = os.environ.get("DASHSCOPE_BASE_URL")
    if not os.environ.get(key_name) or (not base_url and provider not in {"openai", "anthropic"}):
        raise RuntimeError("credential_missing")
    config = {"provider": provider, "api_key": os.environ[key_name], "model": model}
    if base_url:
        config["base_url"] = base_url
    return config
