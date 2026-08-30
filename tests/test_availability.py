"""The binding path must not be able to fail for external reasons.

A judge's fair question about putting a gate in the payment path is: what happens
when it is unavailable? If it fails closed it becomes a single point of failure
for a payments company; if it fails open it is decorative.

The answer here is structural rather than operational. Warrant fails closed --
no verdict, no debit -- and that is safe to do because **the binding path has no
external dependencies at all**. No network, no model, no database read, no clock
it does not receive as an argument. It is a pure function of
(intent, cart, state, now, key), so it cannot be down unless the merchant's own
process is down, at which point there is no checkout to protect.

These tests hold that claim to account by removing the outside world entirely and
asserting a verdict still comes back.
"""

from __future__ import annotations

import socket

import pytest

from warrant.gate import MandateState, evaluate
from warrant.models import LineItem, Verdict


@pytest.fixture
def no_network(monkeypatch):
    """Make any socket use raise. Nothing in the binding path may touch one."""

    def forbidden(*args, **kwargs):
        raise AssertionError("the binding path opened a socket")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    return None


@pytest.fixture
def state(intent) -> MandateState:
    return MandateState(intent_digest=intent.digest)


def test_a_clean_cart_is_allowed_with_no_network(
    intent, make_cart, state, user_key, chai, samosa, no_network
):
    decision = evaluate(
        intent, make_cart((chai, samosa)), state, now=2_000, subject_key=user_key.public
    )
    assert decision.verdict is Verdict.ALLOW


def test_an_out_of_scope_cart_is_blocked_with_no_network(
    intent, make_cart, state, user_key, no_network
):
    laptop = LineItem(
        sku="lap", name="Laptop", category="electronics", qty=1, unit_paise=42_000
    )
    decision = evaluate(
        intent, make_cart((laptop,)), state, now=2_000, subject_key=user_key.public
    )
    assert decision.verdict is Verdict.BLOCK


def test_the_binding_path_never_reports_a_model_was_used(
    intent, make_cart, state, user_key, chai, no_network
):
    decision = evaluate(
        intent, make_cart((chai,)), state, now=2_000, subject_key=user_key.public
    )
    assert decision.model_used is False


def test_every_rule_still_fires_with_no_network(
    intent, make_cart, state, user_key, chai, no_network
):
    """A gate that silently skipped rules when something was unreachable would be
    worse than one that failed."""
    decision = evaluate(
        intent, make_cart((chai,)), state, now=2_000, subject_key=user_key.public
    )
    rules = {c.rule for c in decision.checks}
    for required in (
        "chain.intent_signature",
        "chain.cart_binds_intent",
        "replay.cart_nonce",
        "scope.window",
        "scope.merchant",
        "scope.category",
        "merchant.mcc_scope",
        "scope.per_txn_ceiling",
        "scope.total_ceiling",
        "scope.txn_count",
        "rail.block_remaining",
    ):
        assert required in rules


def test_the_clock_is_an_argument_not_a_syscall(
    intent, make_cart, state, user_key, chai
):
    """Two evaluations at the same supplied instant must be identical, whatever
    the wall clock did in between."""
    cart = make_cart((chai,))
    first = evaluate(intent, cart, state, now=2_000, subject_key=user_key.public)
    second = evaluate(intent, cart, state, now=2_000, subject_key=user_key.public)
    assert first == second


def test_the_gate_does_not_mutate_the_state_it_is_given(
    intent, make_cart, state, user_key, chai
):
    """Evaluation is a read. Nothing may advance a counter as a side effect,
    or a retried request would silently consume budget."""
    before = (state.spent_paise, state.txn_count, frozenset(state.seen_nonces))
    evaluate(intent, make_cart((chai,)), state, now=2_000, subject_key=user_key.public)
    after = (state.spent_paise, state.txn_count, frozenset(state.seen_nonces))
    assert before == after


def test_no_verdict_means_no_debit(intent, make_cart, user_key, chai):
    """Fail closed, stated as a test.

    An authoriser that cannot produce a verdict must not settle. The orchestrator
    only calls the rail after a decision exists, so a raising gate stops the money
    rather than letting it through.
    """
    from warrant.authorize import Authorizer
    from warrant.chain import Ledger
    from warrant.crypto import SigningKey

    placed: list[str] = []

    class _RecordingRail:
        kind = "recording"

        def attempt(self, cart, *, idempotency_key):  # pragma: no cover - must not run
            placed.append(cart.id)
            raise AssertionError("the rail was called without a verdict")

    authorizer = Authorizer(
        authorizer_key=SigningKey.from_seed("test/authorizer"),
        ledger=Ledger(),
        rail=_RecordingRail(),
    )

    import warrant.authorize as authorize_module

    def exploding_evaluate(*args, **kwargs):
        raise RuntimeError("gate unavailable")

    original = authorize_module.evaluate
    authorize_module.evaluate = exploding_evaluate
    try:
        cart = authorizer.propose_cart(
            intent, merchant="zomato", items=(chai,), now=2_000, nonce="failclosed"
        )
        with pytest.raises(RuntimeError, match="gate unavailable"):
            authorizer.authorize(
                intent, cart, subject_key=user_key.public, now=2_000, skip_semantic=True
            )
    finally:
        authorize_module.evaluate = original

    assert placed == []
