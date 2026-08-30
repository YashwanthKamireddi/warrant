"""The AP2-shaped export has to be verifiable, and honest about where it diverges.

An export nobody can check is a slide. The important test here reconstructs a
verifier's job from the emitted document alone -- canonicalize, check the proof
against the published key, follow the digests -- and confirms it holds.
"""

from __future__ import annotations

from warrant.canon import canonicalize
from warrant.crypto import Signature, SigningKey, VerifyKey
from warrant.interop import AP2_MAPPING, DIVERGENCES, to_ap2_chain
from warrant.models import IntentMandate, LineItem


def _chain(intent, cart=None, receipt=None, key=None, decision=None):
    return to_ap2_chain(intent, cart, receipt, subject_key=key.public, decision=decision)


def test_the_three_documents_map_onto_ap2s_vocabulary(intent, user_key, make_cart, chai):
    chain = _chain(intent, make_cart((chai,)), None, user_key)
    kinds = [c["type"][1] for c in chain["verifiableCredential"]]
    assert kinds == ["IntentMandate", "CartMandate"]


def test_the_receipt_is_exported_as_a_payment_mandate(settled_chain):
    chain, _ = settled_chain
    kinds = [c["type"][1] for c in chain["verifiableCredential"]]
    assert kinds == ["IntentMandate", "CartMandate", "PaymentMandate"]


def test_a_purchase_that_never_settled_exports_no_payment_credential(
    intent, user_key, make_cart, chai
):
    """The honest representation of a blocked cart is an absent payment, not a
    payment marked failed."""
    chain = _chain(intent, make_cart((chai,)), None, user_key)
    assert all(c["type"][1] != "PaymentMandate" for c in chain["verifiableCredential"])


# -- the export is actually verifiable ------------------------------------- #


def test_a_verifier_can_check_the_intent_proof_from_the_document_alone(
    intent, user_key, make_cart, chai
):
    chain = _chain(intent, make_cart((chai,)), None, user_key)
    published = VerifyKey.from_b64(chain["verification"]["subject_public_key"])

    credential = chain["verifiableCredential"][0]
    proof = credential["proof"]
    signature = Signature(
        key_id=proof["verificationMethod"],
        algorithm=proof["cryptosuite"],
        value=proof["proofValue"],
    )
    assert published.verify(credential["credentialSubject"], signature)


def test_tampering_with_an_exported_subject_breaks_its_proof(
    intent, user_key, make_cart, chai
):
    chain = _chain(intent, make_cart((chai,)), None, user_key)
    published = VerifyKey.from_b64(chain["verification"]["subject_public_key"])
    credential = chain["verifiableCredential"][0]
    proof = credential["proof"]

    forged = dict(credential["credentialSubject"])
    forged["scope"] = {**forged["scope"], "max_total_paise": 10_000_000}

    signature = Signature(
        key_id=proof["verificationMethod"],
        algorithm=proof["cryptosuite"],
        value=proof["proofValue"],
    )
    assert not published.verify(forged, signature)


def test_the_cart_credential_references_the_intents_digest(
    intent, user_key, make_cart, chai
):
    chain = _chain(intent, make_cart((chai,)), None, user_key)
    intent_cred, cart_cred = chain["verifiableCredential"][:2]
    assert cart_cred["credentialSubject"]["intent_digest"] == intent_cred["digest"]


def test_the_exported_digest_matches_the_canonical_subject(
    intent, user_key, make_cart, chai
):
    import hashlib

    chain = _chain(intent, make_cart((chai,)), None, user_key)
    for credential in chain["verifiableCredential"]:
        recomputed = (
            "sha256:"
            + hashlib.sha256(canonicalize(credential["credentialSubject"])).hexdigest()
        )
        assert recomputed == credential["digest"]


def test_an_unsigned_document_exports_a_null_proof_rather_than_a_fake_one(
    scope, user_key, make_cart, chai
):
    unsigned = IntentMandate(
        subject="user_priya",
        agent="agent_claude",
        utterance="x",
        scope=scope,
        issued_at=1_000,
        nonce="n",
    )
    chain = to_ap2_chain(unsigned, None, None, subject_key=user_key.public)
    assert chain["verifiableCredential"][0]["proof"] is None


# -- honesty about the boundary -------------------------------------------- #


def test_the_evaluation_is_namespaced_not_presented_as_ap2(settled_chain):
    """AP2 defines no evaluation. Exporting one under an AP2 key would imply the
    standard blesses it."""
    chain, _ = settled_chain
    assert "warrant:evaluation" in chain
    assert chain["warrant:evaluation"] is not None
    assert not any(k.startswith("ap2:") for k in chain)


def test_the_divergences_travel_with_the_document(settled_chain):
    chain, _ = settled_chain
    topics = {d["topic"] for d in chain["warrant:divergences"]}
    assert "who signs the cart" in topics
    assert len(chain["warrant:divergences"]) == len(DIVERGENCES)


def test_the_mapping_covers_every_document_type():
    assert {w for w, _, _ in AP2_MAPPING} == {
        "IntentMandate",
        "CartMandate",
        "DebitReceipt",
    }


def test_the_verification_block_tells_a_stranger_what_to_do(
    intent, user_key, make_cart, chai
):
    chain = _chain(intent, make_cart((chai,)), None, user_key)
    assert chain["verification"]["canonicalization"] == "RFC 8785 (JCS)"
    assert "Canonicalize" in chain["verification"]["instructions"]
    assert chain["verification"]["subject_key_id"] == user_key.public.key_id


def test_the_holder_is_the_agent_not_the_merchant(intent, user_key):
    chain = _chain(intent, None, None, user_key)
    assert chain["holder"] == intent.agent


def test_an_out_of_scope_cart_still_exports_a_faithful_chain(
    intent, user_key, make_cart
):
    laptop = LineItem(
        sku="lap", name="Laptop", category="electronics", qty=1, unit_paise=42_000
    )
    chain = _chain(intent, make_cart((laptop,)), None, user_key)
    subject = chain["verifiableCredential"][1]["credentialSubject"]
    assert subject["line_items"][0]["category"] == "electronics"


def test_seeded_keys_make_the_export_reproducible(intent, user_key, make_cart, chai):
    a = _chain(intent, make_cart((chai,)), None, user_key)
    b = _chain(intent, make_cart((chai,)), None, SigningKey.from_seed("test/user"))
    assert a == b
