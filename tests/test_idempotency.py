"""Retries.

An agent that sends a basket, times out, and sends it again must not be charged
twice. This was broken: every call minted a fresh cart nonce, so the same basket
sent three times was three purchases and the engine's own replay guard never
saw a repeat. It is the worst failure a payments API can have and it was in the
convenience layer, not the engine.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from warrant import Warrant
from warrant.merchants import MerchantRecord, MerchantRegistry
from warrant.models import Scope, Verdict
from warrant.service import NO_AUTH, create_app

NOW = int(time.time())
GROCER = MerchantRegistry((
    MerchantRecord("acme", "5411", "Grocery stores", frozenset({"food_beverage"})),
))
SANDWICH = {"sku": "sandwich", "category": "food_beverage", "qty": 1, "unit_paise": 24_000}


def scope(**over) -> Scope:
    return Scope(**{
        "merchants": ("acme",), "categories": ("food_beverage",),
        "max_total_paise": 200_000, "max_per_txn_paise": 100_000, "max_txns": 6,
        "not_before": NOW, "expires_at": NOW + 7200, **over,
    })


@pytest.fixture
def warrant():
    with Warrant(merchants=GROCER) as w:
        yield w


def spent(warrant, permission) -> int:
    return warrant._authorizer.state_for(permission.intent).spent_paise


# ------------------------------------------------------------------- the SDK


def test_a_retry_with_the_same_key_charges_once(warrant):
    permission = warrant.permit("lunch", scope=scope())

    results = [
        warrant.spend(permission, "acme", [SANDWICH], idempotency_key="order-1")
        for _ in range(3)
    ]

    assert all(r.allowed for r in results)
    assert len({r.cart.id for r in results}) == 1
    assert spent(warrant, permission) == 24_000


def test_the_repeat_returns_the_first_decision_not_a_refusal(warrant):
    """A retry that comes back 'blocked: replay' looks like a failure.

    The caller would reasonably try again, or tell someone the payment did not
    go through. It did.
    """
    permission = warrant.permit("lunch", scope=scope())

    first = warrant.spend(permission, "acme", [SANDWICH], idempotency_key="order-2")
    again = warrant.spend(permission, "acme", [SANDWICH], idempotency_key="order-2")

    assert again.verdict is Verdict.ALLOW
    assert again.settled
    assert again.outcome is first.outcome


def test_different_keys_are_different_purchases(warrant):
    """Buying the same sandwich twice is a normal thing to do."""
    permission = warrant.permit("lunch", scope=scope())

    warrant.spend(permission, "acme", [SANDWICH], idempotency_key="order-3")
    warrant.spend(permission, "acme", [SANDWICH], idempotency_key="order-4")

    assert spent(warrant, permission) == 48_000


def test_without_a_key_two_identical_baskets_are_two_purchases(warrant):
    """Documented, deliberate, and the reason the key exists."""
    permission = warrant.permit("lunch", scope=scope())

    warrant.spend(permission, "acme", [SANDWICH])
    warrant.spend(permission, "acme", [SANDWICH])

    assert spent(warrant, permission) == 48_000


def test_a_key_is_scoped_to_its_permission(warrant):
    """One caller's `order-1` must not answer for another's."""
    first = warrant.permit("lunch", scope=scope())
    second = warrant.permit("lunch", scope=scope())

    a = warrant.spend(first, "acme", [SANDWICH], idempotency_key="order-5")
    b = warrant.spend(second, "acme", [SANDWICH], idempotency_key="order-5")

    assert a.cart.id != b.cart.id
    assert spent(warrant, first) == 24_000
    assert spent(warrant, second) == 24_000


def test_the_engine_guard_still_catches_a_repeat_the_cache_forgot(warrant):
    """The cache is bounded, so it is a convenience and not the safety net.

    Evicting the entry must not turn a retry into a second charge: the nonce is
    derived from the key, so the same key rebuilds the same cart and the gate's
    replay.cart_nonce check refuses it.
    """
    permission = warrant.permit("lunch", scope=scope())
    warrant.spend(permission, "acme", [SANDWICH], idempotency_key="order-6")

    warrant._seen.clear()  # simulate eviction under load

    again = warrant.spend(permission, "acme", [SANDWICH], idempotency_key="order-6")

    assert again.verdict is Verdict.BLOCK
    assert any("replay" in c.rule for c in again.decision.failures)
    assert spent(warrant, permission) == 24_000


def test_the_cache_is_bounded(warrant):
    from warrant.client import IDEMPOTENCY_CACHE

    permission = warrant.permit("lunch", scope=scope(max_txns=100, max_total_paise=10_000_000))
    for n in range(5):
        warrant.spend(permission, "acme", [SANDWICH], idempotency_key=f"k{n}")

    assert len(warrant._seen) <= IDEMPOTENCY_CACHE


# --------------------------------------------------------------- over HTTP


def test_the_idempotency_key_header_is_honoured():
    with (
        Warrant(merchants=GROCER) as w,
        TestClient(create_app(w, auth=NO_AUTH)) as client,
    ):
        pid = client.post(
            "/warrant/permissions",
            json={"utterance": "lunch", "scope": scope().model_dump(mode="json")},
        ).json()["id"]

        body = {"merchant": "acme", "items": [SANDWICH]}
        headers = {"Idempotency-Key": "http-order-1"}

        first = client.post(f"/warrant/permissions/{pid}/spend", json=body, headers=headers)
        again = client.post(f"/warrant/permissions/{pid}/spend", json=body, headers=headers)

        assert first.status_code == 200
        assert again.status_code == 200
        assert first.json()["cart_id"] == again.json()["cart_id"]
