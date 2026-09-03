"""Capture the screenshots the README embeds, from the console as it is now.

They were taken by hand once and then left behind by four days of redesign, so
the README showed a two-pane cockpit that no longer exists. A reader scrolling
GitHub saw a different product from the one they would get.

    make screenshots

Each shot is framed on the thing its caption claims, rather than on whatever
happened to be in the viewport, and `make docs-check` fails if any of them is
older than the console source.
"""

from __future__ import annotations

import pathlib
import sys

from playwright.sync_api import sync_playwright

import drive

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8899"
OUT = pathlib.Path(__file__).resolve().parents[1] / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

VIEWPORT = {"width": 1440, "height": 900}


def shoot(page, name: str, selector: str | None = None) -> None:
    """Frame the element the caption is about, with room to breathe around it."""
    target = page.locator(selector).first if selector else None
    if target:
        target.scroll_into_view_if_needed()
        page.wait_for_timeout(350)
        box = target.bounding_box()
        if box:
            # Pad the sides and the bottom, never the top: the element sits
            # under a sticky header, and reaching above it crops through the
            # header's own text.
            #
            # Everything is clamped to what is actually rendered. A disclosure
            # that opens below the fold leaves a box the page does not fully
            # cover, and Playwright answers a clip like that with "clipped area
            # is either empty or outside the resulting image" rather than with
            # a smaller picture.
            pad = 24
            page_height = page.evaluate("document.documentElement.scrollHeight")
            x = max(box["x"] - pad, 0)
            y = max(min(box["y"], page_height - 1), 0)
            width = min(box["width"] + pad * 2, VIEWPORT["width"] - x)
            height = min(box["height"] + pad, page_height - y)
            if width > 1 and height > 1:
                page.screenshot(
                    path=str(OUT / f"{name}.png"),
                    clip={"x": x, "y": y, "width": width, "height": height},
                )
                print(f"  captured {name}.png")
                return
    page.screenshot(path=str(OUT / f"{name}.png"))
    print(f"  captured {name}.png (viewport)")


with sync_playwright() as pw:
    browser = pw.chromium.launch()

    # The landing page, which nothing in the README showed at all.
    page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2)
    page.goto(f"{BASE}/", wait_until="networkidle")
    page.wait_for_selector(".lp-open h1", timeout=15_000)
    page.wait_for_timeout(900)
    shoot(page, "01-architecture")

    page.locator(".lp-evidence").scroll_into_view_if_needed()
    page.wait_for_timeout(900)
    shoot(page, "08-evidence-numbers", ".lp-scores")
    page.close()

    # The walkthrough.
    page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2)
    drive.enter(page, BASE)
    page.wait_for_timeout(500)
    shoot(page, "09-permission", ".act")

    drive.scripted_baskets(page)
    page.wait_for_timeout(400)
    shoot(page, "02-decisions", ".decisions")

    # No click: the act seeds itself with whatever this merchant sells that the
    # permission does not cover. Naming a product here was a promise about
    # somebody else's inventory, and it broke the moment the catalogue became
    # a real storefront's.
    drive.step(page, "prevents")
    page.wait_for_selector(".cf-columns", timeout=20_000)
    page.wait_for_timeout(700)
    shoot(page, "07-razorpay", ".cf")

    drive.step(page, "record")
    page.wait_for_selector(".ledger-row", timeout=10_000)
    page.wait_for_timeout(400)
    shoot(page, "03-ledger", ".ledger")

    page.locator(".more > summary", has_text="dispute pack").click()
    page.wait_for_timeout(900)
    shoot(page, "04-evidence", ".doc")

    page.locator(".more > summary", has_text="AP2").click()
    page.wait_for_selector(".cred", timeout=10_000)
    page.wait_for_timeout(500)
    shoot(page, "06-ap2", ".creds")

    page.get_by_role("button", name="Try to rewrite the ledger").click()
    page.wait_for_selector(".notice.stop, .ledger-row.orphaned", timeout=10_000)
    page.wait_for_timeout(500)
    shoot(page, "05-tampered", ".ledger")

    browser.close()

print(f"\nwrote {len(list(OUT.glob('*.png')))} screenshots to {OUT}")
