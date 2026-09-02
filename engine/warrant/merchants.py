"""Who says a merchant sells food?

The gate's weakest joint is that categories arrive on the line item, from the
merchant's own catalog, and nothing checks them. A merchant that tags a power
bank ``food_beverage`` walks straight through a food-only mandate.

Card networks solved the first half of this decades ago and payments still runs
on it: an acquirer assigns a merchant a **category code** at onboarding, and the
merchant does not get to pick it. Razorpay does exactly this today -- it is the
MCC on every merchant account it underwrites.

So this module holds an acquirer-side registry: merchant -> assigned MCC ->
the categories that code permits. The gate then checks the merchant's *declared*
item categories against what its acquirer *assigned* it, and refuses the ones
outside.

Be precise about what that closes and what it does not:

  closed    A merchant outside a category cannot participate in a mandate scoped
            to it. An electronics retailer cannot serve a food-only mandate by
            relabelling its catalog, because its MCC says what it is and it did
            not write that.

  still open  A merchant *inside* the category mislabelling within its own
            catalog. Zomato is MCC 5812; a power bank listed there as
            ``food_beverage`` still passes this check. Catching that needs the
            actual purchased item, which no metadata layer can see -- it needs the
            rail. That is the same argument for scope living in UAP rather than
            merchant-side, and it is stated in the README rather than papered over.
"""

from __future__ import annotations

from typing import NamedTuple

__all__ = ["MerchantRecord", "REGISTRY", "assigned_categories", "is_registered"]


class MerchantRecord(NamedTuple):
    """What the acquirer underwrote, not what the merchant claims."""

    merchant: str
    mcc: str
    description: str
    categories: frozenset[str]


# ISO 18245 merchant category codes, the same vocabulary an acquirer assigns.
_RECORDS: tuple[MerchantRecord, ...] = (
    MerchantRecord(
        "zomato", "5812", "Eating places and restaurants", frozenset({"food_beverage"})
    ),
    MerchantRecord(
        "swiggy", "5812", "Eating places and restaurants", frozenset({"food_beverage"})
    ),
    MerchantRecord(
        "zepto",
        "5411",
        "Grocery stores and supermarkets",
        frozenset({"groceries", "food_beverage"}),
    ),
    MerchantRecord(
        "amazon",
        "5399",
        "General merchandise",
        frozenset({"electronics", "apparel", "groceries", "other"}),
    ),
    # A live Shopify store, underwritten as an eating place. This is the record
    # a real acquirer would hold, and it is what makes the store's own product
    # types checkable: the store may list an "Electronics" product, and its MCC
    # says it was not underwritten to sell one under a food mandate.
    MerchantRecord(
        "shopify", "5812", "Eating places and restaurants", frozenset({"food_beverage"})
    ),
)

REGISTRY: dict[str, MerchantRecord] = {r.merchant: r for r in _RECORDS}


def is_registered(merchant: str) -> bool:
    return merchant in REGISTRY


def assigned_categories(merchant: str) -> frozenset[str]:
    """Categories the acquirer's MCC permits. Empty for an unregistered merchant.

    Empty means *nothing is permitted*, not *anything is permitted*. An
    unregistered merchant fails closed.
    """
    record = REGISTRY.get(merchant)
    return record.categories if record else frozenset()
