"""Razorpay test mode.

An honest note about what this does and does not do, because the distinction
matters when reading the benchmark numbers.

Razorpay's API creates Orders and Payment Links server to server. It does not
complete a payment server to server -- authorising a card or a UPI collect
requires the customer's own device, which is exactly the property that makes the
rail trustworthy and exactly the reason a script cannot fake it. So this rail:

  * creates a **real** Order in your Razorpay test account
  * creates a **real** Payment Link against it
  * reports ``ok=True, settled=False`` -- the debit is placed, not completed
  * moves to settled only when :meth:`poll` sees Razorpay report a captured
    payment, or a webhook delivers one

Run ``warrant demo --rail razorpay`` and the orders appear in your test
dashboard; nothing here is mocked. The batch benchmark deliberately runs on the
simulated rail instead, because measuring an authorization policy against network
variance measures the network.
"""

from __future__ import annotations

import os
from typing import Any

from ..models import CartMandate, RailRef
from .base import RailResult

__all__ = ["RazorpayRail", "RazorpayNotConfigured"]


class SignatureRejected(RuntimeError):
    """Razorpay Checkout reported a payment the key secret does not vouch for."""


class RazorpayNotConfigured(RuntimeError):
    """Raised when the Razorpay rail is selected without test-mode credentials."""


class RazorpayRail:
    """Places authorized debits on Razorpay test mode as real Orders and Payment Links."""

    kind = "razorpay"

    def __init__(
        self,
        key_id: str | None = None,
        key_secret: str | None = None,
        *,
        client: Any | None = None,
    ) -> None:
        if client is not None:
            self._client = client
            return

        key_id = key_id or os.environ.get("RAZORPAY_KEY_ID")
        key_secret = key_secret or os.environ.get("RAZORPAY_KEY_SECRET")
        if not key_id or not key_secret:
            raise RazorpayNotConfigured(
                "Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET to use the Razorpay rail, "
                "or run with --rail simulated."
            )
        if not key_id.startswith("rzp_test_"):
            raise RazorpayNotConfigured(
                f"Refusing to run against a non-test key ({key_id[:12]}...). Warrant "
                "only ever talks to Razorpay test mode."
            )

        import razorpay

        self._client = razorpay.Client(auth=(key_id, key_secret))

    def attempt(self, cart: CartMandate, *, idempotency_key: str) -> RailResult:
        """Create a real test-mode Order and Payment Link for an authorized cart."""
        try:
            order = self._client.order.create(
                {
                    "amount": cart.total_paise,
                    "currency": cart.currency,
                    # Razorpay dedupes on receipt, which gives us idempotency for free.
                    "receipt": idempotency_key[:40],
                    "notes": {
                        "warrant_cart": cart.id,
                        "warrant_intent": cart.intent_digest[:32],
                        "merchant": cart.merchant,
                    },
                }
            )
            link = self._client.payment_link.create(
                {
                    "amount": cart.total_paise,
                    "currency": cart.currency,
                    "description": f"{cart.merchant} · {len(cart.line_items)} items",
                    "reference_id": idempotency_key[:40],
                    "notes": {"warrant_cart": cart.id},
                }
            )
        except Exception as exc:  # noqa: BLE001 - the rail reports, it does not raise
            return RailResult(
                ok=False,
                settled=False,
                ref=RailRef(kind="razorpay", status="rejected"),
                amount_paise=cart.total_paise,
                error_code="RAIL_REJECTED",
                error_source="gateway",
                error_step="order_creation",
                error_reason=str(exc)[:200],
            )

        return RailResult(
            ok=True,
            settled=False,
            ref=RailRef(
                kind="razorpay",
                order_id=order.get("id"),
                status=order.get("status", "created"),
            ),
            amount_paise=cart.total_paise,
            raw={"payment_link": link.get("short_url"), "payment_link_id": link.get("id")},
        )

    def create_order(self, cart: CartMandate, *, idempotency_key: str) -> dict[str, Any]:
        """Just the Order, with no Payment Link beside it.

        A test account allows 30 links a day and far more orders, so when the
        link cap is reached this is what still produces a real Razorpay object
        somebody can look up.
        """
        return self._client.order.create(
            {
                "amount": cart.total_paise,
                "currency": "INR",
                "payment_capture": 1,
                "receipt": idempotency_key[:40],
                "notes": {
                    "cart_digest": cart.digest,
                    "intent_digest": cart.intent_digest,
                },
            }
        )

    def verify_checkout_signature(
        self, *, order_id: str, payment_id: str, signature: str
    ) -> None:
        """Confirm Razorpay signed this payment, using the secret we hold.

        Razorpay Checkout runs in the customer's browser and hands the page back
        an order id, a payment id and an HMAC of the two under the key secret. A
        browser is not a trustworthy reporter of whether it paid, so this is the
        step that separates "the popup said it worked" from a fact: only a party
        holding the secret can produce that signature, and only this process
        holds it.
        """
        try:
            self._client.utility.verify_payment_signature(
                {
                    "razorpay_order_id": order_id,
                    "razorpay_payment_id": payment_id,
                    "razorpay_signature": signature,
                }
            )
        except Exception as exc:  # noqa: BLE001 - the SDK raises its own type
            raise SignatureRejected(
                "Razorpay did not sign this payment. The order id, payment id and "
                "signature do not agree under the key secret."
            ) from exc

    def payment(self, payment_id: str) -> dict[str, Any]:
        """What Razorpay itself says about a payment, fetched server-side."""
        return dict(self._client.payment.fetch(payment_id))

    def poll(self, order_id: str, cart: CartMandate) -> RailResult:
        """Ask Razorpay whether anything has been captured against this order yet."""
        try:
            payments = self._client.order.payments(order_id).get("items", [])
        except Exception as exc:  # noqa: BLE001
            return RailResult(
                ok=False,
                settled=False,
                ref=RailRef(kind="razorpay", order_id=order_id, status="unknown"),
                amount_paise=cart.total_paise,
                error_code="RAIL_UNREACHABLE",
                error_reason=str(exc)[:200],
            )

        captured = next((p for p in payments if p.get("status") == "captured"), None)
        if captured:
            return RailResult(
                ok=True,
                settled=True,
                ref=RailRef(
                    kind="razorpay",
                    order_id=order_id,
                    payment_id=captured.get("id"),
                    status="captured",
                ),
                amount_paise=captured.get("amount", cart.total_paise),
            )

        failed = next((p for p in payments if p.get("status") == "failed"), None)
        if failed:
            source = failed.get("error_source")
            return RailResult(
                ok=False,
                settled=False,
                ref=RailRef(
                    kind="razorpay",
                    order_id=order_id,
                    payment_id=failed.get("id"),
                    status="failed",
                ),
                amount_paise=cart.total_paise,
                error_code=failed.get("error_code"),
                error_source=source,
                error_step=failed.get("error_step"),
                error_reason=failed.get("error_reason"),
            )

        return RailResult(
            ok=True,
            settled=False,
            ref=RailRef(kind="razorpay", order_id=order_id, status="awaiting_payment"),
            amount_paise=cart.total_paise,
        )
