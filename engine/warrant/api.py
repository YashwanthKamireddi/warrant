"""HTTP surface for the console.

The console is a view onto the engine, never a second implementation of it.
Every verdict rendered in the browser came from :func:`warrant.gate.evaluate`;
nothing is re-derived client side. That matters because a control plane that
computes its own idea of what happened is not a control plane, it is a picture
of one.

Sessions live in memory. Warrant is an authorization layer, not a database, and
a demo that needs no migrations is a demo a reviewer can actually run.
"""

from __future__ import annotations

import copy
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import shop
from .authorize import Authorizer, PendingIntent
from .catalog import active_catalog, by_sku, teaching_roles
from .chain import EventKind, Ledger
from .crypto import SigningKey
from .demo import PINNED_SCOPE, UTTERANCE, build_scenario
from .evidence import assemble_evidence
from .gate import evaluate
from .interop import to_ap2_chain
from .llm import describe_capability
from .merchants import active_registry
from .models import (
    CartMandate,
    CheckStatus,
    DebitReceipt,
    IntentMandate,
    LineItem,
    RailBinding,
    Scope,
    Verdict,
)
from .rails.razorpay_rail import RazorpayNotConfigured, RazorpayRail
from .rails.simulated import SimulatedRail

__all__ = ["app"]

app = FastAPI(title="Warrant", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# The demo storefront. Deliberately small, and deliberately includes items an
# agent could plausibly drift onto.
# --------------------------------------------------------------------------- #
# The demo storefront lives in catalog.py so the CLI demo, the API and the
# console cannot drift apart. They did once, by exactly one SKU.
# --------------------------------------------------------------------------- #

# Read from the active catalog rather than the bundled tuple, so a console
# started with WARRANT_CATALOG set shows that merchant's products. The bundled
# ones are a demonstration; they are not what an adopter is supposed to sell.
CATALOG: tuple[dict[str, Any], ...] = tuple(p._asdict() for p in active_catalog())


def _available_rails() -> list[dict[str, Any]]:
    """Only offer a rail that will actually work.

    The Razorpay rail refuses to construct without test-mode credentials, so
    offering it unconditionally would put a control in the console that errors
    the moment anyone touches it.
    """
    rails: list[dict[str, Any]] = [
        {
            "id": "simulated",
            "label": "Simulated rail",
            "note": "Deterministic. Settles immediately. No network.",
            "available": True,
        }
    ]
    try:
        RazorpayRail()
    except RazorpayNotConfigured as exc:
        rails.append(
            {
                "id": "razorpay",
                "label": "Razorpay test mode",
                "note": str(exc),
                "available": False,
            }
        )
    else:
        rails.append(
            {
                "id": "razorpay",
                "label": "Razorpay test mode",
                "note": (
                    "Creates real Orders and Payment Links in your test account. "
                    "Reports settled=False until the rail confirms a capture."
                ),
                "available": True,
            }
        )
    return rails


def _build_rail(kind: str):
    if kind == "razorpay":
        return RazorpayRail()
    return SimulatedRail()


@dataclass(slots=True)
class Session:
    """One demo session: its ledger, its keys, its signed intent."""

    id: str
    authorizer: Authorizer
    subject_key: SigningKey
    rail_kind: str = "simulated"
    documents: list[tuple[CartMandate, DebitReceipt | None]] = field(default_factory=list)
    """The signed documents behind each outcome.

    Kept here rather than serialised into every response: the AP2 export needs the
    real objects, and shipping a second copy of each cart to the browser added
    several kilobytes per request for something the browser never reads.
    """

    intent: IntentMandate | None = None
    pending: PendingIntent | None = None
    clock: int = 0
    outcomes: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    nonces: list[str] = field(default_factory=list)
    """One per submitted cart. A replay re-presents an earlier one."""

    def tick(self, seconds: int = 47) -> int:
        with self._lock:
            self.clock += seconds
            return self.clock

    def next_nonce(self) -> str:
        """Derive and reserve a cart nonce in one step.

        Reading the length and then appending is a read-modify-write. Under
        CPython's GIL the window is a few bytecodes and it did not reproduce in
        sixty trials of sixteen racing threads -- but it is incorrect regardless,
        and free-threaded builds remove the accident that hides it. A collision
        here would refuse a legitimate cart as a replay, which is friction rather
        than a hole, and still worth not having.
        """
        with self._lock:
            nonce = f"{self.id}-cart-{len(self.nonces) + 1}"
            self.nonces.append(nonce)
            return nonce

    def reserve_nonce(self, nonce: str) -> None:
        with self._lock:
            self.nonces.append(nonce)

    def record(self, payload: dict[str, Any], cart, receipt) -> None:
        """Keep the rendered outcome and its signed documents in step."""
        with self._lock:
            self.outcomes.append(payload)
            self.documents.append((cart, receipt))


MAX_SESSIONS = 64
"""Demo sessions are held in memory, each owning a SQLite ledger. Without a
bound they accumulate for the lifetime of the process -- fine for a five-minute
demo, a leak in anything left running. Oldest out first; insertion order is
creation order, which is what a dict already gives us."""

SESSIONS: dict[str, Session] = {}


def _remember(session: Session) -> None:
    """Store a session, evicting the oldest once the cap is reached.

    Dict insertion order is creation order, so the first key is the oldest. The
    evicted session's ledger is closed rather than dropped, because it owns a
    SQLite connection.
    """
    SESSIONS[session.id] = session
    while len(SESSIONS) > MAX_SESSIONS:
        oldest = next(iter(SESSIONS))
        SESSIONS.pop(oldest).authorizer.ledger.close()


def _session(session_id: str) -> Session:
    session = SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #


class StartRequest(BaseModel):
    utterance: str = Field(default=UTTERANCE, max_length=400)
    rail: Literal["simulated", "razorpay"] = "simulated"
    derive: bool = Field(
        default=False,
        description=(
            "Interpret the utterance with a live model instead of using the pinned "
            "scope. Off by default so the scripted run is reproducible: a model is "
            "entitled to read 'for my team' as one order rather than two, and when "
            "it did, the fifth basket stopped demonstrating step-up."
        ),
    )


class ApproveRequest(BaseModel):
    approved: bool = True


class CartLine(BaseModel):
    sku: str
    qty: int = Field(gt=0, le=50)


class CartRequest(BaseModel):
    merchant: str = "zomato"
    lines: list[CartLine] = Field(min_length=1, max_length=20)
    cosign: bool = Field(
        default=False,
        description="Simulate the subject approving a step-up by co-signing the cart",
    )
    replay_of: int | None = Field(
        default=None,
        ge=1,
        description=(
            "1-based index of an earlier cart in this session whose nonce to re-present. "
            "This is how the console demonstrates a replay: same basket, same nonce, "
            "which the gate must refuse."
        ),
    )


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #


def _scope_json(intent: IntentMandate, session: Session) -> dict[str, Any]:
    state = session.authorizer.state_for(intent)
    scope = intent.scope
    return {
        "merchants": list(scope.merchants),
        "categories": list(scope.categories),
        "max_total_paise": scope.max_total_paise,
        "max_per_txn_paise": scope.max_per_txn_paise,
        "max_txns": scope.max_txns,
        "step_up_over_paise": scope.step_up_over_paise,
        "not_before": scope.not_before,
        "expires_at": scope.expires_at,
        "spent_paise": state.spent_paise,
        "txns_used": state.txn_count,
        "revoked": state.revoked,
        "rail_block_paise": intent.rail.block_paise,
        "rail_block_used_paise": state.rail_block_used_paise,
        "rail_kind": intent.rail.kind,
    }


def _outcome_json(outcome, step_label: str | None = None) -> dict[str, Any]:
    return {
        "cart": {
            "id": outcome.cart.id,
            "digest": outcome.cart.digest,
            "merchant": outcome.cart.merchant,
            "total_paise": outcome.cart.total_paise,
            "signature": outcome.cart.signature.to_dict() if outcome.cart.signature else None,
            "line_items": [
                {
                    "sku": i.sku,
                    "name": i.name,
                    "category": i.category,
                    "qty": i.qty,
                    "unit_paise": i.unit_paise,
                    "line_paise": i.line_paise,
                }
                for i in outcome.cart.line_items
            ],
        },
        "verdict": str(outcome.decision.verdict),
        "model_used": outcome.decision.model_used,
        "reasons": list(outcome.decision.reasons),
        "checks": [c.model_dump(mode="json") for c in outcome.decision.checks],
        "receipt": outcome.receipt.envelope() if outcome.receipt else None,
        "rail": outcome.rail.model_dump(mode="json") if outcome.rail else None,
        "ledger_seqs": list(outcome.ledger_seqs),
        "label": step_label,
    }


def _ledger_json(session: Session, *, since: int = 0) -> list[dict[str, Any]]:
    """Serialise ledger entries, optionally only those after ``since``.

    Write endpoints return just what they added. Returning the whole ledger on
    every write made each response carry a full copy of every prior decision --
    a single cart_allowed entry is over 3KB because it embeds the cart envelope
    and all sixteen checks -- so a five-basket session was re-sending tens of
    kilobytes the client already had. The full ledger is available from its own
    endpoint for a first load or a refresh.
    """
    if session.intent is None:
        return []
    sid = session.authorizer.session_for(session.intent)
    return [
        {
            "seq": e.seq,
            "kind": str(e.kind),
            "recorded_at": e.recorded_at,
            "prev_hash": e.prev_hash,
            "hash": e.hash,
            "payload": e.payload,
        }
        for e in session.authorizer.ledger.entries(sid)
        if e.seq > since
    ]


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@app.get("/api/meta")
def meta() -> dict[str, Any]:
    """What the console needs to describe the running system honestly."""
    capability = describe_capability()
    return {
        "capability": capability.model_dump(mode="json"),
        "capability_note": capability.note,
        "rails": _available_rails(),
        "catalog": list(CATALOG),
        "default_utterance": console_utterance(),
        "scripted_steps": _scripted_steps(),
    }


def console_merchant() -> str:
    """The merchant the console demonstrates against.

    The scope was pinned to zomato, so a console pointed at a grocer's catalogue
    had a permission for a merchant none of its products belonged to and a
    scripted run with nothing in it. The primary merchant is whichever one has
    the most products in the active catalogue -- which is the bundled zomato
    when nothing is configured, and yours when something is.
    """
    catalog = active_catalog()
    counts: dict[str, int] = {}
    for product in catalog:
        counts[product.merchant] = counts.get(product.merchant, 0) + 1
    if not counts:
        return PINNED_SCOPE.merchants[0]
    return max(counts, key=lambda m: (counts[m], m))


def console_scope() -> Scope:
    """The pinned demo scope, retargeted at whatever catalogue is loaded.

    The bounds are the demonstration and stay fixed; only the merchant, and the
    categories its acquirer underwrote it for, follow the configuration.
    """
    merchant = console_merchant()
    if merchant == PINNED_SCOPE.merchants[0]:
        return PINNED_SCOPE

    permitted = active_registry().assigned_categories(merchant)
    categories = tuple(sorted(permitted)) or PINNED_SCOPE.categories
    return PINNED_SCOPE.model_copy(
        update={"merchants": (merchant,), "categories": categories}
    )


def _retarget(pending: PendingIntent) -> PendingIntent:
    """Point a pinned permission at the catalogue that is actually loaded.

    The permission said zomato while the products said acme-grocers, so a
    configured console signed a mandate for a merchant none of its products
    belonged to and refused its own scripted run on the merchant bound. The
    numbers are the demonstration and stay fixed; the merchant and its
    underwritten categories follow the configuration, and so does the sentence
    the person is asked to approve.
    """
    scope = console_scope()
    if scope is PINNED_SCOPE:
        return pending

    where = ", ".join(scope.merchants)
    what = ", ".join(c.replace("_", " and ") for c in scope.categories)
    prompt = (
        f"Allow up to Rs {scope.max_total_paise / 100:,.0f} at {where} for {what}, "
        f"across at most {scope.max_txns} orders, for the next 2 hours."
    )
    return pending.model_copy(update={
        "scope": scope,
        "proposal": pending.proposal.model_copy(update={
            "merchants": scope.merchants,
            "categories": scope.categories,
            "plain_english": prompt,
        }),
    })


def console_utterance() -> str:
    """The instruction, naming the products the scripted basket actually buys.

    It was fixed text about chai and samosas while the basket was built from
    whatever the catalogue happened to stock. The advisory judge compares the
    two and escalated the first step for exactly that reason, which was correct
    of it. Deriving one from the other keeps them honest for any catalogue.
    """
    scope = console_scope()
    roles = teaching_roles(
        active_catalog(),
        merchant=scope.merchants[0],
        permitted=frozenset(scope.categories),
        step_up_paise=scope.step_up_over_paise,
    )
    first = roles.get("in_scope")
    if first is None:
        return UTTERANCE
    second = roles.get("in_scope_second")
    what = first.name if second is None else f"{first.name} and {second.name}"
    rupees = scope.max_total_paise // 100
    return f"order {what.lower()} for my team from {scope.merchants[0]}, keep it under {rupees}"


def _in_scope_basket(roles: dict[str, Any], scope: Scope) -> list[dict[str, Any]]:
    """A basket that looks like the order the instruction describes.

    Two products rather than one, in quantities that read as an order for a
    group and land comfortably under the co-signature threshold. A single cheap
    item satisfies every arithmetic bound and still does not match a sentence
    asking for two things for a team -- and the advisory judge says so, which is
    correct of it and made the first scripted step escalate the moment a model
    was reachable.
    """
    first = roles["in_scope"]
    second = roles.get("in_scope_second")

    # Under the co-signature threshold, so the first basket is an unqualified
    # allow -- and small enough that the step-up basket still fits under the
    # *running total* afterwards. Sizing to the threshold alone left Rs 415 plus
    # a Rs 649 platter at Rs 1,064 against a Rs 1,000 ceiling, so the step that
    # exists to demonstrate escalation blocked on the budget instead.
    ceiling = scope.step_up_over_paise or scope.max_per_txn_paise
    over = roles.get("over_threshold")
    headroom = scope.max_total_paise - (over.unit_paise if over else 0)
    target = int(min(ceiling, max(headroom, ceiling // 4)) * 0.9)

    if second is None:
        qty = max(1, min(6, target // first.unit_paise))
        return [{"sku": first.sku, "qty": qty}]

    # Most of the budget on the cheaper line, the rest on the second, so the
    # basket reads as "a lot of the cheap thing and a few of the other".
    first_qty = max(1, min(6, int(target * 0.65) // first.unit_paise))
    spent = first_qty * first.unit_paise
    second_qty = min(4, (target - spent) // second.unit_paise)
    if second_qty < 1:
        # No room for the second product. Forcing one in anyway pushed the
        # basket past the target by exactly the price of the thing that did not
        # fit, which is how a Rs 356 basket ended up Rs 5 over a Rs 1,000
        # ceiling three steps later.
        return [{"sku": first.sku, "qty": max(1, min(6, target // first.unit_paise))}]
    return [
        {"sku": first.sku, "qty": first_qty},
        {"sku": second.sku, "qty": second_qty},
    ]


def _scripted_steps() -> list[dict[str, Any]]:
    """The five-basket run, built from whatever catalogue is loaded.

    It used to name skus straight out of the bundled products, so a console
    started with WARRANT_CATALOG set asked a grocer for `chai-6` and got a 400.
    The run asks for roles instead -- something in scope, something in the wrong
    category, something carrying an injected instruction, something over the
    step-up threshold -- and a role nothing can fill is left out rather than
    faked.
    """
    scope = console_scope()
    merchant = scope.merchants[0]
    roles = teaching_roles(
        active_catalog(),
        merchant=merchant,
        permitted=frozenset(scope.categories),
        step_up_paise=scope.step_up_over_paise,
    )

    def basket(*skus: str) -> list[dict[str, Any]]:
        return [{"sku": sku, "qty": 1} for sku in skus]

    steps: list[dict[str, Any]] = []
    legit = roles.get("in_scope")
    legit_lines = _in_scope_basket(roles, scope)

    if legit:
        steps.append({
            "label": "What was asked for",
            "expect": "allow",
            "teaches": "Every bound the subject signed is satisfied, so the debit proceeds.",
            "merchant": merchant,
            "lines": legit_lines,
            "replay_of": None,
        })
    if legit and (drift := roles.get("wrong_category")):
        steps.append({
            "label": "An extra nobody asked for",
            "expect": "block",
            "teaches": (
                "The basket is under every ceiling and at the right merchant. It "
                f"still fails, because '{drift.category}' is not a category the "
                "subject authorized."
            ),
            "merchant": merchant,
            "lines": [
                {"sku": legit.sku, "qty": 1},
                {"sku": drift.sku, "qty": 1},
            ],
            "replay_of": None,
        })
    if injected := roles.get("injection"):
        steps.append({
            "label": "An injected instruction",
            "expect": "block",
            "teaches": (
                "The payload is blocked on a bound the subject signed, not on having "
                "spotted the payload. Delete every injection heuristic and this still "
                "fails."
            ),
            "merchant": merchant,
            "lines": basket(injected.sku),
            "replay_of": None,
        })
    if legit:
        steps.append({
            "label": "The same cart, replayed",
            "expect": "block",
            "teaches": (
                "A settled cart's nonce cannot be presented twice, so a replay is "
                "refused."
            ),
            "merchant": merchant,
            "lines": legit_lines,
            "replay_of": 1,
        })
    if over := roles.get("over_threshold"):
        steps.append({
            "label": "Over the step-up threshold",
            "expect": "escalate",
            "teaches": (
                "Nothing is violated. The amount crosses the threshold the subject "
                "set for a second signature, so it stops for a human rather than "
                "proceeding quietly."
            ),
            "merchant": merchant,
            "lines": basket(over.sku),
            "replay_of": None,
        })
    return steps


@app.post("/api/sessions")
def start_session(body: StartRequest) -> dict[str, Any]:
    """Derive a scope from an utterance. Signs nothing -- approval comes next."""
    scenario = build_scenario()
    session_id = "sess_" + secrets.token_hex(6)
    try:
        rail = _build_rail(body.rail)
    except RazorpayNotConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    session = Session(
        id=session_id,
        authorizer=Authorizer(
            authorizer_key=SigningKey.from_seed(f"warrant/console/authorizer/{session_id}"),
            ledger=Ledger(),
            envelope=scenario.authorizer.envelope,
            rail=rail,
        ),
        subject_key=SigningKey.from_seed("warrant/demo/subject/priya"),
        clock=scenario.t0,
        rail_kind=body.rail,
    )
    if body.derive:
        session.pending = session.authorizer.prepare_intent(
            body.utterance, subject="user_priya", agent="agent_claude", now=session.clock
        )
    else:
        session.pending = _retarget(
            build_scenario(derive=False).pending_for(body.utterance)
        )
    _remember(session)

    return {
        "session_id": session_id,
        "utterance": body.utterance,
        "rail": body.rail,
        "pending": {
            "approval_prompt": session.pending.approval_prompt,
            "ambiguities": list(session.pending.proposal.ambiguities),
            "source": session.pending.proposal.source,
            "narrowed_by_envelope": session.pending.was_narrowed,
            "proposed_max_total_paise": session.pending.proposal.max_total_paise,
            "scope": {
                "merchants": list(session.pending.scope.merchants),
                "categories": list(session.pending.scope.categories),
                "max_total_paise": session.pending.scope.max_total_paise,
                "max_per_txn_paise": session.pending.scope.max_per_txn_paise,
                "max_txns": session.pending.scope.max_txns,
                "step_up_over_paise": session.pending.scope.step_up_over_paise,
                "expires_at": session.pending.scope.expires_at,
                "not_before": session.pending.scope.not_before,
            },
        },
        "envelope": session.authorizer.envelope.model_dump(mode="json"),
    }


@app.post("/api/sessions/{session_id}/approve")
def approve(session_id: str, body: ApproveRequest) -> dict[str, Any]:
    """The human approves. Their key turns the scope into authority."""
    session = _session(session_id)
    if session.pending is None:
        raise HTTPException(status_code=409, detail="nothing pending for this session")
    if not body.approved:
        SESSIONS.pop(session_id, None)
        return {"approved": False, "session_id": session_id}

    session.intent = session.authorizer.issue_intent(
        session.pending,
        subject_key=session.subject_key,
        now=session.clock,
        nonce=f"{session_id}-intent",
        rail=RailBinding(kind="upi_reserve_pay", block_paise=100_000),
    )
    session.pending = None
    return {
        "approved": True,
        "intent": session.intent.envelope(),
        "scope": _scope_json(session.intent, session),
        "subject_public_key": session.subject_key.public.b64,
        "ledger": _ledger_json(session),
    }


@app.post("/api/sessions/{session_id}/carts")
def submit_cart(session_id: str, body: CartRequest) -> dict[str, Any]:
    """The agent proposes a basket. Everything interesting happens here."""
    session = _session(session_id)
    if session.intent is None:
        raise HTTPException(status_code=409, detail="intent has not been approved yet")

    items: list[LineItem] = []
    for line in body.lines:
        try:
            product = by_sku(line.sku)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        items.append(
            LineItem(
                sku=product.sku,
                name=product.name,
                category=product.category,
                qty=line.qty,
                unit_paise=product.unit_paise,
            )
        )

    before = session.authorizer.ledger.length

    if body.replay_of is not None:
        if body.replay_of > len(session.nonces):
            raise HTTPException(
                status_code=400,
                detail=f"cannot replay cart {body.replay_of}; only {len(session.nonces)} submitted",
            )
        nonce = session.nonces[body.replay_of - 1]
        session.reserve_nonce(nonce)
    else:
        nonce = session.next_nonce()

    now = session.tick()
    cart = session.authorizer.propose_cart(
        session.intent,
        merchant=body.merchant,
        items=tuple(items),
        now=now,
        nonce=nonce,
    )
    if body.cosign:
        cart = cart.model_copy(
            update={"user_cosignature": session.subject_key.sign(cart.body())}
        )

    started = time.perf_counter()
    outcome = session.authorizer.authorize(
        session.intent, cart, subject_key=session.subject_key.public, now=now
    )
    elapsed_us = (time.perf_counter() - started) * 1_000_000

    payload = _outcome_json(outcome)
    payload["elapsed_us"] = round(elapsed_us, 1)
    # The rail is a network call on the Razorpay path and would swamp the number
    # people actually want, which is what the gate itself costs.
    payload["rail_kind"] = session.rail_kind
    session.record(payload, outcome.cart, outcome.receipt)

    return {
        "outcome": payload,
        "scope": _scope_json(session.intent, session),
        "ledger_added": _ledger_json(session, since=before),
    }


class CompareRequest(BaseModel):
    merchant: str = "zomato"
    lines: list[CartLine] = Field(min_length=1, max_length=20)


@app.post("/api/sessions/{session_id}/compare")
def compare(session_id: str, body: CompareRequest) -> dict[str, Any]:
    """The same basket, with and without a gate.

    A rule name is not a stake. `scope.category -> BLOCK` is correct and
    verifiable and says nothing about what it was worth. This runs one basket
    through both worlds and answers in money: what settles when nothing checks,
    what evidence exists afterwards, and what happens instead.

    Nothing here is illustrative -- the "with" column is a real evaluation by the
    same gate the rest of the system uses, on the real mandate in this session.
    """
    session = _session(session_id)
    if session.intent is None:
        raise HTTPException(status_code=409, detail="intent has not been approved yet")

    items: list[LineItem] = []
    for line in body.lines:
        try:
            product = by_sku(line.sku)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        items.append(
            LineItem(
                sku=product.sku,
                name=product.name,
                category=product.category,
                qty=line.qty,
                unit_paise=product.unit_paise,
            )
        )

    cart = CartMandate(
        intent_digest=session.intent.digest,
        merchant=body.merchant,
        line_items=tuple(items),
        total_paise=sum(i.line_paise for i in items),
        issued_at=session.clock,
        nonce=f"{session_id}-compare-{secrets.token_hex(4)}",
    )

    # Evaluated against a copy of the live state, so previewing never consumes
    # budget, a nonce, or an attempt from the real mandate.
    decision = session.authorizer.preview(
        session.intent,
        cart,
        subject_key=session.subject_key.public,
        now=session.clock,
    )

    failures = [c for c in decision.checks if c.status is CheckStatus.FAIL]
    warnings = [c for c in decision.checks if c.status is CheckStatus.WARN]

    return {
        "cart": {
            "merchant": cart.merchant,
            "total_paise": cart.total_paise,
            "line_items": [
                {"name": i.name, "qty": i.qty, "category": i.category, "line_paise": i.line_paise}
                for i in cart.line_items
            ],
        },
        "without": {
            # No gate is not a policy; it is what happens when nobody wrote one.
            "outcome": "settled",
            "amount_paise": cart.total_paise,
            "evidence": [
                {"item": "device fingerprint", "present": False},
                {"item": "browsing session", "present": False},
                {"item": "customer click", "present": False},
                {"item": "signed permission", "present": False},
            ],
            "on_dispute": "The merchant has nothing to submit and absorbs the chargeback.",
        },
        "with": {
            "outcome": str(decision.verdict),
            "amount_paise": 0 if decision.verdict is Verdict.BLOCK else cart.total_paise,
            "failed_rules": [
                {"rule": c.rule, "detail": c.detail, "observed": c.observed, "limit": c.limit}
                for c in failures
            ],
            "warned_rules": [{"rule": c.rule, "detail": c.detail} for c in warnings],
            "checks_run": len(decision.checks),
            "model_used": decision.model_used,
            "evidence": [
                {"item": "signed permission", "present": True},
                {"item": "checked basket", "present": True},
                {"item": "bound receipt", "present": decision.verdict is Verdict.ALLOW},
            ],
            "on_dispute": (
                "The money never moved."
                if decision.verdict is Verdict.BLOCK
                else "The merchant submits the signed chain, verifiable against the "
                "cardholder's own public key."
            ),
        },
    }


class AgentRunRequest(BaseModel):
    merchant: str = "zomato"
    attempts: int = Field(default=3, ge=1, le=5)


@app.post("/api/sessions/{session_id}/agent-run")
def agent_run(session_id: str, body: AgentRunRequest) -> dict[str, Any]:
    """Let the agent shop, and gate whatever it decides.

    This is the product as it actually runs. A model reads the instruction and
    the merchant's catalog, picks a basket and says why; Warrant checks it before
    any payment exists; and if it is refused, the agent is told the reason and
    tries again.

    Nothing tells the agent to misbehave and nothing tells it the customer's
    limits -- it does not have them, which is the entire situation this exists
    for. An agent being generous with someone else's money is the common failure,
    not an agent being malicious.
    """
    session = _session(session_id)
    if session.intent is None:
        raise HTTPException(status_code=409, detail="intent has not been approved yet")

    attempts: list[dict[str, Any]] = []
    rejected: list[str] = []

    for _ in range(body.attempts):
        basket = shop(
            session.intent.utterance,
            merchant=body.merchant,
            rejected=tuple(rejected),
            client=session.authorizer.model_client,
        )
        items = basket.line_items()
        now = session.tick()
        cart = session.authorizer.propose_cart(
            session.intent,
            merchant=basket.merchant,
            items=items,
            now=now,
            nonce=session.next_nonce(),
        )
        # Timed twice, because one number would be a lie. The deterministic gate
        # is what sits in the payment path and it runs in microseconds; the
        # advisory judge is a network round trip and only runs on carts that
        # already cleared every binding check. Reporting the total as "the gate"
        # would make a sub-millisecond decision look like a second.
        gate_started = time.perf_counter()
        gate_only = evaluate(
            session.intent,
            cart,
            copy.deepcopy(session.authorizer.state_for(session.intent)),
            now=now,
            subject_key=session.subject_key.public,
        )
        gate_us = (time.perf_counter() - gate_started) * 1_000_000
        del gate_only

        started = time.perf_counter()
        outcome = session.authorizer.authorize(
            session.intent, cart, subject_key=session.subject_key.public, now=now
        )
        elapsed_us = (time.perf_counter() - started) * 1_000_000

        payload = _outcome_json(outcome)
        payload["elapsed_us"] = round(elapsed_us, 1)
        payload["gate_us"] = round(gate_us, 1)
        payload["rail_kind"] = session.rail_kind
        payload["label"] = basket.reasoning
        session.record(payload, outcome.cart, outcome.receipt)

        attempts.append(
            {
                "agent": {
                    "reasoning": basket.reasoning,
                    "source": basket.source,
                    "picks": [
                        {"sku": p.sku, "qty": p.qty, "name": by_sku(p.sku).name}
                        for p in basket.picks
                    ],
                    "total_paise": basket.total_paise,
                },
                "outcome": payload,
            }
        )

        if outcome.verdict is Verdict.ALLOW:
            break
        # The agent is told why, not what the limits are. It has to infer.
        rejected.extend(outcome.decision.reasons)

    return {
        "attempts": attempts,
        "scope": _scope_json(session.intent, session),
        "ledger_added": _ledger_json(session, since=0),
    }


@app.post("/api/sessions/{session_id}/settle")
def settle(session_id: str) -> dict[str, Any]:
    """Ask the rail whether anything it accepted has since been captured.

    On the Razorpay path this is how a debit actually finishes: the order and
    payment link go out, the customer authorises on their own device, and this
    turns that into a signed receipt and a settled ledger entry.
    """
    session = _session(session_id)
    if session.intent is None:
        raise HTTPException(status_code=409, detail="no intent in this session")

    before = session.authorizer.ledger.length
    finished = session.authorizer.settle_pending(session.intent, now=session.tick())
    for outcome in finished:
        payload = _outcome_json(outcome)
        payload["label"] = "Settled asynchronously after the customer authorised."
        session.record(payload, outcome.cart, outcome.receipt)

    return {
        "settled": [_outcome_json(o) for o in finished],
        "scope": _scope_json(session.intent, session),
        "ledger_added": _ledger_json(session, since=before),
    }


@app.post("/api/sessions/{session_id}/revoke")
def revoke(session_id: str) -> dict[str, Any]:
    """The subject withdraws authority mid-session."""
    session = _session(session_id)
    if session.intent is None:
        raise HTTPException(status_code=409, detail="nothing to revoke")
    before = session.authorizer.ledger.length
    session.authorizer.revoke(
        session.intent, now=session.tick(), reason="subject revoked from the console"
    )
    return {
        "scope": _scope_json(session.intent, session),
        "ledger_added": _ledger_json(session, since=before),
    }


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str) -> dict[str, Any]:
    session = _session(session_id)
    return {
        "session_id": session_id,
        "intent": session.intent.envelope() if session.intent else None,
        "scope": _scope_json(session.intent, session) if session.intent else None,
        "outcomes": session.outcomes,
        "ledger": _ledger_json(session),
        "chain": _chain_status(session),
    }


def _chain_status(session: Session) -> dict[str, Any]:
    audit = session.authorizer.ledger.audit()
    return {
        "intact": audit is None,
        "length": session.authorizer.ledger.length,
        "head": session.authorizer.ledger.head,
        "break": audit.model_dump(mode="json") if audit else None,
    }


@app.get("/api/sessions/{session_id}/ledger")
def ledger(session_id: str) -> dict[str, Any]:
    """The full ledger, for a first load or a refresh."""
    session = _session(session_id)
    return {"ledger": _ledger_json(session)}


@app.get("/api/sessions/{session_id}/chain")
def chain(session_id: str) -> dict[str, Any]:
    return _chain_status(_session(session_id))


@app.post("/api/sessions/{session_id}/tamper")
def tamper(session_id: str) -> dict[str, Any]:
    """Edit a settled ledger entry directly in SQLite, the way an insider would.

    This exists so the tamper-evidence claim can be checked rather than believed.
    It rewrites the amount on a settled debit -- the single most valuable edit
    someone could make -- and the chain audit names the entry it broke.
    """
    session = _session(session_id)
    ledger = session.authorizer.ledger
    target = next(
        (e for e in ledger.entries() if e.kind is EventKind.DEBIT_SETTLED),
        None,
    ) or next((e for e in ledger.entries() if e.kind is EventKind.INTENT_ISSUED), None)
    if target is None:
        raise HTTPException(status_code=409, detail="nothing settled to tamper with")

    import json

    payload = json.loads(json.dumps(target.payload))
    if target.kind is EventKind.DEBIT_SETTLED:
        payload["receipt"]["body"]["amount_paise"] = 999_00
        what = "rewrote a settled debit from its real amount to ₹999.00"
    else:
        payload["intent"]["body"]["scope"]["max_total_paise"] = 10_000_000
        what = "widened the signed spending ceiling to ₹100,000.00"

    ledger._db.execute(
        "UPDATE ledger SET payload = ? WHERE seq = ?",
        (json.dumps(payload, separators=(",", ":"), sort_keys=True), target.seq),
    )
    ledger._db.commit()

    return {"tampered_seq": target.seq, "what": what, "chain": _chain_status(session)}


@app.get("/api/sessions/{session_id}/ap2")
def ap2_chain(session_id: str) -> dict[str, Any]:
    """The same chain in AP2's vocabulary, W3C-VC shaped.

    Shape-compatible, not certified interop -- the divergences travel inside the
    document rather than being left for someone to discover.
    """
    session = _session(session_id)
    if session.intent is None:
        raise HTTPException(status_code=409, detail="no intent in this session")

    settled = next(
        ((c, r) for c, r in reversed(session.documents) if r is not None), None
    )
    latest = session.documents[-1] if session.documents else None
    source = settled or latest

    cart = receipt = None
    decision = None
    if source is not None:
        cart, receipt = source
        match = next(
            (o for o in session.outcomes if o["cart"]["digest"] == cart.digest), None
        )
        if match is not None:
            decision = {"verdict": match["verdict"], "checks": match["checks"]}

    return to_ap2_chain(
        session.intent,
        cart,
        receipt,
        subject_key=session.subject_key.public,
        decision=decision,
    )


@app.get("/api/sessions/{session_id}/evidence")
def evidence(session_id: str, payment_id: str | None = None) -> dict[str, Any]:
    """Assemble the dispute pack for a settled payment."""
    session = _session(session_id)
    if session.intent is None:
        raise HTTPException(status_code=409, detail="no intent in this session")
    try:
        pack = assemble_evidence(
            session.authorizer.ledger,
            session.authorizer.session_for(session.intent),
            subject_key=session.subject_key.public,
            payment_id=payment_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return pack.model_dump(mode="json")


# --------------------------------------------------------------------------- #
# The built console, when it exists.
#
# Mounted last so it never shadows /api. A source checkout without a build still
# runs the API and the CLI; only the browser view needs `npm run build`.
# --------------------------------------------------------------------------- #

_CONSOLE = Path(__file__).resolve().parents[2] / "console" / "dist"

if _CONSOLE.is_dir():
    app.mount("/", StaticFiles(directory=_CONSOLE, html=True), name="console")
else:  # pragma: no cover - depends on whether the console has been built

    @app.get("/", status_code=503)
    def console_missing(response: Response) -> dict[str, str]:
        """The console is a build artifact and does not ship in the wheel.

        This used to answer 200 with an error message in the body, which tells
        every client the request succeeded, and it advised `make console` --
        useless to somebody who installed the package and has no Makefile.
        """
        response.status_code = 503
        return {
            "detail": (
                "The console has not been built. It ships with the repository, "
                "not with the package: clone the repo and run `make console`. "
                "To use Warrant from an installed package, run `warrant api` for "
                "the authorization service, or import it directly."
            ),
            "service": "warrant api --help",
            "openapi": "/docs",
        }
