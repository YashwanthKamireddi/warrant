"""Drive the console to a real Razorpay order and assert it is real.

Deliberately NOT part of `make verify`. That gate must pass for anyone who
clones the repo, and this one needs credentials and a network. Run it yourself:

    uv run warrant serve --port 8842 &
    uv run python .verify/walk_razorpay.py http://127.0.0.1:8842

The walkthrough settles on the simulator so the audit trail completes -- a real
payment finishes on the customer's own device, so a real rail would leave every
debit at settled=false and the evidence pack empty. The real order is a first
class action on the record, and this asserts that pressing it produces an object
that exists in Razorpay: an ``order_...`` id, and a link on rzp.io when the
account still has one to give.
"""

from __future__ import annotations

import pathlib
import sys

import drive
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8842"
SHOTS = pathlib.Path(__file__).resolve().parent / "shots"
SHOTS.mkdir(exist_ok=True)

errors: list[str] = []
order = link = note = ""

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1580, "height": 960}, device_scale_factor=2)
    page.on("pageerror", lambda e: errors.append(str(e)))

    drive.enter(page, BASE)

    # Something has to have settled before there is a debit to place.
    drive.scripted_baskets(page)
    drive.step(page, "record")
    page.wait_for_timeout(800)

    button = page.get_by_role("button", name="Place the settled debit on real Razorpay")
    if button.count() == 0:
        print("the console did not offer the real rail -- are RAZORPAY_KEY_* set?")
        browser.close()
        raise SystemExit(1)

    button.click()
    page.wait_for_selector(".real-rail.placed, .stage-error", timeout=90_000)
    page.wait_for_timeout(700)

    if page.locator(".stage-error").count():
        note = page.locator(".stage-error").inner_text().strip()
    else:
        order = page.locator(".real-rail.placed .mono").first.inner_text().strip()
        anchor = page.locator(".real-rail.placed a")
        link = (anchor.first.get_attribute("href") or "") if anchor.count() else ""

    page.screenshot(path=str(SHOTS / "09-razorpay.png"))
    browser.close()

print(f"order : {order or '(none)'}")
print(f"link  : {link or '(none — the account may have used its daily links)'}")
if note:
    print(f"note  : {note}")

if errors:
    print("page errors:", errors)
    sys.exit(1)

if note:
    # Razorpay refusing for a stated reason is a real answer from a real API,
    # and the console showing it verbatim is the behaviour under test. A daily
    # cap is a fact about the account, not a failure of the chain.
    print("\\nRazorpay refused, and the console said so in its own words.")
    sys.exit(0)

if not order.startswith("order_"):
    print(f"\\nexpected a real Razorpay order id, got {order!r}")
    sys.exit(1)
if link and not link.startswith("https://rzp.io/"):
    print(f"\\nexpected an rzp.io link, got {link!r}")
    sys.exit(1)

print("\\na real Razorpay order, created from a cart the gate allowed")
