"""The four policies under test.

Three of them are baselines, and two of those are not strawmen -- they are what
agent payments actually run on today. ``no_gate`` is the status quo: an agent
holds a Reserve Pay block and spends against it with nothing checking the basket.
``amount_only`` is the obvious first thing a team builds, a ceiling and nothing
else. ``model_only`` is the tempting shortcut: skip the rules, ask a model
whether the basket looks right, and act on the answer.

``model_only`` is included specifically so its failure mode is measured rather
than asserted. It is the design Warrant argues against, and the benchmark should
show what it costs instead of taking my word for it.
"""

from __future__ import annotations

from collections.abc import Callable

from warrant.crypto import VerifyKey
from warrant.divergence import judge_divergence
from warrant.gate import MandateState, evaluate
from warrant.models import CartMandate, IntentMandate, Verdict

__all__ = ["POLICIES", "Policy"]

Policy = Callable[
    [IntentMandate, CartMandate, MandateState, int, VerifyKey, object | None], Verdict
]


def no_gate(
    intent: IntentMandate,
    cart: CartMandate,
    state: MandateState,
    now: int,
    subject_key: VerifyKey,
    client: object | None,
) -> Verdict:
    """The status quo. The block is authorized once; nothing checks the basket."""
    return Verdict.ALLOW


def amount_only(
    intent: IntentMandate,
    cart: CartMandate,
    state: MandateState,
    now: int,
    subject_key: VerifyKey,
    client: object | None,
) -> Verdict:
    """A single ceiling, which is what most first implementations amount to."""
    if cart.total_paise > intent.scope.max_per_txn_paise:
        return Verdict.BLOCK
    if state.spent_paise + cart.total_paise > intent.scope.max_total_paise:
        return Verdict.BLOCK
    return Verdict.ALLOW


def model_only(
    intent: IntentMandate,
    cart: CartMandate,
    state: MandateState,
    now: int,
    subject_key: VerifyKey,
    client: object | None,
) -> Verdict:
    """Ask a model whether the basket looks right, and treat the answer as binding.

    This is the design Warrant exists to argue against. Note what it cannot see:
    a replayed nonce, an expired window and a cumulative ceiling are all facts
    about session state, not about the basket, so no amount of reading the cart
    reveals them.
    """
    finding = judge_divergence(intent, cart, client=client)
    if not finding.ran:
        # No model reachable. The honest behaviour for a model-only policy is to
        # have no opinion, which means the money moves.
        return Verdict.ALLOW
    return Verdict.ALLOW if finding.verdict == "consistent" else Verdict.BLOCK


def warrant(
    intent: IntentMandate,
    cart: CartMandate,
    state: MandateState,
    now: int,
    subject_key: VerifyKey,
    client: object | None,
) -> Verdict:
    """The full system: deterministic gate first and binding, model advisory."""
    decision = evaluate(intent, cart, state, now=now, subject_key=subject_key)
    if decision.verdict is Verdict.BLOCK:
        return decision.verdict

    finding = judge_divergence(intent, cart, client=client)
    check = finding.as_check()
    if check.status == "warn" and decision.verdict is Verdict.ALLOW:
        return Verdict.ESCALATE
    return decision.verdict


POLICIES: dict[str, tuple[Policy, str]] = {
    "no_gate": (no_gate, "no checks at all — today's default for agent payments"),
    "amount_only": (amount_only, "a spending ceiling and nothing else"),
    "model_only": (model_only, "ask a model whether the basket looks right"),
    "warrant": (warrant, "deterministic gate binding, model advisory"),
}
