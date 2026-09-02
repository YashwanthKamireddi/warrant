"""The mandate rail, driven against a recording client.

These run offline. What they pin down is the shape of every call we make to
Razorpay and, more importantly, the refusals: a debit before authorisation, a
ceiling above what NPCI will register, a revocation that actually deletes the
token. The live counterpart is ``.verify/walk_mandate.py``, which does all of
this against the real test account.
"""

from __future__ import annotations

import pytest

from warrant.models import CartMandate, LineItem
from warrant.rails.razorpay_mandate import (
    MAX_MANDATE_PAISE,
    MandateNotAuthorised,
    RazorpayMandate,
)


class FakeClient:
    """Records every call and answers the way Razorpay test mode answers."""

    def __init__(self, *, token_after_fetch: str | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._token_after_fetch = token_after_fetch
        self.deleted: list[tuple[str, str]] = []

        outer = self

        class _Customer:
            def create(self, data):
                outer.calls.append(("customer.create", data))
                return {"id": "cust_TEST", **data}

        class _Invoice:
            def create(self, data):
                outer.calls.append(("invoice.create", data))
                return {
                    "id": "inv_TEST",
                    "order_id": "order_REG",
                    "short_url": "https://rzp.io/rzp/TESTLINK",
                    "status": "issued",
                }

            def fetch(self, invoice_id):
                outer.calls.append(("invoice.fetch", {"id": invoice_id}))
                return {
                    "id": invoice_id,
                    "status": "paid" if outer._token_after_fetch else "issued",
                    "token_id": outer._token_after_fetch,
                    "payment_id": "pay_REG" if outer._token_after_fetch else None,
                }

        class _Order:
            def create(self, data):
                outer.calls.append(("order.create", data))
                return {"id": "order_DEBIT", "status": "created"}

            def payments(self, order_id):
                outer.calls.append(("order.payments", {"id": order_id}))
                return {"items": [{"id": "pay_DEBIT", "status": "captured"}]}

        class _Payment:
            def createRecurring(self, data):  # noqa: N802 -- the SDK's own name
                outer.calls.append(("payment.createRecurring", data))
                return {"id": "pay_DEBIT", "status": "captured"}

        class _Token:
            def delete(self, customer_id, token_id):
                outer.deleted.append((customer_id, token_id))
                return {"deleted": True}

        self.customer, self.invoice, self.order = _Customer(), _Invoice(), _Order()
        self.payment, self.token = _Payment(), _Token()

    def call(self, name):
        return next((data for n, data in self.calls if n == name), None)


def cart(total: int = 48_000) -> CartMandate:
    return CartMandate(
        intent_digest="i" * 64,
        merchant="zomato",
        line_items=(
            LineItem(
                sku="chai-6",
                name="Masala Chai",
                category="food_beverage",
                qty=6,
                unit_paise=total // 6,
            ),
        ),
        total_paise=total,
        issued_at=2_000,
        nonce="n" * 32,
    )


# ------------------------------------------------------------- registration


def test_registers_with_the_ceiling_the_person_approved():
    """The sentence's ceiling is what ends up enforced on the NPCI rails."""
    client = FakeClient()
    mandate = RazorpayMandate(client=client)

    handle = mandate.register(ceiling_paise=100_000, description="Up to Rs 1,000")

    registration = client.call("invoice.create")["subscription_registration"]
    assert registration["max_amount"] == 100_000
    assert registration["method"] == "upi"
    assert registration["frequency"] == "as_presented"
    assert handle.short_url.startswith("https://")
    assert handle.ceiling_paise == 100_000


def test_refuses_a_ceiling_above_what_upi_autopay_allows():
    mandate = RazorpayMandate(client=FakeClient())
    with pytest.raises(ValueError, match="caps a mandate"):
        mandate.register(ceiling_paise=MAX_MANDATE_PAISE + 1, description="too much")


def test_refuses_a_ceiling_of_nothing():
    mandate = RazorpayMandate(client=FakeClient())
    with pytest.raises(ValueError, match="positive"):
        mandate.register(ceiling_paise=0, description="nothing")


# ------------------------------------------------------------ authorisation


def test_unauthorised_until_the_customer_has_paid_the_registration():
    mandate = RazorpayMandate(client=FakeClient())
    mandate.register(ceiling_paise=100_000, description="Up to Rs 1,000")

    status = mandate.status()
    assert status.status == "issued"
    assert status.token_id is None
    assert not status.authorised
    assert not mandate.authorised


def test_a_debit_before_authorisation_is_refused_not_attempted():
    """No token means no debit, and no order created on the way to finding out."""
    client = FakeClient()
    mandate = RazorpayMandate(client=client)
    mandate.register(ceiling_paise=100_000, description="Up to Rs 1,000")

    with pytest.raises(MandateNotAuthorised):
        mandate.attempt(cart(), idempotency_key="k")

    assert client.call("order.create") is None


def test_authorising_mints_the_token():
    client = FakeClient(token_after_fetch="token_ABC")
    mandate = RazorpayMandate(client=client)
    mandate.register(ceiling_paise=100_000, description="Up to Rs 1,000")

    status = mandate.status()
    assert status.authorised
    assert status.token_id == "token_ABC"
    assert mandate.authorised


# -------------------------------------------------------------------- debit


def test_a_debit_needs_no_human_and_carries_the_cart_binding():
    """The whole point of a mandate: money moves with nobody asked anything."""
    client = FakeClient(token_after_fetch="token_ABC")
    mandate = RazorpayMandate(client=client)
    mandate.register(ceiling_paise=100_000, description="Up to Rs 1,000")
    mandate.status()

    basket = cart()
    result = mandate.attempt(basket, idempotency_key="idem-key-1")

    assert result.ok and result.settled
    assert result.ref.order_id == "order_DEBIT"
    assert result.ref.payment_id == "pay_DEBIT"

    charge = client.call("payment.createRecurring")
    assert charge["token"] == "token_ABC"
    assert charge["recurring"] == "1"
    assert charge["amount"] == basket.total_paise
    # Nothing in the charge tells the bank what is in the basket. The binding
    # only survives because we put it on the order ourselves.
    notes = client.call("order.create")["notes"]
    assert notes["cart_digest"] == basket.digest
    assert notes["intent_digest"] == basket.intent_digest


def test_the_same_cart_reuses_the_same_receipt_so_a_retry_cannot_double_charge():
    client = FakeClient(token_after_fetch="token_ABC")
    mandate = RazorpayMandate(client=client)
    mandate.register(ceiling_paise=100_000, description="Up to Rs 1,000")
    mandate.status()

    mandate.attempt(cart(), idempotency_key="stable-key")
    receipts = [d["receipt"] for n, d in client.calls if n == "order.create"]
    mandate.attempt(cart(), idempotency_key="stable-key")
    receipts = [d["receipt"] for n, d in client.calls if n == "order.create"]

    assert receipts[0] == receipts[1] == "stable-key"


def test_a_failed_debit_reports_rather_than_raises():
    """A rail failure is a decision the ledger records, not a crash."""

    class Boom(FakeClient):
        def __init__(self):
            super().__init__(token_after_fetch="token_ABC")

            class _Order:
                def create(self, data):
                    raise RuntimeError("mandate revoked at the bank")

            self.order = _Order()

    mandate = RazorpayMandate(client=Boom())
    mandate.register(ceiling_paise=100_000, description="Up to Rs 1,000")
    mandate.status()

    result = mandate.attempt(cart(), idempotency_key="k")
    assert not result.ok
    assert not result.settled
    assert "revoked at the bank" in (result.error_reason or "")
    assert result.failure_summary.startswith("razorpay")


# ----------------------------------------------------------------- revoking


def test_revoking_deletes_the_token_at_the_bank():
    client = FakeClient(token_after_fetch="token_ABC")
    mandate = RazorpayMandate(client=client)
    mandate.register(ceiling_paise=100_000, description="Up to Rs 1,000")
    mandate.status()

    assert mandate.revoke() is True
    assert client.deleted == [("cust_TEST", "token_ABC")]
    assert not mandate.authorised


def test_revoking_then_debiting_is_refused():
    client = FakeClient(token_after_fetch="token_ABC")
    mandate = RazorpayMandate(client=client)
    mandate.register(ceiling_paise=100_000, description="Up to Rs 1,000")
    mandate.status()
    mandate.revoke()

    with pytest.raises(MandateNotAuthorised):
        mandate.attempt(cart(), idempotency_key="k")


def test_revoking_an_unauthorised_mandate_is_a_no_op():
    mandate = RazorpayMandate(client=FakeClient())
    mandate.register(ceiling_paise=100_000, description="Up to Rs 1,000")
    assert mandate.revoke() is False
