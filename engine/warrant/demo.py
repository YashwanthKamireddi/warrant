"""The canonical scenario: one person, one instruction, five carts.

Every step is fixed and seeded, so this produces identical output -- identical
ledger hashes included -- on any machine. That is deliberate: a reviewer can run
it and check the hashes against the ones in the README.

Which is why the scenario's scope is **pinned, not derived**. Derivation is a real
feature and it is exercised in the console, in the tests and under ``--derive``,
but a live model is entitled to read "for my team" as one order rather than two --
and when it did, the fifth step stopped demonstrating step-up and started
demonstrating the transaction cap instead. A teaching scenario whose lesson
changes because a model changed its mind is a bad teaching scenario, and a
reproducibility claim that a model can break is a false one.

The five carts are chosen to demonstrate the three verdicts and, more
importantly, *why* each one happened:

  1. what was asked for               allow     the ordinary case
  2. an extra nobody asked for        block     scope drift, caught on category
  3. an injected instruction          block     caught on the bound, not the payload
  4. the same cart a second time      block     replay
  5. a large legitimate order         escalate  step-up, a human decides
"""

from __future__ import annotations

from dataclasses import dataclass

from .authorize import Authorizer, PendingIntent
from .catalog import line_item
from .chain import Ledger
from .crypto import SigningKey
from .derive import Envelope, ScopeProposal
from .models import IntentMandate, LineItem, RailBinding, Scope

__all__ = ["DemoStep", "Scenario", "build_scenario", "UTTERANCE"]

UTTERANCE = "order chai and samosas for my team from zomato, keep it under 1000"

T0 = 1_788_255_000  # 2026-09-01 09:30 UTC, fixed so runs are byte-identical


@dataclass(frozen=True, slots=True)
class DemoStep:
    """One cart, plus what a viewer should understand from the outcome."""

    label: str
    merchant: str
    items: tuple[LineItem, ...]
    nonce: str
    expect: str
    teaches: str
    offset: int = 0


STEPS: tuple[DemoStep, ...] = (
    DemoStep(
        label="What was asked for",
        merchant="zomato",
        items=(line_item("chai-6", 6), line_item("samosa-2", 2)),
        nonce="cart-legit-1",
        expect="allow",
        teaches="Every bound the subject signed is satisfied, so the debit proceeds.",
        offset=60,
    ),
    DemoStep(
        label="An extra nobody asked for",
        merchant="zomato",
        items=(line_item("chai-6", 2), line_item("powerbank", 1)),
        nonce="cart-drift-1",
        expect="block",
        teaches=(
            "The basket is under every ceiling and at the right merchant. It still "
            "fails, because 'electronics' is not a category the subject authorized."
        ),
        offset=180,
    ),
    DemoStep(
        label="An injected instruction",
        merchant="zomato",
        items=(line_item("promo", 1),),
        nonce="cart-inject-1",
        expect="block",
        teaches=(
            "The payload is blocked on the category bound, not on having spotted the "
            "payload. Delete the injection heuristic entirely and this still fails."
        ),
        offset=300,
    ),
    DemoStep(
        label="The same cart, replayed",
        merchant="zomato",
        items=(line_item("chai-6", 6), line_item("samosa-2", 2)),
        nonce="cart-legit-1",
        expect="block",
        teaches="A settled cart's nonce cannot be presented twice, so a replay is refused.",
        offset=420,
    ),
    DemoStep(
        label="A large legitimate order",
        merchant="zomato",
        items=(line_item("catering", 1),),
        nonce="cart-stepup-1",
        expect="escalate",
        teaches=(
            "Nothing is wrong with it, and it fits inside every ceiling. It crosses the "
            "step-up threshold, so the standing delegation collapses back to one "
            "explicit human decision."
        ),
        offset=540,
    ),
)


@dataclass(slots=True)
class Scenario:
    """A fully wired demo: keys, ledger, authorizer and a signed intent."""

    authorizer: Authorizer
    intent: IntentMandate
    subject_key: SigningKey
    approval_prompt: str
    derivation_source: str
    steps: tuple[DemoStep, ...] = STEPS
    t0: int = T0
    pending: PendingIntent | None = None

    def pending_for(self, utterance: str) -> PendingIntent:
        """The pinned permission, restated for whatever the person typed.

        The scope stays fixed so a scripted run is reproducible; only the recorded
        utterance changes, which is what the ledger and the evidence pack quote.
        """
        assert self.pending is not None
        return self.pending.model_copy(update={"utterance": utterance})


PINNED_PROMPT = (
    "Allow up to Rs 1,000 at Zomato for food and drink, across at most 2 orders, "
    "for the next 2 hours."
)

PINNED_SCOPE = Scope(
    merchants=("zomato",),
    categories=("food_beverage",),
    max_total_paise=100_000,
    max_per_txn_paise=100_000,
    max_txns=2,
    step_up_over_paise=50_000,
    not_before=T0,
    expires_at=T0 + 2 * 3_600,
)


def build_scenario(
    *,
    ledger: Ledger | None = None,
    rail=None,
    model_client: object | None = None,
    derive: bool = False,
) -> Scenario:
    """Wire up the demo.

    ``derive=False`` pins the scope so the run is byte-identical everywhere.
    ``derive=True`` runs the real derivation, which is what the console does.
    """
    subject_key = SigningKey.from_seed("warrant/demo/subject/priya")
    authorizer_key = SigningKey.from_seed("warrant/demo/authorizer")

    envelope = Envelope(
        max_total_paise=200_000,
        max_per_txn_paise=100_000,
        max_txns=4,
        max_duration_seconds=2 * 3_600,
        step_up_over_paise=50_000,
        allowed_categories=("food_beverage", "groceries"),
        allowed_merchants=("zomato", "swiggy", "zepto"),
    )

    authorizer = Authorizer(
        authorizer_key=authorizer_key,
        ledger=ledger if ledger is not None else Ledger(),
        envelope=envelope,
        model_client=model_client,
        **({"rail": rail} if rail is not None else {}),
    )

    if derive:
        pending = authorizer.prepare_intent(
            UTTERANCE, subject="user_priya", agent="agent_claude", now=T0
        )
    else:
        pending = PendingIntent(
            utterance=UTTERANCE,
            proposal=ScopeProposal(
                merchants=("zomato",),
                categories=("food_beverage",),
                max_total_paise=100_000,
                max_per_txn_paise=100_000,
                max_txns=2,
                duration_seconds=2 * 3_600,
                plain_english=PINNED_PROMPT,
                ambiguities=("team size not stated, so the per-order ceiling is the "
                             "full budget",),
                source="pinned",
            ),
            scope=PINNED_SCOPE,
            subject="user_priya",
            agent="agent_claude",
        )
    intent = authorizer.issue_intent(
        pending,
        subject_key=subject_key,
        now=T0,
        nonce="warrant-demo-intent-1",
        rail=RailBinding(kind="upi_reserve_pay", block_paise=100_000),
    )

    return Scenario(
        authorizer=authorizer,
        intent=intent,
        subject_key=subject_key,
        approval_prompt=pending.approval_prompt,
        derivation_source=pending.proposal.source,
        pending=pending,
    )
