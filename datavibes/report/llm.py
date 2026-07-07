"""The LLM seam — a one-method interface plus provider implementations.

The reporter depends only on the :class:`LlmClient` protocol, so tests inject a
fake and no network is touched. Two providers ship:

* :class:`AnthropicLlmClient` — Claude models via the ``anthropic`` SDK.
* :class:`OpenAiLlmClient` — any OpenAI-compatible Chat Completions endpoint
  (DeepSeek, OpenAI, local servers, …) via the ``openai`` SDK + a ``base_url``.

Both SDKs are imported lazily so the core SDK works without them. The API key is
read from the environment variable named in config — never from ``config.yaml``.
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

from datavibes.config.app_config import LlmConfig
from datavibes.errors import DatavibesError


@runtime_checkable
class LlmClient(Protocol):
    """Turn a system + user prompt into completion text. That's all the reporter needs."""

    def complete(self, system: str, prompt: str) -> str: ...


class AnthropicLlmClient:
    """`LlmClient` backed by the Anthropic Messages API (``claude-*`` models)."""

    def __init__(self, config: LlmConfig):
        self.config = config
        self._client = None  # built lazily on first use

    def complete(self, system: str, prompt: str) -> str:
        client = self._ensure_client()
        # Opus 4.8: adaptive thinking is opt-in and sampling params are removed;
        # a single non-streaming call suffices for a few-thousand-token report.
        response = client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            system=system,
            output_config={"effort": self.config.effort},
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        api_key = os.environ.get(self.config.api_key_env, "")
        if not api_key:
            raise DatavibesError(
                f"LLM reports need an API key in ${self.config.api_key_env} "
                f"(set it in .env or the environment)"
            )
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise DatavibesError(
                "LLM reports require the optional 'anthropic' dependency; "
                "install it with: pip install 'datavibes[report]'"
            ) from exc
        self._client = anthropic.Anthropic(api_key=api_key)
        return self._client


class OpenAiLlmClient:
    """`LlmClient` backed by any OpenAI-compatible Chat Completions endpoint.

    Works with OpenAI itself and drop-in compatibles such as **DeepSeek**
    (``base_url=https://api.deepseek.com``, ``model=deepseek-chat``). The
    Anthropic-only ``effort`` setting is ignored here.
    """

    def __init__(self, config: LlmConfig):
        self.config = config
        self._client = None  # built lazily on first use

    def complete(self, system: str, prompt: str) -> str:
        client = self._ensure_client()
        response = client.chat.completions.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return (response.choices[0].message.content or "").strip()

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        api_key = os.environ.get(self.config.api_key_env, "")
        if not api_key:
            raise DatavibesError(
                f"LLM reports need an API key in ${self.config.api_key_env} "
                f"(set it in .env or the environment)"
            )
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise DatavibesError(
                "OpenAI-compatible LLM reports require the optional 'openai' "
                "dependency; install it with: pip install 'datavibes[openai]'"
            ) from exc
        kwargs = {"api_key": api_key}
        if self.config.base_url:
            kwargs["base_url"] = self.config.base_url
        self._client = OpenAI(**kwargs)
        return self._client


def default_llm_client(config: LlmConfig) -> LlmClient:
    """The production `LlmClient` factory (injected by the SDK), by provider."""
    if config.provider == "openai":
        return OpenAiLlmClient(config)
    if config.provider == "anthropic":
        return AnthropicLlmClient(config)
    raise DatavibesError(
        f"unknown llm.provider '{config.provider}' (expected 'anthropic' or 'openai')"
    )
