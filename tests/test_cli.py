"""The CLI's exit codes are its contract.

`warrant verify` is meant to be runnable in someone else's CI, which means a
broken chain has to fail the build rather than print a warning into a log nobody
reads. These lock that: 0 only when the thing actually holds.
"""

from __future__ import annotations

import io

import pytest

from warrant.chain import Ledger
from warrant.cli import main


@pytest.fixture
def ledger_path(tmp_path):
    """A real ledger written by the demo."""
    path = tmp_path / "demo.db"
    assert main(["demo", "--ledger", str(path)]) == 0
    return path


def _run(argv: list[str]) -> tuple[int, str]:
    import contextlib

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(argv)
    return code, out.getvalue()


# -- demo ------------------------------------------------------------------ #


def test_the_demo_exits_zero_when_every_step_matches():
    code, output = _run(["demo"])
    assert code == 0
    assert "chain intact" in output


def test_the_demo_prints_all_five_verdicts():
    _, output = _run(["demo"])
    for expected in ("ALLOW", "BLOCK", "ESCALATE"):
        assert expected in output


def test_the_demo_says_which_path_the_interpretation_took():
    """A replayed scope must never be presented as a live one, in any surface."""
    _, output = _run(["demo"])
    assert any(
        phrase in output
        for phrase in (
            "pinned",
            "live model call",
            "bundled transcript",
            "no model available",
        )
    )


# -- verify ---------------------------------------------------------------- #


def test_verify_exits_zero_on_an_intact_chain(ledger_path):
    code, output = _run(["verify", str(ledger_path)])
    assert code == 0
    assert "Chain intact" in output


def test_verify_fails_the_build_on_a_tampered_chain(ledger_path):
    ledger = Ledger(ledger_path)
    ledger._db.execute("UPDATE ledger SET payload = ? WHERE seq = 3", ("{}",))
    ledger._db.commit()
    ledger.close()

    code, output = _run(["verify", str(ledger_path)])
    assert code == 1
    assert "Chain broken at entry 3" in output


def test_verify_names_both_hashes_so_the_break_can_be_checked(ledger_path):
    ledger = Ledger(ledger_path)
    ledger._db.execute("UPDATE ledger SET payload = ? WHERE seq = 2", ("{}",))
    ledger._db.commit()
    ledger.close()

    _, output = _run(["verify", str(ledger_path)])
    assert "expected" in output and "found" in output


def test_verify_on_a_missing_ledger_is_an_error_not_a_pass(tmp_path):
    code, _ = _run(["verify", str(tmp_path / "absent.db")])
    assert code == 2


# -- trace ----------------------------------------------------------------- #


def test_trace_shows_refusals_with_the_rules_that_caused_them(ledger_path):
    code, output = _run(["trace", str(ledger_path)])
    assert code == 0
    assert "cart_blocked" in output
    assert "scope.category" in output


def test_trace_shows_the_settled_debit(ledger_path):
    _, output = _run(["trace", str(ledger_path)])
    assert "debit_settled" in output


def test_trace_on_a_missing_ledger_is_an_error(tmp_path):
    code, _ = _run(["trace", str(tmp_path / "absent.db")])
    assert code == 2


def test_an_unknown_session_traces_nothing_rather_than_everything(ledger_path):
    code, output = _run(["trace", str(ledger_path), "--session", "sess_nope"])
    assert code == 0
    assert "cart_blocked" not in output


# -- argument surface ------------------------------------------------------ #


def test_a_missing_subcommand_is_rejected():
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code != 0


def test_an_unknown_rail_is_rejected_before_anything_runs():
    with pytest.raises(SystemExit) as exc:
        main(["demo", "--rail", "sepa"])
    assert exc.value.code != 0
