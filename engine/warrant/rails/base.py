"""The rail interface.

Warrant decides whether a debit is authorized. A rail is what actually attempts
it. Keeping the two apart is what lets the benchmark run thousands of decisions
against a deterministic rail while the demo runs the same decisions against
Razorpay's test mode with nothing else changed.

Every rail call is idempotent on a key derived from the cart mandate's digest, so
a retry after a timeout cannot double-charge: the same cart always produces the
same key, and the same key always produces the same rail attempt.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from ..models import CartMandate, Paise, RailRef

__all__ = ["Rail", "RailResult"]


class RailResult(BaseModel):
    """What a rail reports back. Failures carry Razorpay's own error vocabulary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ok: bool
    """The rail accepted the attempt without erroring."""

    settled: bool
    """Money actually moved. A receipt is only issued when this is true."""

    ref: RailRef
    amount_paise: Paise
    error_code: str | None = None
    error_source: str | None = None
    error_step: str | None = None
    error_reason: str | None = None
    raw: dict[str, Any] = {}

    @property
    def failure_summary(self) -> str:
        if self.ok:
            return "settled"
        parts = [p for p in (self.error_source, self.error_step, self.error_reason) if p]
        return " / ".join(parts) or (self.error_code or "unknown failure")


class Rail(Protocol):
    """Anything that can attempt a debit for an authorized cart."""

    kind: str

    def attempt(self, cart: CartMandate, *, idempotency_key: str) -> RailResult:
        """Attempt the debit. Must be idempotent on ``idempotency_key``."""
        ...
