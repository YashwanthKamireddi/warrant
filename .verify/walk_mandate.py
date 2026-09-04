"""Drive a real UPI Autopay mandate end to end against Razorpay test mode.

This is the live counterpart to ``tests/test_razorpay_mandate.py``. Nothing here
is faked: it registers a real mandate on your test account, waits for you to
authorise it on the real Razorpay page, then puts two baskets through the gate --
one the signed permission covers and one it does not -- and debits the mandate
for whichever one survives.

    uv run python .verify/walk_mandate.py

The interesting moment is the second basket. The mandate's ``max_amount`` is
happy to pay for it: it is well under the ceiling, and the bank has no idea what
is in it. The only reason the money does not move is the gate.

Pass --skip-auth to check registration and refusal without authorising, which is
what CI does; the debit steps are then reported as skipped rather than passed.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "engine"))

import drive  # noqa: E402

from warrant.catalog import PRODUCTS, Product  # noqa: E402
from warrant.crypto import SigningKey  # noqa: E402
from warrant.gate import MandateState, evaluate  # noqa: E402
from warrant.models import (  # noqa: E402
    CartMandate,
    IntentMandate,
    LineItem,
    Scope,
    Verdict,
)
from warrant.rails.razorpay_mandate import (  # noqa: E402
    MandateNotAuthorised,
    RazorpayMandate,
)
from warrant.storefront import StorefrontUnavailable, load_snapshot  # noqa: E402

CEILING = 100_000  # Rs 1,000, the ceiling the sentence asked for
failures: list[str] = []
skipped: list[str] = []




def one(product: Product) -> LineItem:
    return LineItem(
        sku=product.sku,
        name=product.name,
        category=product.category,
        qty=1,
        unit_paise=product.unit_paise,
    )


def pick() -> tuple[str, Product, Product]:
    """One thing the permission covers and one it does not, from a real shop.

    Naming SKUs here was a promise about somebody else's inventory. It broke the
    moment the default catalogue became a real storefront's: ``chai-6`` is not
    something Sleepy Owl sells, so the script died before it reached the mandate
    it exists to test.
    """
    try:
        catalog = load_snapshot("sleepyowl")
        merchant = "sleepyowl"
    except StorefrontUnavailable:
        catalog, merchant = PRODUCTS, "zomato"
    orderable = [p for p in catalog if not p.sku.startswith("warrant-")]
    covered = next(p for p in orderable if p.category == "food_beverage")
    other = next(p for p in orderable if p.category != "food_beverage")
    return merchant, covered, other


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-auth", action="store_true")
    ap.add_argument("--wait", type=int, default=180)
    args = ap.parse_args()

    drive.load_env()
    now = int(time.time())
    merchant, covered, uncovered = pick()

    # ---------------------------------------------------------- the promise
    subject = SigningKey.from_seed("warrant/mandate-walk/subject")
    scope = Scope(
        merchants=(merchant,),
        categories=("food_beverage",),
        max_total_paise=CEILING,
        max_per_txn_paise=CEILING,
        max_txns=2,
        not_before=now,
        expires_at=now + 7200,
    )
    intent = IntentMandate(
        subject="user_priya",
        agent="agent_claude",
        utterance=f"order coffee for my team from {merchant}, keep it under 1000",
        scope=scope,
        issued_at=now,
        nonce="mandate-walk",
    )
    intent = intent.signed_by(subject)
    print(f"1. signed permission  {intent.id}")
    print(f"   ceiling Rs {CEILING // 100:,} · {merchant} · food_beverage · 2 orders · 2 hours")

    # ------------------------------------------------------- the real mandate
    mandate = RazorpayMandate()
    try:
        handle = mandate.register(
            ceiling_paise=scope.max_total_paise,
            description=f"Authorise up to Rs {CEILING // 100:,} for 2 hours",
        )
    except Exception as exc:  # noqa: BLE001 - a live API limit is not a crash
        # A test account gets 30 payment links a day and registering a mandate
        # spends one. Hitting that is a fact about the account, not a fault in
        # anything under test, and a traceback tells the reader the opposite.
        print(f"\n2. Razorpay would not register a mandate: {exc}")
        skipped.append("the real mandate, the debit and the revocation")
        return report()
    print(f"\n2. real {handle.method} mandate   {handle.invoice_id}")
    print(f"   max_amount Rs {handle.ceiling_paise // 100:,}, frequency as_presented")
    print(f"   authorise it here: {handle.short_url}")

    status = mandate.status()
    if status.authorised:
        failures.append("a freshly registered mandate reported itself authorised")
    print(f"   status {status.status}, token {status.token_id or 'not yet minted'}")

    # A debit before anyone authorised must be refused without touching the API.
    try:
        mandate.attempt(
            CartMandate(
                intent_digest=intent.digest,
                merchant=merchant,
                line_items=(one(covered),),
                total_paise=one(covered).line_paise,
                issued_at=now,
                nonce="pre-auth",
            ),
            idempotency_key="pre-auth",
        )
        failures.append("debiting an unauthorised mandate was allowed")
    except MandateNotAuthorised:
        print("   a debit before authorisation is refused, as it must be")

    if args.skip_auth:
        print("\n3. --skip-auth: not waiting for authorisation")
        skipped.append("the gate check and the live debit")
        return report()

    # ---------------------------------------------------------- authorisation
    print(f"\n3. waiting up to {args.wait}s for you to authorise that link…")
    deadline = time.time() + args.wait
    while time.time() < deadline:
        status = mandate.status()
        if status.authorised:
            break
        time.sleep(3)
    if not status.authorised:
        print("   nobody authorised it in time")
        skipped.append("the debit and the revocation")
        return report()
    print(f"   authorised. token {status.token_id}")
    print("   from here the agent can debit with nobody asked anything.")

    # ------------------------------------------------------------- the gate
    state = MandateState(intent_digest=intent.digest)
    baskets = [
        ("in scope", one(covered), True),
        ("out of scope", one(uncovered), False),
    ]
    for label, item, should_allow in baskets:
        cart = CartMandate(
            intent_digest=intent.digest,
            merchant=merchant,
            line_items=(item,),
            total_paise=item.line_paise,
            issued_at=int(time.time()),
            nonce=f"walk-{item.sku}",
        )
        decision = evaluate(
            intent=intent, cart=cart, state=state, now=int(time.time()),
            subject_key=subject.public,
        )
        allowed = decision.verdict is Verdict.ALLOW
        under_ceiling = cart.total_paise <= handle.ceiling_paise
        print(f"\n4. {label}: {item.name} Rs {item.line_paise // 100}")
        print(f"   under the mandate ceiling: {under_ceiling}  ->  the bank would pay it")
        print(f"   gate: {decision.verdict.value.upper()}")
        if allowed != should_allow:
            failures.append(f"{label} basket returned {decision.verdict.value}")
            continue

        if not allowed:
            reasons = [c.rule for c in decision.failures]
            print(f"   refused by {', '.join(reasons)} — no debit is attempted at all")
            continue

        state.record_authorized(cart)
        result = mandate.attempt(cart, idempotency_key=cart.digest[:40])
        print(f"   debited: ok={result.ok} settled={result.settled} "
              f"order={result.ref.order_id} payment={result.ref.payment_id}")
        if not result.ok:
            failures.append(f"the in-scope debit failed: {result.failure_summary}")
        else:
            state.record_settled(cart)

    # ------------------------------------------------------------- revocation
    print("\n5. revoking the mandate at the bank")
    if mandate.revoke():
        print("   token deleted; the agent cannot debit again")
    else:
        failures.append("revoking an authorised mandate reported nothing to revoke")

    return report()


def plural(n: int) -> str:
    return "one leg" if n == 1 else f"{n} legs"


def report() -> int:
    print()
    for s in skipped:
        print(f"skipped: {s}")
    if failures:
        print(f"{len(failures)} problem(s):")
        for f in failures:
            print("  -", f)
        return 1
    print("the mandate path holds" if not skipped
          else f"what ran, held. {plural(len(skipped))} never ran — see above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
