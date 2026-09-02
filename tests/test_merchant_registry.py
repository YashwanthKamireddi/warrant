"""The merchant registry as configuration rather than as source.

Nobody adopting this runs an Indian food-delivery marketplace by coincidence.
The bundled records exist so the demo runs; the product is the registry being
something you supply. These tests hold that boundary: a supplied registry wins,
a bad one is refused loudly, and an unknown merchant fails closed.
"""

from __future__ import annotations

import pytest

from warrant.gate import MandateState, evaluate
from warrant.merchants import (
    MerchantRecord,
    MerchantRegistry,
    active_registry,
    bundled_registry,
    load_registry,
    use_registry,
)
from warrant.models import Verdict

GROCER = MerchantRecord(
    "acme-grocers", "5411", "Grocery stores and supermarkets",
    frozenset({"grocery", "food_beverage"}),
)

TOML = """
[[merchant]]
id = "acme-grocers"
mcc = "5411"
description = "Grocery stores and supermarkets"
categories = ["grocery", "food_beverage"]

[[merchant]]
id = "northwind-electronics"
mcc = "5732"
description = "Electronics stores"
categories = ["electronics"]
"""


# ------------------------------------------------------------- construction


def test_a_registry_is_built_from_a_file_anyone_can_write(tmp_path):
    path = tmp_path / "warrant.toml"
    path.write_text(TOML)

    registry = MerchantRegistry.from_file(path)

    assert len(registry) == 2
    assert registry.get("acme-grocers").mcc == "5411"
    assert registry.assigned_categories("northwind-electronics") == frozenset({"electronics"})


def test_a_merchant_registered_twice_is_refused():
    with pytest.raises(ValueError, match="registered twice"):
        MerchantRegistry((GROCER, GROCER))


def test_an_mcc_that_is_not_an_iso_18245_code_is_refused():
    """A four digit code is the whole contract with the acquirer's vocabulary."""
    for bad in ("541", "54111", "54a1", ""):
        with pytest.raises(ValueError, match="four digits"):
            MerchantRegistry((MerchantRecord("x", bad, "", frozenset()),))


def test_a_merchant_entry_missing_a_required_field_names_the_field():
    with pytest.raises(ValueError, match="mcc"):
        MerchantRegistry.from_mapping({"merchant": [{"id": "x", "categories": []}]})


def test_a_registry_file_that_was_asked_for_and_is_missing_raises(tmp_path):
    """A typo in a path must not quietly hand back the bundled merchants."""
    with pytest.raises(FileNotFoundError):
        load_registry(tmp_path / "nope.toml")


def test_no_configuration_at_all_falls_back_to_the_bundled_records(monkeypatch):
    monkeypatch.delenv("WARRANT_MERCHANTS", raising=False)
    assert len(load_registry()) == len(bundled_registry())


def test_the_environment_can_point_at_a_registry(tmp_path, monkeypatch):
    path = tmp_path / "warrant.toml"
    path.write_text(TOML)
    monkeypatch.setenv("WARRANT_MERCHANTS", str(path))

    assert {m.merchant for m in load_registry()} == {
        "acme-grocers", "northwind-electronics"
    }


def test_a_registry_is_extended_by_copying_not_by_mutating():
    """Two requests must never disagree about what a merchant may sell."""
    base = MerchantRegistry((GROCER,))
    extended = base.with_merchant(
        MerchantRecord("northwind", "5732", "Electronics stores", frozenset({"electronics"}))
    )

    assert len(base) == 1
    assert len(extended) == 2


# ------------------------------------------------------------------- swapping


def test_installing_a_registry_returns_the_one_it_replaced():
    original = active_registry()
    mine = MerchantRegistry((GROCER,))
    try:
        previous = use_registry(mine)
        assert previous is original
        assert active_registry() is mine
    finally:
        use_registry(original)


# ---------------------------------------------------------------- the gate


def test_the_gate_uses_the_registry_it_is_handed(intent, make_cart, chai, user_key):
    """An adopter's own merchants govern, without touching process state."""
    cart = make_cart((chai,), merchant="zomato")
    state = MandateState(intent_digest=intent.digest)

    # A registry that has never heard of zomato must fail it closed, even though
    # the bundled one underwrites it.
    empty = MerchantRegistry(())
    decision = evaluate(
        intent=intent, cart=cart, state=state, now=intent.issued_at + 1,
        subject_key=user_key.public, registry=empty,
    )

    assert decision.verdict is Verdict.BLOCK
    assert any(c.rule == "merchant.mcc_scope" for c in decision.failures)
    # and the process-wide registry is untouched by having passed one in
    assert "zomato" in active_registry()


def test_an_unregistered_merchant_fails_closed_rather_than_open(
    intent, make_cart, chai, user_key
):
    cart = make_cart((chai,), merchant="a-merchant-nobody-underwrote")
    decision = evaluate(
        intent=intent, cart=cart, state=MandateState(intent_digest=intent.digest),
        now=intent.issued_at + 1, subject_key=user_key.public,
    )

    assert decision.verdict is Verdict.BLOCK
    mcc = next(c for c in decision.checks if c.rule == "merchant.mcc_scope")
    assert "not a registered merchant" in mcc.detail
