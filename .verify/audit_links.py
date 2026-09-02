"""Every relative link and image in the documentation points at something.

A broken link is invisible to the person who wrote it -- they know where they
meant to point -- and it is the first thing a reviewer clicks. Nothing else in
this build looks at them: docs-check verifies the numbers, docs-examples runs
the code, and both are happy with a README whose every link 404s.

Only relative targets are checked. Reaching out to the network to prove that
somebody else's site is up would make the build fail for reasons that have
nothing to do with this repository.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = [ROOT / "README.md", ROOT / "ARCHITECTURE.md", ROOT / "INCIDENTS.md",
        ROOT / "SUBMISSION.md", ROOT / "docs" / "INTEGRATION.md"]

MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
HTML_SRC = re.compile(r'<img[^>]+src="([^"]+)"')

failures: list[str] = []
checked = 0


def is_external(target: str) -> bool:
    return target.startswith(("http://", "https://", "mailto:", "//"))


for doc in DOCS:
    if not doc.exists():
        continue
    text = doc.read_text(encoding="utf-8")
    targets = MARKDOWN_LINK.findall(text) + HTML_SRC.findall(text)

    for target in targets:
        if is_external(target):
            continue

        # An in-page anchor points at a heading in the same file.
        if target.startswith("#"):
            slug = target.lstrip("#").lower()
            headings = {
                re.sub(r"[^a-z0-9\s-]", "", line.lstrip("#").strip().lower())
                .replace(" ", "-")
                for line in text.splitlines()
                if line.startswith("#")
            }
            checked += 1
            if slug not in headings:
                failures.append(f"{doc.name}: anchor {target} has no heading")
            continue

        path, _, anchor = target.partition("#")
        resolved = (doc.parent / path).resolve()
        checked += 1
        if not resolved.exists():
            failures.append(f"{doc.name}: {target} does not exist")
            continue

        # A link into another document's heading should land somewhere.
        if anchor and resolved.suffix == ".md":
            other = resolved.read_text(encoding="utf-8")
            headings = {
                re.sub(r"[^a-z0-9\s-]", "", line.lstrip("#").strip().lower())
                .replace(" ", "-")
                for line in other.splitlines()
                if line.startswith("#")
            }
            if anchor.lower() not in headings:
                failures.append(f"{doc.name}: {target} names a heading {resolved.name} lacks")

    print(f"  ok   {doc.relative_to(ROOT)!s:<26} {len(targets)} links")

print()
if failures:
    print(f"{len(failures)} broken reference(s):")
    for failure in failures:
        print("  -", failure)
    sys.exit(1)
print(f"all {checked} relative references resolve")
