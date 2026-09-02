"""Fail the build when the documentation stops telling the truth.

A repository whose entire argument is honest reporting cannot afford a stale
number, and stale numbers are exactly what a fast-moving repo produces. This one
had four at once: a corpus that had grown from 405 to 540 sessions, a headline
figure of 13.3% where the code measured 81.8%, a test count from several commits
earlier, and a contrast audit covering 31 pairs while the README claimed 29.

Every one of those was written by hand and then left behind by the code. So the
numbers are now generated and checked:

  make bench   writes bench/RESULTS.json
  README.md    quotes it
  this gate    re-measures and fails if any of them disagree

Latency is checked as a bound rather than a point. A microsecond figure quoted in
a README is a claim about one laptop; "p50 under 300µs" is a claim about the
design, and it is the one worth defending.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
RESULTS = ROOT / "bench" / "RESULTS.json"

failures: list[str] = []
readme = README.read_text()
MAKEFILE = (ROOT / "Makefile").read_text()


def check(label: str, claimed: object, actual: object) -> None:
    if str(claimed) != str(actual):
        failures.append(f"{label}: README says {claimed!r}, measured {actual!r}")
    else:
        print(f"  ok   {label:<34} {actual}")


# -- the benchmark artifact must be current -------------------------------- #

fresh = ROOT / "bench" / ".RESULTS.check.json"
subprocess.run(
    ["uv", "run", "python", "bench/run.py", "--write-results", str(fresh)],
    cwd=ROOT,
    capture_output=True,
    check=True,
)
measured = json.loads(fresh.read_text())
fresh.unlink(missing_ok=True)

if not RESULTS.is_file():
    failures.append("bench/RESULTS.json is missing. Run `make bench`.")
    committed = {}
else:
    committed = json.loads(RESULTS.read_text())
    if committed != measured:
        failures.append(
            "bench/RESULTS.json is stale. Run `make bench` and commit the result."
        )
    else:
        print("  ok   bench/RESULTS.json                current")

results = measured
policies = results["policies"]


def rupees(paise: int) -> str:
    return f"₹{paise / 100:,.0f}"


# -- corpus size ------------------------------------------------------------ #

sessions = re.search(r"(\d[\d,]*) labelled sessions", readme)
check("corpus size", sessions.group(1) if sessions else None, results["cases"])

# -- the results table ------------------------------------------------------ #

for name in ("no_gate", "amount_only", "model_only", "warrant"):
    pattern = rf"`{name}`.*?\|\s*\*{{0,2}}([\d.]+%)\*{{0,2}}\s*\|\s*\*{{0,2}}(₹[\d,]+)"
    row = re.search(pattern, readme)
    if row is None:
        failures.append(f"results table: no row found for `{name}`")
        continue
    check(f"{name} caught", row.group(1), f"{policies[name]['recall'] * 100:.1f}%")
    check(f"{name} leaked", row.group(2), rupees(policies[name]["leaked_paise"]))

# -- the categories reported as zero ---------------------------------------- #

per_cat = policies["warrant"]["per_category"]
for category in ("injection_subtle", "semantic_drift"):
    claimed = re.search(rf"`{category}`: (\d+) of (\d+)", readme)
    if claimed is None:
        failures.append(f"losses section: no figure quoted for `{category}`")
        continue
    check(
        f"{category}",
        f"{claimed.group(1)}/{claimed.group(2)}",
        f"{per_cat[category][0]}/{per_cat[category][1]}",
    )

# -- test count ------------------------------------------------------------- #

pytest_out = subprocess.run(
    ["uv", "run", "pytest", "-q", "--no-header"],
    cwd=ROOT,
    capture_output=True,
    text=True,
    check=False,
).stdout
actual_tests = re.search(r"(\d+) passed", pytest_out)
claimed_tests = re.search(r"\*\*(\d+) tests\*\*|\| `test` \| (\d+) tests", readme)

# The badge is the most-read number on the page and this gate never looked at
# it: the table said 341 while the badge said 211 and the build was green.
# Anything shaped like a shields.io count is checked against the same source.
badge_tests = re.search(r"badge/tests-(\d+)%20passing", readme)
check(
    "test count (badge)",
    badge_tests.group(1) if badge_tests else None,
    actual_tests.group(1) if actual_tests else "unknown",
)

badge_gates = re.search(r"badge/gates-(\d+)%20green", readme)
gate_targets = len(
    re.findall(r"^(test|lint|typecheck|audit-\w+|docs-\w+|browser):", MAKEFILE, re.M)
)
check("gate count (badge)", badge_gates.group(1) if badge_gates else None, str(gate_targets))
check(
    "test count",
    (claimed_tests.group(1) or claimed_tests.group(2)) if claimed_tests else None,
    actual_tests.group(1) if actual_tests else "unknown",
)

# -- contrast pairs --------------------------------------------------------- #

contrast = subprocess.run(
    ["uv", "run", "python", ".verify/audit_contrast.py"],
    cwd=ROOT,
    capture_output=True,
    text=True,
    check=False,
).stdout
actual_pairs = re.search(r"all (\d+) rendered pairs", contrast)
claimed_pairs = re.search(r"all (\d+) rendered pairs", readme)
check(
    "contrast pairs",
    claimed_pairs.group(1) if claimed_pairs else None,
    actual_pairs.group(1) if actual_pairs else "unknown",
)

# -- latency, as a bound ---------------------------------------------------- #

if "p50 under 300µs" not in readme:
    failures.append(
        "latency claim: README should state a bound (p50 under 300µs), not a point "
        "figure, which is a claim about one machine"
    )
else:
    print("  ok   latency stated as a bound")

# -- module listings --------------------------------------------------------- #
#
# README.md and ARCHITECTURE.md both draw the package as a tree, by hand. A
# module added without touching them is invisible to a reader following either
# one, which is how ARCHITECTURE.md ended up describing half the system.

ENGINE = ROOT / "engine" / "warrant"
ARCHITECTURE = (ROOT / "ARCHITECTURE.md").read_text()

shipped = {
    path.name
    for path in ENGINE.glob("*.py")
    if not path.name.startswith("_")
}
for doc_name, text in (("README.md", readme), ("ARCHITECTURE.md", ARCHITECTURE)):
    missing = sorted(name for name in shipped if name not in text)
    if missing:
        failures.append(
            f"{doc_name} does not mention {', '.join(missing)}"
        )
        print(f"  FAIL modules listed in {doc_name:<18} missing {', '.join(missing)}")
    else:
        print(f"  ok   modules listed in {doc_name:<18} all {len(shipped)}")

print()
if failures:
    print(f"{len(failures)} documentation drift(s):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("every number in the README matches what the code measures")
