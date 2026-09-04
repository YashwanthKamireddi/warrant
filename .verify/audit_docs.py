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

# -- screenshots ------------------------------------------------------------- #
#
# They were captured once by hand and then left behind by four days of redesign,
# so the README showed a console that no longer existed. A reader scrolling
# GitHub saw a different product from the one they would get.

SHOTS = ROOT / "docs" / "screenshots"
CONSOLE_SRC = ROOT / "console" / "src"
if SHOTS.is_dir() and CONSOLE_SRC.is_dir():
    newest_source = max(
        (path.stat().st_mtime for path in CONSOLE_SRC.rglob("*") if path.is_file()),
        default=0,
    )
    stale = sorted(
        path.name
        for path in SHOTS.glob("*.png")
        if path.stat().st_mtime < newest_source
    )
    if stale:
        failures.append(
            f"screenshots older than the console source: {', '.join(stale)} "
            "-- run `make screenshots`"
        )
        print(f"  FAIL screenshots                    {len(stale)} stale")
    else:
        print(f"  ok   screenshots                    {len(list(SHOTS.glob('*.png')))} current")

print()
# -- the narration script --------------------------------------------------- #
#
# NARRATION.md is read aloud over the film, so its numbers are the ones a judge
# actually hears. It had drifted furthest of anything in the repo -- it claimed
# 211 tests and 8 gates against 367 and 11, and quoted two money figures that
# were never measured -- because nothing checked it. Now something does.
#
# It spells numbers out, the way a person reads them, so the check is written
# the other way round: take the measured value, spell it, and require the words
# to appear.

NARRATION = ROOT / ".video" / "NARRATION.md"

ONES = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
]
TENS = ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def spell(n: int) -> str:
    """British-English words for a number, the way the script says them."""
    if n < 20:
        return ONES[n]
    if n < 100:
        tens, rest = divmod(n, 10)
        return TENS[tens - 2] + (f"-{ONES[rest]}" if rest else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        head = f"{ONES[hundreds]} hundred"
        return f"{head} and {spell(rest)}" if rest else head
    thousands, rest = divmod(n, 1000)
    head = f"{spell(thousands)} thousand"
    return f"{head} {spell(rest)}" if rest else head


if not NARRATION.is_file():
    failures.append(".video/NARRATION.md is missing")
else:
    # The script is a wrapped markdown blockquote, so a spoken number routinely
    # straddles a line break and a "> " marker: "thirty thousand two\n> hundred".
    # Matching the raw text finds none of them.
    spoken = re.sub(r"[\s>]+", " ", NARRATION.read_text().lower())
    spoken_drift: list[str] = []

    def spoken_claim(label: str, value: int) -> None:
        """The film says this number out loud, so the words have to be there."""
        words = spell(value)
        if words not in spoken:
            spoken_drift.append(
                f"narration: says nothing matching {label} = {value} "
                f'(expected the words "{words}")'
            )

    spoken_claim("the corpus size", results["cases"])
    spoken_claim("what an amount ceiling misses", policies["amount_only"]["misses"])
    spoken_claim("what Warrant misses", policies["warrant"]["misses"])
    if actual_tests:
        spoken_claim("the test count", int(actual_tests.group(1)))
    spoken_claim("the gate count", gate_targets)

    # Money is rounded when it is read aloud, and there is more than one honest
    # way to round it: Rs 302,663 is "three hundred and two thousand" to one
    # speaker and "three hundred and three thousand" to another. Any of those
    # is fine. What this is here to catch is the figure that was never measured
    # at all -- the script said "two hundred and eighty-one thousand" for a
    # while, which is not a rounding of anything.
    def spoken_money(label: str, paise: int) -> None:
        rupees_ = paise / 100
        candidates = {
            spell(int(rupees_ // 1000) * 1000),
            spell(round(rupees_ / 1000) * 1000),
            spell(int(rupees_ // 100) * 100),
            spell(round(rupees_ / 100) * 100),
        }
        # Said aloud, "one hundred" is usually just "a hundred".
        candidates |= {c.replace("one hundred", "a hundred") for c in candidates}
        if not any(c in spoken for c in candidates):
            spoken_drift.append(
                f"narration: says nothing matching {label} = {rupees(paise)} "
                f"(any of: {', '.join(sorted(candidates))})"
            )

    for policy, label in (("warrant", "what Warrant leaks"),
                          ("no_gate", "what no gate leaks"),
                          ("amount_only", "what an amount ceiling leaks")):
        spoken_money(label, policies[policy]["leaked_paise"])

    # The console picks which ledger entry to rewrite at runtime, so naming one
    # is a promise the footage breaks on the next take.
    if re.search(r"entry (one|two|three|four|five|six|seven|eight|nine|\d+)", spoken):
        spoken_drift.append(
            "narration: names a specific ledger entry for the tamper. The console "
            "chooses that entry at runtime, so the number is wrong on some runs."
        )

    failures.extend(spoken_drift)
    if not spoken_drift:
        print("  ok   .video/NARRATION.md            numbers match")

if failures:
    print(f"\n{len(failures)} documentation drift(s):")
    for f in failures:
        print("  -", f)
    sys.exit(1)

print("every number in the README and the narration matches what the code measures")
