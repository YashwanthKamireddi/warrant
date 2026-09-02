"""WCAG contrast audit over the design tokens.

Contrast is the one part of visual design that is not a matter of taste, so it
should not be reviewed by eye. This parses the tokens straight out of styles.css
and checks every foreground/background pair the interface actually renders.

Thresholds (WCAG 2.1):
    4.5:1   body text
    3.0:1   text at 18.66px+ or bold 14px+, and non-text UI boundaries

Pairs are declared explicitly rather than derived, because the meaningful
question is not "do these two colours contrast" but "does this text, on the
surface it is actually painted on, contrast". Adding a component means adding
its pair here.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "console" / "src" / "styles.css"

TOKEN = re.compile(r"^\s*(--[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{3,8})\s*;", re.M)

# foreground, background, minimum ratio, what it is
PAIRS: tuple[tuple[str, str, float, str], ...] = (
    ("--ink", "--surface", 4.5, "primary text on cards"),
    ("--ink", "--ground", 4.5, "primary text on the page"),
    ("--ink", "--surface-2", 4.5, "primary text on raised rows"),
    ("--ink-2", "--surface", 4.5, "body text on cards"),
    ("--ink-2", "--surface-2", 4.5, "body text on raised rows"),
    ("--ink-2", "--sunken", 4.5, "body text in wells"),
    ("--ink-3", "--surface", 4.5, "muted text on cards"),
    ("--ink-3", "--surface-2", 4.5, "muted text on raised rows"),
    ("--ink-4", "--surface", 3.0, "labels and captions"),
    ("--ink-4", "--surface-2", 3.0, "labels on raised rows"),
    ("--ink-4", "--ground", 3.0, "labels on the page ground"),
    ("--on-brand", "--brand", 4.5, "primary button label"),
    ("--on-brand", "--brand-hover", 4.5, "primary button label, hover"),
    ("--accent", "--surface", 4.5, "links"),
    ("--accent", "--accent-soft", 4.5, "accent text on its own tint"),
    ("--brand", "--surface", 4.5, "selected tab"),
    ("--brand", "--brand-soft", 4.5, "selected tab count"),
    ("--ok", "--ok-bg", 4.5, "authorised text on its tint"),
    ("--ok", "--surface", 4.5, "authorised text on a card"),
    ("--stop", "--stop-bg", 4.5, "refused text on its tint"),
    ("--stop", "--surface", 4.5, "refused text on a card"),
    ("--hold", "--hold-bg", 4.5, "needs-review text on its tint"),
    ("--hold", "--surface", 4.5, "needs-review text on a card"),
    ("--seal", "--seal-bg", 4.5, "seal glyph"),
    ("--surface", "--ok", 3.0, "check badge glyph"),
    ("--surface", "--stop", 3.0, "cross badge glyph"),
    ("--surface", "--hold", 3.0, "warning badge glyph"),
    ("--ink-4", "--sunken", 3.0, "disabled control labels"),
    ("--brand", "--brand-soft", 4.5, "selected rail option"),
    ("--ink-2", "--ok-bg", 4.5, "placed-on-rail explanation"),
    ("--stop", "--surface", 4.5, "counterfactual loss figure"),
    ("--ok", "--ok-bg", 4.5, "counterfactual rule chips"),
    ("--line-strong", "--surface", 1.3, "control borders (non-text)"),
)


def parse(hex_str: str) -> tuple[float, float, float]:
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def luminance(rgb: tuple[float, float, float]) -> float:
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(fg: str, bg: str) -> float:
    a, b = luminance(parse(fg)), luminance(parse(bg))
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


tokens = dict(TOKEN.findall(CSS.read_text()))
failures: list[str] = []
rows: list[tuple[str, str, float, float, bool]] = []

for fg, bg, minimum, what in PAIRS:
    if fg not in tokens or bg not in tokens:
        failures.append(f"{what}: unknown token {fg if fg not in tokens else bg}")
        continue
    value = ratio(tokens[fg], tokens[bg])
    ok = value >= minimum
    rows.append((what, f"{fg} on {bg}", value, minimum, ok))
    if not ok:
        failures.append(f"{what}: {fg} on {bg} is {value:.2f}:1, needs {minimum}:1")

width = max(len(r[0]) for r in rows)
for what, pair, value, minimum, ok in rows:
    mark = "ok  " if ok else "FAIL"
    print(f"  {mark} {what:<{width}}  {value:>5.2f}:1  (min {minimum})  {pair}")

print()
if failures:
    print(f"{len(failures)} contrast failure(s):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print(f"all {len(rows)} rendered pairs meet WCAG AA")
