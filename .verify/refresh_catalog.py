"""Take a snapshot of a real merchant's live storefront.

    make catalog-refresh

Writes engine/warrant/fixtures/storefront-<merchant>.json with the date it was
taken. Everything else reads the committed file: a build that reaches the
network fails when somebody else's site is slow, and a benchmark that reads live
prices measures a different corpus every day.
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "engine"))

from warrant.storefront import Storefront, StorefrontUnavailable, snapshot  # noqa: E402

STORES = [
    ("sleepyowl.co", "sleepyowl"),
    ("bluetokaicoffee.com", "bluetokai"),
]

failures = 0
for domain, merchant in STORES:
    store = Storefront.at(domain, merchant)
    try:
        payload = store.fetch()
    except StorefrontUnavailable as exc:
        print(f"  skip  {merchant:<12} {exc}")
        failures += 1
        continue

    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(json.dumps(payload, indent=1), encoding="utf-8")

    catalog = snapshot(payload)
    real = [p for p in catalog if not p.sku.startswith("warrant-")]
    categories = sorted({p.category for p in real})
    print(
        f"  ok    {merchant:<12} {len(real)} real products, "
        f"categories {', '.join(categories)}"
    )

print()
if failures == len(STORES):
    print("no storefront could be read; the committed snapshots are unchanged")
    sys.exit(1)
print("snapshots written")
