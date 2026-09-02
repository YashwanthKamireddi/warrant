"""A real merchant, with a real catalog and real orders.

Every catalog in this project up to now was a tuple in a Python file. That is
fine for a benchmark and dishonest for a demonstration: a gate that only ever
sees items its own author wrote is not being tested against anything.

This module points the agent at a Shopify store instead. The products are ones a
merchant actually listed, the prices are the ones actually set, and an allowed
basket becomes an order that actually exists in a merchant's admin. Warrant
sits between the two, and the Razorpay mandate moves the money.

    agent  --reads-->  Shopify Storefront (real products)
      |
      v  proposes a basket
    WARRANT  allow / block / escalate
      |
      v  allowed only
    Razorpay UPI mandate  (real debit, nobody asked anything)
      |
      v
    Shopify Admin API  (real order)

Credentials come from SHOPIFY_STORE, SHOPIFY_CLIENT_ID and
SHOPIFY_CLIENT_SECRET. Shopify retired admin-created custom apps on 1 January
2026, so there is no token to paste any more: an app created in the Dev
Dashboard hands out a client id and secret, and the token is exchanged for at
call time through the client credentials grant. That exchange lives in
:meth:`ShopifyStore.token`.

A store that is not configured raises :class:`ShopifyNotConfigured` rather than
quietly returning invented products -- an empty catalog that looks real is worse
than no catalog.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from .catalog import Product

__all__ = [
    "ShopifyNotConfigured",
    "ShopifyOrder",
    "ShopifyStore",
    "category_for",
]

API_VERSION = "2026-01"

# A merchant's own product taxonomy is not a payment category, and the merchant
# does not get to invent payment categories -- that is the whole argument in
# `merchants.py`. So a Shopify productType is mapped onto the category
# vocabulary the mandate speaks, and anything unrecognised becomes "other",
# which no food-scoped mandate permits. Erring toward refusal is the only safe
# direction for an unknown product type.
PRODUCT_TYPE_CATEGORIES: dict[str, str] = {
    "food": "food_beverage",
    "beverage": "food_beverage",
    "beverages": "food_beverage",
    "drink": "food_beverage",
    "drinks": "food_beverage",
    "snack": "food_beverage",
    "snacks": "food_beverage",
    "meal": "food_beverage",
    "meals": "food_beverage",
    "grocery": "grocery",
    "groceries": "grocery",
    "electronics": "electronics",
    "accessories": "electronics",
    "apparel": "apparel",
    "clothing": "apparel",
}


def category_for(product_type: str) -> str:
    """Map a merchant's product type onto a payment category.

    Unknown types become ``other`` deliberately. A mandate scoped to food does
    not permit ``other``, so a product the merchant has not classified cannot be
    bought by an agent working from a food-scoped permission.
    """
    return PRODUCT_TYPE_CATEGORIES.get(product_type.strip().lower(), "other")


class ShopifyNotConfigured(RuntimeError):
    """Raised when the Shopify merchant is used without credentials."""


class ShopifyOrder(BaseModel):
    """An order that exists in a merchant's admin, not a receipt we printed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    """The merchant-facing order number, like #1001."""

    total_paise: int
    currency: str


_PRODUCTS_QUERY = """
query Catalog($first: Int!) {
  products(first: $first, query: "status:active") {
    edges {
      node {
        id
        title
        productType
        variants(first: 1) {
          edges { node { id sku price inventoryQuantity } }
        }
      }
    }
  }
}
"""

_ORDER_MUTATION = """
mutation CreateOrder($order: OrderCreateOrderInput!) {
  orderCreate(order: $order) {
    order {
      id
      name
      totalPriceSet { shopMoney { amount currencyCode } }
    }
    userErrors { field message }
  }
}
"""


class ShopifyStore:
    """Reads a real catalog and writes real orders."""

    merchant_id = "shopify"

    def __init__(
        self,
        shop: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 20.0,
    ) -> None:
        shop = shop or os.environ.get("SHOPIFY_STORE", "")
        self._client_id = client_id or os.environ.get("SHOPIFY_CLIENT_ID", "")
        self._client_secret = client_secret or os.environ.get("SHOPIFY_CLIENT_SECRET", "")

        if not (shop and self._client_id and self._client_secret):
            raise ShopifyNotConfigured(
                "Set SHOPIFY_STORE, SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET to "
                "use a real Shopify catalog, or run with the bundled catalog."
            )

        # Accept "my-store", "my-store.myshopify.com" or a full URL.
        shop = shop.strip().removeprefix("https://").removeprefix("http://").rstrip("/")
        self.shop = shop if shop.endswith(".myshopify.com") else f"{shop}.myshopify.com"

        self._http = httpx.Client(timeout=timeout, transport=transport)
        self._token: str | None = None
        self._token_expires_at = 0.0

    # ------------------------------------------------------------------ auth

    def token(self) -> str:
        """Exchange the client credentials for an Admin API token.

        Cached until shortly before it expires. Shopify hands these out per
        call now rather than once in the UI, which means a leaked token stops
        working on its own -- worth keeping rather than working around.
        """
        if self._token and time.time() < self._token_expires_at:
            return self._token

        response = self._http.post(
            f"https://{self.shop}/admin/oauth/access_token",
            json={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "client_credentials",
            },
        )
        response.raise_for_status()
        payload = response.json()
        self._token = payload["access_token"]
        # Refresh a minute early rather than discovering expiry mid-checkout.
        self._token_expires_at = time.time() + max(payload.get("expires_in", 3600) - 60, 0)
        return self._token

    def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        response = self._http.post(
            f"https://{self.shop}/admin/api/{API_VERSION}/graphql.json",
            headers={"X-Shopify-Access-Token": self.token()},
            json={"query": query, "variables": variables},
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("errors"):
            raise RuntimeError(f"Shopify rejected the query: {payload['errors']}")
        return payload["data"]

    # --------------------------------------------------------------- catalog

    def catalog(self, first: int = 50) -> tuple[Product, ...]:
        """The merchant's real products, in the shape the gate already speaks."""
        data = self._graphql(_PRODUCTS_QUERY, {"first": first})
        products: list[Product] = []

        for edge in data["products"]["edges"]:
            node = edge["node"]
            variants = node["variants"]["edges"]
            if not variants:
                continue
            variant = variants[0]["node"]

            # Shopify prices are decimal strings in the shop's currency. Money
            # is integer paise everywhere inside Warrant, and a float here would
            # be rejected by the canonicaliser further down, so it converts once
            # and at the boundary.
            unit_paise = int(round(float(variant["price"]) * 100))
            if unit_paise <= 0:
                continue

            products.append(
                Product(
                    sku=variant["sku"] or node["id"].rsplit("/", 1)[-1],
                    name=node["title"],
                    category=category_for(node.get("productType") or ""),
                    unit_paise=unit_paise,
                    merchant=self.merchant_id,
                    note=f"listed by the merchant as {node.get('productType') or 'untyped'}",
                )
            )
        return tuple(products)

    def variant_ids(self, first: int = 50) -> dict[str, str]:
        """SKU to Shopify variant id, needed to place an order."""
        data = self._graphql(_PRODUCTS_QUERY, {"first": first})
        ids: dict[str, str] = {}
        for edge in data["products"]["edges"]:
            node = edge["node"]
            for variant_edge in node["variants"]["edges"]:
                variant = variant_edge["node"]
                ids[variant["sku"] or node["id"].rsplit("/", 1)[-1]] = variant["id"]
        return ids

    # ----------------------------------------------------------------- order

    def create_order(
        self,
        line_items: list[tuple[str, int]],
        *,
        email: str = "demo@example.com",
        note: str = "",
        tags: list[str] | None = None,
    ) -> ShopifyOrder:
        """Place a real order for ``(variant_id, quantity)`` pairs.

        Called only after the gate has allowed the basket and the mandate has
        actually been debited, so an order in the merchant's admin always has a
        settled payment and a signed permission behind it. That ordering is the
        point: an order that exists without a receipt is exactly the dispute
        this project is about.
        """
        variables = {
            "order": {
                "email": email,
                "note": note,
                "tags": tags or ["warrant"],
                "lineItems": [
                    {"variantId": variant_id, "quantity": qty}
                    for variant_id, qty in line_items
                ],
            }
        }
        data = self._graphql(_ORDER_MUTATION, variables)
        result = data["orderCreate"]
        if result["userErrors"]:
            raise RuntimeError(f"Shopify refused the order: {result['userErrors']}")

        order = result["order"]
        money = order["totalPriceSet"]["shopMoney"]
        return ShopifyOrder(
            id=order["id"],
            name=order["name"],
            total_paise=int(round(float(money["amount"]) * 100)),
            currency=money["currencyCode"],
        )

    def close(self) -> None:
        self._http.close()
