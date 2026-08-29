"""Ed25519 signing over canonical JSON.

Three primitives the rest of the engine builds on:

  * :func:`digest` -- a content address for any signable structure
  * :class:`SigningKey` / :class:`VerifyKey` -- Ed25519, with key ids derived
    from the public key so a signature always names the key that made it
  * :func:`sign` / :func:`verify` -- detached signatures over canonical bytes

Keys can be derived deterministically from a seed. That is what makes
``make demo`` reproducible: the same seed yields the same keys, the same
signatures and therefore the same ledger hashes on every machine, which is
what lets a reviewer check our published output against their own run.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .canon import canonicalize

__all__ = [
    "ALGORITHM",
    "Signature",
    "SigningKey",
    "VerifyKey",
    "digest",
    "sign",
    "verify",
]

ALGORITHM = "ed25519-sha256-jcs"
_DIGEST_PREFIX = "sha256:"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def digest(value: Any) -> str:
    """Content address of a signable structure, e.g. ``sha256:9f86d081...``.

    This is how mandates reference each other. A cart mandate carries the digest
    of the intent mandate it was issued under, so altering the intent by even one
    byte orphans every cart beneath it.
    """
    return _DIGEST_PREFIX + hashlib.sha256(canonicalize(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class Signature:
    """A detached signature. Serializes into the mandate it authenticates."""

    key_id: str
    algorithm: str
    value: str

    def to_dict(self) -> dict[str, str]:
        return {"key_id": self.key_id, "algorithm": self.algorithm, "value": self.value}

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> Signature:
        return cls(
            key_id=data["key_id"],
            algorithm=data["algorithm"],
            value=data["value"],
        )

    @property
    def short(self) -> str:
        """Eight characters, for display. The console shows this on the seal."""
        return self.value[:8]


def _key_id(public_bytes: bytes) -> str:
    return "key_" + hashlib.sha256(public_bytes).hexdigest()[:16]


class VerifyKey:
    """The public half. Anyone holding this can check a signature."""

    __slots__ = ("_key", "_raw")

    def __init__(self, raw: bytes) -> None:
        self._raw = raw
        self._key: Ed25519PublicKey = Ed25519PublicKey.from_public_bytes(raw)

    @classmethod
    def from_b64(cls, text: str) -> VerifyKey:
        return cls(_unb64(text))

    @property
    def raw(self) -> bytes:
        return self._raw

    @property
    def b64(self) -> str:
        return _b64(self._raw)

    @property
    def key_id(self) -> str:
        return _key_id(self._raw)

    def verify(self, payload: Any, signature: Signature) -> bool:
        if signature.algorithm != ALGORITHM:
            return False
        if not hmac.compare_digest(signature.key_id, self.key_id):
            return False
        try:
            self._key.verify(_unb64(signature.value), canonicalize(payload))
        except (InvalidSignature, ValueError):
            return False
        return True


class SigningKey:
    """The private half. Held by whoever is authorized to issue mandates."""

    __slots__ = ("_key", "_public")

    def __init__(self, key: Ed25519PrivateKey) -> None:
        self._key = key
        self._public = VerifyKey(
            key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        )

    @classmethod
    def generate(cls) -> SigningKey:
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_seed(cls, seed: str | bytes) -> SigningKey:
        """Derive a key deterministically from a label.

        Used for demos, fixtures and the benchmark so that runs are reproducible.
        Never use this for a key that guards real money.
        """
        if isinstance(seed, str):
            seed = seed.encode("utf-8")
        material = hashlib.sha256(b"warrant/ed25519/v1" + seed).digest()
        return cls(Ed25519PrivateKey.from_private_bytes(material))

    @property
    def public(self) -> VerifyKey:
        return self._public

    @property
    def key_id(self) -> str:
        return self._public.key_id

    def sign(self, payload: Any) -> Signature:
        return Signature(
            key_id=self.key_id,
            algorithm=ALGORITHM,
            value=_b64(self._key.sign(canonicalize(payload))),
        )


def sign(payload: Any, key: SigningKey) -> Signature:
    return key.sign(payload)


def verify(payload: Any, signature: Signature, key: VerifyKey) -> bool:
    return key.verify(payload, signature)
