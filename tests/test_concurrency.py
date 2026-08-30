"""Concurrent carts against one mandate must not be able to overspend it.

Checking a ceiling and then spending against it is a read-modify-write. Six carts
arriving together each read a budget nobody had claimed yet, all passed a ₹100
ceiling and settled ₹360 between them -- a direct double-spend in the one thing
this system exists to prevent, and invisible to 198 single-threaded tests.
"""

from __future__ import annotations

import threading

import pytest

from warrant.authorize import Authorizer
from warrant.chain import Ledger
from warrant.crypto import SigningKey
from warrant.models import IntentMandate, LineItem, RailBinding, Scope, Verdict


@pytest.fixture
def tight_intent(user_key):
    """A ₹100 ceiling that only one ₹60 basket can fit under."""
    scope = Scope(
        merchants=("zomato",),
        categories=("food_beverage",),
        max_total_paise=10_000,
        max_per_txn_paise=10_000,
        max_txns=10,
        step_up_over_paise=None,
        not_before=1_000,
        expires_at=99_000,
    )
    return IntentMandate(
        subject="user_priya",
        agent="agent_claude",
        utterance="chai for the team",
        scope=scope,
        rail=RailBinding(kind="simulated"),
        issued_at=1_000,
        nonce="tight",
    ).signed_by(user_key)


@pytest.fixture
def item() -> LineItem:
    return LineItem(
        sku="chai-6", name="Masala Chai", category="food_beverage", qty=1, unit_paise=6_000
    )


def _race(authorizer, intent, item, user_key, n: int) -> list[Verdict]:
    """Fire n carts at the same instant, using a barrier to maximise overlap."""
    verdicts: list[Verdict] = []
    barrier = threading.Barrier(n)
    lock = threading.Lock()

    def buy(i: int) -> None:
        cart = authorizer.propose_cart(
            intent, merchant="zomato", items=(item,), now=2_000, nonce=f"cart-{i}"
        )
        barrier.wait()
        outcome = authorizer.authorize(
            intent, cart, subject_key=user_key.public, now=2_000, skip_semantic=True
        )
        with lock:
            verdicts.append(outcome.verdict)

    threads = [threading.Thread(target=buy, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return verdicts


def test_concurrent_carts_cannot_overspend_the_ceiling(tight_intent, item, user_key):
    authorizer = Authorizer(
        authorizer_key=SigningKey.from_seed("test/authorizer"), ledger=Ledger()
    )
    _race(authorizer, tight_intent, item, user_key, 6)
    state = authorizer.state_for(tight_intent)
    assert state.spent_paise <= tight_intent.scope.max_total_paise


def test_only_one_of_six_racing_carts_is_allowed(tight_intent, item, user_key):
    authorizer = Authorizer(
        authorizer_key=SigningKey.from_seed("test/authorizer"), ledger=Ledger()
    )
    verdicts = _race(authorizer, tight_intent, item, user_key, 6)
    assert sum(1 for v in verdicts if v is Verdict.ALLOW) == 1


def test_the_transaction_count_is_not_exceeded_under_a_race(user_key, item):
    """Two permitted debits, ten racing carts."""
    scope = Scope(
        merchants=("zomato",),
        categories=("food_beverage",),
        max_total_paise=1_000_000,
        max_per_txn_paise=1_000_000,
        max_txns=2,
        step_up_over_paise=None,
        not_before=1_000,
        expires_at=99_000,
    )
    intent = IntentMandate(
        subject="u",
        agent="a",
        utterance="x",
        scope=scope,
        rail=RailBinding(kind="simulated"),
        issued_at=1_000,
        nonce="counted",
    ).signed_by(user_key)

    authorizer = Authorizer(
        authorizer_key=SigningKey.from_seed("test/authorizer"), ledger=Ledger()
    )
    _race(authorizer, intent, item, user_key, 10)
    assert authorizer.state_for(intent).txn_count <= 2


def test_the_ledger_stays_intact_through_a_race(tight_intent, item, user_key):
    ledger = Ledger()
    authorizer = Authorizer(
        authorizer_key=SigningKey.from_seed("test/authorizer"), ledger=ledger
    )
    _race(authorizer, tight_intent, item, user_key, 6)
    assert ledger.audit() is None


def test_different_mandates_do_not_serialise_against_each_other(user_key, item):
    """The lock is per mandate. One customer's session must not block another's."""
    authorizer = Authorizer(
        authorizer_key=SigningKey.from_seed("test/authorizer"), ledger=Ledger()
    )

    def make(nonce: str) -> IntentMandate:
        scope = Scope(
            merchants=("zomato",),
            categories=("food_beverage",),
            max_total_paise=100_000,
            max_per_txn_paise=100_000,
            max_txns=5,
            step_up_over_paise=None,
            not_before=1_000,
            expires_at=99_000,
        )
        return IntentMandate(
            subject="u",
            agent="a",
            utterance="x",
            scope=scope,
            rail=RailBinding(kind="simulated"),
            issued_at=1_000,
            nonce=nonce,
        ).signed_by(user_key)

    a, b = make("mandate-a"), make("mandate-b")
    assert authorizer._lock_for(a) is not authorizer._lock_for(b)
    assert authorizer._lock_for(a) is authorizer._lock_for(a)
