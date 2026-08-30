"""Exporting the mandate chain in the shape the emerging standards use.

The fair criticism of this project is that Google's AP2 already defines a chained
mandate model -- Intent, Cart, Payment -- with 60-plus partners, and NPCI's UAP is
being designed to do agent authorisation at the network level. So why is there a
merchant-side implementation at all?

Because those specify **what the credential is**, not **who checks it**.

AP2 standardises a signed, chained, non-repudiable record of what a user
authorised. It does not say which rules a merchant must evaluate before
settlement, what happens when a basket sits inside every stated bound and is
still wrong, or how a refusal gets recorded. That gap is what the deterministic
gate, the advisory judge and the ledger in this repository are. The two are
complementary: the standard is the document, this is the check.

This module makes that concrete rather than rhetorical. It maps Warrant's chain
onto AP2's vocabulary and emits it in a W3C Verifiable-Credentials-shaped
envelope, so the same audit trail can be handed to something that speaks AP2.

**What this is not.** It is a shape-compatible export, not certified
interoperability. Nothing here has been tested against a real AP2 verifier,
because there was none to test against. The mapping table below states every
place the two models genuinely differ, including the one that matters.
"""

from __future__ import annotations

from typing import Any

from .crypto import VerifyKey
from .models import CartMandate, DebitReceipt, IntentMandate

__all__ = ["AP2_MAPPING", "DIVERGENCES", "to_ap2_chain"]

AP2_CONTEXT = (
    "https://www.w3.org/ns/credentials/v2",
    "https://agentpayments.dev/ns/ap2/v1",
)

AP2_MAPPING: tuple[tuple[str, str, str], ...] = (
    (
        "IntentMandate",
        "IntentMandate",
        "Same role and same signer: the human delegates bounded authority with "
        "their own key.",
    ),
    (
        "CartMandate",
        "CartMandate",
        "Same role, different signer by default. See DIVERGENCES.",
    ),
    (
        "DebitReceipt",
        "PaymentMandate",
        "Same role: the credential that binds a settled rail payment to the cart "
        "and the intent above it.",
    ),
)

DIVERGENCES: tuple[tuple[str, str], ...] = (
    (
        "who signs the cart",
        "AP2 has the user sign the Cart Mandate, approving one specific basket at "
        "one specific price. Warrant has the authoriser sign it, attesting that it "
        "checked the basket against the intent -- and requires the user's "
        "co-signature only above a step-up threshold. That is deliberate: UPI "
        "Reserve Pay exists so a user does not re-authenticate per purchase, and a "
        "chain that demands a user signature on every cart cannot express standing "
        "delegation at all. Above the threshold the two models converge exactly.",
    ),
    (
        "rail binding",
        "AP2 is payment-method agnostic. Warrant carries UPI Reserve Pay semantics "
        "explicitly -- the blocked amount and how much of it remains -- because that "
        "block is a real constraint enforced by the rail, independent of anything "
        "this layer decides, and pretending otherwise would let the gate authorise "
        "spend the rail will refuse.",
    ),
    (
        "the check itself",
        "AP2 does not specify the evaluation. Warrant's gate, its rule-level "
        "verdicts and its refusal records have no counterpart in the standard, and "
        "are exported here as an extension rather than dressed up as AP2.",
    ),
)


def _credential(kind: str, envelope: dict[str, Any], issuer: str) -> dict[str, Any]:
    """One document in a Verifiable-Credentials-shaped wrapper."""
    signature = envelope.get("signature")
    return {
        "@context": list(AP2_CONTEXT),
        "type": ["VerifiableCredential", kind],
        "id": f"urn:warrant:{envelope['id']}",
        "issuer": issuer,
        "credentialSubject": envelope["body"],
        "digest": envelope["digest"],
        "proof": None
        if signature is None
        else {
            "type": "Ed25519Signature2020",
            "verificationMethod": signature["key_id"],
            "proofValue": signature["value"],
            # The bytes signed are the canonical JSON of credentialSubject,
            # per RFC 8785. A verifier must canonicalize before checking.
            "cryptosuite": signature["algorithm"],
        },
    }


def to_ap2_chain(
    intent: IntentMandate,
    cart: CartMandate | None = None,
    receipt: DebitReceipt | None = None,
    *,
    subject_key: VerifyKey,
    decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Emit the chain in AP2's vocabulary, W3C-VC shaped.

    Only the documents that exist are included, so a blocked cart exports an
    intent and a cart with no payment credential -- which is the honest
    representation of a purchase that never settled.
    """
    credentials = [_credential("IntentMandate", intent.envelope(), intent.subject)]
    if cart is not None:
        credentials.append(_credential("CartMandate", cart.envelope(), "authorizer"))
    if receipt is not None:
        credentials.append(_credential("PaymentMandate", receipt.envelope(), "authorizer"))

    return {
        "@context": list(AP2_CONTEXT),
        "type": ["VerifiablePresentation", "AgentPaymentChain"],
        "holder": intent.agent,
        "verifiableCredential": credentials,
        "verification": {
            "subject_public_key": subject_key.b64,
            "subject_key_id": subject_key.key_id,
            "canonicalization": "RFC 8785 (JCS)",
            "instructions": (
                "Canonicalize each credentialSubject per RFC 8785, verify its proof "
                "against the subject public key for the IntentMandate, then confirm "
                "each digest matches the reference held by the credential beneath it."
            ),
        },
        # Namespaced, because the standard does not define an evaluation and
        # presenting one as though it did would be the dishonest move.
        "warrant:evaluation": decision,
        "warrant:divergences": [
            {"topic": topic, "note": note} for topic, note in DIVERGENCES
        ],
    }
