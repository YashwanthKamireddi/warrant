"""Finishing a debit the rail accepted but had not yet captured.

A real rail settles asynchronously: an order and a payment link go out, and the
customer authorises on their own device minutes later. Until settle_pending()
existed, a debit placed from the console could never finish -- no receipt, no
evidence pack, and the one demo path that matters most was impossible.

Pending work is reconstructed from the ledger rather than held in memory, so a
restarted process still finishes what it started. These tests build the
orchestrator fresh each time to hold that.
"""

from __future__ import annotations

import pytest

from warrant.authorize import Authorizer
from warrant.chain import EventKind, Ledger
from warrant.crypto import SigningKey
from warrant.models import RailRef
from warrant.rails.base import RailResult


class _AsyncRail:
    """Accepts a debit, then reports whatever the test tells it to on poll."""

    kind = "async"

    def __init__(self) -> None:
        self.captured = False
        self.broken = False
        self.polls = 0

    def attempt(self, cart, *, idempotency_key):
        return RailResult(
            ok=True,
            settled=False,
            ref=RailRef(kind="razorpay", order_id="order_async1", status="created"),
            amount_paise=cart.total_paise,
        )

    def poll(self, order_id: str, cart):
        self.polls += 1
        if self.broken:
            return RailResult(
                ok=False,
                settled=False,
                ref=RailRef(kind="razorpay", order_id=order_id, status="failed"),
                amount_paise=cart.total_paise,
                error_code="BAD_REQUEST_ERROR",
                error_source="customer",
                error_step="payment_authentication",
                error_reason="incorrect_otp",
            )
        if not self.captured:
            return RailResult(
                ok=True,
                settled=False,
                ref=RailRef(kind="razorpay", order_id=order_id, status="awaiting_payment"),
                amount_paise=cart.total_paise,
            )
        return RailResult(
            ok=True,
            settled=True,
            ref=RailRef(
                kind="razorpay", order_id=order_id, payment_id="pay_async1", status="captured"
            ),
            amount_paise=cart.total_paise,
        )


@pytest.fixture
def placed(intent, user_key, chai):
    """A debit accepted by an asynchronous rail but not yet captured."""
    ledger = Ledger()
    rail = _AsyncRail()
    authorizer = Authorizer(
        authorizer_key=SigningKey.from_seed("test/authorizer"), ledger=ledger, rail=rail
    )
    cart = authorizer.propose_cart(
        intent, merchant="zomato", items=(chai,), now=2_000, nonce="async"
    )
    outcome = authorizer.authorize(
        intent, cart, subject_key=user_key.public, now=2_000, skip_semantic=True
    )
    assert outcome.receipt is None
    return authorizer, rail, ledger, intent


def test_an_uncaptured_debit_stays_unsettled(placed):
    authorizer, _, _, intent = placed
    assert authorizer.settle_pending(intent, now=3_000) == []


def test_still_awaiting_is_not_recorded_as_an_event(placed):
    """A console left open must not fill the chain with nothing happening."""
    authorizer, _, ledger, intent = placed
    before = ledger.length
    authorizer.settle_pending(intent, now=3_000)
    assert ledger.length == before


def test_a_capture_produces_a_signed_receipt(placed):
    authorizer, rail, _, intent = placed
    rail.captured = True
    finished = authorizer.settle_pending(intent, now=3_000)
    assert len(finished) == 1
    receipt = finished[0].receipt
    assert receipt is not None
    assert receipt.rail.payment_id == "pay_async1"
    assert receipt.verify_with(authorizer.authorizer_key.public)


def test_a_capture_charges_the_budget(placed, chai):
    authorizer, rail, _, intent = placed
    state = authorizer.state_for(intent)
    assert state.spent_paise == 0
    rail.captured = True
    authorizer.settle_pending(intent, now=3_000)
    assert state.spent_paise == chai.line_paise
    assert state.txn_count == 1


def test_settling_twice_does_not_double_count(placed):
    authorizer, rail, _, intent = placed
    rail.captured = True
    authorizer.settle_pending(intent, now=3_000)
    spent = authorizer.state_for(intent).spent_paise
    assert authorizer.settle_pending(intent, now=4_000) == []
    assert authorizer.state_for(intent).spent_paise == spent


def test_pending_work_is_reconstructed_from_the_ledger(placed):
    """A restarted process must still finish what it started."""
    authorizer, rail, ledger, intent = placed
    rail.captured = True

    restarted = Authorizer(
        authorizer_key=SigningKey.from_seed("test/authorizer"), ledger=ledger, rail=rail
    )
    finished = restarted.settle_pending(intent, now=3_000)
    assert len(finished) == 1
    assert restarted.state_for(intent).txn_count == 1


def test_a_failed_payment_is_recorded_with_razorpays_vocabulary(placed):
    authorizer, rail, ledger, intent = placed
    rail.broken = True
    assert authorizer.settle_pending(intent, now=3_000) == []
    failures = [e for e in ledger.entries() if e.kind is EventKind.DEBIT_FAILED]
    assert len(failures) == 1
    assert failures[0].payload["rail"]["error_reason"] == "incorrect_otp"


def test_a_rail_that_cannot_poll_is_simply_skipped(intent, user_key, chai):
    """The simulated rail settles synchronously and has no poll method."""
    authorizer = Authorizer(
        authorizer_key=SigningKey.from_seed("test/authorizer"), ledger=Ledger()
    )
    cart = authorizer.propose_cart(
        intent, merchant="zomato", items=(chai,), now=2_000, nonce="sync"
    )
    authorizer.authorize(
        intent, cart, subject_key=user_key.public, now=2_000, skip_semantic=True
    )
    assert authorizer.settle_pending(intent, now=3_000) == []


def test_the_chain_stays_intact_through_asynchronous_settlement(placed):
    authorizer, rail, ledger, intent = placed
    rail.captured = True
    authorizer.settle_pending(intent, now=3_000)
    assert ledger.audit() is None
