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
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "engine"))

from warrant.catalog import line_item  # noqa: E402
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

CEILING = 100_000  # Rs 1,000, the ceiling the sentence asked for
failures: list[str] = []


def load_env() -> None:
    env = pathlib.Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def sku(name: str) -> LineItem:
    return line_item(name, 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-auth", action="store_true")
    ap.add_argument("--wait", type=int, default=180)
    args = ap.parse_args()

    load_env()
    now = int(time.time())

    # ---------------------------------------------------------- the promise
    subject = SigningKey.from_seed("warrant/mandate-walk/subject")
    scope = Scope(
        merchants=("zomato",),
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
        utterance="order chai and samosas for my team from zomato, keep it under 1000",
        scope=scope,
        issued_at=now,
        nonce="mandate-walk",
    )
    intent = intent.signed_by(subject)
    print(f"1. signed permission  {intent.id}")
    print(f"   ceiling Rs {CEILING // 100:,} · zomato · food_beverage · 2 orders · 2 hours")

    # ------------------------------------------------------- the real mandate
    mandate = RazorpayMandate()
    handle = mandate.register(
        ceiling_paise=scope.max_total_paise,
        description=f"Authorise up to Rs {CEILING // 100:,} for 2 hours",
    )
    print(f"\n2. real UPI mandate   {handle.invoice_id}")
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
                merchant="zomato",
                line_items=(sku("chai-6"),),
                total_paise=sku("chai-6").line_paise,
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
        print("   skipped: the gate check and the live debit")
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
        print("   nobody authorised it in time; skipping the debit steps")
        return report()
    print(f"   authorised. token {status.token_id}")
    print("   from here the agent can debit with nobody asked anything.")

    # ------------------------------------------------------------- the gate
    state = MandateState(intent_digest=intent.digest)
    baskets = [
        ("in scope", sku("chai-6"), True),
        ("out of scope", sku("powerbank"), False),
    ]
    for label, item, should_allow in baskets:
        cart = CartMandate(
            intent_digest=intent.digest,
            merchant="zomato",
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


def report() -> int:
    print()
    if failures:
        print(f"{len(failures)} problem(s):")
        for f in failures:
            print("  -", f)
        return 1
    print("the mandate path holds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
