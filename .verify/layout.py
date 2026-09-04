"""Assert the frame holds at every viewport a reviewer might open it at.

Layout bugs are the ones a build cannot catch and a single screenshot hides. The
invariants below are the ones that would actually cost someone a demo:

  * the page itself never scrolls -- this is an app frame, not a document
  * nothing overflows horizontally, at any width a reviewer might open it at
  * long content scrolls inside the stage rather than pushing the frame
  * the walkthrough and its next/back control are always reachable
  * the act being read is never wider than its measure
  * the record's two actions are reachable without scrolling past the record
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
        drive.enter(page, BASE)
        # Wait for every decision, not for the first one plus a guessed delay.
        # The scripted run issues five sequential requests, so a fixed timeout
        # races them and fails intermittently on a slower machine.
        drive.scripted_baskets(page)

        checks = page.evaluate(
            """() => {
                const q = s => document.querySelector(s);
                const inView = el => {
                    const r = el.getBoundingClientRect();
                    return r.top >= 0 && r.bottom <= window.innerHeight;
                };
                const stage = q('.stage');
                return {
                    bodyScrollsY: document.documentElement.scrollHeight > window.innerHeight + 1,
                    bodyScrollsX: document.documentElement.scrollWidth > window.innerWidth + 1,
                    stageOverflowsX: stage.scrollWidth > stage.clientWidth + 1,
                    stepsVisible: !!q('.stepbtn') && inView(q('.steps')),
                    // Four bare numbers are not navigation. Whatever else the
                    // stepper drops on a narrow screen, the step you are on
                    // keeps its name.
                    currentStepNamed:
                        (q('.stepbtn.on')?.innerText || '').replace(/[0-9\s]/g, '')
                            .length > 0,
                    navVisible: inView(q('.stagenav')),
                    nextInView: inView(q('.stagenav .btn-primary')),
                    // A line of text wider than about 90 characters stops being
                    // readable. The measure is the whole reason for the column.
                    actTooWide: q('.act').getBoundingClientRect().width > 820,
                    stageScrolls: stage.scrollHeight > stage.clientHeight,
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
        if checks["stageOverflowsX"]:
            problems.append("the stage overflows horizontally")
        if not checks["stepsVisible"]:
            problems.append("the walkthrough steps are not visible")
        if not checks["currentStepNamed"]:
            problems.append("the current step shows only a number, not its name")
        if not checks["navVisible"]:
            problems.append("the stage nav is not visible")
        if not checks["nextInView"]:
            problems.append("the primary action is not in the viewport")
        if checks["actTooWide"]:
            problems.append("the act is wider than a readable measure")
        if checks["decisions"] != 5:
            problems.append(f"expected 5 decisions, rendered {checks['decisions']}")

        # The record grows an entry per decision, and the two things worth
        # pressing on that screen sat underneath all of them. On a laptop you
        # scrolled past a table to discover there was anything to do, which is
        # the difference between a demo that lands and one that reads as a log
        # viewer. The table scrolls inside itself now; this is what holds it.
        if height >= 700:
            drive.step(page, "record")
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
                problems.append(f"the record's “{name}” is not reachable without scrolling")

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
