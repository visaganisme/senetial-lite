"""Per-provider model construction. One OpenAI-compatible client for groq/cloudflare/
openrouter; Cohere via its official LangChain integration."""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel

from sentinel.config import secret
from sentinel.router.schema import ChainEntry

OPENAI_COMPAT: dict[str, tuple[str, str]] = {
    # provider -> (base_url, env key name)
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
}
CF_AI_BASE = "https://api.cloudflare.com/client/v4/accounts"


class MissingKey(RuntimeError):
    """Provider has no key in .env; treated as a fallback condition, not an abort."""


def make_model(entry: ChainEntry, timeout_s: float = 45.0) -> BaseChatModel:
    if entry.provider == "cohere":
        key = secret("COHERE_API_KEY")
        if not key:
            raise MissingKey("cohere")
        from langchain_cohere import ChatCohere

        return ChatCohere(model=entry.model, cohere_api_key=key, timeout=timeout_s)

    base_key = OPENAI_COMPAT.get(entry.provider)
    if base_key:
        base, env_name = base_key
        key = secret(env_name)
        if not key:
            raise MissingKey(entry.provider)
        from langchain_openai import ChatOpenAI

        headers = (
            {"HTTP-Referer": "http://localhost", "X-Title": "sentinel-lite"}
            if entry.provider == "openrouter"
            else None
        )
        return ChatOpenAI(
            model=entry.model,
            base_url=base,
            api_key=key,
            timeout=timeout_s,
            max_retries=0,
            default_headers=headers,
            temperature=0.0,
        )

    if entry.provider == "cloudflare":
        account = secret("CLOUDFLARE_ACCOUNT_ID")
        key = secret("CLOUDFLARE_API_TOKEN")
        if not account or not key:
            raise MissingKey("cloudflare")
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=entry.model,
            base_url=f"{CF_AI_BASE}/{account}/ai/v1",
            api_key=key,
            timeout=timeout_s,
            max_retries=0,
            temperature=0.0,
        )

    raise ValueError(f"unknown provider: {entry.provider}")
