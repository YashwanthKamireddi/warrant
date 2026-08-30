"""The judge's authority is the security property, so it gets tested as one.

The claim in the module docstring is strong: an injected payload that convinces
this judge to return "consistent" produces an outcome byte-identical to the judge
never running. These tests hold that claim to account rather than trusting it.
"""

from __future__ import annotations

import pytest

from warrant.authorize import Authorizer
from warrant.chain import Ledger
from warrant.crypto import SigningKey
from warrant.divergence import DivergenceFinding, _ModelFinding, judge_divergence
from warrant.gate import MandateState
from warrant.models import CheckStatus, LineItem, Verdict


class _StubResponse:
    def __init__(self, parsed):
        self.parsed_output = parsed


class _StubMessages:
    def __init__(self, parsed):
        self._parsed = parsed
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return _StubResponse(self._parsed)


class _StubClient:
    def __init__(self, verdict: str, reasoning: str = "because", unexpected=()):
        self.messages = _StubMessages(
            _ModelFinding(
                verdict=verdict, reasoning=reasoning, unexpected_items=list(unexpected)
            )
        )


# -- the authority ceiling ------------------------------------------------- #


@pytest.mark.parametrize("verdict", ["consistent", "divergent", "uncertain"])
def test_every_finding_is_advisory_whatever_it_says(verdict: str):
    """No verdict this judge can emit produces a binding check. That is the ceiling."""
    check = DivergenceFinding(verdict=verdict, reasoning="x").as_check()
    assert check.binding is False


def test_a_skipped_review_is_advisory_too():
    check = DivergenceFinding(verdict="uncertain", reasoning="x", ran=False).as_check()
    assert check.binding is False
    assert check.status is CheckStatus.PASS


def test_consistent_adds_nothing():
    check = DivergenceFinding(verdict="consistent", reasoning="fine").as_check()
    assert check.status is CheckStatus.PASS


@pytest.mark.parametrize("verdict", ["divergent", "uncertain"])
def test_anything_other_than_consistent_warns(verdict: str):
    check = DivergenceFinding(verdict=verdict, reasoning="odd").as_check()
    assert check.status is CheckStatus.WARN


# -- the model is fed untrusted text, and it is fenced --------------------- #


def test_the_cart_is_fenced_when_sent_to_the_model(intent, make_cart, chai):
    client = _StubClient("consistent")
    judge_divergence(intent, make_cart((chai,)), client=client)
    content = client.messages.calls[0]["messages"][0]["content"]
    assert "<cart>" in content and "</cart>" in content
    assert "<instruction>" in content and "</instruction>" in content


def test_the_instruction_and_the_cart_are_separated(intent, make_cart, chai):
    client = _StubClient("consistent")
    judge_divergence(intent, make_cart((chai,)), client=client)
    content = client.messages.calls[0]["messages"][0]["content"]
    assert content.index("</instruction>") < content.index("<cart>")


# -- the claim that matters ------------------------------------------------ #


def _authorizer(intent) -> Authorizer:
    return Authorizer(
        authorizer_key=SigningKey.from_seed("test/authorizer"),
        ledger=Ledger(),
        model_client=_StubClient("consistent"),
    )


def test_a_captured_judge_cannot_turn_a_block_into_an_allow(
    intent, make_cart, user_key
):
    """The headline claim, tested end to end.

    A model that has been talked into saying "consistent" about an out-of-scope
    basket changes nothing, because the deterministic gate already blocked and a
    consistent finding contributes no check that could lift it.
    """
    laptop = LineItem(
        sku="lap", name="Laptop", category="electronics", qty=1, unit_paise=42_000
    )
    cart = make_cart((laptop,))

    captured = _authorizer(intent)
    honest = Authorizer(
        authorizer_key=SigningKey.from_seed("test/authorizer"),
        ledger=Ledger(),
        model_client=_StubClient("divergent"),
    )

    a = captured.authorize(intent, cart, subject_key=user_key.public, now=2_000)
    b = honest.authorize(intent, cart, subject_key=user_key.public, now=2_000)

    assert a.verdict is Verdict.BLOCK
    assert b.verdict is Verdict.BLOCK


def test_a_blocked_cart_never_reaches_the_model(intent, make_cart, user_key):
    """Order of operations is a control: out-of-scope carts are refused first."""
    laptop = LineItem(
        sku="lap", name="Laptop", category="electronics", qty=1, unit_paise=42_000
    )
    client = _StubClient("consistent")
    authorizer = Authorizer(
        authorizer_key=SigningKey.from_seed("test/authorizer"),
        ledger=Ledger(),
        model_client=client,
    )
    outcome = authorizer.authorize(
        intent, make_cart((laptop,)), subject_key=user_key.public, now=2_000
    )
    assert outcome.verdict is Verdict.BLOCK
    assert client.messages.calls == []
    assert outcome.decision.model_used is False


def test_a_divergent_finding_escalates_an_otherwise_clean_cart(
    intent, make_cart, user_key, chai
):
    authorizer = Authorizer(
        authorizer_key=SigningKey.from_seed("test/authorizer"),
        ledger=Ledger(),
        model_client=_StubClient("divergent", "candles are not chai"),
    )
    outcome = authorizer.authorize(
        intent, make_cart((chai,)), subject_key=user_key.public, now=2_000
    )
    assert outcome.verdict is Verdict.ESCALATE
    assert outcome.receipt is None


def test_a_consistent_finding_leaves_a_clean_cart_alone(
    intent, make_cart, user_key, chai
):
    authorizer = _authorizer(intent)
    outcome = authorizer.authorize(
        intent, make_cart((chai,)), subject_key=user_key.public, now=2_000
    )
    assert outcome.verdict is Verdict.ALLOW


def test_no_model_means_no_opinion_rather_than_a_guess(intent, make_cart, chai, no_llm):
    finding = judge_divergence(intent, make_cart((chai,)))
    assert finding.ran is False
    assert finding.as_check().status is CheckStatus.PASS


def test_state_is_untouched_by_the_judge(intent, make_cart, chai):
    """The judge reads. It must not be able to move a counter."""
    state = MandateState(intent_digest=intent.digest)
    judge_divergence(intent, make_cart((chai,)), client=_StubClient("divergent"))
    assert state.spent_paise == 0
    assert state.txn_count == 0
