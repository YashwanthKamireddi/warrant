"""Shared fixtures. Every key is seeded so the whole suite is deterministic."""

from __future__ import annotations

from pathlib import Path

import pytest

from warrant import llm
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


@pytest.fixture
def no_llm(monkeypatch):
    """Force the deterministic fallback: no live client, no transcript on disk."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(llm, "_live_client", lambda: None)
    monkeypatch.setattr(llm, "TRANSCRIPT_PATH", Path("/nonexistent/transcript.json"))
    monkeypatch.setattr(
        llm.TranscriptClient,
        "__init__",
        lambda self, transcript=None: setattr(self, "transcript", llm.Transcript()),
    )
    return None


@pytest.fixture
def settled_chain(intent, user_key, chai, samosa):
    """A full chain with a settled payment, exported in AP2 shape."""
    from warrant.authorize import Authorizer
    from warrant.chain import Ledger
    from warrant.interop import to_ap2_chain

    authorizer = Authorizer(
        authorizer_key=SigningKey.from_seed("test/authorizer"), ledger=Ledger()
    )
    cart = authorizer.propose_cart(
        intent, merchant="zomato", items=(chai, samosa), now=NOW, nonce="interop"
    )
    outcome = authorizer.authorize(
        intent, cart, subject_key=user_key.public, now=NOW, skip_semantic=True
    )
    chain = to_ap2_chain(
        intent,
        outcome.cart,
        outcome.receipt,
        subject_key=user_key.public,
        decision=outcome.decision.model_dump(mode="json"),
    )
    return chain, outcome
