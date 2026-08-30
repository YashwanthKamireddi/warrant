"""The evidence pack is what a bank reads. It has to be assembled, not asserted.

Two properties matter more than the prose: every field is derived from ledger
entries (no model writes evidence, because evidence a model wrote is evidence the
other side gets to question), and the pack refuses to vouch for itself when the
chain or the signature does not hold up.
"""

from __future__ import annotations

import pytest

from warrant.authorize import Authorizer
from warrant.chain import EventKind, Ledger
from warrant.crypto import SigningKey
from warrant.evidence import EVIDENCE_LIMIT, assemble_evidence
from warrant.models import LineItem, RailBinding


@pytest.fixture
def settled(intent, user_key, chai, samosa):
    """One settled debit, and everything needed to read it back."""
    ledger = Ledger()
    authorizer = Authorizer(
        authorizer_key=SigningKey.from_seed("test/authorizer"), ledger=ledger
    )
    authorizer._states[intent.digest] = authorizer.state_for(intent)
    ledger.append(
        EventKind.INTENT_ISSUED,
        authorizer.session_for(intent),
        {
            "intent": intent.envelope(),
            "derivation": {
                "source": "transcript",
                "plain_english": "Allow up to ₹1,000 at Zomato for food, for 2 hours.",
                "ambiguities": [],
            },
        },
        recorded_at=1_000,
    )
    cart = authorizer.propose_cart(
        intent, merchant="zomato", items=(chai, samosa), now=2_000, nonce="cart-ev"
    )
    outcome = authorizer.authorize(
        intent, cart, subject_key=user_key.public, now=2_000, skip_semantic=True
    )
    assert outcome.receipt is not None
    return ledger, authorizer.session_for(intent), outcome


def _pack(settled, key):
    ledger, session, _ = settled
    return assemble_evidence(ledger, session, subject_key=key.public)


# -- assembly -------------------------------------------------------------- #


def test_the_pack_names_the_settled_payment(settled, user_key):
    pack = _pack(settled, user_key)
    _, _, outcome = settled
    assert pack.payment_id == outcome.rail.ref.payment_id
    assert pack.amount_paise == outcome.cart.total_paise


def test_the_explanation_letter_fits_razorpays_limit(settled, user_key):
    assert len(_pack(settled, user_key).explanation_letter) <= EVIDENCE_LIMIT


def test_the_letter_quotes_the_instruction_verbatim(settled, user_key, intent):
    assert intent.utterance in _pack(settled, user_key).explanation_letter


def test_customer_communication_carries_what_was_shown_before_signing(
    settled, user_key
):
    text = _pack(settled, user_key).customer_communication
    assert "Allow up to ₹1,000 at Zomato" in text
    assert "signed by device key" in text.lower() or "device key" in text


def test_proof_of_service_lists_what_was_delivered(settled, user_key):
    text = _pack(settled, user_key).proof_of_service
    assert "Masala Chai" in text
    assert "Samosa Plate" in text


def test_the_activity_log_carries_the_whole_chain(settled, user_key):
    log = _pack(settled, user_key).access_activity_log
    assert log["intent_mandate"]["signature"] is not None
    assert log["cart_mandate"]["digest"]
    assert log["debit_receipt"]["digest"]
    assert len(log["ledger"]) >= 5


def test_the_log_publishes_the_key_needed_to_check_it(settled, user_key):
    log = _pack(settled, user_key).access_activity_log
    assert log["verification"]["subject_public_key"] == user_key.public.b64
    assert log["verification"]["subject_key_id"] == user_key.public.key_id


def test_the_chain_links_receipt_to_cart_to_intent(settled, user_key, intent):
    log = _pack(settled, user_key).access_activity_log
    assert log["debit_receipt"]["body"]["cart_digest"] == log["cart_mandate"]["digest"]
    assert log["cart_mandate"]["body"]["intent_digest"] == intent.digest


# -- self-verification ----------------------------------------------------- #


def test_a_sound_pack_vouches_for_itself(settled, user_key):
    pack = _pack(settled, user_key)
    assert pack.signatures_verified
    assert pack.chain_intact
    assert "WARNING" not in pack.verification_note


def test_the_pack_refuses_to_vouch_for_a_broken_chain(settled, user_key):
    # Edit an entry the assembly does not read, so the pack is built successfully
    # and then has to catch the tampering on its own.
    ledger, session, _ = settled
    ledger._db.execute(
        "UPDATE ledger SET payload = ? WHERE kind = ?", ('{"x":1}', "cart_proposed")
    )
    ledger._db.commit()
    pack = assemble_evidence(ledger, session, subject_key=user_key.public)
    assert pack.chain_intact is False
    assert "WARNING" in pack.verification_note
    assert "Do not submit" in pack.verification_note


def test_the_pack_refuses_when_the_signature_is_from_another_key(settled):
    ledger, session, _ = settled
    impostor = SigningKey.from_seed("not-the-subject")
    pack = assemble_evidence(ledger, session, subject_key=impostor.public)
    assert pack.signatures_verified is False
    assert "WARNING" in pack.verification_note


# -- failure modes --------------------------------------------------------- #


def test_an_unknown_session_is_an_error_not_an_empty_pack():
    with pytest.raises(ValueError, match="no ledger entries"):
        assemble_evidence(Ledger(), "sess_nope", subject_key=SigningKey.generate().public)


def test_a_session_with_no_settled_debit_cannot_produce_a_pack(intent, user_key):
    ledger = Ledger()
    authorizer = Authorizer(
        authorizer_key=SigningKey.from_seed("test/authorizer"), ledger=ledger
    )
    session = authorizer.session_for(intent)
    ledger.append(
        EventKind.INTENT_ISSUED,
        session,
        {"intent": intent.envelope(), "derivation": {}},
        recorded_at=1_000,
    )
    laptop = LineItem(
        sku="lap", name="Laptop", category="electronics", qty=1, unit_paise=42_000
    )
    cart = authorizer.propose_cart(
        intent, merchant="zomato", items=(laptop,), now=2_000, nonce="blocked"
    )
    authorizer.authorize(
        intent, cart, subject_key=user_key.public, now=2_000, skip_semantic=True
    )
    with pytest.raises(ValueError, match="no settled payment"):
        assemble_evidence(ledger, session, subject_key=user_key.public)


def test_the_contest_payload_stays_within_the_field_limit(settled, user_key):
    payload = _pack(settled, user_key).as_contest_payload()
    assert len(payload["summary"]) <= EVIDENCE_LIMIT
    assert payload["action"] == "draft"


def test_no_rail_binding_still_produces_a_pack(intent, user_key, chai):
    """A mandate with no rail block must not break evidence assembly."""
    # Changing the rail changes the signed body, so this has to be re-signed.
    # (An earlier version of this test did not, and the gate correctly refused it.)
    plain = intent.model_copy(
        update={"rail": RailBinding(kind="simulated"), "signature": None}
    ).signed_by(user_key)
    ledger = Ledger()
    authorizer = Authorizer(
        authorizer_key=SigningKey.from_seed("test/authorizer"), ledger=ledger
    )
    session = authorizer.session_for(plain)
    ledger.append(
        EventKind.INTENT_ISSUED,
        session,
        {"intent": plain.envelope(), "derivation": {"plain_english": "x"}},
        recorded_at=1_000,
    )
    cart = authorizer.propose_cart(
        plain, merchant="zomato", items=(chai,), now=2_000, nonce="n"
    )
    authorizer.authorize(
        plain, cart, subject_key=user_key.public, now=2_000, skip_semantic=True
    )
    pack = assemble_evidence(ledger, session, subject_key=user_key.public)
    assert pack.signatures_verified
