"""The console against a catalogue that is not the bundled one.

The scripted run named skus straight out of the bundled products, so a console
started with WARRANT_CATALOG set asked a grocer for `chai-6`. Worse, the pinned
permission still said zomato, so the console signed a mandate for a merchant
none of its own products belonged to. Everything it showed contradicted
everything else it showed.

These drive the whole scripted run against both catalogues and assert the
verdicts, because "the console is configurable" is a claim about outcomes, not
about whether the file parses.
"""

from __future__ import annotations

import pathlib

import pytest
from fastapi.testclient import TestClient

from warrant.catalog import Catalog, bundled_catalog, teaching_roles, use_catalog
from warrant.merchants import MerchantRegistry, bundled_registry, use_registry

ROOT = pathlib.Path(__file__).resolve().parents[1]

EXPECTED = ["allow", "block", "block", "block", "escalate"]


@pytest.fixture(params=["bundled", "example"])
def configured(request):
    """Run the body once per catalogue, restoring the process afterwards."""
    if request.param == "bundled":
        catalog, registry = bundled_catalog(), bundled_registry()
    else:
        catalog = Catalog.from_file(ROOT / "catalog.example.toml")
        registry = MerchantRegistry.from_file(ROOT / "warrant.example.toml")

    previous_catalog = use_catalog(catalog)
    previous_registry = use_registry(registry)
    try:
        # api.py reads the active catalogue at import for its CATALOG constant,
        # so it is reloaded here rather than imported once at module scope.
        import importlib

        from warrant import api

        importlib.reload(api)
        yield request.param, api
    finally:
        use_catalog(previous_catalog)
        use_registry(previous_registry)
        import importlib

        from warrant import api as restored

        importlib.reload(restored)


def test_the_scripted_run_reaches_every_verdict_on_either_catalogue(configured):
    name, api = configured
    with TestClient(api.app) as client:
        meta = client.get("/api/meta").json()
        steps = meta["scripted_steps"]
        assert len(steps) == 5, f"{name}: built {len(steps)} steps"

        session = client.post(
            "/api/sessions", json={"utterance": "lunch for the team", "rail": "simulated"}
        ).json()
        sid = session["session_id"]

        # The permission must be for a merchant this catalogue actually sells at.
        merchants = set(session["pending"]["scope"]["merchants"])
        catalogue_merchants = {p["merchant"] for p in meta["catalog"]}
        assert merchants & catalogue_merchants, (
            f"{name}: permission is for {merchants}, catalogue sells at "
            f"{catalogue_merchants}"
        )

        client.post(f"/api/sessions/{sid}/approve", json={})

        verdicts = []
        for step in steps:
            body = {
                "merchant": step["merchant"],
                "lines": step["lines"],
                "cosign": False,
                "replay_of": step.get("replay_of"),
            }
            response = client.post(f"/api/sessions/{sid}/carts", json=body)
            assert response.status_code == 200, f"{name}: {step['label']} -> {response.text}"
            outcome = response.json()["outcome"]
            verdicts.append(outcome.get("verdict") or outcome["decision"]["verdict"])

        assert verdicts == EXPECTED, f"{name}: {verdicts}"


def test_every_step_asks_for_a_sku_the_catalogue_has(configured):
    """The failure that started this: a step naming a product nobody sells."""
    name, api = configured
    with TestClient(api.app) as client:
        meta = client.get("/api/meta").json()
        known = {p["sku"] for p in meta["catalog"]}
        for step in meta["scripted_steps"]:
            for line in step["lines"]:
                assert line["sku"] in known, f"{name}: {step['label']} wants {line['sku']}"


def test_a_catalogue_with_no_injection_omits_that_step_rather_than_faking_one():
    """A demonstration missing a case is honest. Inventing one is not."""
    plain = Catalog.from_mapping({"product": [
        {"sku": "a", "name": "Bread", "category": "food_beverage",
         "unit_paise": 4_000, "merchant": "m"},
        {"sku": "b", "name": "Cable", "category": "electronics",
         "unit_paise": 9_000, "merchant": "m"},
    ]})
    roles = teaching_roles(
        plain, merchant="m", permitted=frozenset({"food_beverage"}), step_up_paise=50_000
    )

    assert "injection" not in roles
    assert "injection_in_scope" not in roles
    assert roles["in_scope"].sku == "a"
    assert roles["wrong_category"].sku == "b"


def test_the_blockable_injection_is_the_one_that_fails_on_a_bound():
    """The lesson is 'refused on a bound', not 'the payload was spotted'.

    Choosing the subtle in-scope injection made that step allow -- the right
    verdict for that product and the wrong lesson for that step -- and the extra
    purchase then exhausted the mandate's transaction count and broke the step
    after it.
    """
    roles = teaching_roles(
        bundled_catalog(),
        merchant="zomato",
        permitted=frozenset({"food_beverage"}),
        step_up_paise=50_000,
    )

    assert roles["injection"].category not in {"food_beverage"}
    assert roles["injection_in_scope"].category == "food_beverage"
