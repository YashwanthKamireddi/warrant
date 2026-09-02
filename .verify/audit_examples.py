"""Run every Python example in the documentation.

Two ticks ago the SDK's own docstring example refused every basket it showed,
because with no model configured the derivation step narrows to a scope that
permits nothing. The code was correct, the docs were wrong, and nothing in the
build could tell -- prose is not executed.

This executes it. Every ```python block in the tracked documentation runs in a
fresh interpreter with the repo root as the working directory, and a block that
raises fails the build. Blocks fenced as anything else (```toml, ```, bash) are
left alone.

Examples are written to be self-contained on purpose. A block that needs three
earlier blocks to make sense is a block a reader cannot copy.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = [
    ROOT / "docs" / "INTEGRATION.md",
    ROOT / "README.md",
]

BLOCK = re.compile(r"^```python\n(.*?)^```", re.M | re.S)

failures: list[str] = []
ran = 0

for doc in DOCS:
    if not doc.exists():
        continue
    blocks = BLOCK.findall(doc.read_text(encoding="utf-8"))
    for i, source in enumerate(blocks, 1):
        label = f"{doc.relative_to(ROOT)} block {i}"
        result = subprocess.run(
            [sys.executable, "-c", source],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        ran += 1
        if result.returncode != 0:
            tail = (result.stderr or result.stdout).strip().splitlines()
            failures.append(f"{label}: {tail[-1] if tail else 'exited nonzero'}")
            print(f"  FAIL {label}")
            for line in tail[-6:]:
                print(f"       {line}")
        else:
            first = source.strip().splitlines()[0][:56]
            print(f"  ok   {label:<34} {first}")

print()
if not ran:
    print("no python examples found -- the extractor is probably broken")
    sys.exit(1)
if failures:
    print(f"{len(failures)} documentation example(s) do not run:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print(f"all {ran} documentation examples run")
