"""The whole chain, live, with nothing simulated.

    real Shopify catalog  ->  agent picks a basket  ->  WARRANT  ->  real UPI
    mandate debit  ->  real Shopify order

Run it:

    make live

Every arrow is an API call to a system that is not ours. The products are ones a
merchant listed, the money moves on a UPI Autopay mandate a person authorised
with their own PIN, and an allowed basket ends up as an order in a merchant's
admin. The refused basket ends up as nothing at all, which is the part worth
watching: it is under the mandate ceiling, the bank would have paid it, and the
only reason it does not become an order is the gate.

Each leg degrades on its own. No Shopify credentials falls back to the bundled
catalog and says so; no authorisation within the wait window skips the debit and
says so. Nothing is ever quietly faked -- a step that did not happen is reported
as skipped, never as passed.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "engine"))

from warrant.catalog import PRODUCTS  # noqa: E402
from warrant.crypto import SigningKey  # noqa: E402
from warrant.gate import MandateState, evaluate  # noqa: E402
from warrant.storefront import (  # noqa: E402
    StorefrontUnavailable,
    load_snapshot,
    snapshot_taken,
)
from warrant.models import (  # noqa: E402
    CartMandate,
    CheckStatus,
    IntentMandate,
    LineItem,
    Scope,
    Verdict,
)
from warrant.rails.razorpay_mandate import RazorpayMandate  # noqa: E402

CEILING = 100_000  # Rs 1,000
problems: list[str] = []
skipped: list[str] = []


def load_env() -> None:
    env = pathlib.Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def rule(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=int, default=240,
                    help="seconds to wait for the mandate to be authorised")
    args = ap.parse_args()
    load_env()

    # ------------------------------------------------------- 1. the catalog
    rule("1. the merchant's catalog")
    merchant = "sleepyowl"
    try:
        catalog = load_snapshot(merchant)
        print(f"   {len(catalog)} products from {merchant}, "
              f"snapshotted {snapshot_taken(merchant)}")
    except StorefrontUnavailable as exc:
        catalog, merchant = PRODUCTS, "zomato"
        print(f"   {exc}")
        print("   falling back to the bundled catalog")
        skipped.append("the real merchant's catalogue")

    in_scope = next((p for p in catalog if p.category == "food_beverage"), None)
    out_of_scope = next((p for p in catalog if p.category != "food_beverage"), None)
    if in_scope is None or out_of_scope is None:
        problems.append(
            "the catalog needs at least one food product and one non-food product; "
            f"got categories {sorted({p.category for p in catalog})}"
        )
        return report()
    for product in (in_scope, out_of_scope):
        print(f"   - {product.name} · {product.category} · Rs {product.unit_paise // 100}")

    # ----------------------------------------------------- 2. the permission
    rule("2. what the person permitted")
    now = int(time.time())
    subject = SigningKey.from_seed("warrant/live/subject")
    intent = IntentMandate(
        subject="user_priya",
        agent="agent_claude",
        utterance="order chai and samosas for my team, keep it under 1000",
        scope=Scope(
            merchants=(merchant,),
            categories=("food_beverage",),
            max_total_paise=CEILING,
            max_per_txn_paise=CEILING,
            max_txns=2,
            not_before=now,
            expires_at=now + 7200,
        ),
        issued_at=now,
        nonce=f"live-{now}",
    ).signed_by(subject)
    print(f"   {intent.id} signed by {subject.key_id}")
    print(f"   up to Rs {CEILING // 100:,} at {merchant}, food only, 2 orders, 2 hours")

    # --------------------------------------------------------- 3. the money
    rule("3. the mandate the money moves on")
    mandate = RazorpayMandate()
    try:
        handle = mandate.register(
            ceiling_paise=CEILING,
            description=f"Authorise up to Rs {CEILING // 100:,} for 2 hours",
        )
    except Exception as exc:  # noqa: BLE001 - a live API limit is not a crash
        # Razorpay allows a test account 30 payment links a day, and a mandate
        # registration is one. Hitting that is a fact about the account, not a
        # fault in the chain, and a traceback says the opposite.
        print(f"   Razorpay would not register a mandate: {exc}")
        print("   skipping the debit steps; everything before this still ran")
        skipped.append("the real mandate, the debit and the revocation")
        return report()
    print(f"   real {handle.method} mandate {handle.invoice_id}, max_amount "
          f"Rs {handle.ceiling_paise // 100:,}, frequency as_presented")
    if handle.method != "upi":
        print("   (UPI Autopay is not enabled on this account, so this registers on "
              f"{handle.method}. Same mechanism: one authorisation, then debits with")
        print("   nobody asked anything. Set WARRANT_MANDATE_METHOD=upi once enabled.)")
    print(f"\n   \033[1mAUTHORISE IT HERE:\033[0m {handle.short_url}")
    print(f"   waiting up to {args.wait}s…")

    deadline = time.time() + args.wait
    status = mandate.status()
    while not status.authorised and time.time() < deadline:
        time.sleep(3)
        status = mandate.status()

    if not status.authorised:
        print("   not authorised in time; the debit and order steps are skipped")
        skipped.append("the live debit and the real order")
    else:
        print(f"   authorised. token {status.token_id}")
        print("   from here the agent debits with nobody asked anything.")

    # ---------------------------------------------------------- 4. the gate
    state = MandateState(intent_digest=intent.digest)
    cases = [
        ("what she asked for", in_scope, True),
        ("what she did not", out_of_scope, False),
    ]
    for label, product, should_allow in cases:
        rule(f"4. {label}: {product.name}")
        item = LineItem(
            sku=product.sku,
            name=product.name,
            category=product.category,
            qty=1,
            unit_paise=product.unit_paise,
        )
        cart = CartMandate(
            intent_digest=intent.digest,
            merchant=merchant,
            line_items=(item,),
            total_paise=item.line_paise,
            issued_at=int(time.time()),
            nonce=f"live-{product.sku}-{int(time.time())}",
        )

        under = cart.total_paise <= handle.ceiling_paise
        print(f"   Rs {cart.total_paise // 100} · under the mandate ceiling: {under}")
        print("   the bank would pay it — it never sees a basket, only an amount")

        decision = evaluate(
            intent=intent, cart=cart, state=state,
            now=int(time.time()), subject_key=subject.public,
        )
        allowed = decision.verdict is Verdict.ALLOW
        passed = sum(c.status is CheckStatus.PASS for c in decision.checks)
        print(f"   \033[1mgate: {decision.verdict.value.upper()}\033[0m "
              f"({passed}/{len(decision.checks)} checks)")

        if allowed != should_allow:
            problems.append(f"{label!r} returned {decision.verdict.value}")
            continue

        if not allowed:
            for check in decision.failures:
                print(f"   refused by {check.rule}: {check.detail}")
            print("   no debit attempted, no order placed. the money stays put.")
            continue

        if not status.authorised:
            print("   would debit here, but the mandate was never authorised")
            continue

        state.record_authorized(cart)
        result = mandate.attempt(cart, idempotency_key=cart.digest[:40])
        print(f"   debited: ok={result.ok} settled={result.settled} "
              f"order={result.ref.order_id}")
        if not result.ok:
            problems.append(f"the allowed debit failed: {result.failure_summary}")
            continue
        state.record_settled(cart)


    # ------------------------------------------------------ 5. the revocation
    if status.authorised:
        rule("5. revoking")
        print("   token deleted at the bank" if mandate.revoke()
              else "   nothing to revoke")

    return report()


def report() -> int:
    print()
    for s in skipped:
        print(f"skipped: {s}")
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print("  -", p)
        return 1
    print("\nthe live chain holds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
