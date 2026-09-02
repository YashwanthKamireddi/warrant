"""Warrant — an authorization layer for agent-initiated payments.

Importing the package loads ``.env`` from the project root if one exists, so a
reviewer who follows the README and drops their Razorpay test keys in a file
gets the behaviour the README promised. Real environment variables always win:
``load_dotenv`` does not override what is already set.
"""

from __future__ import annotations

from pathlib import Path as _Path

try:
    from dotenv import load_dotenv as _load_dotenv
except ImportError:  # pragma: no cover - dotenv is a declared dependency
    _load_dotenv = None

if _load_dotenv is not None:
    for _candidate in (
        _Path.cwd() / ".env",
        _Path(__file__).resolve().parents[2] / ".env",
    ):
        if _candidate.is_file():
            _load_dotenv(_candidate, override=False)
            break

__version__ = "0.1.0"

# The front door. Everything else in the package is reachable, and nothing else
# in the package is the first thing anybody should have to meet.
from .client import Permission, Warrant, WarrantDecision  # noqa: E402
from .merchants import MerchantRecord, MerchantRegistry  # noqa: E402
from .models import Verdict  # noqa: E402

__all__ = [
    "MerchantRecord",
    "MerchantRegistry",
    "Permission",
    "Verdict",
    "Warrant",
    "WarrantDecision",
    "__version__",
]
