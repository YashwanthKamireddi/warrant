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

__all__ = [
    "AnthropicProvider",
    "model_for",
    "GroqProvider",
    "Provider",
    "ProviderName",
    "resolve_provider",
    "resolve_providers",
]

ProviderName = Literal["anthropic", "groq"]

def model_for(provider: ProviderName, override: str | None = None) -> str:
    """The model id to use for one provider.

    Model names are provider-specific, so a single ``WARRANT_MODEL`` applied
    across providers is a bug waiting to happen -- and was one: a leftover
    ``WARRANT_MODEL=claude-sonnet-5`` was handed to Groq, which 404s, and the
    engine silently fell through to a transcript rather than using a working key.

    So the generic override is only honoured when a single provider is pinned.
    Otherwise each provider reads its own ``WARRANT_<PROVIDER>_MODEL``.
    """
    scoped = os.environ.get(f"WARRANT_{provider.upper()}_MODEL")
    if scoped:
        return scoped
    if override:
        return override
    pinned = (os.environ.get("WARRANT_PROVIDER") or "").lower() == provider
    generic = os.environ.get("WARRANT_MODEL")
    if pinned and generic:
        return generic
    return DEFAULT_MODELS[provider]


DEFAULT_MODELS: dict[ProviderName, str] = {
    "anthropic": "claude-opus-5",
    # Groq rotates which open-weights models it serves, so this is a default and
    # not a guarantee -- GET /openai/v1/models lists what an account can actually
    # reach, and WARRANT_MODEL overrides. 120B is comfortably strong enough for
    # the two narrow jobs asked of it.
    "groq": "openai/gpt-oss-120b",
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


def resolve_providers(
    preferred: str | None = None, *, client: Any | None = None
) -> list[Provider]:
    """Every provider that can be constructed, in the order they should be tried.

    A list rather than a single choice, because constructing a client proves a
    credential was *found*, not that it works -- an expired token builds a client
    happily and only fails when it is used. Returning one provider meant a stale
    Anthropic profile shadowed a working Groq key and the fallback never ran.
    The caller tries them in order and moves on when one actually fails.

    ``WARRANT_PROVIDER`` pins a single provider. Otherwise Anthropic leads -- it
    enforces the schema server-side and is the stack Razorpay itself uses -- with
    Groq behind it, so a reviewer holding only a free key still gets a live run.
    """
    if client is not None:
        return [AnthropicProvider(client=client)]

    wanted = (preferred or os.environ.get("WARRANT_PROVIDER") or "auto").lower()
    pinned = wanted in ("anthropic", "groq")
    order: list[ProviderName] = [wanted] if pinned else ["anthropic", "groq"]  # type: ignore[list-item]

    built: list[Provider] = []
    for name in order:
        try:
            built.append(AnthropicProvider() if name == "anthropic" else GroqProvider())
        except Exception:  # noqa: BLE001 - an unavailable provider is a normal state
            continue
    return built


def resolve_provider(
    preferred: str | None = None, *, client: Any | None = None
) -> Provider | None:
    """The first constructible provider, for callers that only need to report one."""
    providers = resolve_providers(preferred, client=client)
    return providers[0] if providers else None
