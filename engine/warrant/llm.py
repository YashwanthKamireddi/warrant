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
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from .providers import DEFAULT_MODELS, Provider, resolve_provider

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
    provider = _live_client(client)

    if provider is not None:
        chosen = model or os.environ.get("WARRANT_MODEL") or DEFAULT_MODELS[provider.name]
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
        except Exception:  # noqa: BLE001 - fall through to the transcript
            pass

    try:
        return TranscriptClient().fetch(output_format, content), "transcript"
    except (KeyError, ValueError):
        return None, "fallback"


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
