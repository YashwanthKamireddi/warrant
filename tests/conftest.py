"""Shared fixtures. Every key is seeded so the whole suite is deterministic."""

from __future__ import annotations

import pytest

from warrant.crypto import SigningKey
from warrant.models import (
    CartMandate,
    IntentMandate,
    LineItem,
    RailBinding,
    Scope,
)

NOW = 2_000
WINDOW_OPENS = 1_000
WINDOW_CLOSES = 99_000


@pytest.fixture
def user_key() -> SigningKey:
    return SigningKey.from_seed("test/user")


@pytest.fixture
def authorizer_key() -> SigningKey:
    return SigningKey.from_seed("test/authorizer")


@pytest.fixture
def scope() -> Scope:
    return Scope(
        merchants=("zomato",),
        categories=("food_beverage",),
        max_total_paise=100_000,
        max_per_txn_paise=60_000,
        max_txns=2,
        step_up_over_paise=50_000,
        not_before=WINDOW_OPENS,
        expires_at=WINDOW_CLOSES,
    )


@pytest.fixture
def intent(scope: Scope, user_key: SigningKey) -> IntentMandate:
    return IntentMandate(
        subject="user_priya",
        agent="agent_claude",
        utterance="order chai and samosas for my team, keep it under 1000",
        scope=scope,
        rail=RailBinding(kind="upi_reserve_pay", block_paise=100_000),
        issued_at=WINDOW_OPENS,
        nonce="intent-nonce-1",
    ).signed_by(user_key)


@pytest.fixture
def chai() -> LineItem:
    return LineItem(
        sku="chai", name="Masala Chai", category="food_beverage", qty=6, unit_paise=4_000
    )


@pytest.fixture
def samosa() -> LineItem:
    return LineItem(
        sku="samosa", name="Samosa Plate", category="food_beverage", qty=2, unit_paise=12_000
    )


@pytest.fixture
def make_cart(intent: IntentMandate):
    def _make(
        items: tuple[LineItem, ...],
        *,
        merchant: str = "zomato",
        nonce: str = "cart-1",
        intent_digest: str | None = None,
    ) -> CartMandate:
        return CartMandate(
            intent_digest=intent_digest or intent.digest,
            merchant=merchant,
            line_items=items,
            total_paise=sum(i.line_paise for i in items),
            issued_at=NOW,
            nonce=nonce,
        )

    return _make
