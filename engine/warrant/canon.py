"""Canonical JSON serialization.

Every signature in Warrant is computed over bytes, not over a Python object.
Two parties must therefore agree, byte for byte, on how a mandate serializes --
otherwise a signature that is valid on one machine fails on another and the whole
chain becomes unverifiable.

This is a strict subset of RFC 8785 (JSON Canonicalization Scheme):

  * object keys sorted by UTF-16 code unit, as JavaScript's ``Array.sort`` does
  * no insignificant whitespace
  * UTF-8 output, minimal string escaping
  * **floats are rejected outright**

That last rule is the important one. Floats have no canonical decimal form that
every language agrees on, and more to the point money must never be a float.
Warrant carries every amount as an integer count of paise. If a float reaches
this function it is a bug in the caller, and we would rather fail loudly here
than sign an amount that rounds differently on the verifier's machine.
"""

from __future__ import annotations

import json
from typing import Any

__all__ = ["CanonError", "canonicalize", "canonical_str"]


class CanonError(TypeError):
    """A value was handed to the canonicalizer that cannot be signed safely."""


def _check(value: Any, path: str) -> None:
    """Walk the structure and reject anything without a canonical form."""
    if value is None or isinstance(value, str):
        return
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        # Beyond 2^53 a JSON number cannot survive a round trip through a
        # JavaScript verifier, and our console is JavaScript.
        if abs(value) > 2**53 - 1:
            raise CanonError(f"{path}: integer {value} exceeds safe JSON range")
        return
    if isinstance(value, float):
        raise CanonError(
            f"{path}: floats cannot be canonicalized. Money is carried in integer "
            f"paise; got {value!r}"
        )
    if isinstance(value, list):
        for i, item in enumerate(value):
            _check(item, f"{path}[{i}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonError(f"{path}: object keys must be strings, got {key!r}")
            _check(item, f"{path}.{key}")
        return
    raise CanonError(f"{path}: {type(value).__name__} has no canonical JSON form")


def _sort_key(key: str) -> tuple[int, ...]:
    """Sort by UTF-16 code unit, which is what RFC 8785 specifies.

    Python sorts ``str`` by code point. The two orders diverge above U+FFFF,
    where UTF-16 uses surrogate pairs -- a supplementary character sorts *before*
    U+E000..U+FFFF in UTF-16 but after it by code point. Encoding to UTF-16BE and
    comparing code units gets this right for every input.
    """
    return tuple(key.encode("utf-16-be"))


def _write(value: Any, out: list[str]) -> None:
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, int):
        out.append(str(value))
    elif isinstance(value, str):
        out.append(json.dumps(value, ensure_ascii=False))
    elif isinstance(value, list):
        out.append("[")
        for i, item in enumerate(value):
            if i:
                out.append(",")
            _write(item, out)
        out.append("]")
    elif isinstance(value, dict):
        out.append("{")
        for i, key in enumerate(sorted(value, key=_sort_key)):
            if i:
                out.append(",")
            out.append(json.dumps(key, ensure_ascii=False))
            out.append(":")
            _write(value[key], out)
        out.append("}")
    else:  # pragma: no cover - _check has already rejected these
        raise CanonError(f"{type(value).__name__} has no canonical JSON form")


def canonical_str(value: Any) -> str:
    """Canonical JSON as ``str``. Prefer :func:`canonicalize` when signing."""
    _check(value, "$")
    out: list[str] = []
    _write(value, out)
    return "".join(out)


def canonicalize(value: Any) -> bytes:
    """Canonical JSON as UTF-8 bytes. This is what gets signed and hashed."""
    return canonical_str(value).encode("utf-8")
