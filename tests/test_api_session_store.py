"""The session store is bounded, and responses do not ship what nobody reads.

Two defects found by auditing the API rather than the engine: sessions
accumulated for the lifetime of the process, each owning a SQLite ledger, and
every cart response carried a second serialised copy of the cart so that one
server-side endpoint could rebuild it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from warrant import api
from warrant.api import MAX_SESSIONS, SESSIONS, app


@pytest.fixture(autouse=True)
def clean_store():
    SESSIONS.clear()
    yield
    SESSIONS.clear()


@pytest.fixture
def client():
    return TestClient(app)


def _session_with_cart(client) -> str:
    sid = client.post("/api/sessions", json={}).json()["session_id"]
    client.post(f"/api/sessions/{sid}/approve", json={"approved": True})
    client.post(
        f"/api/sessions/{sid}/carts",
        json={"merchant": "zomato", "lines": [{"sku": "chai-6", "qty": 6}]},
    )
    return sid


# -- the store is bounded --------------------------------------------------- #


def test_sessions_do_not_accumulate_without_limit(client):
    for _ in range(MAX_SESSIONS + 12):
        client.post("/api/sessions", json={})
    assert len(SESSIONS) <= MAX_SESSIONS


def test_the_oldest_session_is_evicted_first(client):
    first = client.post("/api/sessions", json={}).json()["session_id"]
    for _ in range(MAX_SESSIONS):
        client.post("/api/sessions", json={})
    assert first not in SESSIONS
    assert client.get(f"/api/sessions/{first}").status_code == 404


def test_a_recent_session_survives_eviction(client):
    for _ in range(MAX_SESSIONS - 1):
        client.post("/api/sessions", json={})
    recent = client.post("/api/sessions", json={}).json()["session_id"]
    client.post("/api/sessions", json={})
    assert recent in SESSIONS


def test_an_evicted_ledger_is_closed_rather_than_dropped(client, monkeypatch):
    """It owns a SQLite connection. Dropping the reference leaks the handle."""
    closed: list[str] = []
    original = api.Ledger.close

    def tracking_close(self):
        closed.append("closed")
        original(self)

    monkeypatch.setattr(api.Ledger, "close", tracking_close)
    for _ in range(MAX_SESSIONS + 3):
        client.post("/api/sessions", json={})
    assert len(closed) >= 3


# -- responses carry only what the client reads ----------------------------- #


def test_a_cart_response_does_not_ship_a_second_copy_of_the_cart(client):
    sid = client.post("/api/sessions", json={}).json()["session_id"]
    client.post(f"/api/sessions/{sid}/approve", json={"approved": True})
    body = client.post(
        f"/api/sessions/{sid}/carts",
        json={"merchant": "zomato", "lines": [{"sku": "chai-6", "qty": 6}]},
    ).json()
    assert "cart_body" not in body["outcome"]
    assert body["outcome"]["cart"]["digest"]


def test_the_ap2_export_still_works_without_the_wire_copy(client):
    sid = _session_with_cart(client)
    chain = client.get(f"/api/sessions/{sid}/ap2").json()
    kinds = [c["type"][1] for c in chain["verifiableCredential"]]
    assert kinds == ["IntentMandate", "CartMandate", "PaymentMandate"]


def test_the_ap2_export_keeps_the_authorizers_signatures(client):
    sid = _session_with_cart(client)
    chain = client.get(f"/api/sessions/{sid}/ap2").json()
    for credential in chain["verifiableCredential"]:
        assert credential["proof"] is not None


def test_the_ap2_export_carries_the_decision_for_that_cart(client):
    sid = _session_with_cart(client)
    chain = client.get(f"/api/sessions/{sid}/ap2").json()
    assert chain["warrant:evaluation"]["verdict"] == "allow"


def test_an_unknown_session_is_a_404_not_a_crash(client):
    assert client.get("/api/sessions/sess_nope").status_code == 404
    assert client.get("/api/sessions/sess_nope/ap2").status_code == 404


# -- responses do not re-send what the client already has ------------------- #


def test_a_write_returns_only_the_entries_it_appended(client):
    sid = client.post("/api/sessions", json={}).json()["session_id"]
    client.post(f"/api/sessions/{sid}/approve", json={"approved": True})

    first = client.post(
        f"/api/sessions/{sid}/carts",
        json={"merchant": "zomato", "lines": [{"sku": "chai-6", "qty": 6}]},
    ).json()
    second = client.post(
        f"/api/sessions/{sid}/carts",
        json={"merchant": "zomato", "lines": [{"sku": "samosa-2", "qty": 1}]},
    ).json()

    assert "ledger" not in first
    first_seqs = {e["seq"] for e in first["ledger_added"]}
    second_seqs = {e["seq"] for e in second["ledger_added"]}
    assert first_seqs and second_seqs
    assert first_seqs.isdisjoint(second_seqs)


def test_response_size_does_not_grow_with_session_history(client):
    """A cart_allowed entry is over 3KB. Re-sending every prior one on each write
    made a five-basket session carry tens of kilobytes it already had."""
    sid = client.post("/api/sessions", json={}).json()["session_id"]
    client.post(f"/api/sessions/{sid}/approve", json={"approved": True})

    sizes = []
    for _ in range(3):
        response = client.post(
            f"/api/sessions/{sid}/carts",
            json={"merchant": "zomato", "lines": [{"sku": "chai-6", "qty": 1}]},
        )
        sizes.append(len(response.content))

    # Later writes must not be dramatically larger than the first.
    assert max(sizes) < sizes[0] * 1.6


def test_the_full_ledger_is_still_available_from_its_own_endpoint(client):
    sid = _session_with_cart(client)
    entries = client.get(f"/api/sessions/{sid}/ledger").json()["ledger"]
    kinds = [e["kind"] for e in entries]
    assert "intent_issued" in kinds
    assert "debit_settled" in kinds
