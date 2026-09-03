"""Drive the console in a real browser and capture what a reviewer would see.

A green build says the TypeScript compiled. It says nothing about whether the
page renders, whether the API answers, or whether anything throws at runtime.
This walks the whole flow and fails loudly on any console error.
"""

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

import drive

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

    started_with: list[str] = []

    def _watch_session_start(request) -> None:
        if request.method != "POST" or not request.url.endswith("/api/sessions"):
            return
        try:
            started_with.append(json.loads(request.post_data or "{}").get("rail", ""))
        except ValueError:
            started_with.append("")

    page.on("request", _watch_session_start)


    print("the landing page")
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_selector(".lp-open h1", timeout=10_000)
    page.wait_for_timeout(400)
    shot(page, "00-landing")
    for required in (".lp-open", ".lp-gap", ".lp-evidence", ".lp-chain", ".lp-specs", ".lp-end"):
        if page.locator(required).count() == 0:
            errors.append(f"landing page is missing {required}")
    # Reveal-on-scroll must never be the reason a reader cannot read something.
    # If the observer fails to fire, the page is blank and the build should say so.
    page.locator(".lp-end").scroll_into_view_if_needed()
    page.wait_for_timeout(900)
    unread = page.evaluate(
        "() => [...document.querySelectorAll('.lp-open [data-reveal], .lp-end [data-reveal]')]"
        "  .filter(e => getComputedStyle(e).opacity === '0').length"
    )
    if unread:
        errors.append(f"{unread} landing elements never revealed")
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(400)
    page.get_by_role("button", name="See it work").first.click()
    page.wait_for_selector(".shell", timeout=10_000)

    print(f"opening {BASE}")

    # What the console actually asked the API for, so the chip can be held to
    # it. The app bar said "Razorpay test mode" while the bootstrap posted
    # rail="simulated" -- the console asserting a real rail and running on the
    # simulator, which is incident 2 in INCIDENTS.md happening a second time.
    drive.enter(page, BASE)

    claimed = page.locator(".appbar .pill").last.inner_text().strip().lower()
    asked_for = started_with[-1] if started_with else ""
    if not asked_for:
        errors.append("the console never told the API which rail to use")
    elif ("razorpay" in claimed) != (asked_for == "razorpay"):
        errors.append(
            f"the app bar claims {claimed!r} while the session was started on "
            f"{asked_for!r}"
        )
    else:
        print(f"  rail claimed and used agree: {asked_for}")
    page.wait_for_timeout(500)
    shot(page, "01-initial")

    # Step 1 must open on a signed permission with no clicking. A visitor who
    # has to operate a form before seeing anything real has already left.
    if page.locator(".seal.unsigned").count():
        errors.append("step 1 opened unsigned; the bootstrap did not sign")
    shot(page, "02-derived")
    page.locator(".terms-more > summary").click()
    page.wait_for_timeout(250)
    shot(page, "03-signed")

    print("running the five scripted baskets")
    drive.scripted_baskets(page)
    page.wait_for_timeout(400)
    shot(page, "04-decisions")

    verdicts = page.locator(".decision .verdict").all_inner_texts()
    print(f"  verdicts: {verdicts}")
    expected = ["ALLOW", "BLOCK", "BLOCK", "BLOCK", "ESCALATE"]
    if verdicts != expected:
        errors.append(f"verdicts {verdicts} != {expected} printed by `warrant demo`")

    print("opening what it prevents")
    drive.step(page, "prevents")
    # Ask the page which product is out of category rather than naming one. The
    # catalogue is a real merchant's now, so a hard-coded product name is a
    # promise about somebody else's inventory.
    out_of_scope = page.evaluate(
        "() => { const el = [...document.querySelectorAll('.product')]"
        "  .find(e => /electronics|merchandise|equipment|apparel/i.test(e.innerText));"
        "  return el ? el.querySelector('button[aria-label^=\"Add one\"]')"
        "    ?.getAttribute('aria-label') : null; }"
    )
    if not out_of_scope:
        errors.append("the storefront offers nothing outside the mandate's categories")
    else:
        page.get_by_role("button", name=out_of_scope).click()
    page.wait_for_selector(".cf-columns", timeout=15_000)
    page.wait_for_timeout(700)
    shot(page, "09-counterfactual")
    if page.locator(".cf-amount.bad").count() == 0:
        errors.append("counterfactual did not render the loss figure")

    print("opening the ledger")
    drive.step(page, "record")
    page.wait_for_selector(".ledger-row", timeout=10_000)
    shot(page, "05-ledger")

    print("opening the dispute evidence")
    page.locator(".more > summary", has_text="dispute pack").click()
    page.wait_for_timeout(900)
    shot(page, "06-evidence")

    print("opening the AP2 export")
    page.locator(".more > summary", has_text="AP2").click()
    page.wait_for_selector(".cred", timeout=10_000)
    page.wait_for_timeout(500)
    shot(page, "08-standards")
    creds = page.locator(".cred-kind").all_inner_texts()
    if creds != ["IntentMandate", "CartMandate", "PaymentMandate"]:
        errors.append(f"AP2 export rendered {creds}")
    proofs = page.locator(".cred-proof").all_inner_texts()
    if any("unsigned" in p for p in proofs):
        errors.append(f"AP2 export reported an unsigned credential: {proofs}")
    signers = {p.split("·")[-1].strip() for p in proofs}
    if len(signers) < 2:
        errors.append("AP2 export does not show the subject and authorizer as different signers")

    # The tamper button destroys a property, so the property has to be visible
    # before it is destroyed. An intact chain that says nothing leaves the
    # demonstration with no "before".
    if page.locator(".notice.ok").count() == 0:
        errors.append("the ledger does not say the chain is intact before tampering")

    print("tampering with the ledger")
    page.get_by_role("button", name="Try to rewrite the ledger").click()
    page.wait_for_selector(".notice.stop, .ledger-row.orphaned", timeout=10_000)
    page.wait_for_timeout(500)
    if page.locator(".notice.ok").count() != 0:
        errors.append("the chain still claims to be intact after being tampered with")
    shot(page, "07-tampered")

    browser.close()

print()
if errors:
    print(f"{len(errors)} console problem(s):")
    for e in errors[:20]:
        print("  -", e)
    sys.exit(1)
print("no console errors")
