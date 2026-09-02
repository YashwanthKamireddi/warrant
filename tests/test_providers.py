"""Two providers, one interface, and the engine cannot tell which answered.

The architectural claim this project makes is that the model is a component and
not the system. A second provider is how that claim gets tested rather than
asserted -- and Groq's free tier exists for a specific reason: a submission whose
numbers can only be checked by someone holding a paid key is a submission whose
numbers cannot really be checked.
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from warrant.providers import (
    DEFAULT_MODELS,
    AnthropicProvider,
    GroqProvider,
    resolve_provider,
)


class Shape(BaseModel):
    verdict: str
    reason: str


# -- resolution ------------------------------------------------------------ #


def test_no_credentials_resolves_to_nothing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("WARRANT_PROVIDER", "groq")
    assert resolve_provider() is None


def test_groq_is_used_when_pinned(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("WARRANT_PROVIDER", "groq")
    provider = resolve_provider()
    assert provider is not None
    assert provider.name == "groq"


def test_groq_serves_as_a_fallback_when_anthropic_is_unavailable(monkeypatch):
    """The point of the second provider: a reviewer with no paid key still gets
    a live run rather than a replayed transcript."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.delenv("WARRANT_PROVIDER", raising=False)
    monkeypatch.setattr(
        "warrant.providers.AnthropicProvider.__init__",
        lambda self, client=None: (_ for _ in ()).throw(RuntimeError("no creds")),
    )
    provider = resolve_provider()
    assert provider is not None
    assert provider.name == "groq"


def test_an_injected_client_is_always_anthropic(monkeypatch):
    monkeypatch.setenv("WARRANT_PROVIDER", "groq")
    provider = resolve_provider(client=object())
    assert provider is not None
    assert provider.name == "anthropic"


def test_every_provider_has_a_default_model():
    assert set(DEFAULT_MODELS) == {"anthropic", "groq"}
    assert all(DEFAULT_MODELS.values())


def test_groq_without_a_key_refuses_to_construct(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        GroqProvider()


# -- the groq request shape ------------------------------------------------ #


class _Response:
    def __init__(self, payload: str, status: int = 200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self._payload}}]}


def _capture(monkeypatch, payload: str, status: int = 200) -> dict:
    seen: dict = {}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return _Response(payload, status)

    monkeypatch.setattr("httpx.post", fake_post)
    return seen


def test_groq_asks_for_a_json_object(monkeypatch):
    seen = _capture(monkeypatch, json.dumps({"verdict": "allow", "reason": "fits"}))
    GroqProvider(api_key="gsk_test").structured(
        output_format=Shape, system="sys", content="msg", model="m", max_tokens=100
    )
    assert seen["json"]["response_format"] == {"type": "json_object"}
    assert seen["json"]["temperature"] == 0


def test_groq_sends_the_schema_because_it_is_not_enforced_server_side(monkeypatch):
    seen = _capture(monkeypatch, json.dumps({"verdict": "allow", "reason": "fits"}))
    GroqProvider(api_key="gsk_test").structured(
        output_format=Shape, system="sys", content="msg", model="m", max_tokens=100
    )
    system_message = seen["json"]["messages"][0]["content"]
    assert "JSON Schema" in system_message
    assert "verdict" in system_message


def test_groq_returns_the_validated_model(monkeypatch):
    _capture(monkeypatch, json.dumps({"verdict": "block", "reason": "out of scope"}))
    result = GroqProvider(api_key="gsk_test").structured(
        output_format=Shape, system="s", content="c", model="m", max_tokens=100
    )
    assert isinstance(result, Shape)
    assert result.verdict == "block"


def test_a_reply_that_does_not_fit_the_shape_is_a_failed_call(monkeypatch):
    """Coercing a half-understood reply would put it into the signing path."""
    _capture(monkeypatch, json.dumps({"nonsense": True}))
    with pytest.raises(RuntimeError, match="does not match the schema"):
        GroqProvider(api_key="gsk_test").structured(
            output_format=Shape, system="s", content="c", model="m", max_tokens=100
        )


def test_a_non_json_reply_is_a_failed_call(monkeypatch):
    _capture(monkeypatch, "I'm afraid I can't do that")
    with pytest.raises(RuntimeError):
        GroqProvider(api_key="gsk_test").structured(
            output_format=Shape, system="s", content="c", model="m", max_tokens=100
        )


def test_an_http_error_is_not_swallowed(monkeypatch):
    _capture(monkeypatch, "", status=429)
    with pytest.raises(RuntimeError, match="429"):
        GroqProvider(api_key="gsk_test").structured(
            output_format=Shape, system="s", content="c", model="m", max_tokens=100
        )


# -- the anthropic path is unchanged --------------------------------------- #


def test_anthropic_uses_server_side_schema_enforcement():
    seen: dict = {}

    class _Messages:
        def parse(self, **kwargs):
            seen.update(kwargs)

            class R:
                parsed_output = Shape(verdict="allow", reason="ok")

            return R()

    class _Client:
        messages = _Messages()

    result = AnthropicProvider(client=_Client()).structured(
        output_format=Shape, system="s", content="c", model="claude-opus-5", max_tokens=99
    )
    assert result.verdict == "allow"
    assert seen["output_format"] is Shape
    assert seen["model"] == "claude-opus-5"
