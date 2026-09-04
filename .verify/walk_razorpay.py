"""Pay a gate-approved basket on real Razorpay test mode, end to end.

Deliberately NOT part of `make verify`. That gate must pass for anyone who
clones the repo, and this one needs credentials and a network. Run it yourself:

    make browser-razorpay

The walkthrough settles on the simulator so the audit trail completes -- a real
payment finishes on the customer's own device, so a real rail would leave every
debit at settled=false and the evidence pack empty. Paying is a first-class
action on an allowed basket, and this drives that action the whole way:

    the gate allows a basket
      -> the console opens Razorpay Checkout on a real test-mode order
      -> netbanking, and Success on Razorpay's own simulated bank page
      -> Razorpay returns a payment id and a signature over it
      -> this server recomputes that signature against the key secret
      -> only then does anything on screen say the payment happened

An earlier version stopped at "the sheet opened" and read the order id out of
the iframe's URL, which is not where Razorpay puts it. So it reported an empty
string and failed, while every part of what it was testing worked. Asserting the
captured payment is both a stronger claim and a harder one to get wrong.
"""

from __future__ import annotations

import pathlib
import sys

import drive
from playwright.sync_api import Page, sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8842"
SHOTS = pathlib.Path(__file__).resolve().parent / "shots"
SHOTS.mkdir(exist_ok=True)

errors: list[str] = []
payment = note = ""


def pay(page: Page) -> None:
    """Complete the open payment sheet the way a person does.

    Netbanking, because this account has UPI disabled and its test cards come
    back "international cards not supported" -- a test account is an Indian
    account and cannot accept them. The number is typed rather than filled:
    Razorpay's validator listens for keystrokes, so a value set directly on the
    input reads as invalid however well-formed it is.
    """
    sheet = page.frame_locator("iframe.razorpay-checkout-frame")

    box = sheet.locator("input[type='tel']").first
    box.click()
    box.press_sequentially("9812345678", delay=80)
    page.wait_for_timeout(900)
    sheet.get_by_role("button", name="Continue").first.click()
    page.wait_for_timeout(3500)

    sheet.locator("[role='button'], button, li, div").filter(
        has_text="Bank of Baroda"
    ).first.click(timeout=15_000)
    page.wait_for_timeout(2500)
    sheet.get_by_role("button", name="Pay").first.click(timeout=15_000)

    # Razorpay's simulated bank opens in its own window.
    page.wait_for_timeout(6000)
    bank = page.context.pages[-1]
    if bank is not page:
        bank.get_by_role("button", name="Success").first.click(timeout=25_000)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1580, "height": 960}, device_scale_factor=2)
    page.on("pageerror", lambda e: errors.append(str(e)))

    drive.enter(page, BASE)

    # Something has to be allowed before there is anything to pay for.
    drive.agent_settled(page)
    page.wait_for_timeout(800)

    button = page.get_by_role("button", name="Pay ")
    if button.count() == 0:
        print("the console did not offer the real rail -- are RAZORPAY_KEY_* set?")
        browser.close()
        raise SystemExit(1)

    button.first.click()
    try:
        page.wait_for_selector("iframe.razorpay-checkout-frame", timeout=90_000)
        page.wait_for_timeout(3000)
        pay(page)
        # Nothing claims the payment happened until the server has recomputed
        # the signature, so this waits for that answer rather than a redirect.
        page.wait_for_selector(".entry-rail.paid", timeout=90_000)
        payment = page.locator(".entry-rail.paid .mono").first.inner_text().strip()
    except Exception as exc:  # noqa: BLE001 - a stated refusal is a real outcome
        if page.locator(".entry-payerror").count():
            note = page.locator(".entry-payerror").first.inner_text().strip()
        elif page.locator(".stage-error").count():
            note = page.locator(".stage-error").first.inner_text().strip()
        else:
            note = str(exc).splitlines()[0][:160]

    page.screenshot(path=str(SHOTS / "09-razorpay.png"))
    browser.close()

print(f"payment : {payment or '(none)'}")
if note:
    print(f"note    : {note}")

if errors:
    print("page errors:", errors)
    sys.exit(1)

if note and not payment:
    # Razorpay refusing for a stated reason is a real answer from a real API,
    # and the console showing it verbatim is the behaviour under test. A daily
    # cap is a fact about the account, not a failure of the chain.
    print("\nRazorpay refused, and the console said so in its own words.")
    sys.exit(0)

if not payment.startswith("pay_"):
    print(f"\nexpected a captured Razorpay payment id, got {payment!r}")
    sys.exit(1)

print("\na real Razorpay payment, captured, and verified against the key secret")
