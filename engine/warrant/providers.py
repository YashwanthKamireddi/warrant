"""Model providers.

Warrant treats the model as a component, not as the system. This module is where
that claim gets tested: two providers, one interface, and the engine cannot tell
which one answered.

  anthropic   Claude, via the official SDK and its strict json_schema output.
              Razorpay's own Agent Studio is built on the Claude Agent SDK, so
              this is the default.
  groq        An OpenAI-compatible endpoint on Groq's free tier, called over
              plain HTTP. It exists so **a reviewer can reproduce the benchmark
              without paying for anything.**

That second reason is the important one. A submission whose numbers can only be
checked by someone holding a paid API key is a submission whose numbers cannot
really be checked.

The two differ in how hard they enforce a schema. Anthropic validates against a
JSON Schema server-side; Groq guarantees only that the response is *some* JSON
object. So the Groq path sends the schema in the prompt and validates the reply
with the same pydantic model either way -- a provider that returns something
unusable is a failed call, not a silently degraded result.
"""

from __future__ import annotations

import json
import os
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ValidationError

__all__ = ["Provider", "ProviderName", "resolve_provider", "AnthropicProvider", "GroqProvider"]

ProviderName = Literal["anthropic", "groq"]

DEFAULT_MODELS: dict[ProviderName, str] = {
    "anthropic": "claude-opus-5",
    # 70B, free tier, and strong enough for the two narrow jobs asked of it.
    "groq": "llama-3.3-70b-versatile",
}


class Provider(Protocol):
    """Anything that can turn a system prompt plus a message into a typed object."""

    name: ProviderName

    def structured(
        self,
        *,
        output_format: type[BaseModel],
        system: str,
        content: str,
        model: str,
        max_tokens: int,
    ) -> BaseModel: ...


class AnthropicProvider:
    """Claude, with server-side schema enforcement."""

    name: ProviderName = "anthropic"

    def __init__(self, client: Any | None = None) -> None:
        if client is not None:
            self._client = client
            return
        import anthropic

        self._client = anthropic.Anthropic()

    def structured(
        self,
        *,
        output_format: type[BaseModel],
        system: str,
        content: str,
        model: str,
        max_tokens: int,
    ) -> BaseModel:
        response = self._client.messages.parse(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
            output_format=output_format,
        )
        return response.parsed_output


class GroqProvider:
    """Groq's OpenAI-compatible endpoint, called over plain HTTP.

    No SDK: the request is four keys of JSON and adding a dependency to send it
    would be the more complicated choice, not the simpler one.
    """

    name: ProviderName = "groq"
    ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, api_key: str | None = None, *, timeout: float = 60.0) -> None:
        key = api_key or os.environ.get("GROQ_API_KEY")
        if not key:
            raise RuntimeError("GROQ_API_KEY is not set")
        self._key = key
        self._timeout = timeout

    def structured(
        self,
        *,
        output_format: type[BaseModel],
        system: str,
        content: str,
        model: str,
        max_tokens: int,
    ) -> BaseModel:
        import httpx

        # Groq guarantees valid JSON, not a valid *shape*. The schema goes in the
        # prompt, and pydantic is what actually enforces it.
        schema = json.dumps(output_format.model_json_schema(), separators=(",", ":"))
        instructions = (
            f"{system}\n\n"
            "Reply with a single JSON object and nothing else. It must validate "
            f"against this JSON Schema:\n{schema}"
        )

        response = httpx.post(
            self.ENDPOINT,
            timeout=self._timeout,
            headers={"Authorization": f"Bearer {self._key}"},
            json={
                "model": model,
                "max_tokens": max_tokens,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": content},
                ],
            },
        )
        response.raise_for_status()
        body = response.json()["choices"][0]["message"]["content"]

        try:
            return output_format.model_validate_json(body)
        except ValidationError as exc:
            # A reply that does not fit the shape is a failed call. Coercing it
            # would put a half-understood scope into the signing path.
            raise RuntimeError(
                f"{model} returned a reply that does not match the schema: {exc}"
            ) from exc


def resolve_provider(
    preferred: str | None = None, *, client: Any | None = None
) -> Provider | None:
    """Return the first provider that can actually be constructed.

    ``WARRANT_PROVIDER`` pins one explicitly. Otherwise Anthropic is tried first
    -- it enforces the schema server-side and is the stack Razorpay itself uses --
    and Groq is the fallback, so a reviewer with no paid key still gets a live run.
    """
    if client is not None:
        return AnthropicProvider(client=client)

    wanted = (preferred or os.environ.get("WARRANT_PROVIDER") or "auto").lower()
    order: list[ProviderName]
    if wanted == "anthropic":
        order = ["anthropic"]
    elif wanted == "groq":
        order = ["groq"]
    else:
        order = ["anthropic", "groq"]

    for name in order:
        try:
            return AnthropicProvider() if name == "anthropic" else GroqProvider()
        except Exception:  # noqa: BLE001 - an unavailable provider is a normal state
            continue
    return None
