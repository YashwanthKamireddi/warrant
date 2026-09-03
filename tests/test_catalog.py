"""Guards against the drift that broke the console once.

The scripted demo, the API and the console all render the same storefront. When
that list lived in two places they disagreed by one SKU, the console's scripted
run died on a 400, and every backend test stayed green -- because nothing tested
the seam. These do.
"""

from __future__ import annotations

import pytest

from warrant.api import catalog_json
from warrant.catalog import PRODUCTS, by_sku, line_item
from warrant.demo import STEPS


def test_every_scripted_sku_exists_in_the_catalog():
    catalog_skus = {p.sku for p in PRODUCTS}
    scripted_skus = {item.sku for step in STEPS for item in step.items}
    assert scripted_skus <= catalog_skus


def test_the_api_serves_exactly_the_shared_catalog():
    """And reads it when asked, so swapping the catalogue actually swaps it."""
    assert [c["sku"] for c in catalog_json()] == [p.sku for p in PRODUCTS]

    from warrant.catalog import Catalog, Product, use_catalog

    mine = Catalog((Product("only-one", "Only One", "food_beverage", 100, "m", ""),))
    previous = use_catalog(mine)
    try:
        assert [c["sku"] for c in catalog_json()] == ["only-one"]
    finally:
        use_catalog(previous)


def test_scripted_items_match_catalog_prices_and_categories():
    # A step that priced an item differently from the storefront would make the
    # console and the CLI demo disagree about the same basket.
    for step in STEPS:
        for item in step.items:
            product = by_sku(item.sku)
            assert item.unit_paise == product.unit_paise
            assert item.category == product.category
            assert item.name == product.name


def test_catalog_skus_are_unique():
    skus = [p.sku for p in PRODUCTS]
    assert len(skus) == len(set(skus))


def test_line_item_takes_its_price_from_the_catalog_not_the_caller():
    item = line_item("chai-6", 3)
    assert item.unit_paise == by_sku("chai-6").unit_paise
    assert item.line_paise == item.unit_paise * 3


def test_unknown_sku_names_the_sku_that_was_asked_for():
    with pytest.raises(KeyError, match="nope"):
        by_sku("nope")


def test_the_catalog_contains_items_that_must_be_refused():
    # A storefront where everything is in scope cannot demonstrate a control plane.
    categories = {p.category for p in PRODUCTS}
    merchants = {p.merchant for p in PRODUCTS}
    assert len(categories) > 1
    assert len(merchants) > 1
