"""Fail if any component introduces a colour outside the token system.

A design system holds together only while every value comes from one place. The
usual way it rots is a single hard-coded hex in one component, added in a hurry,
which then survives every review because it looks fine on the day. This makes
that a build failure instead.

Rules:
  * raw hex, rgb(), hsl() and named colours are allowed only inside :root
  * inline style props in TSX may reference var(--token), never a literal
  * every var(--x) referenced anywhere must actually be defined in :root
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "console" / "src"
CSS = ROOT / "styles.css"

HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
FUNC = re.compile(r"\b(?:rgba?|hsla?)\s*\(")
NAMED = re.compile(
    r"(?<![\w-])(?:red|blue|green|black|white|grey|gray|orange|purple|yellow)(?![\w-])"
)
VAR_DEF = re.compile(r"^\s*(--[a-z0-9-]+)\s*:", re.M)
VAR_USE = re.compile(r"var\((--[a-z0-9-]+)")

failures: list[str] = []

BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
LINE_COMMENT = re.compile(r"//[^\n]*")


def blank_comments(text: str, *, line_comments: bool) -> str:
    """Replace comment bodies with spaces, preserving offsets and line numbers.

    Prose mentions colour words -- "emerald, red and bronze mean authorised,
    refused and needs-a-human" is a sentence, not a style rule. Blanking rather
    than deleting keeps every reported line number honest.
    """

    def blank(match: re.Match[str]) -> str:
        return "".join("\n" if ch == "\n" else " " for ch in match.group(0))

    text = BLOCK_COMMENT.sub(blank, text)
    return LINE_COMMENT.sub(blank, text) if line_comments else text


def root_block(css: str) -> tuple[int, int]:
    start = css.index(":root {")
    depth, i = 0, start
    while i < len(css):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return start, i
        i += 1
    raise ValueError(":root block is unterminated")


RAW_CSS = CSS.read_text()
css = blank_comments(RAW_CSS, line_comments=False)
r_start, r_end = root_block(css)
defined = set(VAR_DEF.findall(css[r_start:r_end]))

# 1. literals outside :root
for match in list(HEX.finditer(css)) + list(FUNC.finditer(css)) + list(NAMED.finditer(css)):
    if r_start <= match.start() <= r_end:
        continue
    line = css[: match.start()].count("\n") + 1
    context = RAW_CSS.splitlines()[line - 1].strip()
    failures.append(f"styles.css:{line}  literal colour outside :root  →  {context}")

# 2. undefined tokens anywhere
for path in [CSS, *ROOT.rglob("*.tsx"), *ROOT.rglob("*.ts")]:
    text = blank_comments(path.read_text(), line_comments=path.suffix != ".css")
    for match in VAR_USE.finditer(text):
        token = match.group(1)
        if token not in defined:
            line = text[: match.start()].count("\n") + 1
            failures.append(f"{path.name}:{line}  undefined token {token}")

# 3. literals in TSX inline styles
for path in ROOT.rglob("*.tsx"):
    text = blank_comments(path.read_text(), line_comments=True)
    for match in HEX.finditer(text):
        line = text[: match.start()].count("\n") + 1
        failures.append(f"{path.name}:{line}  hard-coded hex in a component")

print(f"tokens defined: {len(defined)}")
if failures:
    print(f"\n{len(failures)} token violation(s):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("no literal colours outside :root, no undefined tokens")
