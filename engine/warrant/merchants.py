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

  configurable  The registry below is a *default*, not the product. Nobody
            adopting this runs an Indian food-delivery marketplace by
            coincidence, so the records load from a TOML file -- point
            WARRANT_MERCHANTS at your own, or hand a MerchantRegistry to
            evaluate() directly. The bundled records exist so the thing runs
            out of the box, not because they are the ones that matter.

  still open  A merchant *inside* the category mislabelling within its own
            catalog. Zomato is MCC 5812; a power bank listed there as
            ``food_beverage`` still passes this check. Catching that needs the
            actual purchased item, which no metadata layer can see -- it needs the
            rail. That is the same argument for scope living in UAP rather than
            merchant-side, and it is stated in the README rather than papered over.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import NamedTuple

__all__ = [
    "MerchantRecord",
    "MerchantRegistry",
    "REGISTRY",
    "active_registry",
    "assigned_categories",
    "bundled_registry",
    "is_registered",
    "load_registry",
    "use_registry",
]


class MerchantRecord(NamedTuple):
    """What the acquirer underwrote, not what the merchant claims."""

    merchant: str
    mcc: str
    description: str
    categories: frozenset[str]


class MerchantRegistry:
    """An acquirer's book of who it underwrote, and for what.

    Immutable once built. Swapping the registry is how an adopter configures
    this for their own merchants; mutating a shared one at runtime is how two
    requests end up disagreeing about what a merchant is allowed to sell.
    """

    __slots__ = ("_records",)

    def __init__(self, records: tuple[MerchantRecord, ...] = ()) -> None:
        seen: dict[str, MerchantRecord] = {}
        for record in records:
            if record.merchant in seen:
                raise ValueError(f"merchant {record.merchant!r} is registered twice")
            if not record.mcc.isdigit() or len(record.mcc) != 4:
                raise ValueError(
                    f"{record.merchant!r} has MCC {record.mcc!r}; ISO 18245 codes are "
                    "four digits"
                )
            seen[record.merchant] = record
        self._records = seen

    # ------------------------------------------------------------- accessors

    def get(self, merchant: str) -> MerchantRecord | None:
        return self._records.get(merchant)

    def __contains__(self, merchant: object) -> bool:
        return merchant in self._records

    def __len__(self) -> int:
        return len(self._records)

    def __iter__(self):
        return iter(self._records.values())

    def assigned_categories(self, merchant: str) -> frozenset[str]:
        """Categories the acquirer's MCC permits. Empty for an unknown merchant.

        Empty means *nothing is permitted*, not *anything is permitted*. An
        unregistered merchant fails closed, which is the only safe direction:
        the alternative lets anyone who is not in the book sell anything.
        """
        record = self._records.get(merchant)
        return record.categories if record else frozenset()

    def with_merchant(self, record: MerchantRecord) -> MerchantRegistry:
        """A new registry with one more merchant in it."""
        return MerchantRegistry((*self._records.values(), record))

    # ------------------------------------------------------------ construction

    @classmethod
    def from_mapping(cls, data: dict) -> MerchantRegistry:
        """Build from parsed TOML or JSON.

        Expects a ``merchant`` array of tables::

            [[merchant]]
            id = "acme-grocers"
            mcc = "5411"
            description = "Grocery stores and supermarkets"
            categories = ["grocery", "food_beverage"]
        """
        entries = data.get("merchant") or data.get("merchants") or []
        records = []
        for i, entry in enumerate(entries):
            missing = {"id", "mcc", "categories"} - entry.keys()
            if missing:
                raise ValueError(
                    f"merchant #{i + 1} is missing {', '.join(sorted(missing))}"
                )
            records.append(
                MerchantRecord(
                    merchant=str(entry["id"]),
                    mcc=str(entry["mcc"]),
                    description=str(entry.get("description", "")),
                    categories=frozenset(entry["categories"]),
                )
            )
        return cls(tuple(records))

    @classmethod
    def from_file(cls, path: str | Path) -> MerchantRegistry:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"no merchant registry at {path}")
        return cls.from_mapping(tomllib.loads(path.read_text(encoding="utf-8")))


# ISO 18245 merchant category codes, the same vocabulary an acquirer assigns.
# These are a starting point for the demo and the benchmark, not the product.
_BUNDLED: tuple[MerchantRecord, ...] = (
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
    # The real storefront the console reads. An acquirer underwriting a coffee D2C
    # brand assigns 5499 -- miscellaneous food stores -- which covers what they
    # sell to eat and drink and does not cover the mugs and tote bags in the same
    # catalogue. That is not a contrivance: it is why the mug is refused twice,
    # once by the code its acquirer assigned and once by the mandate's own
    # categories, and neither refusal needed anybody to plant anything.
    MerchantRecord(
        "sleepyowl", "5499", "Miscellaneous food stores", frozenset({"food_beverage"})
    ),
)


def bundled_registry() -> MerchantRegistry:
    return MerchantRegistry(_BUNDLED)


def load_registry(path: str | Path | None = None) -> MerchantRegistry:
    """Load a registry from a file, from WARRANT_MERCHANTS, or fall back.

    A path that was asked for and does not exist raises. Only the *absence* of
    any configuration falls back to the bundled records -- a typo in a path
    should not silently hand you a registry full of Indian food delivery.
    """
    path = path or os.environ.get("WARRANT_MERCHANTS")
    if not path:
        return bundled_registry()
    return MerchantRegistry.from_file(path)


_active: MerchantRegistry = load_registry()


def active_registry() -> MerchantRegistry:
    """The registry the gate consults when it is not handed one."""
    return _active


def use_registry(registry: MerchantRegistry) -> MerchantRegistry:
    """Install a registry process-wide. Returns the one it replaced."""
    global _active
    previous, _active = _active, registry
    return previous


# Kept because the demo, the benchmark and the console all read it directly, and
# because "the merchants this build knows about" is a genuinely useful thing to
# be able to print.
REGISTRY: dict[str, MerchantRecord] = {r.merchant: r for r in _BUNDLED}


def is_registered(merchant: str) -> bool:
    return merchant in _active


def assigned_categories(merchant: str) -> frozenset[str]:
    """Categories the acquirer's MCC permits, per the active registry."""
    return _active.assigned_categories(merchant)
