"""Run every policy over the labelled corpus and print the numbers, losses included.

Two things this report refuses to do.

It does not quote a bare accuracy figure. The corpus is eight-ninths violations
by construction, so "96% correct" would mean almost nothing; what matters is how
much money each policy let through and how much legitimate spend it killed to
get there.

It does not hide the category Warrant scores zero on. ``semantic_drift`` -- a
basket inside every signed bound that is still not what was asked for -- is
undetectable by arithmetic, and with no model reachable Warrant catches none of
it. That row is printed in the same table as everything else.

    uv run python bench/run.py
    uv run python bench/run.py --json          machine-readable
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(__file__))

from warrant.crypto import SigningKey  # noqa: E402
from warrant.gate import MandateState  # noqa: E402
from warrant.llm import describe_capability  # noqa: E402
from warrant.models import CartMandate, Verdict  # noqa: E402

from corpus import CATEGORIES, Case, build_corpus  # noqa: E402

from policies import POLICIES  # noqa: E402  isort: skip

_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


DIM = lambda t: _c("2", t)  # noqa: E731
BOLD = lambda t: _c("1", t)  # noqa: E731
RED = lambda t: _c("31", t)  # noqa: E731
GREEN = lambda t: _c("32", t)  # noqa: E731


@dataclass
class Tally:
    """Outcomes for one policy. Money is the point; the ratios are context."""

    true_stops: int = 0
    false_stops: int = 0
    misses: int = 0
    correct_allows: int = 0

    leaked_paise: int = 0
    """Money that moved and should not have."""
    friction_paise: int = 0
    """Legitimate spend that was stopped. The cost of being wrong the other way."""

    per_category: dict[str, list[int]] = field(default_factory=dict)
    """category -> [handled correctly, total]. For `legitimate` that means
    allowed; for every other category it means not settled."""

    @property
    def recall(self) -> float:
        denom = self.true_stops + self.misses
        return self.true_stops / denom if denom else 0.0

    @property
    def precision(self) -> float:
        denom = self.true_stops + self.false_stops
        return self.true_stops / denom if denom else 0.0

    @property
    def false_stop_rate(self) -> float:
        denom = self.false_stops + self.correct_allows
        return self.false_stops / denom if denom else 0.0


def run_policy(name: str, cases: list[Case], client: object | None) -> Tally:
    policy, _ = POLICIES[name]
    subject = SigningKey.from_seed("bench/subject")
    tally = Tally()

    for case in cases:
        state = MandateState(intent_digest=case.intent.digest)
        cart = CartMandate(
            intent_digest=case.intent.digest,
            merchant=case.merchant,
            line_items=case.items,
            total_paise=case.total_paise,
            issued_at=case.now,
            nonce=case.nonce,
        )
        if case.settle_first:
            state.record_settled(cart)

        verdict = policy(case.intent, cart, state, case.now, subject.public, client)

        stopped = verdict is not Verdict.ALLOW
        should_stop = case.should is not Verdict.ALLOW

        bucket = tally.per_category.setdefault(case.category, [0, 0])
        bucket[1] += 1

        if should_stop and stopped:
            tally.true_stops += 1
            bucket[0] += 1
        elif should_stop and not stopped:
            tally.misses += 1
            tally.leaked_paise += case.total_paise
        elif not should_stop and stopped:
            tally.false_stops += 1
            tally.friction_paise += case.total_paise
        else:
            tally.correct_allows += 1
            bucket[0] += 1

    return tally


def _rupees(paise: int) -> str:
    return f"₹{paise / 100:,.0f}"


def report(results: dict[str, Tally], cases: list[Case]) -> None:
    capability = describe_capability()
    total_at_risk = sum(c.total_paise for c in cases if c.should is not Verdict.ALLOW)

    print()
    print(BOLD("WARRANT BENCHMARK"))
    print(DIM(f"{len(cases)} labelled sessions · seed 20260901 · {len(CATEGORIES)} categories"))
    print(DIM(f"model path: {capability.note}"))
    print()

    header = f"  {'policy':<13} {'caught':>7} {'missed':>7} {'wrong stops':>12} " \
             f"{'leaked':>11} {'friction':>11}"
    print(BOLD(header))
    print(DIM("  " + "─" * (len(header) - 2)))
    for name, tally in results.items():
        leaked = _rupees(tally.leaked_paise)
        print(
            f"  {name:<13} "
            f"{tally.recall:>6.1%} "
            f"{tally.misses:>7} "
            f"{tally.false_stops:>12} "
            f"{(RED(leaked) if tally.leaked_paise else GREEN(leaked)):>11} "
            f"{_rupees(tally.friction_paise):>11}"
        )
    print()
    print(DIM("  caught    = share of violations that did not settle"))
    print(
        DIM(
            "  leaked    = money that moved and should not have, "
            f"of {_rupees(total_at_risk)} at risk"
        )
    )
    print(DIM("  friction  = legitimate spend stopped, i.e. conversion killed"))
    print()

    # -- per category, for the full system ------------------------------- #

    print(BOLD("  Warrant, by category"))
    print(DIM("  handled correctly: allowed for `legitimate`, stopped for the rest"))
    print(DIM("  " + "─" * 58))
    warrant = results["warrant"]
    zero_rows: list[str] = []
    for category in CATEGORIES:
        correct, total = warrant.per_category.get(category, [0, 0])
        rate = correct / total if total else 0.0
        bar = "█" * round(rate * 22) + DIM("·" * (22 - round(rate * 22)))
        line = f"  {category:<16} {bar} {rate:>6.1%}  {correct}/{total}"
        print(RED(line) if rate < 0.5 else line)
        if rate < 0.5:
            zero_rows.append(category)
    print()

    # -- the honest part -------------------------------------------------- #

    print(BOLD("  Where this loses"))
    print(DIM("  " + "─" * 58))

    subtle = warrant.per_category.get("injection_subtle", [0, 0])
    drift = warrant.per_category.get("semantic_drift", [0, 0])
    print(
        f"  injection_subtle {subtle[0]}/{subtle[1]} and semantic_drift {drift[0]}/{drift[1]}.\n"
        "  Both sit inside every bound the subject signed -- right merchant, right\n"
        "  category, under every ceiling -- so no arithmetic touches them, and the\n"
        "  payload in injection_subtle is phrased to evade the instruction-text\n"
        "  heuristic. Only reading the basket against the instruction catches either,\n"
        "  and no model was reachable on this run.\n"
    )
    print(
        "  Those two rows are the only ones a live model moves. Every other row is\n"
        "  arithmetic and will not change.\n"
    )
    print(
        "  injection_oos is scored separately on purpose. Those payloads are blocked,\n"
        "  but on the category bound -- nothing recognised the payload. Counting them\n"
        "  as 'injection caught' would be the flattering way to report this.\n"
    )
    print(
        f"  legitimate {warrant.per_category.get('legitimate', [0, 0])[0]}"
        f"/{warrant.per_category.get('legitimate', [0, 0])[1]} and friction "
        f"{_rupees(warrant.friction_paise)} are close to circular: this corpus defines\n"
        "  a legitimate basket as one inside the scope, and the policy allows baskets\n"
        "  inside the scope. Read that row as evidence the gate is not over-firing,\n"
        "  and nothing more. It is not evidence that real customers would not be\n"
        "  blocked, because no real customer generated it.\n"
    )
    print(
        "  The mechanical categories are exact by construction, not by cleverness.\n"
        "  A ceiling comparison cannot be 97% right. Read those rows as a check that\n"
        "  the rules are wired up, not as evidence the approach is smart.\n"
    )

    model_only = results["model_only"]
    print(BOLD("  Why not just ask a model"))
    print(DIM("  " + "─" * 58))
    print(
        f"  model_only leaked {_rupees(model_only.leaked_paise)} across "
        f"{model_only.misses} sessions. Replay, expiry and\n"
        "  cumulative ceilings are facts about session state, not about the basket,\n"
        "  so reading the cart cannot reveal them however good the model is.\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-category", type=int, default=45)
    parser.add_argument("--json", action="store_true", help="emit machine-readable results")
    args = parser.parse_args()

    cases = build_corpus(n_per_category=args.per_category)
    results = {name: run_policy(name, cases, None) for name in POLICIES}

    if args.json:
        print(
            json.dumps(
                {
                    "cases": len(cases),
                    "policies": {
                        name: {
                            "recall": round(t.recall, 4),
                            "precision": round(t.precision, 4),
                            "false_stop_rate": round(t.false_stop_rate, 4),
                            "misses": t.misses,
                            "false_stops": t.false_stops,
                            "leaked_paise": t.leaked_paise,
                            "friction_paise": t.friction_paise,
                            "per_category": t.per_category,
                        }
                        for name, t in results.items()
                    },
                },
                indent=2,
            )
        )
        return 0

    report(results, cases)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
