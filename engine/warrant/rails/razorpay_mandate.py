"""A real UPI Autopay mandate, and debits placed against it.

This is the part of the story that is not a simulation.

UPI Reserve Pay -- the thing Razorpay and NPCI put behind Claude in February
2026 -- lets a person block funds once with their PIN so an agent can debit
repeatedly without being asked again. It is a pilot: you cannot get at it
without an NPCI and Razorpay partnership. What you *can* get at, on any test
account, is the primitive underneath it: a UPI Autopay mandate registered
``as_presented``, with a ``max_amount`` ceiling the NPCI rails themselves
enforce.

The shapes are the same, and so is the hole in the middle:

    the mandate enforces the amount.
    nothing enforces what it is spent on.

A ``max_amount`` of Rs 1,000 is equally happy to buy chai for a team and a pair
of Rs 999 earbuds. The bank cannot tell them apart -- it never sees a basket,
only a debit. That gap is the entire reason Warrant exists, and this module is
what makes the gap real rather than argued: every debit here is a genuine
recurring charge against a genuine mandate, and the only thing standing between
the agent and the money is the gate.

Nothing in this module is mocked. Registering mints a real invoice in your test
account with a real short URL; authorising it on a phone mints a real token;
charging it moves real test-mode money.
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, ConfigDict

from ..models import CartMandate, Paise, RailRef
from .base import RailResult

__all__ = [
    "MandateHandle",
    "MandateNotAuthorised",
    "MandateStatus",
    "RazorpayMandate",
    "RazorpayNotConfigured",
]

from .razorpay_rail import RazorpayNotConfigured

# NPCI caps a single UPI Autopay mandate. Asking for more is rejected at
# registration, which is a confusing place to discover it, so it is checked here.
MAX_MANDATE_PAISE: Paise = 100_000_00

# `as_presented` is the frequency that matches an agent: debit when there is
# something to debit, not on a calendar. It is also the only frequency for which
# "what is this particular debit for?" is a question nobody can answer from the
# mandate alone.
FREQUENCY = "as_presented"


class MandateHandle(BaseModel):
    """What a registration produced. The URL is the part a human has to visit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    invoice_id: str
    customer_id: str
    order_id: str | None
    short_url: str
    ceiling_paise: Paise
    """The mandate's ``max_amount`` -- enforced by NPCI, not by us."""


class MandateStatus(BaseModel):
    """Where a registration has got to."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    invoice_id: str
    status: str
    """Razorpay's own vocabulary: issued, paid, cancelled, expired."""

    token_id: str | None = None
    """Present once the customer has authorised. This is the reserve block."""

    payment_id: str | None = None

    @property
    def authorised(self) -> bool:
        return self.token_id is not None


class MandateNotAuthorised(RuntimeError):
    """Raised when a debit is attempted before anyone authorised the mandate."""


class RazorpayMandate:
    """Registers a real UPI mandate and debits against it.

    Satisfies :class:`~warrant.rails.base.Rail` once :meth:`register` has been
    called and the customer has authorised, so the authorization path does not
    know or care that this rail needs a mandate behind it.
    """

    kind = "razorpay_mandate"

    def __init__(
        self,
        key_id: str | None = None,
        key_secret: str | None = None,
        *,
        client: Any | None = None,
        handle: MandateHandle | None = None,
        token_id: str | None = None,
    ) -> None:
        self._handle = handle
        self._token_id = token_id

        if client is not None:
            self._client = client
            return

        key_id = key_id or os.environ.get("RAZORPAY_KEY_ID")
        key_secret = key_secret or os.environ.get("RAZORPAY_KEY_SECRET")
        if not key_id or not key_secret:
            raise RazorpayNotConfigured(
                "Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET to register a mandate, "
                "or run with --rail simulated."
            )
        if not key_id.startswith("rzp_test_"):
            raise RazorpayNotConfigured(
                f"Refusing to run against a non-test key ({key_id[:12]}...). Warrant "
                "only ever talks to Razorpay test mode."
            )

        import razorpay

        self._client = razorpay.Client(auth=(key_id, key_secret))

    # ------------------------------------------------------------- lifecycle

    def register(
        self,
        *,
        ceiling_paise: Paise,
        description: str,
        name: str = "Warrant demo customer",
        email: str = "demo@example.com",
        contact: str = "9123456780",
    ) -> MandateHandle:
        """Create a real mandate whose ceiling is the one the person approved.

        ``ceiling_paise`` comes from the signed IntentMandate, so the sentence a
        person said is what ends up enforced on the NPCI rails. Everything the
        sentence *also* said -- which merchant, which categories, how many
        orders, for how long -- has nowhere to go here. That is the point.
        """
        if ceiling_paise <= 0:
            raise ValueError("a mandate ceiling must be positive")
        if ceiling_paise > MAX_MANDATE_PAISE:
            raise ValueError(
                f"UPI Autopay caps a mandate at {MAX_MANDATE_PAISE // 100:,} rupees; "
                f"this scope asks for {ceiling_paise // 100:,}"
            )

        customer = self._client.customer.create(
            {"name": name, "email": email, "contact": contact, "fail_existing": "0"}
        )
        invoice = self._client.invoice.create(
            {
                "type": "link",
                "customer_id": customer["id"],
                # The registration itself carries a nominal amount; the ceiling
                # that matters is max_amount below.
                "amount": 100,
                "currency": "INR",
                "description": description,
                "subscription_registration": {
                    "method": "upi",
                    "max_amount": ceiling_paise,
                    "expire_at": 4102444800,
                    "frequency": FREQUENCY,
                },
            }
        )
        self._handle = MandateHandle(
            invoice_id=invoice["id"],
            customer_id=customer["id"],
            order_id=invoice.get("order_id"),
            short_url=invoice["short_url"],
            ceiling_paise=ceiling_paise,
        )
        return self._handle

    def status(self, invoice_id: str | None = None) -> MandateStatus:
        """Ask Razorpay whether the customer has authorised yet."""
        invoice_id = invoice_id or (self._handle.invoice_id if self._handle else None)
        if invoice_id is None:
            raise MandateNotAuthorised("no mandate has been registered")

        invoice = self._client.invoice.fetch(invoice_id)
        token_id = invoice.get("token_id")
        if token_id:
            self._token_id = token_id
        return MandateStatus(
            invoice_id=invoice_id,
            status=invoice.get("status", "unknown"),
            token_id=token_id,
            payment_id=invoice.get("payment_id"),
        )

    def revoke(self) -> bool:
        """Delete the token. After this the agent cannot debit at all.

        Warrant's own revocation is instant and local; this is the rail-side
        half of it, so a revoked mandate is revoked at the bank too rather than
        only in our ledger.
        """
        if not (self._handle and self._token_id):
            return False
        self._client.token.delete(self._handle.customer_id, self._token_id)
        self._token_id = None
        return True

    # ------------------------------------------------------------------ rail

    @property
    def authorised(self) -> bool:
        return self._token_id is not None

    @property
    def handle(self) -> MandateHandle | None:
        return self._handle

    def attempt(self, cart: CartMandate, *, idempotency_key: str) -> RailResult:
        """Debit the mandate for an authorized cart, with no human in the loop.

        This is the call the whole product is about. Nothing about it asks the
        customer anything -- that is what a mandate buys -- so the only check
        that ever happens on *what* is being bought is the one that already
        happened before we got here.
        """
        if not (self._handle and self._token_id):
            raise MandateNotAuthorised(
                "the mandate has not been authorised yet; open its short_url first"
            )

        try:
            order = self._client.order.create(
                {
                    "amount": cart.total_paise,
                    "currency": "INR",
                    "payment_capture": 1,
                    "customer_id": self._handle.customer_id,
                    "receipt": idempotency_key[:40],
                    "notes": {
                        "cart_digest": cart.digest,
                        "intent_digest": cart.intent_digest,
                        "warrant": "debit authorized against a signed mandate",
                    },
                }
            )
            payment = self._client.payment.createRecurring(
                {
                    "email": "demo@example.com",
                    "contact": "9123456780",
                    "amount": cart.total_paise,
                    "currency": "INR",
                    "order_id": order["id"],
                    "customer_id": self._handle.customer_id,
                    "token": self._token_id,
                    "recurring": "1",
                    "description": f"{cart.merchant} · {len(cart.line_items)} items",
                }
            )
        except Exception as exc:  # noqa: BLE001 -- Razorpay raises its own types
            return RailResult(
                ok=False,
                settled=False,
                ref=RailRef(kind=self.kind, order_id=None, payment_id=None),
                amount_paise=cart.total_paise,
                error_code="mandate_debit_failed",
                error_source="razorpay",
                error_step="payment_initiation",
                error_reason=str(exc)[:300],
            )

        captured = payment.get("status") == "captured"
        return RailResult(
            ok=True,
            settled=captured,
            ref=RailRef(
                kind=self.kind,
                order_id=order["id"],
                payment_id=payment.get("id"),
            ),
            amount_paise=cart.total_paise,
            raw={"order_status": order.get("status"), "payment_status": payment.get("status")},
        )

    def poll(self, order_id: str, cart: CartMandate) -> RailResult:
        """Ask whether anything has been captured against this order yet."""
        payments = self._client.order.payments(order_id).get("items", [])
        captured = next((p for p in payments if p.get("status") == "captured"), None)
        return RailResult(
            ok=True,
            settled=captured is not None,
            ref=RailRef(
                kind=self.kind,
                order_id=order_id,
                payment_id=captured.get("id") if captured else None,
            ),
            amount_paise=cart.total_paise,
        )
