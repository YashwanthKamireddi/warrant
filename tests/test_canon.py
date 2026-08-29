"""Canonical JSON must be byte-stable, or every signature in the system is worthless."""

from __future__ import annotations

import pytest

from warrant.canon import CanonError, canonical_str, canonicalize


def test_object_keys_are_sorted():
    assert canonical_str({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_key_order_does_not_change_output():
    a = {"z": 1, "m": {"q": [3, 2], "a": None}, "b": True}
    b = {"b": True, "m": {"a": None, "q": [3, 2]}, "z": 1}
    assert canonicalize(a) == canonicalize(b)


def test_array_order_is_preserved():
    assert canonical_str([3, 1, 2]) == "[3,1,2]"


def test_no_insignificant_whitespace():
    out = canonical_str({"a": [1, 2], "b": {"c": 3}})
    assert " " not in out
    assert out == '{"a":[1,2],"b":{"c":3}}'


def test_unicode_is_emitted_directly():
    assert canonical_str({"n": "chai"}) == '{"n":"chai"}'
    assert "ä" in canonical_str({"a": "ä"})


def test_floats_are_rejected_because_money_is_never_a_float():
    with pytest.raises(CanonError, match="integer paise"):
        canonicalize({"amount": 12.5})


def test_floats_are_rejected_when_nested():
    with pytest.raises(CanonError, match=r"\$\.cart\.items\[0\]\.price"):
        canonicalize({"cart": {"items": [{"price": 1.0}]}})


def test_integers_beyond_javascript_safe_range_are_rejected():
    # Our console verifies signatures in JavaScript. An integer that cannot
    # survive that round trip must never be signed here.
    with pytest.raises(CanonError, match="safe JSON range"):
        canonicalize({"n": 2**53})


def test_non_string_keys_are_rejected():
    with pytest.raises(CanonError, match="keys must be strings"):
        canonicalize({1: "a"})


def test_unsupported_types_are_rejected():
    with pytest.raises(CanonError, match="no canonical JSON form"):
        canonicalize({"when": object()})


def test_sorting_follows_utf16_code_units_not_code_points():
    # U+FFFD sorts after a supplementary character in UTF-16 (surrogates are
    # D800..DFFF) but before it by code point. Getting this wrong would make our
    # signatures disagree with any JavaScript verifier.
    out = canonical_str({"\U0001f600": 1, "�": 2})
    assert out.index("\U0001f600") < out.index("�")
