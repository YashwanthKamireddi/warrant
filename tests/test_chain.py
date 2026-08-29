"""The ledger's job is to make an undetected edit impossible."""

from __future__ import annotations

from warrant.chain import GENESIS_HASH, EventKind, Ledger


def _seed(ledger: Ledger, n: int = 4, session: str = "sess_1") -> None:
    for i in range(n):
        ledger.append(EventKind.CART_PROPOSED, session, {"n": i}, recorded_at=1_000 + i)


def test_first_entry_links_to_genesis():
    with Ledger() as ledger:
        entry = ledger.append(EventKind.INTENT_ISSUED, "s", {}, recorded_at=1)
        assert entry.prev_hash == GENESIS_HASH
        assert entry.seq == 1


def test_entries_link_to_their_predecessor():
    with Ledger() as ledger:
        first = ledger.append(EventKind.INTENT_ISSUED, "s", {}, recorded_at=1)
        second = ledger.append(EventKind.CART_PROPOSED, "s", {}, recorded_at=2)
        assert second.prev_hash == first.hash


def test_intact_chain_audits_clean():
    with Ledger() as ledger:
        _seed(ledger)
        assert ledger.audit() is None


def test_edited_payload_is_detected():
    with Ledger() as ledger:
        _seed(ledger)
        ledger._db.execute("UPDATE ledger SET payload = ? WHERE seq = 2", ('{"n":99}',))
        ledger._db.commit()
        break_ = ledger.audit()
        assert break_ is not None
        assert break_.seq == 2
        assert "do not match" in break_.reason


def test_deleted_entry_is_detected():
    with Ledger() as ledger:
        _seed(ledger)
        ledger._db.execute("DELETE FROM ledger WHERE seq = 2")
        ledger._db.commit()
        break_ = ledger.audit()
        assert break_ is not None
        assert break_.seq == 3
        assert "contiguous" in break_.reason


def test_relinked_entry_is_detected():
    # The sophisticated edit: change a payload *and* fix up that entry's own
    # hash. The chain still breaks, because the next entry's prev_hash is stale.
    with Ledger() as ledger:
        _seed(ledger)
        from warrant.chain import LedgerEntry

        forged = LedgerEntry(
            seq=2,
            prev_hash=next(e for e in ledger.entries() if e.seq == 2).prev_hash,
            recorded_at=1_001,
            kind=EventKind.CART_PROPOSED,
            session_id="sess_1",
            payload={"n": 99},
        )
        ledger._db.execute(
            "UPDATE ledger SET payload = ?, entry_hash = ? WHERE seq = 2",
            ('{"n":99}', forged.hash),
        )
        ledger._db.commit()
        break_ = ledger.audit()
        assert break_ is not None
        assert break_.seq == 3
        assert "does not link" in break_.reason


def test_entries_are_scoped_by_session():
    with Ledger() as ledger:
        _seed(ledger, 2, "a")
        _seed(ledger, 3, "b")
        assert len(list(ledger.entries("a"))) == 2
        assert len(list(ledger.entries("b"))) == 3
        assert ledger.sessions() == ["a", "b"]


def test_head_advances_and_starts_at_genesis():
    with Ledger() as ledger:
        assert ledger.head == GENESIS_HASH
        entry = ledger.append(EventKind.INTENT_ISSUED, "s", {}, recorded_at=1)
        assert ledger.head == entry.hash
