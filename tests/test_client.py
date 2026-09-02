"""The front door, used the way the docstring says to use it.

If these read like the README that is deliberate. The failure this file exists
to catch is the documented example not working -- which it did not, until the
explicit-scope path was added: with no model configured, derivation fails closed
to a scope permitting only ``other``, and every basket in the docstring was
refused.
"""

from __future__ import annotations

import time

import pytest

from warrant import Warrant
from warrant.crypto import SigningKey
from warrant.merchants import MerchantRecord, MerchantRegistry
from warrant.models import Scope, Verdict

NOW = int(time.time())

GROCER = MerchantRegistry((
    MerchantRecord(
        "acme-grocers", "5411", "Grocery stores and supermarkets",
        frozenset({"grocery", "food_beverage"}),
    ),
))


def lunch_scope(**overrides) -> Scope:
    return Scope(**{
        "merchants": ("acme-grocers",),
        "categories": ("food_beverage",),
        "max_total_paise": 100_000,
        "max_per_txn_paise": 100_000,
        "max_txns": 2,
        "not_before": NOW,
        "expires_at": NOW + 7200,
        **overrides,
    })


SANDWICH = {"sku": "sandwich", "category": "food_beverage", "qty": 2, "unit_paise": 24_000}
CABLE = {"sku": "cable", "category": "electronics", "qty": 1, "unit_paise": 29_900}


@pytest.fixture
def warrant():
    with Warrant(merchants=GROCER) as w:
        yield w


# ------------------------------------------------------------- the first run


def test_the_documented_example_works_with_no_configuration_at_all(warrant):
    """No model, no keys, no ledger file, no registry. It must still decide."""
    permission = warrant.permit("lunch for the team", scope=lunch_scope())
    decision = warrant.check(permission, "acme-grocers", [SANDWICH])

    assert decision.allowed
    assert bool(decision) is True
    assert decision.reasons == ()


def test_an_utterance_with_no_model_fails_closed_and_says_why(warrant):
    """Derivation cannot infer categories without understanding the sentence.

    Narrowing to `other` is correct. What must never happen is it narrowing
    silently -- a first run that refuses everything needs to explain itself.
    """
    permission = warrant.permit("lunch for the team, under 1000")

    assert permission.intent.scope.categories == ("other",)
    assert "no model is configured" in permission.approval_prompt
    assert any("no model" in a for a in permission.pending.proposal.ambiguities)


def test_an_explicitly_given_scope_is_recorded_as_pinned_not_as_interpreted(warrant):
    """A scope from a form was not interpreted, and must not claim it was."""
    permission = warrant.permit("lunch", scope=lunch_scope())

    assert permission.pending.proposal.source == "pinned"
    assert permission.pending.proposal.ambiguities == ()


def test_passing_both_a_pending_intent_and_a_scope_is_refused(warrant):
    pending = warrant.propose("lunch for the team")
    with pytest.raises(TypeError, match="not both"):
        warrant.permit(pending, scope=lunch_scope())


# ------------------------------------------------------------------ deciding


def test_a_basket_outside_the_permitted_category_is_refused_with_reasons(warrant):
    permission = warrant.permit("lunch", scope=lunch_scope())
    decision = warrant.check(permission, "acme-grocers", [CABLE])

    assert not decision.allowed
    assert decision.verdict is Verdict.BLOCK
    assert decision.reasons
    assert any("electronics" in r for r in decision.reasons)


def test_check_spends_nothing(warrant):
    """Previewing must not consume budget, a nonce or an attempt."""
    permission = warrant.permit("lunch", scope=lunch_scope(max_total_paise=200_000))

    for _ in range(5):
        assert warrant.check(permission, "acme-grocers", [SANDWICH]).allowed

    # max_txns is 2. If check() had consumed attempts, both of these would fail.
    assert warrant.spend(permission, "acme-grocers", [SANDWICH]).allowed
    assert warrant.spend(permission, "acme-grocers", [SANDWICH]).allowed
    assert not warrant.spend(permission, "acme-grocers", [SANDWICH]).allowed


def test_approaching_the_ceiling_escalates_rather_than_allowing_silently(warrant):
    """Two baskets that together use 96% of the budget are worth a second look.

    Not a refusal -- everything the person signed is satisfied -- but not a
    silent allow either. The rule is signal.ceiling_creep.
    """
    permission = warrant.permit("lunch", scope=lunch_scope())

    assert warrant.spend(permission, "acme-grocers", [SANDWICH]).allowed
    second = warrant.spend(permission, "acme-grocers", [SANDWICH])

    assert second.verdict is Verdict.ESCALATE
    assert second.needs_approval
    assert not second.allowed


def test_spend_settles_on_the_default_rail(warrant):
    permission = warrant.permit("lunch", scope=lunch_scope())
    decision = warrant.spend(permission, "acme-grocers", [SANDWICH])

    assert decision.allowed
    assert decision.settled
    assert decision.outcome.receipt is not None


def test_the_ceiling_is_enforced_across_purchases(warrant):
    """Two purchases each within the per-order limit, together over the total.

    The amounts leave more than a tenth of the ceiling spare after the first,
    so signal.ceiling_creep stays quiet and the only thing under test is the
    running total.
    """
    half = {**SANDWICH, "qty": 1}
    permission = warrant.permit(
        "lunch",
        scope=lunch_scope(max_total_paise=40_000, max_per_txn_paise=30_000),
    )
    first = warrant.spend(permission, "acme-grocers", [half])
    second = warrant.spend(permission, "acme-grocers", [half])

    assert first.allowed
    assert second.verdict is Verdict.BLOCK
    assert any("ceiling" in r.lower() or "total" in r.lower() for r in second.reasons)


def test_an_empty_basket_is_refused_before_anything_is_built(warrant):
    permission = warrant.permit("lunch", scope=lunch_scope())
    with pytest.raises(ValueError, match="at least one line item"):
        warrant.check(permission, "acme-grocers", [])


# ------------------------------------------------------------- item coercion


def test_a_bare_tuple_item_is_categorised_as_other_rather_than_guessed(warrant):
    """Guessing a category from a sku would quietly widen the scope."""
    permission = warrant.permit("lunch", scope=lunch_scope())
    decision = warrant.check(permission, "acme-grocers", [("sandwich", 2, 24_000)])

    assert not decision.allowed
    assert any("other" in r for r in decision.reasons)


def test_an_item_missing_a_category_is_other_not_permitted(warrant):
    permission = warrant.permit("lunch", scope=lunch_scope())
    decision = warrant.check(
        permission, "acme-grocers", [{"sku": "x", "qty": 1, "unit_paise": 100}]
    )
    assert not decision.allowed


# ------------------------------------------------------------------ lifecycle


def test_revoking_stops_further_spending(warrant):
    permission = warrant.permit("lunch", scope=lunch_scope())
    assert warrant.spend(permission, "acme-grocers", [SANDWICH]).allowed

    warrant.revoke(permission)

    after = warrant.spend(permission, "acme-grocers", [SANDWICH])
    assert not after.allowed


def test_refusals_are_written_to_the_ledger_not_only_successes(warrant):
    """A control plane that logs only its successes cannot be audited."""
    permission = warrant.permit("lunch", scope=lunch_scope())
    warrant.spend(permission, "acme-grocers", [CABLE])

    kinds = [e.kind.value for e in warrant.history(permission)]
    assert kinds, "the ledger recorded nothing at all"
    assert "cart_blocked" in kinds, kinds


def test_a_supplied_registry_governs_rather_than_the_bundled_one():
    """The adopter's merchants decide, not ours."""
    with Warrant(merchants=GROCER) as w:
        permission = w.permit(
            "lunch", scope=lunch_scope(merchants=("zomato",)),
        )
        # zomato is in the bundled registry and not in this one.
        decision = w.check(permission, "zomato", [SANDWICH])
        assert not decision.allowed
        assert any("not a registered merchant" in r for r in decision.reasons)


def test_a_supplied_key_is_used_so_receipts_outlive_the_process():
    key = SigningKey.from_seed("warrant/test/authorizer")
    with Warrant(merchants=GROCER, key=key) as w:
        permission = w.permit("lunch", scope=lunch_scope())
        decision = w.spend(permission, "acme-grocers", [SANDWICH])
        assert decision.settled
        assert decision.outcome.receipt.signature.key_id == key.key_id
