"""The catalogue as configuration.

The bundled products stay so a clone runs with nothing set and so the benchmark
measures the same thing on every machine. What must be true is that they are a
default and not a dependency: an adopter's catalogue governs, and a typo in a
path never quietly hands back somebody else's products.
"""

from __future__ import annotations

import pytest

from warrant.catalog import (
    Catalog,
    Product,
    active_catalog,
    bundled_catalog,
    by_sku,
    load_catalog,
    use_catalog,
)

TOML = """
[[product]]
sku = "sandwich"
name = "Chicken Sandwich"
category = "food_beverage"
unit_paise = 24000
merchant = "acme-grocers"
note = "in scope"

[[product]]
sku = "nw-cable"
name = "USB-C Cable"
category = "electronics"
unit_paise = 29900
merchant = "northwind-electronics"
"""


def write(tmp_path, body=TOML):
    path = tmp_path / "catalog.toml"
    path.write_text(body)
    return path


# ------------------------------------------------------------- construction


def test_a_catalogue_loads_from_a_file_anyone_can_write(tmp_path):
    catalog = Catalog.from_file(write(tmp_path))

    assert len(catalog) == 2
    assert catalog.by_sku("sandwich").unit_paise == 24_000
    assert catalog.merchants() == ("acme-grocers", "northwind-electronics")


def test_a_note_is_optional(tmp_path):
    assert Catalog.from_file(write(tmp_path)).by_sku("nw-cable").note == ""


def test_a_product_missing_a_required_field_names_the_field():
    with pytest.raises(ValueError, match="unit_paise"):
        Catalog.from_mapping({"product": [{"sku": "x", "name": "X",
                                           "category": "c", "merchant": "m"}]})


def test_a_duplicate_sku_is_refused_rather_than_the_second_one_winning():
    item = Product("x", "X", "food_beverage", 100, "m", "")
    with pytest.raises(ValueError, match="appears twice"):
        Catalog((item, item))


def test_a_product_that_costs_nothing_is_refused():
    """Money is integer paise and a product has to cost something."""
    with pytest.raises(ValueError, match="has to cost something"):
        Catalog((Product("x", "X", "food_beverage", 0, "m", ""),))


def test_a_catalogue_that_was_asked_for_and_is_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_catalog(tmp_path / "nope.toml")


@pytest.mark.catalog
def test_no_configuration_reads_a_real_merchants_storefront(monkeypatch):
    """The default is a real catalogue, not one this repository typed."""
    monkeypatch.delenv("WARRANT_CATALOG", raising=False)
    catalog = load_catalog()

    assert len(catalog) > len(bundled_catalog())
    assert catalog.merchants() != ("zomato",)
    # and it has the shape a demonstration needs, without anybody planting it
    categories = {p.category for p in catalog}
    assert "food_beverage" in categories
    assert categories - {"food_beverage"}, "nothing is out of category"


def test_the_environment_can_point_at_a_catalogue(tmp_path, monkeypatch):
    monkeypatch.setenv("WARRANT_CATALOG", str(write(tmp_path)))
    assert {p.sku for p in load_catalog()} == {"sandwich", "nw-cable"}


# ------------------------------------------------------------------ swapping


def test_installing_a_catalogue_returns_the_one_it_replaced(tmp_path):
    original = active_catalog()
    mine = Catalog.from_file(write(tmp_path))
    try:
        assert use_catalog(mine) is original
        assert active_catalog() is mine
        assert by_sku("sandwich").merchant == "acme-grocers"
    finally:
        use_catalog(original)

    assert active_catalog() is original


def test_an_unknown_sku_names_the_sku_that_was_actually_asked_for():
    with pytest.raises(KeyError, match="not-a-real-sku"):
        by_sku("not-a-real-sku")


# ------------------------------------------------------------- the shipped one


def test_the_example_catalogue_is_valid_and_pairs_with_the_example_registry():
    """The two example files have to work together or neither is an example."""
    from pathlib import Path

    from warrant.merchants import MerchantRegistry

    root = Path(__file__).resolve().parents[1]
    catalog = Catalog.from_file(root / "catalog.example.toml")
    registry = MerchantRegistry.from_file(root / "warrant.example.toml")

    for merchant in catalog.merchants():
        assert merchant in registry, f"{merchant} is in the catalogue and not the registry"


def test_the_example_catalogue_contains_things_that_must_be_refused():
    """A gate you can only show allowing things demonstrates nothing."""
    from pathlib import Path

    catalog = Catalog.from_file(
        Path(__file__).resolve().parents[1] / "catalog.example.toml"
    )
    categories = {p.category for p in catalog}
    assert "electronics" in categories, "nothing in the catalogue is out of category"
    assert len(catalog.merchants()) > 1, "nothing is at the wrong merchant"
    assert any(
        "ignore all previous instructions" in p.name.lower() for p in catalog
    ), "no injected instruction to demonstrate against"


@pytest.mark.catalog
def test_the_catalog_does_not_depend_on_import_order():
    """Importing storefront first must not quietly hand back the bundled products.

    `storefront` imports `catalog`, and `catalog` used to call `load_catalog()`
    at module scope. Importing storefront first therefore ran that call while
    storefront was half-initialised: the deferred `from .storefront import
    load_snapshot` raised ImportError, the fallback caught it, and the process
    ran on eleven bundled products while everything written about it described a
    real merchant's catalogue of sixty-two. Same code, same config, different
    answer depending on what something imported first — and nothing looked wrong,
    because a bundled catalog behaves exactly like a working one.
    """
    import subprocess
    import sys

    def size(first: str) -> int:
        out = subprocess.run(
            [
                sys.executable,
                "-c",
                f"import warrant.{first}\n"
                "from warrant.catalog import active_catalog\n"
                "print(len(active_catalog()))",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return int(out.stdout.strip())

    assert size("storefront") == size("catalog")
