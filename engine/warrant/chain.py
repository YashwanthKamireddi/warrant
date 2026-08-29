"""The ledger: an append-only, hash-chained record of every authorization decision.

Each entry commits to the one before it, so altering any past entry changes its
hash and orphans everything after it. :meth:`Ledger.audit` walks the chain and
names the first entry that no longer adds up.

Two properties matter more than the cryptography:

**Refusals are recorded.** A gate that blocks a debit writes a ledger entry
describing what it refused and which rule fired. Most systems log what they did;
the interesting question in a dispute is almost always what they declined to do,
and at what time, and why. "We did not debit at 21:40 because the mandate had
expired at 19:00" is a row here, not an absence of rows.

**Entries are replayable.** Every entry carries the complete input to the
decision it records, so re-running the ledger reproduces the same verdicts. That
is what lets a reviewer -- or a bank -- check our conclusions instead of
trusting them.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from .crypto import digest

__all__ = ["EventKind", "Ledger", "LedgerEntry", "ChainBreak", "GENESIS_HASH"]

GENESIS_HASH = "sha256:" + "0" * 64


class EventKind(StrEnum):
    """Everything the chain can record. Refusals are here alongside actions."""

    INTENT_ISSUED = "intent_issued"
    INTENT_REVOKED = "intent_revoked"
    CART_PROPOSED = "cart_proposed"
    CART_ALLOWED = "cart_allowed"
    CART_BLOCKED = "cart_blocked"
    STEP_UP_REQUESTED = "step_up_requested"
    STEP_UP_SATISFIED = "step_up_satisfied"
    STEP_UP_DECLINED = "step_up_declined"
    DEBIT_AUTHORIZED = "debit_authorized"
    DEBIT_SETTLED = "debit_settled"
    DEBIT_FAILED = "debit_failed"
    DISPUTE_OPENED = "dispute_opened"
    EVIDENCE_ASSEMBLED = "evidence_assembled"


class LedgerEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    seq: int
    prev_hash: str
    recorded_at: int
    kind: EventKind
    session_id: str
    payload: dict[str, Any]

    def commitment(self) -> dict[str, Any]:
        """Exactly what the entry hash covers."""
        return {
            "seq": self.seq,
            "prev_hash": self.prev_hash,
            "recorded_at": self.recorded_at,
            "kind": str(self.kind),
            "session_id": self.session_id,
            "payload": self.payload,
        }

    @property
    def hash(self) -> str:
        return digest(self.commitment())


class ChainBreak(BaseModel):
    """Where the chain stopped adding up, and how."""

    model_config = ConfigDict(frozen=True)

    seq: int
    reason: str
    expected: str
    found: str


class Ledger:
    """Append-only store. SQLite on disk, or in memory for tests and benchmarks."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = str(path) if path else ":memory:"
        self._db = sqlite3.connect(self._path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    def _create_schema(self) -> None:
        with closing(self._db.cursor()) as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS ledger (
                    seq          INTEGER PRIMARY KEY,
                    prev_hash    TEXT NOT NULL,
                    entry_hash   TEXT NOT NULL UNIQUE,
                    recorded_at  INTEGER NOT NULL,
                    kind         TEXT NOT NULL,
                    session_id   TEXT NOT NULL,
                    payload      TEXT NOT NULL
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS ledger_session ON ledger(session_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS ledger_kind ON ledger(kind)")
        self._db.commit()

    # -- writing ----------------------------------------------------------- #

    @property
    def head(self) -> str:
        row = self._db.execute("SELECT entry_hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
        return row["entry_hash"] if row else GENESIS_HASH

    @property
    def length(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) AS n FROM ledger").fetchone()["n"])

    def append(
        self,
        kind: EventKind,
        session_id: str,
        payload: dict[str, Any],
        *,
        recorded_at: int,
    ) -> LedgerEntry:
        """Add an entry. The caller supplies the clock so replays are exact."""
        import json

        entry = LedgerEntry(
            seq=self.length + 1,
            prev_hash=self.head,
            recorded_at=recorded_at,
            kind=kind,
            session_id=session_id,
            payload=payload,
        )
        self._db.execute(
            "INSERT INTO ledger (seq, prev_hash, entry_hash, recorded_at, kind,"
            " session_id, payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                entry.seq,
                entry.prev_hash,
                entry.hash,
                entry.recorded_at,
                str(entry.kind),
                entry.session_id,
                json.dumps(payload, separators=(",", ":"), sort_keys=True),
            ),
        )
        self._db.commit()
        return entry

    # -- reading ----------------------------------------------------------- #

    def _row_to_entry(self, row: sqlite3.Row) -> LedgerEntry:
        import json

        return LedgerEntry(
            seq=row["seq"],
            prev_hash=row["prev_hash"],
            recorded_at=row["recorded_at"],
            kind=EventKind(row["kind"]),
            session_id=row["session_id"],
            payload=json.loads(row["payload"]),
        )

    def entries(self, session_id: str | None = None) -> Iterator[LedgerEntry]:
        if session_id:
            rows = self._db.execute(
                "SELECT * FROM ledger WHERE session_id = ? ORDER BY seq", (session_id,)
            )
        else:
            rows = self._db.execute("SELECT * FROM ledger ORDER BY seq")
        for row in rows:
            yield self._row_to_entry(row)

    def sessions(self) -> list[str]:
        rows = self._db.execute(
            "SELECT session_id, MIN(seq) AS first FROM ledger GROUP BY session_id ORDER BY first"
        )
        return [row["session_id"] for row in rows]

    # -- integrity --------------------------------------------------------- #

    def audit(self) -> ChainBreak | None:
        """Recompute the whole chain. Returns the first break, or None if intact."""
        expected_prev = GENESIS_HASH
        expected_seq = 1
        for row in self._db.execute("SELECT * FROM ledger ORDER BY seq"):
            entry = self._row_to_entry(row)
            if entry.seq != expected_seq:
                return ChainBreak(
                    seq=entry.seq,
                    reason="sequence is not contiguous",
                    expected=str(expected_seq),
                    found=str(entry.seq),
                )
            if entry.prev_hash != expected_prev:
                return ChainBreak(
                    seq=entry.seq,
                    reason="entry does not link to its predecessor",
                    expected=expected_prev,
                    found=entry.prev_hash,
                )
            recomputed = entry.hash
            if recomputed != row["entry_hash"]:
                return ChainBreak(
                    seq=entry.seq,
                    reason="entry contents do not match its recorded hash",
                    expected=row["entry_hash"],
                    found=recomputed,
                )
            expected_prev = recomputed
            expected_seq += 1
        return None

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> Ledger:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
