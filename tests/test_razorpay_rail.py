"""The Razorpay rail, exercised against a fake client.

Real keys prove the integration works on the day. These prove it behaves
correctly on every day, including the ones where Razorpay returns an error, a
pending payment, or nothing at all -- which is most of what a rail has to get
right and none of what a happy-path demo shows.

The property that matters most here: a rail **reports** failures, it never raises
them. A payment layer that throws on a gateway hiccup takes the authorizer down
with it.
"""

from __future__ import annotations

import pytest

from warrant.crypto import SigningKey
from warrant.rails.razorpay_rail import (
    RazorpayNotConfigured,
    RazorpayRail,
    SignatureRejected,
)


class _Resource:
    """One Razorpay API resource, scripted per test."""

    def __init__(self, responses: dict[str, object]):
        self._responses = responses
        self.calls: list[dict] = []

    def _respond(self, name: str, payload: dict | None = None):
        if payload is not None:
            self.calls.append(payload)
        value = self._responses.get(name)
        if isinstance(value, Exception):
            raise value
        return value

    def create(self, payload: dict):
        return self._respond("create", payload)

    def payments(self, order_id: str):
        self.calls.append({"order_id": order_id})
        return self._respond("payments")


class _FakeRazorpay:
    def __init__(self, *, order=None, payment_link=None, payments=None):
        self.order = _Resource({"create": order, "payments": payments})
        self.payment_link = _Resource({"create": payment_link})


ORDER_OK = {"id": "order_test123", "status": "created", "amount": 48_000}
LINK_OK = {"id": "plink_test123", "short_url": "https://rzp.io/i/abc"}


@pytest.fixture
def cart(intent, make_cart, chai, samosa):
    return make_cart((chai, samosa))


# -- refusing to run against anything but test mode ------------------------ #


def test_a_live_key_is_refused(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_live_abcdefgh")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "secret")
    with pytest.raises(RazorpayNotConfigured, match="non-test key"):
        RazorpayRail()


def test_missing_credentials_are_refused_with_a_usable_message(monkeypatch):
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    with pytest.raises(RazorpayNotConfigured, match="--rail simulated"):
        RazorpayRail()


def test_a_key_id_without_a_secret_is_refused(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_abcdefgh")
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    with pytest.raises(RazorpayNotConfigured):
        RazorpayRail()


# -- placing a debit ------------------------------------------------------- #


def test_an_order_is_created_for_the_exact_cart_total(cart):
    client = _FakeRazorpay(order=ORDER_OK, payment_link=LINK_OK)
    RazorpayRail(client=client).attempt(cart, idempotency_key=cart.digest)
    assert client.order.calls[0]["amount"] == cart.total_paise
    assert client.order.calls[0]["currency"] == "INR"


def test_the_receipt_is_the_idempotency_key_so_a_retry_cannot_double_charge(cart):
    """Razorpay dedupes on receipt, which gives idempotency for free -- provided
    we actually send one derived from the cart rather than something random."""
    client = _FakeRazorpay(order=ORDER_OK, payment_link=LINK_OK)
    RazorpayRail(client=client).attempt(cart, idempotency_key=cart.digest)
    assert client.order.calls[0]["receipt"] == cart.digest[:40]


def test_the_order_carries_the_mandate_chain_in_its_notes(cart):
    client = _FakeRazorpay(order=ORDER_OK, payment_link=LINK_OK)
    RazorpayRail(client=client).attempt(cart, idempotency_key=cart.digest)
    notes = client.order.calls[0]["notes"]
    assert notes["warrant_cart"] == cart.id
    assert notes["warrant_intent"] == cart.intent_digest[:32]


def test_a_placed_debit_is_never_reported_as_settled(cart):
    """A script cannot complete a payment server to server. Claiming otherwise
    would make every downstream receipt a lie."""
    client = _FakeRazorpay(order=ORDER_OK, payment_link=LINK_OK)
    result = RazorpayRail(client=client).attempt(cart, idempotency_key=cart.digest)
    assert result.ok is True
    assert result.settled is False
    assert result.ref.order_id == "order_test123"
    assert result.raw["payment_link"] == "https://rzp.io/i/abc"


# -- failures are reported, never raised ----------------------------------- #


def test_an_api_error_is_reported_rather_than_raised(cart):
    client = _FakeRazorpay(order=RuntimeError("gateway exploded"), payment_link=LINK_OK)
    result = RazorpayRail(client=client).attempt(cart, idempotency_key=cart.digest)
    assert result.ok is False
    assert result.settled is False
    assert result.error_code == "RAIL_REJECTED"
    assert "gateway exploded" in (result.error_reason or "")


def test_a_payment_link_failure_is_also_reported(cart):
    client = _FakeRazorpay(order=ORDER_OK, payment_link=RuntimeError("link refused"))
    result = RazorpayRail(client=client).attempt(cart, idempotency_key=cart.digest)
    assert result.ok is False
    assert "link refused" in (result.error_reason or "")


def test_a_huge_error_message_is_truncated(cart):
    client = _FakeRazorpay(order=RuntimeError("x" * 5_000), payment_link=LINK_OK)
    result = RazorpayRail(client=client).attempt(cart, idempotency_key=cart.digest)
    assert len(result.error_reason or "") <= 200


# -- polling for settlement ------------------------------------------------ #


def test_a_captured_payment_settles(cart):
    client = _FakeRazorpay(
        payments={"items": [{"id": "pay_abc", "status": "captured", "amount": 48_000}]}
    )
    result = RazorpayRail(client=client).poll("order_test123", cart)
    assert result.ok and result.settled
    assert result.ref.payment_id == "pay_abc"
    assert result.amount_paise == 48_000


def test_a_failed_payment_carries_razorpays_own_error_vocabulary(cart):
    client = _FakeRazorpay(
        payments={
            "items": [
                {
                    "id": "pay_bad",
                    "status": "failed",
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_source": "customer",
                    "error_step": "payment_authentication",
                    "error_reason": "incorrect_otp",
                }
            ]
        }
    )
    result = RazorpayRail(client=client).poll("order_test123", cart)
    assert result.ok is False and result.settled is False
    assert result.error_source == "customer"
    assert result.error_step == "payment_authentication"
    assert result.error_reason == "incorrect_otp"
    assert result.failure_summary == "customer / payment_authentication / incorrect_otp"


def test_an_order_with_no_payments_is_awaiting_not_failed(cart):
    client = _FakeRazorpay(payments={"items": []})
    result = RazorpayRail(client=client).poll("order_test123", cart)
    assert result.ok is True
    assert result.settled is False
    assert result.ref.status == "awaiting_payment"


def test_a_capture_wins_over_an_earlier_failed_attempt(cart):
    """Customers retry. One failure followed by a capture is a settled order."""
    client = _FakeRazorpay(
        payments={
            "items": [
                {"id": "pay_bad", "status": "failed", "error_reason": "incorrect_otp"},
                {"id": "pay_good", "status": "captured", "amount": 48_000},
            ]
        }
    )
    result = RazorpayRail(client=client).poll("order_test123", cart)
    assert result.settled is True
    assert result.ref.payment_id == "pay_good"


def test_an_unreachable_rail_is_reported_rather_than_raised(cart):
    client = _FakeRazorpay(payments=ConnectionError("network down"))
    result = RazorpayRail(client=client).poll("order_test123", cart)
    assert result.ok is False
    assert result.error_code == "RAIL_UNREACHABLE"


# -- the rail satisfies the interface the engine depends on ---------------- #


def test_the_rail_is_interchangeable_with_the_simulator(cart):
    from warrant.rails.base import Rail

    client = _FakeRazorpay(order=ORDER_OK, payment_link=LINK_OK)
    rail: Rail = RazorpayRail(client=client)
    assert rail.kind == "razorpay"
    result = rail.attempt(cart, idempotency_key=cart.digest)
    assert hasattr(result, "ok") and hasattr(result, "settled")


def test_a_test_key_is_accepted(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_abcdefgh")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "secret")
    rail = RazorpayRail()
    assert rail.kind == "razorpay"


def test_a_seeded_cart_produces_a_stable_idempotency_key(intent, make_cart, chai):
    """Two identical carts must map to the same Razorpay receipt, or a retry
    creates a second order and charges twice."""
    a = make_cart((chai,), nonce="same")
    b = make_cart((chai,), nonce="same")
    assert a.digest == b.digest
    assert SigningKey.from_seed("x")  # keys are irrelevant to the digest


# -- Checkout signature verification --------------------------------------- #


class _Utility:
    """Razorpay's own verifier: an HMAC over "order_id|payment_id"."""

    def __init__(self, secret: str) -> None:
        self._secret = secret

    def verify_payment_signature(self, params: dict) -> None:
        import hashlib
        import hmac

        expected = hmac.new(
            self._secret.encode(),
            f"{params['razorpay_order_id']}|{params['razorpay_payment_id']}".encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, params["razorpay_signature"]):
            raise ValueError("signature mismatch")


class _VerifyingClient:
    def __init__(self, secret: str = "shh") -> None:
        self.utility = _Utility(secret)


def _signature(secret: str, order_id: str, payment_id: str) -> str:
    import hashlib
    import hmac

    return hmac.new(
        secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256
    ).hexdigest()


def test_a_payment_razorpay_signed_is_accepted():
    rail = RazorpayRail(client=_VerifyingClient())
    rail.verify_checkout_signature(
        order_id="order_1",
        payment_id="pay_1",
        signature=_signature("shh", "order_1", "pay_1"),
    )


def test_a_payment_nobody_signed_is_rejected():
    """The browser reports the payment; the browser is not the authority.

    Without this, anyone who can post to the endpoint can claim a Razorpay
    payment happened by inventing a payment id.
    """
    rail = RazorpayRail(client=_VerifyingClient())
    with pytest.raises(SignatureRejected):
        rail.verify_checkout_signature(
            order_id="order_1", payment_id="pay_1", signature="deadbeef"
        )


def test_a_signature_from_another_order_is_rejected():
    """A real signature, replayed onto a different order, still fails."""
    rail = RazorpayRail(client=_VerifyingClient())
    stolen = _signature("shh", "order_OTHER", "pay_1")
    with pytest.raises(SignatureRejected):
        rail.verify_checkout_signature(
            order_id="order_1", payment_id="pay_1", signature=stolen
        )
