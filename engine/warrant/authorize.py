"""The orchestrator: intent in, receipt or refusal out, everything written down.

The order of operations here is itself a control.

The deterministic gate runs **first and alone**. If it blocks, the cart is
refused and the model is never invoked -- an out-of-scope basket carrying an
injected payload in its product names does not reach a model at all, because
there is nothing left for a model to decide. The judge only ever sees carts that
have already cleared every hard bound, and its verdict can move ``allow`` to
``escalate`` and nothing else.

The three verdicts mean exactly this:

  allow      every binding check passed and nothing warned. Rail attempt follows.
  escalate   every binding check passed but something wants a human. No debit.
  block      a binding check failed. No debit, and the refusal is recorded with
             the rule that caused it.

Writes are ordered write-ahead, which matters because this sits in a payment path.
``cart_allowed`` is recorded **before** the rail is called, so a crash between the
two leaves a record of what was about to be attempted and reconciliation has
something to find. ``debit_settled`` is recorded **before** the running totals
move, because those totals are derived from the ledger on replay -- a counter
ahead of the record would survive as a permanent overspend allowance, whereas a
counter behind it is corrected by the next rebuild.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict

from .chain import EventKind, Ledger
from .crypto import SigningKey, VerifyKey
from .derive import Envelope, ScopeProposal, derive_scope, narrow_to_envelope
from .divergence import DivergenceFinding, judge_divergence
from .gate import MandateState, evaluate
from .models import (
    CartMandate,
    Check,
    CheckStatus,
    DebitReceipt,
    Decision,
    IntentMandate,
    LineItem,
    RailBinding,
    Scope,
    Verdict,
)
from .rails.base import Rail, RailResult
from .rails.simulated import SimulatedRail

__all__ = ["Authorizer", "AuthorizationOutcome", "PendingIntent"]


class PendingIntent(BaseModel):
    """A derived scope waiting for the human to approve it. Not yet authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    utterance: str
    proposal: ScopeProposal
    scope: Scope
    subject: str
    agent: str

    @property
    def approval_prompt(self) -> str:
        """What the person is shown before their key signs anything."""
        return self.proposal.plain_english

    @property
    def was_narrowed(self) -> bool:
        """True when the envelope tightened what the derivation step proposed."""
        return (
            self.scope.max_total_paise < self.proposal.max_total_paise
            or self.scope.max_per_txn_paise < self.proposal.max_per_txn_paise
            or self.scope.max_txns < self.proposal.max_txns
            or (self.scope.expires_at - self.scope.not_before) < self.proposal.duration_seconds
        )


class AuthorizationOutcome(BaseModel):
    """Everything that happened for one cart, in a form the console can render."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cart: CartMandate
    decision: Decision
    receipt: DebitReceipt | None = None
    rail: RailResult | None = None
    ledger_seqs: tuple[int, ...] = ()

    @property
    def verdict(self) -> Verdict:
        return self.decision.verdict


@dataclass(slots=True)
class Authorizer:
    """Holds the keys, the ledger and the rail. One per merchant deployment."""

    authorizer_key: SigningKey
    ledger: Ledger
    envelope: Envelope = field(default_factory=Envelope)
    rail: Rail = field(default_factory=SimulatedRail)
    model_client: object | None = None
    _states: dict[str, MandateState] = field(default_factory=dict, init=False)

    # -- issuing authority -------------------------------------------------- #

    def prepare_intent(
        self,
        utterance: str,
        *,
        subject: str,
        agent: str,
        now: int,
    ) -> PendingIntent:
        """Derive a scope and narrow it. Signs nothing -- a human decides next."""
        proposal = derive_scope(utterance, self.envelope, client=self.model_client)
        scope = narrow_to_envelope(proposal, self.envelope, issued_at=now)
        return PendingIntent(
            utterance=utterance,
            proposal=proposal,
            scope=scope,
            subject=subject,
            agent=agent,
        )

    def issue_intent(
        self,
        pending: PendingIntent,
        *,
        subject_key: SigningKey,
        now: int,
        nonce: str,
        rail: RailBinding | None = None,
    ) -> IntentMandate:
        """The human approved. Their key turns the scope into authority."""
        intent = IntentMandate(
            subject=pending.subject,
            agent=pending.agent,
            utterance=pending.utterance,
            scope=pending.scope,
            rail=rail or RailBinding(kind="simulated"),
            issued_at=now,
            nonce=nonce,
        ).signed_by(subject_key)

        self._states[intent.digest] = MandateState(intent_digest=intent.digest)
        self.ledger.append(
            EventKind.INTENT_ISSUED,
            self.session_for(intent),
            {
                "intent": intent.envelope(),
                "derivation": {
                    "source": pending.proposal.source,
                    "plain_english": pending.proposal.plain_english,
                    "ambiguities": list(pending.proposal.ambiguities),
                    "narrowed_by_envelope": pending.was_narrowed,
                    "proposed_max_total_paise": pending.proposal.max_total_paise,
                    "granted_max_total_paise": pending.scope.max_total_paise,
                },
            },
            recorded_at=now,
        )
        return intent

    def revoke(self, intent: IntentMandate, *, now: int, reason: str) -> None:
        """The subject withdraws authority. Everything after this blocks."""
        self.state_for(intent).revoked = True
        self.ledger.append(
            EventKind.INTENT_REVOKED,
            self.session_for(intent),
            {"intent_digest": intent.digest, "reason": reason},
            recorded_at=now,
        )

    # -- proposing a cart --------------------------------------------------- #

    @staticmethod
    def propose_cart(
        intent: IntentMandate,
        *,
        merchant: str,
        items: tuple[LineItem, ...],
        now: int,
        nonce: str,
    ) -> CartMandate:
        """Build the cart the agent wants to buy. Unsigned; not yet authorized."""
        return CartMandate(
            intent_digest=intent.digest,
            merchant=merchant,
            line_items=items,
            total_paise=sum(item.line_paise for item in items),
            issued_at=now,
            nonce=nonce,
        )

    # -- the decision ------------------------------------------------------- #

    def authorize(
        self,
        intent: IntentMandate,
        cart: CartMandate,
        *,
        subject_key: VerifyKey,
        now: int,
        skip_semantic: bool = False,
    ) -> AuthorizationOutcome:
        """Evaluate a cart and, if it clears, place the debit on the rail."""
        session = self.session_for(intent)
        state = self.state_for(intent)
        seqs: list[int] = []

        seqs.append(
            self.ledger.append(
                EventKind.CART_PROPOSED, session, {"cart": cart.envelope()}, recorded_at=now
            ).seq
        )

        decision = evaluate(intent, cart, state, now=now, subject_key=subject_key)

        # A cart that already failed a binding check is never shown to a model.
        if decision.verdict is not Verdict.BLOCK and not skip_semantic:
            finding = judge_divergence(intent, cart, client=self.model_client)
            decision = self._merge(decision, finding)

        if decision.verdict is Verdict.BLOCK:
            seqs.append(self._record_refusal(session, cart, decision, now, EventKind.CART_BLOCKED))
            return AuthorizationOutcome(cart=cart, decision=decision, ledger_seqs=tuple(seqs))

        if decision.verdict is Verdict.ESCALATE:
            seqs.append(
                self._record_refusal(session, cart, decision, now, EventKind.STEP_UP_REQUESTED)
            )
            return AuthorizationOutcome(cart=cart, decision=decision, ledger_seqs=tuple(seqs))

        signed_cart = cart.signed_by(self.authorizer_key)
        seqs.append(
            self.ledger.append(
                EventKind.CART_ALLOWED,
                session,
                {"cart": signed_cart.envelope(), "decision": decision.model_dump(mode="json")},
                recorded_at=now,
            ).seq
        )

        # The nonce is spent the moment the cart reaches the rail. On a rail that
        # settles asynchronously -- which is every real one -- consuming it only on
        # settlement leaves a window in which the same cart can be presented
        # repeatedly, placing an order each time.
        state.record_authorized(signed_cart)

        result = self.rail.attempt(signed_cart, idempotency_key=signed_cart.digest)
        seqs.append(
            self.ledger.append(
                EventKind.DEBIT_AUTHORIZED if result.ok else EventKind.DEBIT_FAILED,
                session,
                {"cart_digest": signed_cart.digest, "rail": result.model_dump(mode="json")},
                recorded_at=now,
            ).seq
        )

        receipt: DebitReceipt | None = None
        if result.settled:
            receipt = DebitReceipt(
                cart_digest=signed_cart.digest,
                intent_digest=intent.digest,
                amount_paise=result.amount_paise,
                rail=result.ref,
                settled_at=now,
            ).signed_by(self.authorizer_key)
            # Ledger first, then state. The ledger is the source of truth: running
            # totals are derived from it on replay, so if this append fails after
            # the counters moved, memory would claim spend the ledger cannot
            # account for -- and a rebuild would under-count and permit an
            # overspend. Writing first means the worst case is a counter behind
            # the record, which the next replay corrects.
            seqs.append(
                self.ledger.append(
                    EventKind.DEBIT_SETTLED,
                    session,
                    {"receipt": receipt.envelope()},
                    recorded_at=now,
                ).seq
            )
            state.record_settled(signed_cart)

        return AuthorizationOutcome(
            cart=signed_cart,
            decision=decision,
            receipt=receipt,
            rail=result,
            ledger_seqs=tuple(seqs),
        )

    # -- helpers ------------------------------------------------------------ #

    @staticmethod
    def _merge(decision: Decision, finding: DivergenceFinding) -> Decision:
        """Fold the advisory finding in. It can raise severity, never lower it."""
        check: Check = finding.as_check()
        checks = (*decision.checks, check)

        if decision.verdict is Verdict.BLOCK:
            verdict, reasons = decision.verdict, decision.reasons
        elif check.status is CheckStatus.WARN:
            verdict = Verdict.ESCALATE
            reasons = (*decision.reasons, check.detail)
        else:
            verdict, reasons = decision.verdict, decision.reasons

        return Decision(
            verdict=verdict,
            checks=checks,
            reasons=reasons,
            model_used=finding.ran,
        )

    def _record_refusal(
        self,
        session: str,
        cart: CartMandate,
        decision: Decision,
        now: int,
        kind: EventKind,
    ) -> int:
        """Refusals are entries, not silences. This is what a dispute reads."""
        return self.ledger.append(
            kind,
            session,
            {
                "cart_digest": cart.digest,
                "verdict": str(decision.verdict),
                "reasons": list(decision.reasons),
                "failed_rules": [c.rule for c in decision.failures],
                "warned_rules": [c.rule for c in decision.warnings],
                "decision": decision.model_dump(mode="json"),
            },
            recorded_at=now,
        ).seq

    @staticmethod
    def session_for(intent: IntentMandate) -> str:
        return f"sess_{intent.digest.removeprefix('sha256:')[:16]}"

    def state_for(self, intent: IntentMandate) -> MandateState:
        return self._states.setdefault(
            intent.digest, MandateState(intent_digest=intent.digest)
        )
