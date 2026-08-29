"""Signing must be deterministic where we need reproducibility, and strict everywhere else."""

from __future__ import annotations

from warrant.crypto import ALGORITHM, Signature, SigningKey, VerifyKey, digest


def test_seeded_keys_are_reproducible():
    assert SigningKey.from_seed("a").key_id == SigningKey.from_seed("a").key_id


def test_different_seeds_give_different_keys():
    assert SigningKey.from_seed("a").key_id != SigningKey.from_seed("b").key_id


def test_key_id_is_derived_from_the_public_key():
    key = SigningKey.from_seed("a")
    assert key.key_id == key.public.key_id
    assert key.key_id == VerifyKey.from_b64(key.public.b64).key_id


def test_signature_round_trips(user_key: SigningKey):
    payload = {"scope": {"max_total_paise": 100_000}}
    sig = user_key.sign(payload)
    assert user_key.public.verify(payload, sig)
    assert Signature.from_dict(sig.to_dict()) == sig


def test_signature_fails_on_a_changed_payload(user_key: SigningKey):
    sig = user_key.sign({"amount": 100})
    assert not user_key.public.verify({"amount": 101}, sig)


def test_signature_fails_under_a_different_key(user_key: SigningKey):
    sig = user_key.sign({"amount": 100})
    assert not SigningKey.from_seed("attacker").public.verify({"amount": 100}, sig)


def test_signature_fails_when_the_key_id_is_swapped(user_key: SigningKey):
    # An attacker relabels a valid signature to claim it came from another key.
    sig = user_key.sign({"amount": 100})
    forged = Signature(key_id="key_deadbeefdeadbeef", algorithm=sig.algorithm, value=sig.value)
    assert not user_key.public.verify({"amount": 100}, forged)


def test_signature_fails_on_an_unknown_algorithm(user_key: SigningKey):
    sig = user_key.sign({"amount": 100})
    downgraded = Signature(key_id=sig.key_id, algorithm="none", value=sig.value)
    assert not user_key.public.verify({"amount": 100}, downgraded)


def test_signature_fails_on_malformed_base64(user_key: SigningKey):
    sig = user_key.sign({"amount": 100})
    assert not user_key.public.verify({"amount": 100}, Signature(sig.key_id, ALGORITHM, "!!!"))


def test_digest_is_stable_across_key_order():
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})


def test_digest_changes_with_content():
    assert digest({"a": 1}) != digest({"a": 2})
