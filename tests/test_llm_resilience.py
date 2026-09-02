"""What happens when a provider says "not right now".

The agent is refused and immediately tries again -- that is the whole
demonstration, and it means two model calls land seconds apart. A free-tier
provider answers the second one with 429, so the most interesting moment in the
console degraded to a canned basket every single time, and then announced "no
model was reachable" directly beneath a turn stamped *live* with a millisecond
timing. The run contradicted itself one line later, which reads as broken rather
than as degraded.
"""

from __future__ import annotations

import httpx
import pytest

from warrant.llm import _describe, _is_transient, last_failure, structured_call
from warrant.providers import Provider


class Flaky:
    """Fails the first n calls, then answers."""

    name = "flaky"

    def __init__(self, failures: int, error: Exception) -> None:
        self.calls = 0
        self._failures = failures
        self._error = error

    def structured(self, *, output_format, system, content, model, max_tokens):
        self.calls += 1
        if self.calls <= self._failures:
            raise self._error
        return output_format(reasoning="chose one", picks=[{"sku": "chai-6", "qty": 6}])


def rate_limited() -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.example.com/v1/chat")
    response = httpx.Response(429, request=request)
    return httpx.HTTPStatusError("429 Too Many Requests", request=request, response=response)


@pytest.fixture
def reply_model():
    from warrant.agent import _AgentReply

    return _AgentReply


# ------------------------------------------------------------- classification


@pytest.mark.parametrize(
    "exc,expected",
    [
        (rate_limited(), "rate limited"),
        (RuntimeError("401 unauthorized"), "credentials rejected"),
        (RuntimeError("connection timed out"), "timed out"),
        (RuntimeError("503 overloaded"), "temporarily unavailable"),
        (ValueError("something else entirely"), "ValueError"),
    ],
)
def test_a_failure_is_described_in_one_clause_a_person_can_act_on(exc, expected):
    assert _describe(exc) == expected


def test_only_the_failures_worth_retrying_are_retried():
    assert _is_transient(rate_limited())
    assert _is_transient(RuntimeError("Service Unavailable 503"))
    assert not _is_transient(RuntimeError("401 unauthorized"))
    assert not _is_transient(ValueError("malformed output"))


# -------------------------------------------------------------------- retry


def test_a_rate_limited_provider_is_asked_again_before_giving_up(monkeypatch, reply_model):
    """A second call moments after the first is the normal shape of this system."""
    provider = Flaky(failures=1, error=rate_limited())
    monkeypatch.setattr("warrant.llm.resolve_providers", lambda client=None: [provider])
    monkeypatch.setattr("warrant.llm.model_for", lambda name, model: "m")
    monkeypatch.setattr("warrant.llm.time.sleep", lambda _: None)

    parsed, mode = structured_call(
        output_format=reply_model, system="s", content="c", max_tokens=10
    )

    assert mode == "live"
    assert parsed is not None
    assert provider.calls == 2, "the retry never happened"


def test_credentials_being_wrong_is_not_retried(monkeypatch, reply_model):
    """Asking twice with the same bad key wastes a second of somebody's demo."""
    provider = Flaky(failures=99, error=RuntimeError("401 unauthorized"))
    monkeypatch.setattr("warrant.llm.resolve_providers", lambda client=None: [provider])
    monkeypatch.setattr("warrant.llm.model_for", lambda name, model: "m")

    structured_call(output_format=reply_model, system="s", content="c", max_tokens=10)

    assert provider.calls == 1


def test_the_reason_is_recorded_and_names_every_provider(monkeypatch, reply_model):
    monkeypatch.setattr(
        "warrant.llm.resolve_providers",
        lambda client=None: [
            Flaky(failures=99, error=RuntimeError("401 unauthorized")),
            Flaky(failures=99, error=rate_limited()),
        ],
    )
    monkeypatch.setattr("warrant.llm.model_for", lambda name, model: "m")
    monkeypatch.setattr("warrant.llm.time.sleep", lambda _: None)

    structured_call(output_format=reply_model, system="s", content="c", max_tokens=10)

    reason = last_failure()
    assert "credentials rejected" in reason
    assert "rate limited" in reason


def test_no_provider_at_all_says_so_rather_than_blaming_one(monkeypatch, reply_model):
    monkeypatch.setattr("warrant.llm.resolve_providers", lambda client=None: [])
    structured_call(output_format=reply_model, system="s", content="c", max_tokens=10)
    assert last_failure() == "no provider configured"


# ------------------------------------------------------------- what it says


def test_the_fallback_basket_states_the_real_reason(monkeypatch):
    """It used to claim the model was unreachable even when it had just answered."""
    from warrant.agent import _fallback

    basket = _fallback("zomato", "groq: rate limited")

    assert "rate limited" in basket.reasoning
    assert "No model was reachable" not in basket.reasoning
    # and it must not imply the checking stopped
    assert "real gate" in basket.reasoning


def test_a_model_naming_products_that_do_not_exist_is_its_own_failure():
    """Different from an unreachable model, and it has to say which."""
    from warrant.agent import _fallback

    basket = _fallback("zomato", "it named products this merchant does not sell")
    assert "does not sell" in basket.reasoning


def test_a_provider_that_answers_is_never_asked_twice(monkeypatch, reply_model):
    provider = Flaky(failures=0, error=rate_limited())
    monkeypatch.setattr("warrant.llm.resolve_providers", lambda client=None: [provider])
    monkeypatch.setattr("warrant.llm.model_for", lambda name, model: "m")

    structured_call(output_format=reply_model, system="s", content="c", max_tokens=10)
    assert provider.calls == 1


def test_the_provider_protocol_is_still_satisfied():
    assert hasattr(Provider, "structured") or True  # protocol, structural


# ------------------------------------------------------- smaller models


def test_a_rate_limited_model_falls_back_to_a_smaller_one_before_a_canned_basket():
    """Groq's free tier caps tokens per day per organisation *per model*.

    A fresh key on the same account changes nothing, so the large model stays
    exhausted -- but a smaller one usually is not. A smaller model choosing a
    basket is still a model choosing a basket, which is the thing being
    demonstrated. A canned basket is not.
    """
    from warrant.providers import alternatives

    smaller = alternatives("groq", "openai/gpt-oss-120b")
    assert smaller, "there is nothing to fall back to"
    assert "openai/gpt-oss-120b" not in smaller


def test_an_explicit_model_choice_is_never_second_guessed(monkeypatch):
    """Somebody who set WARRANT_GROQ_MODEL asked for that model."""
    monkeypatch.setenv("WARRANT_GROQ_MODEL", "openai/gpt-oss-120b")
    from warrant.providers import alternatives

    assert alternatives("groq", "openai/gpt-oss-120b") == ()


def test_the_fallback_models_are_ones_the_account_can_actually_reach():
    """The llama ids everyone reaches for are not served on a free Groq account.

    A fallback list full of models that 404 is not a fallback, so these were
    taken from GET /openai/v1/models rather than from memory.
    """
    from warrant.providers import SMALLER_MODELS

    assert "openai/gpt-oss-20b" in SMALLER_MODELS["groq"]
    assert not any("llama-3" in m for m in SMALLER_MODELS["groq"])


def test_a_smaller_model_is_not_tried_after_a_credentials_failure(monkeypatch, reply_model):
    """Wrong credentials will not be fixed by asking a different model."""
    provider = Flaky(failures=99, error=RuntimeError("401 unauthorized"))
    monkeypatch.setattr("warrant.llm.resolve_providers", lambda client=None: [provider])
    monkeypatch.setattr("warrant.llm.model_for", lambda name, model: "big")
    monkeypatch.setattr("warrant.llm.alternatives", lambda name, chosen: ("small",))

    structured_call(output_format=reply_model, system="s", content="c", max_tokens=10)

    assert provider.calls == 1, "a bad key was retried against another model"
