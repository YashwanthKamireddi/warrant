"""The deterministic gate: the only layer permitted to block a debit.

Every rule here is a comparison between a number in the cart and a number the
human signed. No model is consulted, nothing is inferred, and the result is a
pure function of (intent, cart, state, clock). Run it twice on the same inputs
and you get the same verdict, which is what makes the ledger replayable.

A note on the injection heuristic near the bottom. It exists to raise a flag
early, not to be the defence. The defence is structural: a cart is checked
against a scope the *user's key* signed, and nothing a model emits can widen
that scope. An injected instruction that convinces the agent to buy a laptop
still meets a ceiling of 1,000 rupees and a category allowlist of
``food_beverage``, and still gets blocked -- whether or not the heuristic
noticed the payload. Pattern-matching untrusted text is a losing game played
alone; it is useful only as a signal on top of an architecture that does not
depend on winning it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .crypto import VerifyKey
from .merchants import REGISTRY, assigned_categories
from .models import (
    CartMandate,
    Check,
    CheckStatus,
    Decision,
    IntentMandate,
    Paise,
    Verdict,
)

__all__ = ["MandateState", "evaluate"]

# Deliberately short and obvious. See the module docstring: this is a signal,
# not a control. Each pattern targets a published injection shape, not a novel one.
_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "override",
        re.compile(r"\b(ignore|disregard|forget)\b.{0,24}\b(previous|prior|above|all)\b", re.I),
    ),
    (
        "role-claim",
        re.compile(r"\b(system|developer|admin)\s*(prompt|message|instruction|mode)\b", re.I),
    ),
    (
        "authority-claim",
        re.compile(r"\b(you are|act as)\b.{0,32}\b(authorized|approved|permitted)\b", re.I),
    ),
    (
        "directive",
        re.compile(
            r"\b(add|append|include|purchase|buy|transfer|send)\b.{0,24}"
            r"\b(without|no|skip)\b.{0,24}\b(confirm|approval|check|limit)\b",
            re.I,
        ),
    ),
)


@dataclass(slots=True)
class MandateState:
    """Running totals for one intent mandate. Rebuilt from the ledger on replay."""

    intent_digest: str
    spent_paise: Paise = 0
    txn_count: int = 0
    seen_nonces: set[str] = field(default_factory=set)
    rail_block_used_paise: Paise = 0
    revoked: bool = False

    def record_settled(self, cart: CartMandate) -> None:
        self.spent_paise += cart.total_paise
        self.txn_count += 1
        self.rail_block_used_paise += cart.total_paise
        self.seen_nonces.add(cart.nonce)


def _check(
    rule: str,
    ok: bool,
    detail_ok: str,
    detail_bad: str,
    *,
    observed: int | str | None = None,
    limit: int | str | None = None,
    binding: bool = True,
    warn_instead: bool = False,
) -> Check:
    failed_status = CheckStatus.WARN if warn_instead else CheckStatus.FAIL
    status = CheckStatus.PASS if ok else failed_status
    return Check(
        rule=rule,
        status=status,
        detail=detail_ok if ok else detail_bad,
        observed=observed,
        limit=limit,
        binding=binding,
    )


def _rupees(paise: Paise) -> str:
    return f"₹{paise / 100:,.2f}"


def evaluate(
    intent: IntentMandate,
    cart: CartMandate,
    state: MandateState,
    *,
    now: int,
    subject_key: VerifyKey,
) -> Decision:
    """Evaluate one cart against one intent. Deterministic, total, side-effect free."""
    checks: list[Check] = []
    scope = intent.scope

    # -- provenance ------------------------------------------------------- #

    checks.append(
        _check(
            "chain.intent_signature",
            intent.verify_with(subject_key),
            "Intent mandate carries a valid signature from the subject's device key",
            "Intent mandate signature is missing or was not made by the subject's key",
            observed=intent.signature.key_id if intent.signature else "unsigned",
            limit=subject_key.key_id,
        )
    )
    checks.append(
        _check(
            "chain.cart_binds_intent",
            cart.intent_digest == intent.digest,
            "Cart names this intent as its authority",
            "Cart claims authority from a different intent mandate",
            observed=cart.intent_digest,
            limit=intent.digest,
        )
    )
    checks.append(
        _check(
            "chain.not_revoked",
            not state.revoked,
            "Mandate is live",
            "Mandate was revoked by the subject",
        )
    )
    checks.append(
        _check(
            "replay.cart_nonce",
            cart.nonce not in state.seen_nonces,
            "Cart nonce has not been presented before",
            "Cart nonce was already used; this is a replay",
            observed=cart.nonce,
        )
    )

    # -- validity window --------------------------------------------------- #

    checks.append(
        _check(
            "scope.window",
            scope.not_before <= now < scope.expires_at,
            "Debit falls inside the authorized window",
            "Debit falls outside the authorized window",
            observed=now,
            limit=f"{scope.not_before}..{scope.expires_at}",
        )
    )

    # -- what may be bought ------------------------------------------------ #

    checks.append(
        _check(
            "scope.merchant",
            scope.permits_merchant(cart.merchant),
            f"{cart.merchant} is on the authorized merchant list",
            f"{cart.merchant} is not on the authorized merchant list",
            observed=cart.merchant,
            limit=", ".join(scope.merchants),
        )
    )
    # The merchant declares its own item categories, so before trusting them at
    # all, check them against what the merchant's acquirer assigned it. A merchant
    # does not write its own MCC.
    record = REGISTRY.get(cart.merchant)
    permitted_by_mcc = assigned_categories(cart.merchant)
    unbacked = sorted(c for c in cart.categories if c not in permitted_by_mcc)
    checks.append(
        _check(
            "merchant.mcc_scope",
            not unbacked,
            f"Every declared category is within MCC {record.mcc} "
            f"({record.description})" if record else "",
            (
                f"{cart.merchant} is not a registered merchant, so no category it "
                f"declares is backed by an acquirer"
                if record is None
                else f"Declared categories outside MCC {record.mcc} "
                f"({record.description}): {', '.join(unbacked)}"
            ),
            observed=", ".join(sorted(cart.categories)),
            limit=", ".join(sorted(permitted_by_mcc)) or "unregistered",
        )
    )

    offending = sorted(c for c in cart.categories if not scope.permits_category(c))
    checks.append(
        _check(
            "scope.category",
            not offending,
            "Every line item is in an authorized category",
            f"Line items outside authorized categories: {', '.join(offending)}",
            observed=", ".join(sorted(cart.categories)),
            limit=", ".join(scope.categories),
        )
    )
    checks.append(
        _check(
            "scope.currency",
            cart.currency == scope.currency,
            f"Cart is denominated in {scope.currency}",
            f"Cart currency {cart.currency} does not match mandate currency {scope.currency}",
            observed=cart.currency,
            limit=scope.currency,
        )
    )

    # -- how much ---------------------------------------------------------- #

    checks.append(
        _check(
            "scope.per_txn_ceiling",
            cart.total_paise <= scope.max_per_txn_paise,
            f"{_rupees(cart.total_paise)} is within the per-transaction ceiling",
            f"{_rupees(cart.total_paise)} exceeds the per-transaction ceiling of "
            f"{_rupees(scope.max_per_txn_paise)}",
            observed=cart.total_paise,
            limit=scope.max_per_txn_paise,
        )
    )
    projected = state.spent_paise + cart.total_paise
    checks.append(
        _check(
            "scope.total_ceiling",
            projected <= scope.max_total_paise,
            f"Cumulative {_rupees(projected)} stays within the mandate ceiling",
            f"Cumulative {_rupees(projected)} would exceed the mandate ceiling of "
            f"{_rupees(scope.max_total_paise)}",
            observed=projected,
            limit=scope.max_total_paise,
        )
    )
    checks.append(
        _check(
            "scope.txn_count",
            state.txn_count + 1 <= scope.max_txns,
            f"Debit {state.txn_count + 1} of {scope.max_txns} permitted",
            f"Mandate permits {scope.max_txns} debits and {state.txn_count} have settled",
            observed=state.txn_count + 1,
            limit=scope.max_txns,
        )
    )

    # -- the rail's own ceiling, which is not ours to relax ----------------- #

    if intent.rail.block_paise is not None:
        remaining = intent.rail.block_paise - state.rail_block_used_paise
        checks.append(
            _check(
                "rail.block_remaining",
                cart.total_paise <= remaining,
                f"{_rupees(cart.total_paise)} is within the {_rupees(remaining)} still "
                f"blocked on the rail",
                f"{_rupees(cart.total_paise)} exceeds the {_rupees(remaining)} still "
                f"blocked on the rail",
                observed=cart.total_paise,
                limit=remaining,
            )
        )

    # -- advisory signals: these escalate, they never block ------------------ #

    hits: list[str] = []
    for item in cart.line_items:
        haystack = f"{item.name} {item.sku}"
        hits.extend(
            f"{label} in {item.sku!r}"
            for label, pattern in _INJECTION_PATTERNS
            if pattern.search(haystack)
        )
    checks.append(
        _check(
            "signal.instruction_text",
            not hits,
            "No instruction-shaped text in cart item fields",
            f"Instruction-shaped text in cart item fields: {'; '.join(hits)}",
            observed=len(hits),
            limit=0,
            binding=False,
            warn_instead=True,
        )
    )

    headroom = scope.max_total_paise - projected
    approaching = 0 < headroom <= scope.max_total_paise // 10
    checks.append(
        _check(
            "signal.ceiling_creep",
            not approaching,
            "Comfortable headroom remains under the mandate ceiling",
            f"Only {_rupees(headroom)} would remain under the ceiling after this debit",
            observed=headroom,
            limit=scope.max_total_paise // 10,
            binding=False,
            warn_instead=True,
        )
    )

    # -- step up ------------------------------------------------------------ #

    step_up_needed = (
        scope.step_up_over_paise is not None and cart.total_paise > scope.step_up_over_paise
    )
    if step_up_needed:
        checks.append(
            _check(
                "step_up.cosignature",
                cart.user_cosignature is not None,
                f"{_rupees(cart.total_paise)} crossed the step-up threshold and the "
                f"subject co-signed this cart",
                f"{_rupees(cart.total_paise)} crosses the step-up threshold of "
                f"{_rupees(scope.step_up_over_paise or 0)} and needs the subject's "
                f"co-signature",
                observed=cart.total_paise,
                limit=scope.step_up_over_paise,
                binding=False,
                warn_instead=True,
            )
        )

    # -- verdict ------------------------------------------------------------ #

    binding_failures = [c for c in checks if c.status is CheckStatus.FAIL and c.binding]
    warnings = [c for c in checks if c.status is CheckStatus.WARN]

    if binding_failures:
        verdict = Verdict.BLOCK
        reasons = tuple(c.detail for c in binding_failures)
    elif warnings:
        verdict = Verdict.ESCALATE
        reasons = tuple(c.detail for c in warnings)
    else:
        verdict = Verdict.ALLOW
        reasons = ()

    return Decision(verdict=verdict, checks=tuple(checks), reasons=reasons, model_used=False)
