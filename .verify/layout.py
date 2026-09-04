"""Assert the frame holds at every viewport a reviewer might open it at.

Layout bugs are the ones a build cannot catch and a single screenshot hides. The
invariants below are the ones that would actually cost someone a demo:

  * the page itself never scrolls -- this is an app frame, not a document
  * nothing overflows horizontally, at any width a reviewer might open it at
  * long content scrolls inside the work area rather than pushing the frame
  * what you permitted, and where the money stands, are always on screen
  * the actions are reachable on arrival, not below whatever just happened
  * nothing is ever wider than a readable measure
  * inside the proof drawer, the two destructive actions stay in view
"""

from __future__ import annotations

import sys

import drive
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8805"
# The console shipped a horizontal scrollbar below 860px for weeks because
# this tuple started at 1280. A reviewer opens things on a laptop with a
# sidebar, or a phone; the narrow end is where layout actually breaks.
VIEWPORTS = (
    (1920, 1080),
    (1580, 960),
    (1440, 900),
    (1366, 768),
    (1280, 720),
    (1024, 768),
    (900, 900),
    (820, 1180),
    (768, 1024),
    (430, 932),
    (390, 844),
)

failures: list[str] = []

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for width, height in VIEWPORTS:
        page = browser.new_page(viewport={"width": width, "height": height})
        drive.enter(page, BASE, agent="manual")
        # Wait for the live agent rather than a guessed delay, then add the
        # five reference baskets so the feed is as long as it ever gets.
        drive.scripted_baskets(page)

        checks = page.evaluate(
            """() => {
                const q = s => document.querySelector(s);
                const inView = el => {
                    const r = el.getBoundingClientRect();
                    return r.top >= 0 && r.bottom <= window.innerHeight;
                };
                const stage = q('.work');
                return {
                    bodyScrollsY: document.documentElement.scrollHeight > window.innerHeight + 1,
                    bodyScrollsX: document.documentElement.scrollWidth > window.innerWidth + 1,
                    stageOverflowsX: stage.scrollWidth > stage.clientWidth + 1,
                    // What you permitted is the frame for everything else, so
                    // it is on screen when you arrive.
                    permVisible: !!q('.perm') && !!q('.bounds li'),
                    // Where the money stands never scrolls away.
                    moneyVisible: inView(q('.money')),
                    // And the thing to press is reachable without first
                    // scrolling past whatever the agent just did.
                    actionInView: inView(q('.live-do .btn-primary')),
                    // A line of text wider than about 90 characters stops being
                    // readable. The measure is the whole reason for the column.
                    tooWide: Math.max(
                        q('.perm').getBoundingClientRect().width,
                        q('.live').getBoundingClientRect().width,
                    ) > 900,
                    stageScrolls: stage.scrollHeight > stage.clientHeight,
                    decisions: document.querySelectorAll('.entry').length,
                };
            }"""
        )

        label = f"{width}x{height}"
        problems = []
        if checks["bodyScrollsY"]:
            problems.append("the page itself scrolls vertically")
        if checks["bodyScrollsX"]:
            problems.append("the page scrolls horizontally")
        if checks["stageOverflowsX"]:
            problems.append("the stage overflows horizontally")
        if not checks["permVisible"]:
            problems.append("what you permitted is not on screen")
        if not checks["moneyVisible"]:
            problems.append("where the money stands is not visible")
        if not checks["actionInView"]:
            problems.append("the primary action is not in the viewport")
        if checks["tooWide"]:
            problems.append("a column is wider than a readable measure")
        if checks["decisions"] < 5:
            problems.append(f"expected at least 5 entries, rendered {checks['decisions']}")

        # The record grows an entry per decision, and the two things worth
        # pressing beside it sat underneath all of them. On a laptop you
        # scrolled past a table to discover there was anything to do, which is
        # the difference between a demo that lands and one that reads as a log
        # viewer. The table scrolls inside itself now; this is what holds it.
        if height >= 700:
            drive.open_proof(page)
            page.wait_for_selector(".ledger-row", timeout=20_000)
            page.wait_for_timeout(400)
            hidden = page.evaluate(
                """() => {
                    const names = ['Try to rewrite the ledger', 'Revoke the permission'];
                    const buttons = [...document.querySelectorAll('button')];
                    return names.filter(name => {
                        const el = buttons.find(b => b.innerText.trim().startsWith(name));
                        if (!el) return true;
                        const r = el.getBoundingClientRect();
                        return r.top < 0 || r.bottom > window.innerHeight;
                    });
                }"""
            )
            for name in hidden:
                problems.append(f"the proof drawer's “{name}” is not reachable without scrolling")

        if problems:
            failures.extend(f"{label}: {p}" for p in problems)
            print(f"  FAIL {label}  " + "; ".join(problems))
        else:
            print(f"  ok   {label}  frame holds, stage scrolls: {checks['stageScrolls']}")
        page.close()
    browser.close()

print()
if failures:
    print(f"{len(failures)} layout failure(s)")
    sys.exit(1)
print(f"frame holds at all {len(VIEWPORTS)} viewports")
