"""Drive the console in a real browser and capture what a reviewer would see.

A green build says the TypeScript compiled. It says nothing about whether the
page renders, whether the API answers, or whether anything throws at runtime.
This walks the whole flow and fails loudly on any console error.
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8801"
OUT = Path(__file__).parent / "shots"
OUT.mkdir(exist_ok=True)

errors: list[str] = []


def shot(page, name: str) -> None:
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=False)
    print(f"  captured {name}.png")


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1580, "height": 960}, device_scale_factor=2)

    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}")
            if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

    print(f"opening {BASE}")
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_selector(".brand-words b", timeout=10_000)
    shot(page, "01-initial")

    print("deriving the permission")
    page.get_by_role("button", name="Derive the permission").click()
    page.wait_for_selector(".certificate", timeout=10_000)
    shot(page, "02-derived")

    print("approving and signing")
    page.get_by_role("button", name="Approve and sign with the subject's key").click()
    page.wait_for_selector(".storefront", timeout=10_000)
    page.wait_for_timeout(600)
    shot(page, "03-signed")

    print("running the five scripted baskets")
    page.get_by_role("button", name="Run five scripted baskets").click()
    page.wait_for_selector(".decision", timeout=20_000)
    page.wait_for_timeout(900)
    shot(page, "04-decisions")

    verdicts = page.locator(".decision .verdict").all_inner_texts()
    print(f"  verdicts: {verdicts}")
    expected = ["ALLOW", "BLOCK", "BLOCK", "BLOCK", "ESCALATE"]
    if verdicts != expected:
        errors.append(f"verdicts {verdicts} != {expected} printed by `warrant demo`")

    print("opening the ledger")
    page.get_by_role("tab", name="Ledger").click()
    page.wait_for_selector(".ledger-row", timeout=10_000)
    shot(page, "05-ledger")

    print("opening the dispute evidence")
    page.get_by_role("tab", name="Dispute evidence").click()
    page.wait_for_timeout(900)
    shot(page, "06-evidence")

    print("tampering with the ledger")
    page.get_by_role("button", name="Tamper with the ledger").click()
    page.wait_for_selector(".notice.stop, .ledger-row.orphaned", timeout=10_000)
    page.wait_for_timeout(500)
    shot(page, "07-tampered")

    browser.close()

print()
if errors:
    print(f"{len(errors)} console problem(s):")
    for e in errors[:20]:
        print("  -", e)
    sys.exit(1)
print("no console errors")
