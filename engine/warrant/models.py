"""The mandate chain.

Three documents, each binding to the one above it by content address:

    IntentMandate    signed by the USER's device key
        |            "I authorize my agent to spend up to X at Y for Z, until T"
        v
    CartMandate      signed by the AUTHORIZER (this service)
        |            "I checked this specific basket against that intent. It fits."
        v
    DebitReceipt     signed by the AUTHORIZER
                     "This rail payment settled that cart under that intent."

The trust model is deliberately asymmetric, and the asymmetry is the point.
Only the human's key can widen what may be spent. The authorizer can only ever
attest that something already permitted was checked -- it cannot grant authority
it was not given. A compromised authorizer can refuse valid carts (denial of
service, visible and recoverable) but cannot manufacture a spend the user never
sanctioned, because it does not hold the user's key.

Above a step-up threshold the user must co-sign the cart itself, which collapses
the standing delegation back to explicit per-purchase consent for large amounts.

Identifiers are content addresses. ``im_a3f2...`` *is* the first 16 hex of the
intent's digest, so an id cannot be forged, reassigned, or made to point at a
document other than the one it names.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .crypto import Signature, SigningKey, VerifyKey, digest

__all__ = [
    "CartMandate",
    "Check",
    "CheckStatus",
    "DebitReceipt",
    "Decision",
    "IntentMandate",
    "LineItem",
    "Paise",
    "RailBinding",
    "RailRef",
    "Scope",
    "Verdict",
]

Paise = int
"""Money is always an integer count of paise. There are no floats in this system."""

SCHEMA_VERSION = 1
WILDCARD = "*"


class _Doc(BaseModel):
    """Base for signable documents.

    ``body()`` is the exact structure that gets canonicalized and signed. The
    signature is never part of the body it authenticates, so it is excluded here
    and carried alongside.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    signature: Signature | None = Field(default=None, exclude=True, repr=False)

    _prefix: str = "doc"

    def body(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=False)

    @property
    def digest(self) -> str:
        return digest(self.body())

    @property
    def id(self) -> str:
        return f"{self._prefix}_{self.digest.removeprefix('sha256:')[:16]}"

    def signed_by(self, key: SigningKey) -> Self:
        return self.model_copy(update={"signature": key.sign(self.body())})

    def verify_with(self, key: VerifyKey) -> bool:
        return self.signature is not None and key.verify(self.body(), self.signature)

    def envelope(self) -> dict[str, Any]:
        """Wire form: the document, its id, its digest and its signature."""
        return {
            "id": self.id,
            "digest": self.digest,
            "body": self.body(),
            "signature": self.signature.to_dict() if self.signature else None,
        }


# --------------------------------------------------------------------------- #
# Intent
# --------------------------------------------------------------------------- #


class Scope(BaseModel):
    """What the human actually permitted. Every field is a hard bound.

    A scope is only ever *narrowed* by the engine, never widened. The derivation
    step turns an utterance into one of these; the human then approves it in
    plain English before their key signs it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    merchants: tuple[str, ...] = Field(description="Allowlist of merchant ids, or ('*',)")
    categories: tuple[str, ...] = Field(description="Allowlist of categories, or ('*',)")
    max_total_paise: Paise = Field(gt=0, description="Ceiling across the whole mandate")
    max_per_txn_paise: Paise = Field(gt=0, description="Ceiling for any single debit")
    max_txns: int = Field(gt=0, le=100, description="How many debits this mandate permits")
    step_up_over_paise: Paise | None = Field(
        default=None,
        gt=0,
        description="Above this, the user must co-sign the cart. None disables step-up.",
    )
    currency: Literal["INR"] = "INR"
    not_before: int = Field(description="Unix seconds; the mandate is inert before this")
    expires_at: int = Field(description="Unix seconds; hard expiry")

    @field_validator("merchants", "categories")
    @classmethod
    def _non_empty(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if not v:
            raise ValueError("allowlist cannot be empty; use ('*',) to permit any")
        return v

    def model_post_init(self, _: Any) -> None:
        if self.max_per_txn_paise > self.max_total_paise:
            raise ValueError("max_per_txn_paise cannot exceed max_total_paise")
        if self.expires_at <= self.not_before:
            raise ValueError("expires_at must be after not_before")

    def permits_merchant(self, merchant: str) -> bool:
        return WILDCARD in self.merchants or merchant in self.merchants

    def permits_category(self, category: str) -> bool:
        return WILDCARD in self.categories or category in self.categories


class RailBinding(BaseModel):
    """Which payment rail this mandate is bound to, and its own native ceiling.

    UPI Reserve Pay blocks a fixed sum up front; the block itself is a real
    constraint independent of anything Warrant enforces, so we carry it and check
    against it rather than pretending our ceiling is the only one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["upi_reserve_pay", "razorpay_order", "simulated"] = "simulated"
    block_paise: Paise | None = Field(default=None, gt=0)
    reference: str | None = None


class IntentMandate(_Doc):
    """The root of trust. Signed by the user's device key, never by the agent."""

    _prefix = "im"

    type: Literal["intent_mandate"] = "intent_mandate"
    version: int = SCHEMA_VERSION
    subject: str = Field(description="The human delegating authority")
    agent: str = Field(description="The agent receiving it")
    utterance: str = Field(description="Verbatim instruction the human gave")
    scope: Scope
    rail: RailBinding = RailBinding()
    issued_at: int
    nonce: str = Field(description="Replay guard; unique per mandate")


# --------------------------------------------------------------------------- #
# Cart
# --------------------------------------------------------------------------- #


class LineItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sku: str
    name: str
    category: str
    qty: int = Field(gt=0)
    unit_paise: Paise = Field(gt=0)

    @property
    def line_paise(self) -> Paise:
        return self.qty * self.unit_paise


class CartMandate(_Doc):
    """A specific basket, checked against a specific intent."""

    _prefix = "cm"

    type: Literal["cart_mandate"] = "cart_mandate"
    version: int = SCHEMA_VERSION
    intent_digest: str = Field(description="Content address of the governing intent")
    merchant: str
    line_items: tuple[LineItem, ...] = Field(min_length=1)
    total_paise: Paise = Field(gt=0)
    currency: Literal["INR"] = "INR"
    issued_at: int
    nonce: str
    user_cosignature: Signature | None = Field(
        default=None,
        description="Present when the cart crossed the step-up threshold",
    )

    def model_post_init(self, _: Any) -> None:
        computed = sum(item.line_paise for item in self.line_items)
        if computed != self.total_paise:
            raise ValueError(
                f"total_paise {self.total_paise} does not equal the sum of line "
                f"items {computed}; a cart that does not add up is never signed"
            )

    @property
    def categories(self) -> frozenset[str]:
        return frozenset(item.category for item in self.line_items)


# --------------------------------------------------------------------------- #
# Receipt
# --------------------------------------------------------------------------- #


class RailRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["razorpay", "simulated"]
    order_id: str | None = None
    payment_id: str | None = None
    status: str | None = None


class DebitReceipt(_Doc):
    """Proof that a rail payment settled a particular cart under a particular intent."""

    _prefix = "dr"

    type: Literal["debit_receipt"] = "debit_receipt"
    version: int = SCHEMA_VERSION
    cart_digest: str
    intent_digest: str
    amount_paise: Paise = Field(gt=0)
    currency: Literal["INR"] = "INR"
    rail: RailRef
    settled_at: int


# --------------------------------------------------------------------------- #
# Decisions
# --------------------------------------------------------------------------- #


class Verdict(StrEnum):
    ALLOW = "allow"
    ESCALATE = "escalate"
    BLOCK = "block"


class CheckStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class Check(BaseModel):
    """One rule, its outcome, and the numbers that produced it.

    ``observed`` and ``limit`` are carried separately from ``detail`` so the
    console can render a real meter rather than parse a sentence, and so the
    evidence pack can state a bound numerically.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule: str
    status: CheckStatus
    detail: str
    observed: int | str | None = None
    limit: int | str | None = None
    binding: bool = Field(
        default=True,
        description="Binding checks can block. Advisory checks can only escalate.",
    )


class Decision(BaseModel):
    """The complete, replayable outcome of evaluating one cart."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: Verdict
    checks: tuple[Check, ...]
    reasons: tuple[str, ...] = ()
    model_used: bool = Field(
        default=False,
        description="True when a model contributed. Deterministic verdicts say so.",
    )

    @property
    def failures(self) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if c.status is CheckStatus.FAIL)

    @property
    def warnings(self) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if c.status is CheckStatus.WARN)
