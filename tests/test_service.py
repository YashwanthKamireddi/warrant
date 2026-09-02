"""The mountable service, driven over HTTP.

These use a real ASGI client rather than calling the handlers, because the
things worth pinning down here are HTTP-shaped: which status code a refusal
carries, whether a refusal still explains itself, and whether a probe reports a
broken dependency instead of cheerfully returning 200.
"""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from warrant import Warrant
from warrant.merchants import MerchantRecord, MerchantRegistry
from warrant.models import Scope
from warrant.service import (
    NO_AUTH,
    ApiKeyAuth,
    PermissionStore,
    create_app,
    warrant_router,
)

NOW = int(time.time())

GROCER = MerchantRegistry((
    MerchantRecord(
        "acme-grocers", "5411", "Grocery stores and supermarkets",
        frozenset({"grocery", "food_beverage"}),
    ),
))

SCOPE = {
    "merchants": ["acme-grocers"],
    "categories": ["food_beverage"],
    "max_total_paise": 100_000,
    "max_per_txn_paise": 50_000,
    "max_txns": 3,
    "not_before": NOW,
    "expires_at": NOW + 7200,
}

SANDWICH = {"sku": "sandwich", "category": "food_beverage", "qty": 1, "unit_paise": 24_000}
CABLE = {"sku": "cable", "category": "electronics", "qty": 1, "unit_paise": 29_900}


KEY = "test-key-that-is-long-enough-to-be-real"


@pytest.fixture
def client():
    """Authenticated by default, because everything else here is about what a
    caller who is allowed in can do."""
    with (
        Warrant(merchants=GROCER) as w,
        TestClient(create_app(w, auth=ApiKeyAuth([KEY]))) as c,
    ):
        c.headers["authorization"] = f"Bearer {KEY}"
        yield c


def permit(client, **overrides) -> str:
    body = {"utterance": "lunch for the team", "scope": SCOPE, **overrides}
    response = client.post("/warrant/permissions", json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"]


# ------------------------------------------------------------------- probes


def test_health_answers_while_the_process_can_serve(client):
    r = client.get("/warrant/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_ready_reports_what_it_actually_checked(client):
    r = client.get("/warrant/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["merchants"] == 1
    assert body["ledger_head"]


def test_ready_fails_when_the_ledger_is_gone_rather_than_returning_ok():
    """A process with an unreachable ledger is alive and must not get traffic."""
    warrant = Warrant(merchants=GROCER)
    with TestClient(create_app(warrant, auth=NO_AUTH)) as client:
        warrant.ledger.close()
        r = client.get("/warrant/ready")
        assert r.status_code == 503
        assert "ledger unavailable" in r.json()["detail"]
        # liveness is a different question and still answers
        assert client.get("/warrant/health").status_code == 200


# -------------------------------------------------------------- permissions


def test_creating_a_permission_returns_what_the_person_would_approve(client):
    r = client.post(
        "/warrant/permissions",
        json={"utterance": "lunch for the team", "scope": SCOPE},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["id"].startswith("im_")
    assert "1,000" in body["approval_prompt"]
    assert body["scope"]["max_total_paise"] == 100_000


def test_the_response_says_where_the_signing_key_lives(client):
    """In-process key custody is fine for an evaluation and wrong for production.

    Saying so in the payload means nobody has to read the source to find out.
    """
    r = client.post(
        "/warrant/permissions",
        json={"utterance": "lunch", "scope": SCOPE},
    )
    assert r.json()["key_custody"] == "in_process"


def test_an_unknown_permission_is_404_not_an_empty_decision(client):
    r = client.post(
        "/warrant/permissions/im_nope/check",
        json={"merchant": "acme-grocers", "items": [SANDWICH]},
    )
    assert r.status_code == 404
    assert "no permission" in r.json()["detail"]


def test_a_malformed_scope_is_422_not_500(client):
    r = client.post(
        "/warrant/permissions",
        json={"utterance": "lunch", "scope": {**SCOPE, "max_total_paise": -1}},
    )
    assert r.status_code == 422


def test_an_empty_basket_is_rejected_by_the_schema(client):
    pid = permit(client)
    r = client.post(
        f"/warrant/permissions/{pid}/check",
        json={"merchant": "acme-grocers", "items": []},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------- decisions


def test_check_answers_200_even_when_the_answer_is_no(client):
    """The caller asked a question. A 4xx would confuse 'blocked' with 'malformed'."""
    pid = permit(client)
    r = client.post(
        f"/warrant/permissions/{pid}/check",
        json={"merchant": "acme-grocers", "items": [CABLE]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["allowed"] is False
    assert body["verdict"] == "block"
    assert any("electronics" in reason for reason in body["reasons"])


def test_check_spends_nothing_over_http(client):
    pid = permit(client)
    for _ in range(4):
        client.post(
            f"/warrant/permissions/{pid}/check",
            json={"merchant": "acme-grocers", "items": [SANDWICH]},
        )
    # max_txns is 3; if check() had consumed attempts these would fail.
    for _ in range(3):
        r = client.post(
            f"/warrant/permissions/{pid}/spend",
            json={"merchant": "acme-grocers", "items": [SANDWICH]},
        )
        assert r.status_code == 200, r.text


def test_spend_allows_and_settles(client):
    pid = permit(client)
    r = client.post(
        f"/warrant/permissions/{pid}/spend",
        json={"merchant": "acme-grocers", "items": [SANDWICH]},
    )
    assert r.status_code == 200
    assert r.json()["settled"] is True


def test_a_refused_spend_is_403_and_still_explains_itself(client):
    """An agent that must guess why it was refused will guess wrong."""
    pid = permit(client)
    r = client.post(
        f"/warrant/permissions/{pid}/spend",
        json={"merchant": "acme-grocers", "items": [CABLE]},
    )
    assert r.status_code == 403
    detail = r.json()["detail"]
    assert detail["verdict"] == "block"
    assert detail["reasons"]
    assert detail["checks"]


def test_revoking_stops_later_spending(client):
    pid = permit(client)
    assert client.post(
        f"/warrant/permissions/{pid}/spend",
        json={"merchant": "acme-grocers", "items": [SANDWICH]},
    ).status_code == 200

    assert client.post(f"/warrant/permissions/{pid}/revoke").status_code == 204

    after = client.post(
        f"/warrant/permissions/{pid}/spend",
        json={"merchant": "acme-grocers", "items": [SANDWICH]},
    )
    assert after.status_code == 403


def test_evidence_is_available_after_a_settled_purchase(client):
    pid = permit(client)
    client.post(
        f"/warrant/permissions/{pid}/spend",
        json={"merchant": "acme-grocers", "items": [SANDWICH]},
    )
    r = client.get(f"/warrant/permissions/{pid}/evidence")
    assert r.status_code == 200


# -------------------------------------------------------------------- store


def test_the_store_is_bounded_and_evicts_oldest_first():
    """An unbounded dict keyed by user input is a memory leak with a handler."""
    store = PermissionStore(capacity=2)
    with Warrant(merchants=GROCER) as w:
        first, second, third = (
            w.permit(f"lunch {n}", scope=Scope(**SCOPE))
            for n in range(3)
        )
        for p in (first, second, third):
            store.put(p)

        assert len(store) == 2
        store.get(third.id)
        store.get(second.id)
        with pytest.raises(HTTPException) as evicted:
            store.get(first.id)
        assert evicted.value.status_code == 404


# ------------------------------------------------------------------ mounting


def test_the_router_mounts_into_an_existing_app_without_taking_it_over():
    """A company mounts this beside their own routes, not instead of them."""
    app = FastAPI()

    @app.get("/orders")
    def orders() -> dict[str, str]:
        return {"theirs": "untouched"}

    with Warrant(merchants=GROCER) as w:
        app.include_router(warrant_router(w, auth=NO_AUTH))
        with TestClient(app) as client:
            assert client.get("/orders").json() == {"theirs": "untouched"}
            assert client.get("/warrant/health").status_code == 200


def test_two_routers_in_one_process_are_two_independent_deployments():
    """No module-level state: one tenant's permissions are not another's."""
    app = FastAPI()
    with Warrant(merchants=GROCER) as a, Warrant(merchants=GROCER) as b:
        app.include_router(warrant_router(a, auth=NO_AUTH, prefix="/tenant-a"))
        app.include_router(warrant_router(b, auth=NO_AUTH, prefix="/tenant-b"))
        with TestClient(app) as client:
            created = client.post(
                "/tenant-a/permissions",
                json={"utterance": "lunch", "scope": SCOPE},
            ).json()["id"]

            mine = client.post(
                f"/tenant-a/permissions/{created}/check",
                json={"merchant": "acme-grocers", "items": [SANDWICH]},
            )
            theirs = client.post(
                f"/tenant-b/permissions/{created}/check",
                json={"merchant": "acme-grocers", "items": [SANDWICH]},
            )

            assert mine.status_code == 200
            assert theirs.status_code == 404


# --------------------------------------------------------------------- auth


def test_a_router_with_no_authentication_configured_refuses_to_exist(monkeypatch):
    """Reachable must not mean usable because an argument was forgotten."""
    monkeypatch.delenv("WARRANT_API_KEYS", raising=False)
    with (
        Warrant(merchants=GROCER) as w,
        pytest.raises(RuntimeError, match="needs authentication"),
    ):
        warrant_router(w)


def test_running_open_is_possible_and_has_to_be_spelled(monkeypatch):
    monkeypatch.delenv("WARRANT_API_KEYS", raising=False)
    with Warrant(merchants=GROCER) as w:
        router = warrant_router(w, auth=NO_AUTH)
        assert router is not None


def test_keys_are_picked_up_from_the_environment(monkeypatch):
    monkeypatch.setenv("WARRANT_API_KEYS", KEY)
    with Warrant(merchants=GROCER) as w, TestClient(create_app(w)) as c:
        anonymous = c.post(
            "/warrant/permissions", json={"utterance": "x", "scope": SCOPE}
        )
        assert anonymous.status_code == 401

        allowed = c.post(
            "/warrant/permissions",
            json={"utterance": "x", "scope": SCOPE},
            headers={"authorization": f"Bearer {KEY}"},
        )
        assert allowed.status_code == 201


def test_an_unauthenticated_caller_cannot_mint_or_spend():
    with (
        Warrant(merchants=GROCER) as w,
        TestClient(create_app(w, auth=ApiKeyAuth([KEY]))) as c,
    ):
        for method, path in (
            ("post", "/warrant/permissions"),
            ("post", "/warrant/permissions/im_x/check"),
            ("post", "/warrant/permissions/im_x/spend"),
            ("post", "/warrant/permissions/im_x/revoke"),
            ("get", "/warrant/permissions/im_x/evidence"),
        ):
            kwargs = (
                {"json": {"merchant": "m", "items": [SANDWICH]}}
                if method == "post"
                else {}
            )
            r = getattr(c, method)(path, **kwargs)
            assert r.status_code == 401, f"{path} was reachable without a token"
            assert r.headers["www-authenticate"] == "Bearer"


def test_the_probes_are_never_guarded():
    """An orchestrator holds no credential. A probe that 401s reads as dead."""
    with (
        Warrant(merchants=GROCER) as w,
        TestClient(create_app(w, auth=ApiKeyAuth([KEY]))) as c,
    ):
        assert c.get("/warrant/health").status_code == 200
        assert c.get("/warrant/ready").status_code == 200


def test_a_wrong_token_is_rejected_and_tells_the_caller_nothing_about_why():
    with (
        Warrant(merchants=GROCER) as w,
        TestClient(create_app(w, auth=ApiKeyAuth([KEY]))) as c,
    ):
        for header in (
            "Bearer wrong-key-entirely-but-long-enough",
            f"Bearer {KEY[:-1]}",          # one character off
            f"Basic {KEY}",                # right secret, wrong scheme
            KEY,                           # no scheme at all
            "",
        ):
            r = c.post(
                "/warrant/permissions",
                json={"utterance": "x", "scope": SCOPE},
                headers={"authorization": header},
            )
            assert r.status_code == 401
            # The response must not confirm any part of a real key.
            assert KEY not in r.text


def test_a_key_too_short_to_be_worth_having_is_refused():
    with pytest.raises(ValueError, match="16 characters"):
        ApiKeyAuth(["short"])


def test_an_empty_key_list_is_refused_rather_than_silently_allowing_everyone():
    with pytest.raises(ValueError, match="at least one key"):
        ApiKeyAuth([])
    with pytest.raises(ValueError, match="at least one key"):
        ApiKeyAuth(["", "  "])
