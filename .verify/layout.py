"""Assert the frame holds at every viewport a reviewer might open it at.

Layout bugs are the ones a build cannot catch and a single screenshot hides. The
invariants below are the ones that would actually cost someone a demo:

  * the page itself never scrolls -- this is an app frame, not a document
  * the primary action is always reachable without scrolling to find it
  * long content scrolls inside its own pane rather than pushing the frame
  * nothing overflows horizontally
"""

from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8805"
VIEWPORTS = ((1920, 1080), (1580, 960), (1440, 900), (1366, 768), (1280, 720))

failures: list[str] = []

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for width, height in VIEWPORTS:
        page = browser.new_page(viewport={"width": width, "height": height})
        page.goto(f"{BASE}/#workspace", wait_until="networkidle")
        page.get_by_role("button", name="Derive the permission").click()
        page.wait_for_selector(".certificate", timeout=10_000)
        page.get_by_role("button", name="Approve and sign with the subject's key").click()
        page.wait_for_selector(".storefront", timeout=10_000)
        page.get_by_role("button", name="Run five scripted baskets").click()
        # Wait for every decision, not for the first one plus a guessed delay.
        # The scripted run issues five sequential requests, so a fixed timeout
        # races them and fails intermittently on a slower machine.
        page.wait_for_function(
            "document.querySelectorAll('.decision').length === 5", timeout=30_000
        )

        checks = page.evaluate(
            """() => {
                const q = s => document.querySelector(s);
                const inView = el => {
                    const r = el.getBoundingClientRect();
                    return r.top >= 0 && r.bottom <= window.innerHeight;
                };
                const authorise = [...document.querySelectorAll('.rail-actions .btn-primary')][0];
                return {
                    bodyScrollsY: document.documentElement.scrollHeight > window.innerHeight + 1,
                    bodyScrollsX: document.documentElement.scrollWidth > window.innerWidth + 1,
                    railOverflows: q('.rail').scrollHeight > q('.rail').clientHeight + 1,
                    authoriseInView: authorise ? inView(authorise) : false,
                    paneScrolls: q('.pane').scrollHeight > q('.pane').clientHeight,
                    statusVisible: inView(q('.statusbar')),
                    decisions: document.querySelectorAll('.decision').length,
                };
            }"""
        )

        label = f"{width}x{height}"
        problems = []
        if checks["bodyScrollsY"]:
            problems.append("the page itself scrolls vertically")
        if checks["bodyScrollsX"]:
            problems.append("the page scrolls horizontally")
        if checks["railOverflows"]:
            problems.append("the rail overflows instead of scrolling its panes")
        if not checks["authoriseInView"]:
            problems.append("the primary action is not in the viewport")
        if not checks["statusVisible"]:
            problems.append("the status bar is not visible")
        if checks["decisions"] != 5:
            problems.append(f"expected 5 decisions, rendered {checks['decisions']}")

        if problems:
            failures.extend(f"{label}: {p}" for p in problems)
            print(f"  FAIL {label}  " + "; ".join(problems))
        else:
            print(f"  ok   {label}  frame holds, pane scrolls: {checks['paneScrolls']}")
        page.close()
    browser.close()

print()
if failures:
    print(f"{len(failures)} layout failure(s)")
    sys.exit(1)
print(f"frame holds at all {len(VIEWPORTS)} viewports")
