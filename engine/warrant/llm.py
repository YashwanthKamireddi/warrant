"""Model access, with honest degradation.

Warrant calls a model in exactly two places, and both must keep working when
there is no API key -- a reviewer cloning the repo should get a working
``make demo`` without signing up for anything. That is handled by a transcript:

  live       a provider resolved and the model was really called
  transcript a previously captured response was replayed from disk
  fallback   neither was available; the deterministic path ran and narrowed hard

Two providers can serve ``live``: Anthropic by default, and Groq's free tier as a
fallback so that **a reviewer can reproduce the benchmark without paying for
anything**. Which one answered is recorded alongside the mode, because "a model
ran" and "which model ran" are different claims.

Which of the three ran is recorded on every proposal and finding, travels into
the ledger, and is printed by the CLI. The system never presents a replayed or
fabricated interpretation as a live one.

Set ``WARRANT_RECORD=1`` with working credentials to capture a fresh transcript.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from .providers import Provider, alternatives, model_for, resolve_provider, resolve_providers

__all__ = [
    "Capability",
    "Mode",
    "Transcript",
    "TranscriptClient",
    "describe_capability",
    "structured_call",
]

Mode = Literal["live", "transcript", "fallback"]

TRANSCRIPT_PATH = Path(__file__).parent / "fixtures" / "demo-transcript.json"


def _key(output_format: type[BaseModel], content: str) -> str:
    raw = f"{output_format.__name__}\n{content}".encode()
    return hashlib.sha256(raw).hexdigest()[:32]


class Transcript(BaseModel):
    """Captured model responses, keyed by the exact request that produced them."""

    source: Literal["recorded", "authored"] = "authored"
    model: str | None = None
    recorded_at: str | None = None
    note: str = ""
    entries: dict[str, dict[str, Any]] = {}

    @classmethod
    def load(cls, path: Path = TRANSCRIPT_PATH) -> Transcript:
        if not path.exists():
            return cls()
        return cls.model_validate_json(path.read_text())

    def save(self, path: Path = TRANSCRIPT_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.model_dump(), indent=2, sort_keys=True) + "\n")

    @property
    def provenance(self) -> str:
        if self.source == "recorded":
            return f"replayed from a {self.model} response captured {self.recorded_at}"
        return "replayed from a bundled transcript (authored, not a live capture)"


class TranscriptClient:
    """Replays captured responses. Raises :class:`KeyError` on an unseen request."""

    def __init__(self, transcript: Transcript | None = None) -> None:
        self.transcript = transcript or Transcript.load()

    def fetch(self, output_format: type[BaseModel], content: str) -> BaseModel:
        entry = self.transcript.entries.get(_key(output_format, content))
        if entry is None:
            raise KeyError(f"no transcript entry for {output_format.__name__}")
        return output_format.model_validate(entry)


def _live_client(client: Any | None = None) -> Provider | None:
    """Resolve whichever provider can actually be constructed, or None."""
    try:
        return resolve_provider(client=client)
    except Exception:  # noqa: BLE001 - no credentials is a normal state here
        return None


class Capability(BaseModel):
    """What is *available*, which is not the same as what will happen.

    Constructing an SDK client proves a credential was found, not that it still
    works -- an expired token constructs fine and fails at call time. So this
    reports availability only. The authoritative mode is the ``source`` field on
    each proposal and finding, recorded after the call actually ran.
    """

    credentials_configured: bool
    provider: str | None
    transcript_available: bool
    transcript_provenance: str

    @property
    def note(self) -> str:
        if self.credentials_configured:
            return (
                f"Credentials are configured for {self.provider}. Every interpretation "
                "is still labelled with the path it actually took, because a credential "
                "can be present and expired."
            )
        if self.transcript_available:
            return (
                f"No credentials configured. Interpretations are "
                f"{self.transcript_provenance}."
            )
        return "No credentials and no transcript. Scopes narrow to the deterministic minimum."


def describe_capability() -> Capability:
    """Report what is available. Never claims what a future call will do."""
    transcript = Transcript.load()
    provider = _live_client()
    return Capability(
        credentials_configured=provider is not None,
        provider=provider.name if provider else None,
        transcript_available=bool(transcript.entries),
        transcript_provenance=transcript.provenance,
    )


def structured_call(
    *,
    output_format: type[BaseModel],
    system: str,
    content: str,
    client: object | None = None,
    model: str | None = None,
    max_tokens: int = 2_000,
) -> tuple[BaseModel | None, Mode]:
    """Make one structured request, degrading in a stated order.

    Returns ``(parsed, mode)``. A ``None`` parsed value means every path failed
    and the caller must use its own deterministic fallback.
    """
    # Try each constructible provider in turn. A credential that exists but no
    # longer works must not shadow one that does -- which it did, until this
    # loop replaced a single-provider lookup.
    try:
        providers = resolve_providers(client=client)
    except Exception:  # noqa: BLE001
        providers = []

    failures: list[str] = []

    for provider in providers:
        preferred = model_for(provider.name, model)
        # The preferred model, then smaller ones. A daily token cap is per model
        # and per organisation, so when the large model is exhausted a smaller
        # one usually is not -- and a smaller model choosing is still a model
        # choosing, which is the thing being demonstrated.
        for chosen in (preferred, *alternatives(provider.name, preferred)):
            failed: Exception | None = None
            for attempt in range(_ATTEMPTS):
                try:
                    parsed = provider.structured(
                        output_format=output_format,
                        system=system,
                        content=content,
                        model=chosen,
                        max_tokens=max_tokens,
                    )
                    if os.environ.get("WARRANT_RECORD") == "1":
                        _record(output_format, content, parsed, f"{provider.name}/{chosen}")
                    return parsed, "live"
                except Exception as exc:  # noqa: BLE001 - report, then try the next
                    # A second call moments after the first is the *normal* shape
                    # of this system: the agent is refused and immediately tries
                    # again, and a free tier answers the second one with 429.
                    failed = exc
                    if _is_transient(exc) and attempt + 1 < _ATTEMPTS:
                        time.sleep(_BACKOFF * (attempt + 1))
                        continue
                    break
            if failed is not None and not _is_transient(failed):
                # Wrong credentials will not be fixed by a smaller model.
                failures.append(f"{provider.name}: {_describe(failed)}")
                break
            if failed is not None:
                failures.append(f"{provider.name}/{chosen}: {_describe(failed)}")

    _LAST_FAILURE.set(" · ".join(failures) if failures else "no provider configured")

    try:
        return TranscriptClient().fetch(output_format, content), "transcript"
    except (KeyError, ValueError):
        return None, "fallback"


#: A provider that answers "not right now" deserves a second ask before the
#: whole run degrades. Two attempts, briefly apart -- enough for a rate limit
#: window, short enough that nobody watching notices.
_ATTEMPTS = 2
_BACKOFF = 1.2

#: Why the last call fell back, for a caller that wants to say so accurately.
#: Context-local, so two concurrent runs cannot report each other's reason.
_LAST_FAILURE: ContextVar[str] = ContextVar("warrant_llm_failure", default="")


def last_failure() -> str:
    """A short, honest reason the most recent call did not reach a model."""
    return _LAST_FAILURE.get()


def _is_transient(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(
        marker in text
        for marker in ("429", "too many requests", "rate limit", "timeout", "overloaded", "503")
    )


def _describe(exc: Exception) -> str:
    """One clause a person can act on. Never the provider's whole traceback."""
    text = str(exc)
    lowered = text.lower()
    if "429" in text or "too many requests" in lowered or "rate limit" in lowered:
        return "rate limited"
    if "401" in text or "unauthor" in lowered or "credential" in lowered or "api key" in lowered:
        return "credentials rejected"
    if "timeout" in lowered or "timed out" in lowered:
        return "timed out"
    if "503" in text or "overloaded" in lowered:
        return "temporarily unavailable"
    return type(exc).__name__


def _record(
    output_format: type[BaseModel], content: str, parsed: BaseModel, model: str
) -> None:
    from datetime import UTC, datetime

    transcript = Transcript.load()
    transcript.source = "recorded"
    transcript.model = model
    transcript.recorded_at = datetime.now(UTC).strftime("%Y-%m-%d")
    transcript.entries[_key(output_format, content)] = parsed.model_dump(mode="json")
    transcript.save()
