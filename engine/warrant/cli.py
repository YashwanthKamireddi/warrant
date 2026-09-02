"""``warrant`` -- the terminal surface.

Four commands, each answering one question a reviewer will actually ask:

    warrant demo     what does this do?
    warrant verify   can the ledger be trusted?
    warrant trace    why did it decide that?
    warrant serve    run the console
    warrant api      run the authorization service

Output is plain ANSI with no rendering dependency, and degrades to unstyled text
when stdout is not a terminal, so piping to a file produces something readable.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import TextIO

from .chain import Ledger
from .demo import build_scenario
from .models import CheckStatus, Verdict

__all__ = ["main"]

_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


DIM = lambda t: _c("2", t)  # noqa: E731
BOLD = lambda t: _c("1", t)  # noqa: E731
GREEN = lambda t: _c("32", t)  # noqa: E731
RED = lambda t: _c("31", t)  # noqa: E731
AMBER = lambda t: _c("33", t)  # noqa: E731
CYAN = lambda t: _c("36", t)  # noqa: E731

_VERDICT_STYLE = {
    Verdict.ALLOW: (GREEN, "ALLOW"),
    Verdict.BLOCK: (RED, "BLOCK"),
    Verdict.ESCALATE: (AMBER, "ESCALATE"),
}
_STATUS_MARK = {
    CheckStatus.PASS: lambda: GREEN("ok  "),
    CheckStatus.WARN: lambda: AMBER("warn"),
    CheckStatus.FAIL: lambda: RED("FAIL"),
}


def _rule(out: TextIO, char: str = "─", width: int = 76) -> None:
    out.write(DIM(char * width) + "\n")


def _rupees(paise: int) -> str:
    return f"₹{paise / 100:,.2f}"


def _heading(out: TextIO, text: str) -> None:
    out.write("\n" + BOLD(text) + "\n")
    _rule(out)


# --------------------------------------------------------------------------- #
# demo
# --------------------------------------------------------------------------- #


def cmd_demo(args: argparse.Namespace, out: TextIO) -> int:
    rail = None
    if args.rail == "razorpay":
        from .rails.razorpay_rail import RazorpayNotConfigured, RazorpayRail

        try:
            rail = RazorpayRail()
        except RazorpayNotConfigured as exc:
            out.write(RED("Razorpay rail unavailable: ") + str(exc) + "\n")
            return 2

    ledger = Ledger(args.ledger) if args.ledger else Ledger()
    scenario = build_scenario(ledger=ledger, rail=rail, derive=args.derive)
    intent, scope = scenario.intent, scenario.intent.scope

    out.write("\n" + BOLD("WARRANT") + DIM("  ·  no agent spends without one") + "\n")

    _heading(out, "1  The person says something")
    out.write(f'  {CYAN(chr(34) + intent.utterance + chr(34))}\n')

    _heading(out, "2  It becomes a permission, and they approve it")
    source_note = {
        "pinned": "pinned, so this run is byte-identical everywhere (--derive to interpret)",
        "live": "interpreted by a live model call",
        "transcript": "replayed from the bundled transcript (no credentials present)",
        "fallback": "no model available; narrowed to the deterministic minimum",
    }.get(scenario.derivation_source, scenario.derivation_source)
    out.write(f"  {scenario.approval_prompt}\n")
    out.write(DIM(f"  scope {source_note}\n"))
    out.write(
        DIM("  bounds  ")
        + f"{_rupees(scope.max_total_paise)} total"
        + DIM("  ·  ")
        + f"{_rupees(scope.max_per_txn_paise)} per order"
        + DIM("  ·  ")
        + f"{scope.max_txns} orders"
        + DIM("  ·  ")
        + f"step-up over {_rupees(scope.step_up_over_paise or 0)}\n"
    )
    out.write(
        DIM("  allowed ")
        + f"{', '.join(scope.merchants)}"
        + DIM("  ·  ")
        + f"{', '.join(scope.categories)}\n"
    )
    out.write(DIM(f"  signed  {intent.id} by {intent.signature.key_id}\n"))

    _heading(out, "3  The agent shops; every basket is checked before any money moves")

    failures = 0
    for i, step in enumerate(scenario.steps, 1):
        now = scenario.t0 + step.offset
        cart = scenario.authorizer.propose_cart(
            intent, merchant=step.merchant, items=step.items, now=now, nonce=step.nonce
        )
        outcome = scenario.authorizer.authorize(
            intent, cart, subject_key=scenario.subject_key.public, now=now
        )
        style, label = _VERDICT_STYLE[outcome.verdict]
        matched = str(outcome.verdict) == step.expect
        failures += 0 if matched else 1

        out.write(
            f"\n  {DIM(str(i))}  {BOLD(step.label):<44} {style(label)}"
            + ("" if matched else RED(f"  (expected {step.expect})"))
            + "\n"
        )
        out.write(DIM(f"     {_rupees(cart.total_paise)} at {cart.merchant} · {cart.id}\n"))

        if args.verbose:
            for check in outcome.decision.checks:
                if check.status is CheckStatus.PASS and not args.all_checks:
                    continue
                out.write(
                    f"     {_STATUS_MARK[check.status]()} {DIM(check.rule):<34} {check.detail}\n"
                )
        else:
            for reason in outcome.decision.reasons[:2]:
                out.write(f"     {RED('·')} {reason}\n")

        out.write(DIM(f"     {step.teaches}\n"))
        if outcome.receipt:
            out.write(
                f"     {GREEN('receipt')} {outcome.receipt.id} "
                + DIM(f"rail {outcome.rail.ref.payment_id or outcome.rail.ref.order_id}\n")
            )
        elif outcome.rail and not outcome.rail.settled and outcome.rail.ok:
            link = outcome.rail.raw.get("payment_link")
            out.write(DIM(f"     placed on rail, awaiting payment  {link or ''}\n"))

    _heading(out, "4  The ledger")
    ledger_ = scenario.authorizer.ledger
    counts: dict[str, int] = {}
    for entry in ledger_.entries():
        counts[str(entry.kind)] = counts.get(str(entry.kind), 0) + 1
    for kind, n in counts.items():
        marker = RED("×") if "blocked" in kind or "failed" in kind else DIM("·")
        out.write(f"  {marker} {kind:<22} {n}\n")
    out.write(
        DIM("\n  Refusals are entries, not silences. ")
        + "A dispute can ask why something did not happen.\n"
    )

    audit = ledger_.audit()
    out.write(
        f"\n  {GREEN('chain intact')} {ledger_.length} entries · head {ledger_.head[:23]}…\n"
        if audit is None
        else f"\n  {RED('CHAIN BROKEN')} at entry {audit.seq}: {audit.reason}\n"
    )

    if failures:
        out.write(RED(f"\n{failures} step(s) did not match the expected verdict.\n"))
        return 1
    out.write("\n")
    return 0


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #


def cmd_verify(args: argparse.Namespace, out: TextIO) -> int:
    if not os.path.exists(args.ledger):
        out.write(RED(f"No ledger at {args.ledger}\n"))
        return 2

    ledger = Ledger(args.ledger)
    audit = ledger.audit()
    out.write(f"\n  ledger   {args.ledger}\n")
    out.write(f"  entries  {ledger.length}\n")
    out.write(f"  head     {ledger.head}\n\n")

    if audit is None:
        out.write(GREEN("  Chain intact. Every entry hashes to its recorded value.\n\n"))
        return 0

    out.write(RED(f"  Chain broken at entry {audit.seq}: {audit.reason}\n"))
    out.write(DIM(f"    expected  {audit.expected}\n"))
    out.write(DIM(f"    found     {audit.found}\n\n"))
    return 1


# --------------------------------------------------------------------------- #
# trace
# --------------------------------------------------------------------------- #


def cmd_trace(args: argparse.Namespace, out: TextIO) -> int:
    if not os.path.exists(args.ledger):
        out.write(RED(f"No ledger at {args.ledger}\n"))
        return 2

    ledger = Ledger(args.ledger)
    sessions = ledger.sessions()
    if not sessions:
        out.write(DIM("  Ledger is empty.\n"))
        return 0

    session = args.session or sessions[0]
    out.write(f"\n  {BOLD(session)}\n")
    _rule(out)

    for entry in ledger.entries(session):
        kind = str(entry.kind)
        style = RED if ("blocked" in kind or "failed" in kind) else DIM
        out.write(f"  {DIM(f'{entry.seq:>3}')}  {style(kind):<34}")
        payload = entry.payload
        if "verdict" in payload:
            out.write(f" {payload['verdict']}")
        if payload.get("failed_rules"):
            out.write(DIM(f"  {', '.join(payload['failed_rules'])}"))
        out.write("\n")
        for reason in payload.get("reasons", [])[:2]:
            out.write(DIM(f"        {reason}\n"))

    out.write("\n")
    return 0


# --------------------------------------------------------------------------- #
# serve
# --------------------------------------------------------------------------- #


def cmd_serve(args: argparse.Namespace, out: TextIO) -> int:
    import uvicorn

    out.write(f"\n  Console on {CYAN(f'http://{args.host}:{args.port}')}\n\n")
    uvicorn.run("warrant.api:app", host=args.host, port=args.port, log_level="warning")
    return 0


def cmd_api(args: argparse.Namespace, out: TextIO) -> int:
    """Run the product service: the router a company would mount, standalone.

    Deliberately not the console. `warrant serve` hands you a demonstration
    with a tamper button; this is the thing that goes in front of money.
    """
    import uvicorn

    from .client import Warrant
    from .service import NO_AUTH, ApiKeyAuth, create_app

    auth = NO_AUTH if args.open else ApiKeyAuth.from_env()
    if auth is None:
        out.write(
            "\n  Refusing to start without authentication.\n\n"
            "  Set WARRANT_API_KEYS to one or more comma-separated tokens:\n"
            "    export WARRANT_API_KEYS=$(python -c "
            "'import secrets; print(secrets.token_urlsafe(32))')\n\n"
            "  Or pass --open to run without any, which is for a local look "
            "and nothing else.\n\n"
        )
        return 2

    warrant = Warrant(merchants=args.merchants, ledger=args.ledger)
    base = f"http://{args.host}:{args.port}"
    out.write(f"\n  Warrant API on {CYAN(base)}\n")
    out.write(f"  {len(warrant.registry)} merchants · ledger {args.ledger or 'in memory'}\n")
    out.write(f"  openapi at {base}/docs\n")
    out.write(
        "  auth: open — anyone who can reach this can spend\n\n"
        if args.open
        else "  auth: bearer token required\n\n"
    )

    if args.ledger is None:
        out.write(
            "  Note: no --ledger given, so the record is in memory and dies with "
            "this process.\n\n"
        )

    uvicorn.run(
        create_app(warrant, auth=auth),
        host=args.host,
        port=args.port,
        log_level="warning",
    )
    return 0


# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="warrant",
        description="Authorization layer for agent-initiated payments.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="run the five-cart scenario end to end")
    demo.add_argument(
        "--rail",
        choices=("simulated", "razorpay"),
        default="simulated",
        help="simulated is deterministic; razorpay creates real test-mode orders",
    )
    demo.add_argument("--ledger", help="persist the ledger to this SQLite file")
    demo.add_argument("-v", "--verbose", action="store_true", help="show failed checks per cart")
    demo.add_argument("--all-checks", action="store_true", help="show passing checks too")
    demo.add_argument(
        "--derive",
        action="store_true",
        help=(
            "derive the scope with a live model instead of using the pinned one. "
            "Shows the real feature; the run is no longer byte-identical, because "
            "a model may read the same sentence differently."
        ),
    )
    demo.set_defaults(func=cmd_demo)

    verify = sub.add_parser("verify", help="recompute a ledger's hash chain")
    verify.add_argument("ledger", help="path to the SQLite ledger")
    verify.set_defaults(func=cmd_verify)

    trace = sub.add_parser("trace", help="show every decision in a session")
    trace.add_argument("ledger", help="path to the SQLite ledger")
    trace.add_argument("--session", help="session id (defaults to the first)")
    trace.set_defaults(func=cmd_trace)

    serve = sub.add_parser("serve", help="run the console")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    serve.set_defaults(func=cmd_serve)

    api = sub.add_parser("api", help="run the authorization service")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8080)
    api.add_argument(
        "--merchants",
        default=None,
        help="path to a merchant registry TOML; defaults to WARRANT_MERCHANTS",
    )
    api.add_argument(
        "--ledger",
        default=None,
        help="path to the SQLite ledger; in memory if omitted",
    )
    api.add_argument(
        "--open",
        action="store_true",
        help="run with no authentication at all; for a local look only",
    )
    api.set_defaults(func=cmd_api)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args, sys.stdout))


if __name__ == "__main__":
    raise SystemExit(main())
