"""Detect content painted outside the box that is supposed to contain it.

The bug this exists for: a component rendered `className="signer seal"`, and
`seal` happened to be a standalone rule elsewhere in the stylesheet that sets a
46px circle. The label was clamped to 46x46 and its text spilled
across the content beneath it. The build passed, the types passed, all 82 tests
passed, and the page was visibly wrong.

Two generic checks, because the first one alone did not catch it:

  overflow  an element whose content is larger than its own box while its
            computed overflow is `visible` is painting over its neighbours.
            That is what a cascade collision looks like from the outside, and
            it is what catches the bug above. Sibling-box overlap did not.

  overlap   two in-flow siblings whose boxes intersect. Deliberately positioned
            elements (absolute, fixed, transformed, floated) are exempt, since
            overlapping is the whole point of positioning them.

Neither check knows anything about Warrant. Both would catch the next collision
in a component that does not exist yet.
"""

from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8899"

DETECT = """() => {
    const TOLERANCE = 2;          // sub-pixel rounding and 1px hairlines
    const problems = [];
    const spills = [];

    const positioned = el => {
        const s = getComputedStyle(el);
        return s.position !== 'static' || s.transform !== 'none' ||
               s.float !== 'none' || parseFloat(s.opacity) === 0 ||
               s.visibility === 'hidden' || s.display === 'none';
    };

    const describe = el => {
        const cls = typeof el.className === 'string' && el.className
            ? '.' + el.className.trim().split(/\\s+/).join('.')
            : '';
        return el.tagName.toLowerCase() + cls;
    };

    const overlap = (a, b) => {
        const dx = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const dy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        return dx > TOLERANCE && dy > TOLERANCE ? { dx, dy } : null;
    };

    // SVG internals overlap by design -- a tick drawn inside a shield outline
    // is the drawing, not a bug. Only HTML box layout is checked.
    const inSvg = el => el.closest('svg') !== null;

    for (const parent of document.querySelectorAll('body *')) {
        if (inSvg(parent)) continue;
        const kids = [...parent.children].filter(el => {
            if (positioned(el) || inSvg(el)) return false;
            const r = el.getBoundingClientRect();
            return r.width > TOLERANCE && r.height > TOLERANCE;
        });
        for (let i = 0; i < kids.length; i++) {
            for (let j = i + 1; j < kids.length; j++) {
                const hit = overlap(
                    kids[i].getBoundingClientRect(),
                    kids[j].getBoundingClientRect()
                );
                if (hit) {
                    problems.push({
                        parent: describe(parent),
                        a: describe(kids[i]),
                        b: describe(kids[j]),
                        dx: Math.round(hit.dx),
                        dy: Math.round(hit.dy),
                    });
                }
            }
        }
    }
    // -- content escaping its own box ------------------------------------
    for (const el of document.querySelectorAll('body *')) {
        if (inSvg(el)) continue;
        const s = getComputedStyle(el);
        if (s.overflow !== 'visible' || s.display === 'none' || s.display === 'inline') continue;
        const r = el.getBoundingClientRect();
        if (r.width < TOLERANCE || r.height < TOLERANCE) continue;
        const dy = el.scrollHeight - el.clientHeight;
        const dx = el.scrollWidth - el.clientWidth;
        if (dy > TOLERANCE || dx > TOLERANCE) {
            spills.push({
                el: describe(el),
                dx: Math.max(0, Math.round(dx)),
                dy: Math.max(0, Math.round(dy)),
                text: (el.textContent || '').trim().slice(0, 48),
            });
        }
    }

    return { problems, spills };
}"""

STATES = ("first run", "permission derived", "signed", "decisions", "ledger", "evidence")
failures: list[str] = []

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1580, "height": 960})

    def scan(label: str) -> None:
        result = page.evaluate(DETECT)
        found, spills = result["problems"], result["spills"]

        # De-duplicate: one collision repeated down a list is one bug.
        seen: set[tuple[str, ...]] = set()
        unique = []
        for p in found:
            key = (p["parent"], p["a"], p["b"])
            if key not in seen:
                seen.add(key)
                unique.append(p)

        seen_spills: set[str] = set()
        unique_spills = []
        for p in spills:
            if p["el"] not in seen_spills:
                seen_spills.add(p["el"])
                unique_spills.append(p)

        for p in unique:
            failures.append(
                f"{label}: {p['a']} overlaps {p['b']} by {p['dx']}x{p['dy']}px "
                f"inside {p['parent']}"
            )
        for p in unique_spills:
            failures.append(
                f"{label}: {p['el']} spills {p['dx']}x{p['dy']}px outside its box "
                f"({p['text']!r})"
            )

        total = len(unique) + len(unique_spills)
        if total:
            print(f"  FAIL {label}  {len(unique)} overlap, {len(unique_spills)} spill")
        else:
            print(f"  ok   {label}")

    page.goto(BASE, wait_until="networkidle")
    page.wait_for_selector(".explainer", timeout=10_000)
    scan(STATES[0])

    page.get_by_role("button", name="Derive the permission").click()
    page.wait_for_selector(".certificate", timeout=10_000)
    scan(STATES[1])

    page.get_by_role("button", name="Approve and sign with the subject's key").click()
    page.wait_for_selector(".storefront", timeout=10_000)
    page.wait_for_timeout(600)
    scan(STATES[2])

    page.get_by_role("button", name="Run five scripted baskets").click()
    page.wait_for_selector(".decision", timeout=25_000)
    page.wait_for_timeout(600)
    scan(STATES[3])

    page.get_by_role("tab", name="Ledger").click()
    page.wait_for_selector(".ledger-row", timeout=10_000)
    scan(STATES[4])

    page.get_by_role("tab", name="Dispute evidence").click()
    page.wait_for_timeout(800)
    scan(STATES[5])

    browser.close()

print()
if failures:
    print(f"{len(failures)} rendering fault(s):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print(f"nothing overlapping or spilling across {len(STATES)} states")
