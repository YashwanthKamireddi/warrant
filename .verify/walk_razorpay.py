"""Drive the console against Razorpay test mode and confirm a real order lands.

Deliberately NOT part of `make verify`. That gate must pass for anyone who clones
the repo, and this one needs credentials and a network. Run it yourself:

    uv run warrant serve --port 8842 &
    uv run python .verify/walk_razorpay.py

It selects the Razorpay rail in the console, authorises a basket, and asserts the
decision carries a real order id and a real payment link -- the thing a simulator
cannot fake.
"""

import sys

from playwright.sync_api import sync_playwright

errs = []
with sync_playwright() as pw:
    b = pw.chromium.launch()
    p = b.new_page(viewport={"width": 1580, "height": 960}, device_scale_factor=2)
    p.on("pageerror", lambda e: errs.append(str(e)))
    p.goto(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8842", wait_until="networkidle")
    p.wait_for_selector(".rail-choice", timeout=10_000)
    p.get_by_role("radio", name="Razorpay test mode").click()
    p.get_by_role("button", name="Derive the permission").click()
    p.wait_for_selector(".certificate", timeout=15_000)
    p.get_by_role("button", name="Approve and sign with the subject's key").click()
    p.wait_for_selector(".storefront", timeout=10_000)
    for _ in range(6):
        p.get_by_role("button", name="Add one Masala Chai", exact=True).click()
    p.get_by_role("button", name="Authorise this basket").click()
    p.wait_for_selector(".decision", timeout=30_000)
    p.wait_for_timeout(1200)
    print("verdict:", p.locator(".decision .verdict").first.inner_text())
    print("rail block present:", p.locator(".placed").count())
    if p.locator(".placed").count():
        print("real order:", p.locator(".placed-head .mono").inner_text())
        print("real link :", p.locator(".placed a").get_attribute("href"))
    print("error banner:", p.locator(".notice.stop").count())
    if p.locator(".notice.stop").count():
        print("  ->", p.locator(".notice.stop").first.inner_text()[:200])
    p.wait_for_timeout(600)
    p.screenshot(path="/home/yash/Projects/warrant/.verify/shots/09-razorpay.png")
    order = p.locator(".placed-head .mono").inner_text()
    link = p.locator(".placed a").get_attribute("href")
    b.close()

if errs:
    print("page errors:", errs)
    sys.exit(1)
if not order.startswith("order_"):
    print(f"expected a real Razorpay order id, got {order!r}")
    sys.exit(1)
if not (link or "").startswith("https://rzp.io/"):
    print(f"expected a real Razorpay payment link, got {link!r}")
    sys.exit(1)
print(f"\nreal order {order} with payment link {link}")
