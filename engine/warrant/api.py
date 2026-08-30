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

import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .authorize import Authorizer, PendingIntent
from .catalog import PRODUCTS, by_sku
from .chain import EventKind, Ledger
from .crypto import Signature, SigningKey
from .demo import STEPS, UTTERANCE, build_scenario
from .evidence import assemble_evidence
from .interop import to_ap2_chain
from .llm import describe_capability
from .models import CartMandate, DebitReceipt, IntentMandate, LineItem, RailBinding
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

CATALOG: tuple[dict[str, Any], ...] = tuple(p._asdict() for p in PRODUCTS)


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
    intent: IntentMandate | None = None
    pending: PendingIntent | None = None
    clock: int = 0
    outcomes: list[dict[str, Any]] = field(default_factory=list)
    nonces: list[str] = field(default_factory=list)
    """One per submitted cart. A replay re-presents an earlier one."""

    def tick(self, seconds: int = 47) -> int:
        self.clock += seconds
        return self.clock


SESSIONS: dict[str, Session] = {}


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
        "cart_body": outcome.cart.body(),
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


def _ledger_json(session: Session) -> list[dict[str, Any]]:
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
        "default_utterance": UTTERANCE,
        "scripted_steps": [
            {
                "label": step.label,
                "expect": step.expect,
                "teaches": step.teaches,
                "merchant": step.merchant,
                "lines": [{"sku": i.sku, "qty": i.qty} for i in step.items],
                # A step reusing an earlier step's nonce is a replay by construction.
                "replay_of": next(
                    (j + 1 for j, e in enumerate(STEPS[:i]) if e.nonce == step.nonce),
                    None,
                ),
            }
            for i, step in enumerate(STEPS)
        ],
    }


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
    session.pending = session.authorizer.prepare_intent(
        body.utterance, subject="user_priya", agent="agent_claude", now=session.clock
    )
    SESSIONS[session_id] = session

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

    if body.replay_of is not None:
        if body.replay_of > len(session.nonces):
            raise HTTPException(
                status_code=400,
                detail=f"cannot replay cart {body.replay_of}; only {len(session.nonces)} submitted",
            )
        nonce = session.nonces[body.replay_of - 1]
    else:
        nonce = f"{session_id}-cart-{len(session.nonces) + 1}"
    session.nonces.append(nonce)

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
    session.outcomes.append(payload)

    return {
        "outcome": payload,
        "scope": _scope_json(session.intent, session),
        "ledger": _ledger_json(session),
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

    finished = session.authorizer.settle_pending(session.intent, now=session.tick())
    for outcome in finished:
        payload = _outcome_json(outcome)
        payload["label"] = "Settled asynchronously after the customer authorised."
        session.outcomes.append(payload)

    return {
        "settled": [_outcome_json(o) for o in finished],
        "scope": _scope_json(session.intent, session),
        "ledger": _ledger_json(session),
    }


@app.post("/api/sessions/{session_id}/revoke")
def revoke(session_id: str) -> dict[str, Any]:
    """The subject withdraws authority mid-session."""
    session = _session(session_id)
    if session.intent is None:
        raise HTTPException(status_code=409, detail="nothing to revoke")
    session.authorizer.revoke(
        session.intent, now=session.tick(), reason="subject revoked from the console"
    )
    return {"scope": _scope_json(session.intent, session), "ledger": _ledger_json(session)}


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
        (o for o in reversed(session.outcomes) if o.get("receipt")), None
    )
    last = session.outcomes[-1] if session.outcomes else None
    source = settled or last

    cart = receipt = None
    decision = None
    if source is not None:
        # Rebuild from the signed body and re-attach the signature. Signatures are
        # excluded from body(), so validating the body alone produces a document
        # that reports itself unsigned -- which would understate the integrity of
        # the very thing this export exists to demonstrate.
        cart = CartMandate.model_validate(source["cart_body"])
        if source["cart"].get("signature"):
            cart = cart.model_copy(
                update={"signature": Signature.from_dict(source["cart"]["signature"])}
            )
        decision = {"verdict": source["verdict"], "checks": source["checks"]}
        if source.get("receipt"):
            receipt = DebitReceipt.model_validate(source["receipt"]["body"])
            if source["receipt"].get("signature"):
                receipt = receipt.model_copy(
                    update={
                        "signature": Signature.from_dict(source["receipt"]["signature"])
                    }
                )

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

    @app.get("/")
    def console_missing() -> dict[str, str]:
        return {
            "detail": "Console not built. Run `make console`, or use the API directly.",
            "api": "/docs",
        }
