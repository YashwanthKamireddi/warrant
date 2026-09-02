"""Warrant as something you mount, not something you fork.

    from fastapi import FastAPI
    from warrant import Warrant
    from warrant.service import warrant_router

    app = FastAPI()
    app.include_router(warrant_router(Warrant(merchants="warrant.toml")))

That is the whole integration. Your agent calls ``POST /warrant/permissions``
once when the person approves, then ``POST /warrant/permissions/{id}/spend``
for every basket, and gets a 403 with reasons when the basket is outside what
was signed.

This is deliberately separate from ``warrant.api``, which serves the console: a
demo API grows endpoints for tampering with its own ledger and replaying
scripted baskets, and none of that belongs in something a company mounts.

An honest note about keys. In a real deployment the subject's signing key lives
on the subject's device and this service never sees it -- it receives a signed
mandate and verifies it. The in-process store below keeps the whole
:class:`~warrant.client.Permission`, private half included, because generating
a key here is what lets a first run work without a device enrolment flow. That
is right for an evaluation and wrong for production, and
:func:`warrant_router` says so in its own response payload rather than only in
a comment nobody reads.
"""

from __future__ import annotations

import hmac
import os
from collections import OrderedDict
from collections.abc import Callable, Iterable
from threading import Lock
from typing import Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .client import ItemLike, Permission, Warrant, WarrantDecision
from .models import Scope, Verdict

__all__ = [
    "NO_AUTH",
    "ApiKeyAuth",
    "PermissionStore",
    "create_app",
    "warrant_router",
]

#: Passed as ``auth`` to run with no authentication at all. It has to be typed:
#: a service that mints spending permissions must not become open to the
#: internet because somebody forgot an argument.
NO_AUTH = "none"


class ApiKeyAuth:
    """Bearer tokens, compared in constant time.

    Deliberately small. This is the floor -- enough that the service is not open
    the moment it is reachable -- and anyone with an identity provider should
    pass their own callable instead. What it does not do is as important as what
    it does: it never logs a key, never echoes one back, and never reports
    whether a rejected key was close to a real one.
    """

    def __init__(self, keys: Iterable[str]) -> None:
        self._keys = tuple(k for k in (k.strip() for k in keys) if k)
        if not self._keys:
            raise ValueError(
                "ApiKeyAuth needs at least one key. Pass auth=NO_AUTH to run "
                "without authentication."
            )
        if any(len(k) < 16 for k in self._keys):
            raise ValueError(
                "an API key shorter than 16 characters is not worth having; "
                "use secrets.token_urlsafe(32)"
            )

    @classmethod
    def from_env(cls, var: str = "WARRANT_API_KEYS") -> ApiKeyAuth | None:
        """Read comma-separated keys from the environment, or None if unset."""
        raw = os.environ.get(var, "")
        keys = [k for k in raw.split(",") if k.strip()]
        return cls(keys) if keys else None

    def __call__(self, request: Request) -> None:
        header = request.headers.get("authorization", "")
        scheme, _, credential = header.partition(" ")
        # compare_digest on every key rather than returning at the first match,
        # so a rejection takes the same time whichever key it was measured
        # against.
        ok = scheme.lower() == "bearer" and any(
            hmac.compare_digest(credential, key) for key in self._keys
        )
        if not ok:
            raise HTTPException(
                401,
                detail="a valid bearer token is required",
                headers={"WWW-Authenticate": "Bearer"},
            )

#: How many live permissions a single process keeps. Old ones are evicted
#: oldest-first: a permission whose window has expired cannot authorise anything
#: anyway, and an unbounded dict keyed by user input is a memory leak with a
#: request handler attached.
DEFAULT_CAPACITY = 512


class PermissionStore:
    """Bounded, thread-safe, oldest-out. Not durable, and does not pretend to be.

    A process restart loses the permissions it was holding. That is survivable
    because the ledger is the durable record and a permission is re-signable;
    it is not survivable silently, so :meth:`get` raises a 404 rather than
    inventing an empty one.
    """

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        self._items: OrderedDict[str, Permission] = OrderedDict()
        self._capacity = capacity
        self._lock = Lock()

    def put(self, permission: Permission) -> None:
        with self._lock:
            self._items[permission.id] = permission
            self._items.move_to_end(permission.id)
            while len(self._items) > self._capacity:
                self._items.popitem(last=False)

    def get(self, permission_id: str) -> Permission:
        with self._lock:
            permission = self._items.get(permission_id)
            if permission is None:
                raise HTTPException(
                    404,
                    detail=(
                        f"no permission {permission_id}. It may have expired out of "
                        "this process's store, which holds the most recent "
                        f"{self._capacity}."
                    ),
                )
            self._items.move_to_end(permission_id)
            return permission

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


# --------------------------------------------------------------------- wire


class Item(BaseModel):
    """One basket line, as an agent would send it."""

    model_config = ConfigDict(extra="forbid")

    sku: str
    qty: int = Field(gt=0)
    unit_paise: int = Field(gt=0)
    name: str | None = None
    # Absent means `other`, which no narrow mandate permits. Inferring a
    # category from a product name is exactly the mistake this project exists
    # to stop, so the default is the one that fails closed.
    category: str = "other"


class PermitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    utterance: str
    scope: Scope | None = None
    subject: str = "user"
    agent: str = "agent"


class BasketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant: str
    items: list[Item] = Field(min_length=1)


class DecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Verdict
    allowed: bool
    needs_approval: bool
    reasons: list[str]
    settled: bool
    cart_id: str
    total_paise: int
    checks: list[dict[str, Any]]


class PermissionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    approval_prompt: str
    scope: Scope
    key_custody: Literal["in_process", "device"]
    """Where the subject's signing key lives.

    ``in_process`` means this service generated it, which is fine for an
    evaluation and is not how a deployment should run. It is in the response so
    nobody has to read the source to find out.
    """


def _as_items(items: list[Item]) -> list[ItemLike]:
    return [
        {
            "sku": i.sku,
            "name": i.name or i.sku,
            "category": i.category,
            "qty": i.qty,
            "unit_paise": i.unit_paise,
        }
        for i in items
    ]


def _as_response(decision: WarrantDecision) -> DecisionResponse:
    return DecisionResponse(
        verdict=decision.verdict,
        allowed=decision.allowed,
        needs_approval=decision.needs_approval,
        reasons=list(decision.reasons),
        settled=decision.settled,
        cart_id=decision.cart.id,
        total_paise=decision.cart.total_paise,
        checks=[
            {"rule": c.rule, "status": c.status.value, "detail": c.detail}
            for c in decision.decision.checks
        ],
    )


def warrant_router(
    warrant: Warrant,
    *,
    auth: Callable[[Request], Any] | str | None = None,
    prefix: str = "/warrant",
    store: PermissionStore | None = None,
) -> APIRouter:
    """A router any FastAPI app can mount.

    Holds no global state: the Warrant and the store are captured here, so two
    routers in one process are two independent deployments.

    ``auth`` guards every endpoint that can mint or spend a permission. Omit it
    and WARRANT_API_KEYS is used; with neither, construction raises. A service
    that authorises payments should not become reachable-means-usable because an
    argument was forgotten, so running open is possible and has to be spelled:
    ``auth=NO_AUTH``.

    The health and readiness probes are never guarded. An orchestrator cannot
    hold a credential, and a probe that 401s is a probe that reports the process
    as dead.
    """
    if auth is None:
        auth = ApiKeyAuth.from_env()
    if auth is None:
        raise RuntimeError(
            "warrant_router needs authentication. Set WARRANT_API_KEYS, pass "
            "auth=ApiKeyAuth([...]) or your own callable, or pass auth=NO_AUTH "
            "to run open on purpose."
        )
    guard: list[Any] = [] if auth == NO_AUTH else [Depends(auth)]

    router = APIRouter(prefix=prefix, tags=["warrant"])
    store = store or PermissionStore()

    @router.get("/health")
    def health() -> dict[str, Any]:
        """Liveness. Answers as long as the process can serve at all."""
        return {"status": "ok", "version": __version__}

    @router.get("/ready")
    def ready() -> dict[str, Any]:
        """Readiness. Separate from liveness because they fail for different
        reasons: a process with an unreachable ledger is alive and must not be
        sent traffic."""
        try:
            # `head` is a property, and reading it round-trips to SQLite, which
            # is exactly the dependency a readiness probe is meant to exercise.
            head = warrant.ledger.head
        except Exception as exc:  # noqa: BLE001 - report, never crash a probe
            raise HTTPException(503, detail=f"ledger unavailable: {exc}") from exc
        return {
            "status": "ready",
            "merchants": len(warrant.registry),
            "permissions_held": len(store),
            "ledger_head": head,
        }

    @router.post(
        "/permissions",
        response_model=PermissionResponse,
        status_code=201,
        dependencies=guard,
    )
    def create_permission(body: PermitRequest) -> PermissionResponse:
        """Sign what the person approved. Everything else is checked against it."""
        try:
            permission = warrant.permit(
                body.utterance,
                scope=body.scope,
                subject=body.subject,
                agent=body.agent,
            )
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        store.put(permission)
        return PermissionResponse(
            id=permission.id,
            approval_prompt=permission.approval_prompt,
            scope=permission.intent.scope,
            key_custody="in_process",
        )

    @router.post(
        "/permissions/{permission_id}/check",
        response_model=DecisionResponse,
        dependencies=guard,
    )
    def check(permission_id: str, body: BasketRequest) -> DecisionResponse:
        """Would this basket be allowed? Spends nothing, records nothing.

        Always 200, including for a refusal: the caller asked a question and got
        an answer. Refusing to answer with a 4xx would make "would this be
        blocked?" indistinguishable from "your request was malformed".
        """
        permission = store.get(permission_id)
        return _as_response(
            warrant.check(permission, body.merchant, _as_items(body.items))
        )

    @router.post(
        "/permissions/{permission_id}/spend",
        response_model=DecisionResponse,
        dependencies=guard,
    )
    def spend(permission_id: str, body: BasketRequest) -> DecisionResponse:
        """Decide, and place the debit if it clears.

        A refusal is a 403 carrying the same body a 200 would: an agent that has
        to parse a status code to find out why it was refused will guess, and an
        agent guessing at authorization is the problem.
        """
        permission = store.get(permission_id)
        decision = warrant.spend(permission, body.merchant, _as_items(body.items))
        payload = _as_response(decision)
        if decision.allowed:
            return payload
        raise HTTPException(
            status_code=403 if decision.verdict is Verdict.BLOCK else 409,
            detail=payload.model_dump(mode="json"),
        )

    @router.post("/permissions/{permission_id}/revoke", status_code=204, dependencies=guard)
    def revoke(permission_id: str) -> None:
        """Stop this permission being spendable. Recorded in the ledger."""
        warrant.revoke(store.get(permission_id))

    @router.get("/permissions/{permission_id}/evidence", dependencies=guard)
    def evidence(permission_id: str) -> dict[str, Any]:
        """What a merchant files when a customer disputes one of these charges."""
        permission = store.get(permission_id)
        try:
            return warrant.evidence(permission).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(404, detail=str(exc)) from exc

    return router


def create_app(warrant: Warrant | None = None, **kwargs: Any) -> FastAPI:
    """A standalone service, for anyone who does not already have an app."""
    app = FastAPI(
        title="Warrant",
        version=__version__,
        description="An authorization layer for agent-initiated payments.",
    )
    app.include_router(warrant_router(warrant or Warrant(), **kwargs))
    return app
