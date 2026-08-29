"""A deterministic rail, so the benchmark measures the policy and not the network.

Failures are drawn from Razorpay's own published error vocabulary rather than
invented, because the point of the failure path is to show the system behaving
correctly against errors it will actually meet.
"""

from __future__ import annotations

import hashlib

from ..models import CartMandate, RailRef
from .base import RailResult

__all__ = ["SimulatedRail"]

# Drawn from Razorpay's documented source / step / reason taxonomy.
_FAILURES: tuple[tuple[str, str, str, str], ...] = (
    ("BAD_REQUEST_ERROR", "customer", "payment_authentication", "payment_failed"),
    ("GATEWAY_ERROR", "gateway", "payment_authorization", "bank_not_available"),
    ("BAD_REQUEST_ERROR", "customer", "payment_authentication", "insufficient_funds"),
    ("GATEWAY_ERROR", "gateway", "payment_authorization", "payment_declined"),
    ("BAD_REQUEST_ERROR", "customer", "payment_initiation", "vpa_resolution_failed"),
)


class SimulatedRail:
    """Deterministic rail. The same cart always produces the same outcome.

    ``failure_rate`` is a fraction in basis points of carts that fail, selected by
    hashing the idempotency key -- so a run is reproducible without a PRNG and
    without any global state.
    """

    kind = "simulated"

    def __init__(self, *, failure_rate_bps: int = 0, always_fail: bool = False) -> None:
        if not 0 <= failure_rate_bps <= 10_000:
            raise ValueError("failure_rate_bps must be between 0 and 10000")
        self._failure_rate_bps = failure_rate_bps
        self._always_fail = always_fail
        self._seen: dict[str, RailResult] = {}

    def attempt(self, cart: CartMandate, *, idempotency_key: str) -> RailResult:
        if idempotency_key in self._seen:
            return self._seen[idempotency_key]

        draw = int.from_bytes(
            hashlib.sha256(idempotency_key.encode("utf-8")).digest()[:4], "big"
        )
        fails = self._always_fail or (draw % 10_000) < self._failure_rate_bps

        suffix = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:14]
        if fails:
            code, source, step, reason = _FAILURES[draw % len(_FAILURES)]
            result = RailResult(
                ok=False,
                settled=False,
                ref=RailRef(kind="simulated", order_id=f"order_{suffix}", status="failed"),
                amount_paise=cart.total_paise,
                error_code=code,
                error_source=source,
                error_step=step,
                error_reason=reason,
            )
        else:
            result = RailResult(
                ok=True,
                settled=True,
                ref=RailRef(
                    kind="simulated",
                    order_id=f"order_{suffix}",
                    payment_id=f"pay_{suffix}",
                    status="captured",
                ),
                amount_paise=cart.total_paise,
            )

        self._seen[idempotency_key] = result
        return result
