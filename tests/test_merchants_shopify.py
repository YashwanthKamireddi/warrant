"""The Shopify merchant, driven against a mock transport.

These run offline and pin down the boundary: how a merchant's own product
taxonomy becomes a payment category, how a decimal price string becomes integer
paise, and what happens when the merchant lists something it has not classified.
The last one matters most -- an unclassified product must not inherit the
benefit of the doubt.
"""

from __future__ import annotations

import json

import httpx
import pytest

from warrant.merchants_shopify import (
    ShopifyNotConfigured,
    ShopifyStore,
    category_for,
)

TOKEN = {"access_token": "shpat_fake", "expires_in": 3600}


def product(title, product_type, price, sku, variant_id="gid://shopify/ProductVariant/1"):
    return {
        "node": {
            "id": "gid://shopify/Product/1",
            "title": title,
            "productType": product_type,
            "variants": {
                "edges": [
                    {"node": {"id": variant_id, "sku": sku, "price": price,
                              "inventoryQuantity": 10}}
                ]
            },
        }
    }


def store(*, products=(), order=None, order_errors=(), calls=None) -> ShopifyStore:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        if request.url.path.endswith("/access_token"):
            return httpx.Response(200, json=TOKEN)
        body = json.loads(request.content)
        if "orderCreate" in body["query"]:
            return httpx.Response(200, json={"data": {"orderCreate": {
                "order": order,
                "userErrors": list(order_errors),
            }}})
        return httpx.Response(200, json={"data": {"products": {"edges": list(products)}}})

    return ShopifyStore(
        shop="demo-store",
        client_id="cid",
        client_secret="csecret",
        transport=httpx.MockTransport(handler),
    )


# --------------------------------------------------------------- categories


@pytest.mark.parametrize(
    "product_type,expected",
    [
        ("Food", "food_beverage"),
        ("beverages", "food_beverage"),
        ("  SNACKS  ", "food_beverage"),
        ("Electronics", "electronics"),
        ("Groceries", "grocery"),
    ],
)
def test_a_merchants_product_type_becomes_a_payment_category(product_type, expected):
    assert category_for(product_type) == expected


def test_an_unclassified_product_type_is_not_given_the_benefit_of_the_doubt():
    """A merchant that types nothing must not thereby sell into a food mandate."""
    assert category_for("") == "other"
    assert category_for("Mystery Box") == "other"


# ------------------------------------------------------------ configuration


def test_a_store_without_credentials_refuses_rather_than_inventing_a_catalog(monkeypatch):
    for key in ("SHOPIFY_STORE", "SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ShopifyNotConfigured):
        ShopifyStore()


@pytest.mark.parametrize(
    "given",
    ["demo-store", "demo-store.myshopify.com", "https://demo-store.myshopify.com/"],
)
def test_the_shop_domain_is_accepted_in_any_of_the_shapes_people_paste(given):
    s = ShopifyStore(
        shop=given, client_id="c", client_secret="s",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=TOKEN)),
    )
    assert s.shop == "demo-store.myshopify.com"


# ----------------------------------------------------------------- catalog


def test_the_catalog_is_the_merchants_real_products():
    s = store(products=[
        product("Masala Chai", "Beverages", "40.00", "chai"),
        product("Power Bank", "Electronics", "199.00", "pb"),
    ])
    catalog = s.catalog()

    assert [p.name for p in catalog] == ["Masala Chai", "Power Bank"]
    assert [p.category for p in catalog] == ["food_beverage", "electronics"]
    assert [p.unit_paise for p in catalog] == [4_000, 19_900]
    assert all(p.merchant == "shopify" for p in catalog)


def test_decimal_prices_become_integer_paise_without_a_float_surviving():
    """Money is integer paise everywhere inside; the conversion happens once."""
    s = store(products=[product("Odd Price", "Food", "10.07", "odd")])
    (item,) = s.catalog()
    assert item.unit_paise == 1_007
    assert isinstance(item.unit_paise, int)


def test_a_free_or_zero_priced_product_is_skipped():
    s = store(products=[
        product("Freebie", "Food", "0.00", "free"),
        product("Chai", "Food", "40.00", "chai"),
    ])
    assert [p.sku for p in s.catalog()] == ["chai"]


def test_a_product_with_no_variants_is_skipped_rather_than_crashing():
    empty = {"node": {"id": "gid://shopify/Product/9", "title": "Draft",
                      "productType": "Food", "variants": {"edges": []}}}
    s = store(products=[empty, product("Chai", "Food", "40.00", "chai")])
    assert [p.sku for p in s.catalog()] == ["chai"]


def test_a_product_with_no_sku_falls_back_to_its_shopify_id():
    s = store(products=[product("No SKU", "Food", "40.00", None)])
    (item,) = s.catalog()
    assert item.sku == "1"


# -------------------------------------------------------------------- auth


def test_the_token_is_exchanged_once_and_then_reused():
    calls: list[httpx.Request] = []
    s = store(products=[product("Chai", "Food", "40.00", "chai")], calls=calls)

    s.catalog()
    s.catalog()

    exchanges = [c for c in calls if c.url.path.endswith("/access_token")]
    assert len(exchanges) == 1


def test_the_client_secret_is_sent_only_to_the_token_endpoint():
    """A secret on a GraphQL call would be a secret in every query log."""
    calls: list[httpx.Request] = []
    s = store(products=[product("Chai", "Food", "40.00", "chai")], calls=calls)
    s.catalog()

    graphql = [c for c in calls if c.url.path.endswith("graphql.json")]
    assert graphql
    for call in graphql:
        assert b"csecret" not in call.content
        assert call.headers["X-Shopify-Access-Token"] == "shpat_fake"


# ------------------------------------------------------------------- order


def test_an_allowed_basket_becomes_a_real_order():
    s = store(order={
        "id": "gid://shopify/Order/55",
        "name": "#1001",
        "totalPriceSet": {"shopMoney": {"amount": "480.00", "currencyCode": "INR"}},
    })
    order = s.create_order([("gid://shopify/ProductVariant/1", 6)], note="warrant")

    assert order.name == "#1001"
    assert order.total_paise == 48_000
    assert order.currency == "INR"


def test_a_refused_order_raises_with_the_merchants_own_reason():
    s = store(order=None, order_errors=[{"field": ["lineItems"], "message": "out of stock"}])
    with pytest.raises(RuntimeError, match="out of stock"):
        s.create_order([("gid://shopify/ProductVariant/1", 1)])
