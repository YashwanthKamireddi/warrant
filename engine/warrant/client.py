"""The surface an adopter actually touches.

:class:`Authorizer` is the engine: keys, ledger, envelope, rail, per-mandate
locks, and a clock passed in from outside so the whole thing stays testable. All
of that is deliberate and none of it is a good first thing to meet. Dropping an
authorization check into an existing payment path should not require choosing a
signing key, inventing a nonce or deciding what time it is.

So this is the front door::

    from warrant import Warrant

    warrant = Warrant(merchants="warrant.toml")

    # once, when the person approves. The bounds come from whatever they filled
    # in; pass an utterance on its own instead if you have a model configured
    # and want the sentence interpreted.
    permission = warrant.permit(
        "lunch for the team",
        scope=Scope(
            merchants=("acme-grocers",),
            categories=("food_beverage",),
            max_total_paise=100_000,
            max_per_txn_paise=100_000,
            max_txns=2,
            not_before=now,
            expires_at=now + 7200,
        ),
    )

    # every time the agent wants to buy something
    decision = warrant.check(permission, "acme-grocers", [
        {"sku": "sandwich", "category": "food_beverage", "qty": 2, "unit_paise": 24_000},
    ])
    if not decision.allowed:
        return refuse(decision.reasons)

Everything has a working default and every default is the safe one: an
in-memory ledger, a generated authorizer key, the simulated rail, and the
bundled merchant registry. Nothing here reaches the network unless you hand it
something that does.

The facade adds no policy. It cannot: it calls the same
:func:`~warrant.gate.evaluate` everything else calls, and a convenience layer
that could change a verdict would be a second place for authorization logic to
live, which is how the two drift apart.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .authorize import AuthorizationOutcome, Authorizer, PendingIntent
from .chain import Ledger
from .crypto import SigningKey
from .derive import Envelope, ScopeProposal
from .evidence import EvidencePack
from .merchants import MerchantRegistry, load_registry
from .models import (
    CartMandate,
    CheckStatus,
    Decision,
    IntentMandate,
    LineItem,
    Scope,
    Verdict,
)
from .rails.base import Rail

__all__ = ["Permission", "Warrant", "WarrantDecision"]

#: What a caller may hand us as a basket line. A LineItem if they already have
#: one, otherwise ``(sku, qty, unit_paise)`` or a mapping with those keys plus
#: ``name`` and ``category``.
ItemLike = LineItem | tuple[str, int, int] | dict[str, Any]


def _describe(scope: Scope) -> str:
    """Restate a scope in the words a person would be asked to approve."""
    where = ", ".join(scope.merchants) if scope.merchants else "any merchant"
    what = ", ".join(scope.categories)
    hours = max(round((scope.expires_at - scope.not_before) / 3600), 1)
    orders = "one order" if scope.max_txns == 1 else f"at most {scope.max_txns} orders"
    return (
        f"Allow up to \u20b9{scope.max_total_paise / 100:,.0f} at {where} "
        f"for {what}, across {orders}, for the next "
        f"{'hour' if hours == 1 else f'{hours} hours'}."
    )


def scope_as_proposal(scope: Scope, utterance: str) -> ScopeProposal:
    """Describe an explicitly given scope in the shape derivation produces.

    A scope that came from a form was not interpreted by anything, so its
    provenance is ``pinned`` and its ambiguity list is empty. Recording it as
    though a model had produced it would put a claim in the ledger that nobody
    can substantiate.
    """
    return ScopeProposal(
        merchants=scope.merchants,
        categories=scope.categories,
        max_total_paise=scope.max_total_paise,
        max_per_txn_paise=scope.max_per_txn_paise,
        max_txns=scope.max_txns,
        duration_seconds=max(scope.expires_at - scope.not_before, 1),
        plain_english=_describe(scope),
        source="pinned",
    )


def _coerce(item: ItemLike) -> LineItem:
    if isinstance(item, LineItem):
        return item
    if isinstance(item, tuple):
        sku, qty, unit_paise = item
        return LineItem(
            sku=sku, name=sku, category="other", qty=qty, unit_paise=unit_paise
        )
    data = dict(item)
    data.setdefault("name", data["sku"])
    # An item whose category nobody stated is "other", never "whatever the
    # mandate happens to permit". Guessing here would quietly widen a scope.
    data.setdefault("category", "other")
    return LineItem(**data)


@dataclass(frozen=True)
class Permission:
    """A signed intent and the key that signed it, kept together.

    They are useless apart -- verifying a mandate needs the public half of the
    key that signed it -- and keeping them in one object is what lets
    :meth:`Warrant.check` take one argument instead of three.
    """

    intent: IntentMandate
    signer: SigningKey
    pending: PendingIntent

    @property
    def id(self) -> str:
        return self.intent.id

    @property
    def utterance(self) -> str:
        return self.intent.utterance

    @property
    def approval_prompt(self) -> str:
        """The sentence to put in front of the person before they approve."""
        return self.pending.approval_prompt


@dataclass(frozen=True)
class WarrantDecision:
    """A verdict, its reasons, and whatever the rail did about it."""

    decision: Decision
    cart: CartMandate
    outcome: AuthorizationOutcome | None = None

    @property
    def verdict(self) -> Verdict:
        return self.decision.verdict

    @property
    def allowed(self) -> bool:
        return self.decision.verdict is Verdict.ALLOW

    @property
    def needs_approval(self) -> bool:
        """The amount cleared every bound but crossed the step-up threshold."""
        return self.decision.verdict is Verdict.ESCALATE

    @property
    def reasons(self) -> tuple[str, ...]:
        """Why it was refused, in the order the rules ran. Empty when allowed."""
        return tuple(
            c.detail for c in self.decision.checks if c.status is CheckStatus.FAIL
        )

    @property
    def settled(self) -> bool:
        return bool(self.outcome and self.outcome.receipt is not None)

    def __bool__(self) -> bool:
        return self.allowed


class Warrant:
    """An authorization layer you can put in front of an agent's spending.

    One per deployment. Thread-safe: the engine serialises per mandate, because
    a ceiling check and the spend it authorises have to be atomic with respect
    to each other or two concurrent baskets each see a budget nobody has
    claimed yet.
    """

    def __init__(
        self,
        *,
        merchants: str | Path | MerchantRegistry | None = None,
        ledger: Ledger | str | Path | None = None,
        envelope: Envelope | None = None,
        rail: Rail | None = None,
        key: SigningKey | None = None,
        model: object | None = None,
    ) -> None:
        """
        ``merchants``  a registry, or a path to a TOML one. Defaults to
                       WARRANT_MERCHANTS, then to the bundled records.
        ``ledger``     a Ledger, or a path to a SQLite file. Defaults to memory.
        ``envelope``   the hard outer bound no derived scope may exceed.
        ``rail``       what actually attempts debits. Defaults to the simulated
                       one, which settles immediately and touches no network.
        ``key``        the authorizer's signing key. Generated if absent, which
                       is right for a test and wrong for a deployment -- a
                       generated key means last week's receipts cannot be
                       verified against this week's process.
        ``model``      an Anthropic-style client used to *propose* scopes and to
                       advise. It can never change a verdict.
        """
        self.registry = (
            merchants
            if isinstance(merchants, MerchantRegistry)
            else load_registry(merchants)
        )
        self.ledger = ledger if isinstance(ledger, Ledger) else Ledger(ledger)
        self._authorizer = Authorizer(
            authorizer_key=key or SigningKey.generate(),
            ledger=self.ledger,
            envelope=envelope or Envelope(),
            registry=self.registry,
            **({"rail": rail} if rail is not None else {}),
            model_client=model,
        )

    # ------------------------------------------------------------ permission

    def propose(
        self,
        utterance: str,
        *,
        subject: str = "user",
        agent: str = "agent",
        now: int | None = None,
    ) -> PendingIntent:
        """Derive a scope from what the person said. Signs nothing.

        Split out from :meth:`permit` because the whole point of this step is
        that a human sees the result before anything is signed. Render
        ``pending.approval_prompt``, and sign only if they agree.
        """
        return self._authorizer.prepare_intent(
            utterance, subject=subject, agent=agent, now=now or int(time.time())
        )

    def permit(
        self,
        utterance: str | PendingIntent,
        *,
        scope: Scope | None = None,
        subject: str = "user",
        agent: str = "agent",
        signer: SigningKey | None = None,
        now: int | None = None,
    ) -> Permission:
        """Derive, if needed, and sign. The result is the root of trust.

        ``scope`` skips derivation entirely and signs exactly the bounds you
        pass. Most deployments want this: the limits come from a form the person
        filled in -- an amount, a merchant, a category, a duration -- and there
        is nothing to infer. Interpreting a sentence is what you reach for when
        the person only ever gave you a sentence.

        Without a scope and without a model, derivation fails closed to a scope
        that permits the ``other`` category and one purchase, which is correct
        and buys nothing. If a first run refuses everything, that is why.

        ``signer`` is the person's own device key. Generating one when it is
        absent keeps a first run working; in a deployment the key belongs on the
        person's device and never here, which is the only reason the signature
        means anything.
        """
        now = now or int(time.time())
        if scope is not None:
            if isinstance(utterance, PendingIntent):
                raise TypeError("pass either a PendingIntent or a scope, not both")
            pending = PendingIntent(
                utterance=utterance,
                proposal=scope_as_proposal(scope, utterance),
                scope=scope,
                subject=subject,
                agent=agent,
            )
        else:
            pending = (
                utterance
                if isinstance(utterance, PendingIntent)
                else self.propose(utterance, subject=subject, agent=agent, now=now)
            )
        signer = signer or SigningKey.generate()
        intent = self._authorizer.issue_intent(
            pending,
            subject_key=signer,
            now=now,
            nonce=secrets.token_hex(16),
        )
        return Permission(intent=intent, signer=signer, pending=pending)

    def revoke(self, permission: Permission, *, reason: str = "revoked by the subject") -> None:
        """Stop this permission being spendable, now. Recorded in the ledger."""
        self._authorizer.revoke(permission.intent, now=int(time.time()), reason=reason)

    # --------------------------------------------------------------- deciding

    def check(
        self,
        permission: Permission,
        merchant: str,
        items: Iterable[ItemLike],
        *,
        now: int | None = None,
    ) -> WarrantDecision:
        """Would this basket be allowed? Answers without spending anything.

        Side-effect free: no budget consumed, no nonce burned, no ledger entry.
        Use it to show someone what would happen; use :meth:`spend` to make it
        happen.
        """
        cart = self._cart(permission, merchant, items, now)
        decision = self._authorizer.preview(
            permission.intent, cart, subject_key=permission.signer.public,
            now=now or int(time.time()),
        )
        return WarrantDecision(decision=decision, cart=cart)

    def spend(
        self,
        permission: Permission,
        merchant: str,
        items: Iterable[ItemLike],
        *,
        now: int | None = None,
    ) -> WarrantDecision:
        """Check the basket and, if it clears, place the debit on the rail.

        The refusal is recorded whether or not it clears. A control plane that
        only writes down its successes cannot be audited.
        """
        cart = self._cart(permission, merchant, items, now)
        outcome = self._authorizer.authorize(
            permission.intent, cart,
            subject_key=permission.signer.public,
            now=now or int(time.time()),
        )
        return WarrantDecision(decision=outcome.decision, cart=cart, outcome=outcome)

    # --------------------------------------------------------------- evidence

    def evidence(self, permission: Permission) -> EvidencePack:
        """Everything a merchant would file if this purchase were disputed."""
        from .evidence import assemble_evidence

        return assemble_evidence(
            self.ledger,
            Authorizer.session_for(permission.intent),
            subject_key=permission.signer.public,
        )

    def history(self, permission: Permission | None = None) -> Sequence[Any]:
        """Ledger entries, newest last. Every decision, including refusals."""
        if permission is None:
            return list(self.ledger.entries())
        return list(self.ledger.entries(Authorizer.session_for(permission.intent)))

    def close(self) -> None:
        self.ledger.close()

    def __enter__(self) -> Warrant:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ---------------------------------------------------------------- private

    def _cart(
        self,
        permission: Permission,
        merchant: str,
        items: Iterable[ItemLike],
        now: int | None,
    ) -> CartMandate:
        lines = tuple(_coerce(i) for i in items)
        if not lines:
            raise ValueError("a basket needs at least one line item")
        return Authorizer.propose_cart(
            permission.intent,
            merchant=merchant,
            items=lines,
            now=now or int(time.time()),
            nonce=secrets.token_hex(16),
        )
