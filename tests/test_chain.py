"""The ledger's job is to make an undetected edit impossible."""

from __future__ import annotations

import pytest

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


# -- concurrency ----------------------------------------------------------- #


def test_the_chain_survives_concurrent_appends():
    """Deriving the next sequence number and inserting it is a read-modify-write.

    Before this was serialised, eight concurrent writers lost 251 of 320 entries
    and broke the chain: duplicate sequence numbers, and successors linked to a
    head that had already moved. For an audit trail that is the worst possible
    class of bug, because the damage is invisible until someone verifies.
    """
    import threading

    with Ledger() as ledger:
        errors: list[str] = []
        writers, per_writer = 8, 40

        def write(writer: int) -> None:
            for i in range(per_writer):
                try:
                    ledger.append(
                        EventKind.CART_PROPOSED,
                        f"sess_{writer}",
                        {"writer": writer, "i": i},
                        recorded_at=1_000 + i,
                    )
                except Exception as exc:  # noqa: BLE001 - recorded, then asserted on
                    errors.append(f"{type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=write, args=(w,)) for w in range(writers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert ledger.length == writers * per_writer
        assert ledger.audit() is None


def test_concurrent_appends_produce_contiguous_sequence_numbers():
    import threading

    with Ledger() as ledger:
        def write(writer: int) -> None:
            for i in range(25):
                ledger.append(
                    EventKind.CART_PROPOSED, "s", {"w": writer, "i": i}, recorded_at=1
                )

        threads = [threading.Thread(target=write, args=(w,)) for w in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        seqs = [e.seq for e in ledger.entries()]
        assert seqs == list(range(1, len(seqs) + 1))


def test_a_failed_append_leaves_no_partial_entry(tmp_path):
    """A rolled-back append must not advance the chain."""
    with Ledger(tmp_path / "rollback.db") as ledger:
        ledger.append(EventKind.INTENT_ISSUED, "s", {"ok": True}, recorded_at=1)
        head_before, length_before = ledger.head, ledger.length

        class Unserialisable:
            pass

        with pytest.raises(TypeError):
            ledger.append(
                EventKind.CART_PROPOSED, "s", {"bad": Unserialisable()}, recorded_at=2
            )

        assert ledger.length == length_before
        assert ledger.head == head_before
        assert ledger.audit() is None


def test_sequence_numbers_come_from_the_maximum_not_the_count(tmp_path):
    """A count is wrong the moment anything is removed, and would reuse a number."""
    with Ledger(tmp_path / "gap.db") as ledger:
        for i in range(4):
            ledger.append(EventKind.CART_PROPOSED, "s", {"i": i}, recorded_at=i)
        ledger._db.execute("DELETE FROM ledger WHERE seq = 2")

        entry = ledger.append(EventKind.CART_PROPOSED, "s", {"i": 9}, recorded_at=9)
        assert entry.seq == 5


def test_reads_are_safe_while_a_writer_is_appending():
    """A sqlite3 connection is not safe for interleaved cursor use across threads.

    Locking only the writes left readers walking a cursor while an append moved
    underneath them. That surfaced as entries deserialising with a None kind and
    as 'another row available' errors -- an audit trail handing back garbage
    instead of failing loudly, which is the worst way for this component to be
    wrong.
    """
    import threading

    with Ledger() as ledger:
        ledger.append(EventKind.INTENT_ISSUED, "s", {"seed": True}, recorded_at=1)
        problems: list[str] = []
        stop = threading.Event()

        def writer() -> None:
            for i in range(120):
                try:
                    ledger.append(EventKind.CART_PROPOSED, "s", {"i": i}, recorded_at=i)
                except Exception as exc:  # noqa: BLE001 - recorded, then asserted
                    problems.append(f"write {type(exc).__name__}: {exc}")
            stop.set()

        def reader() -> None:
            while not stop.is_set():
                try:
                    for entry in ledger.entries("s"):
                        assert entry.kind is not None
                        assert entry.seq >= 1
                    ledger.audit()
                    _ = ledger.head, ledger.length
                except Exception as exc:  # noqa: BLE001
                    problems.append(f"read {type(exc).__name__}: {exc}")
                    return

        threads = [threading.Thread(target=writer)] + [
            threading.Thread(target=reader) for _ in range(3)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert problems == []
        assert ledger.audit() is None


def test_abandoning_a_generator_does_not_hold_the_connection():
    """Rows are materialised inside the lock, so a caller that stops reading
    half-way cannot block a writer."""
    with Ledger() as ledger:
        for i in range(10):
            ledger.append(EventKind.CART_PROPOSED, "s", {"i": i}, recorded_at=i)

        stream = ledger.entries()
        next(stream)  # take one, abandon the rest

        entry = ledger.append(EventKind.CART_ALLOWED, "s", {"after": True}, recorded_at=99)
        assert entry.seq == 11
