"""Provider abstraction and model catalog for LLM inference.

Kept separate from inference.py so a future CLI/GUI layer can list
available providers and models (list_providers/list_models) without
importing prompt/dataframe machinery.
"""

from typing import Dict, List, Optional

ALPINE_BASE_URL = "https://api.prod.alpineai.ch/v1"

MODEL_REGISTRY: Dict[str, Dict[str, str]] = {
    "openai": {
        "gpt-4o": "GPT-4o",
        "gpt-4o-mini": "GPT-4o mini",
        "gpt-4.1": "GPT-4.1",
        "gpt-4.1-mini": "GPT-4.1 mini",
        "o3": "o3",
        "o3-mini": "o3-mini",
    },
    "swissgpt": {},
    "anthropic": {
        "claude-opus-5-5": "Claude Opus 5.5",
        "claude-sonnet-5": "Claude Sonnet 5",
        "claude-haiku-4-5-20251001": "Claude Haiku 4.5",
    },
}


class LLMProviderError(Exception):
    """Raised when a provider fails to complete a request."""


class BaseProvider:
    """Common interface every provider implements."""

    def complete(self, system_prompt: str, user_prompt: str, model: str) -> str:
        raise NotImplementedError


class OpenAIProvider(BaseProvider):
    """Provider for the OpenAI Chat Completions API."""

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        import openai

        self._openai = openai
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)

    def complete(self, system_prompt: str, user_prompt: str, model: str) -> str:
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                top_p=0.9,
                frequency_penalty=0,
                presence_penalty=0,
            )
        except self._openai.APIConnectionError as e:
            raise LLMProviderError(f"OpenAI API request failed to connect: {e}") from e
        return response.choices[0].message.content


class SwissGPTProvider(OpenAIProvider):
    """Provider for SwissGPT/AlpineAI, an OpenAI-API-compatible endpoint."""

    def __init__(self, api_key: str):
        super().__init__(api_key, base_url=ALPINE_BASE_URL)


class AnthropicProvider(BaseProvider):
    """Provider for the Anthropic Claude Messages API."""

    def __init__(self, api_key: str):
        try:
            import anthropic
        except ImportError as e:
            raise ImportError(
                "Anthropic support requires the 'anthropic' package. "
                "Install it with: pip install anthropic"
            ) from e

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key)

    def complete(self, system_prompt: str, user_prompt: str, model: str) -> str:
        try:
            response = self.client.messages.create(
                model=model,
                system=system_prompt,
                max_tokens=1024,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except self._anthropic.APIConnectionError as e:
            raise LLMProviderError(f"Anthropic API request failed to connect: {e}") from e
        return response.content[0].text


PROVIDERS = {
    "openai": OpenAIProvider,
    "swissgpt": SwissGPTProvider,
    "anthropic": AnthropicProvider,
}


def get_provider(name: str, api_key: str) -> BaseProvider:
    """Instantiate the provider registered under ``name``."""
    try:
        provider_cls = PROVIDERS[name]
    except KeyError:
        raise ValueError(
            f"Unknown provider '{name}'. Choose one of: {', '.join(PROVIDERS)}"
        ) from None
    return provider_cls(api_key)


def list_providers() -> List[str]:
    """Return the names of all supported providers."""
    return list(PROVIDERS)


def list_models(provider: str) -> Dict[str, str]:
    """Return the {model_id: display_name} catalog for ``provider``."""
    if provider not in MODEL_REGISTRY:
        raise ValueError(
            f"Unknown provider '{provider}'. Choose one of: {', '.join(PROVIDERS)}"
        )
    return MODEL_REGISTRY[provider]


def list_swissgpt_models(api_key: str) -> List[str]:
    """Fetch the live model list from the SwissGPT/AlpineAI /v1/models endpoint."""
    provider = SwissGPTProvider(api_key)
    return [model.id for model in provider.client.models.list()]
