"""Audit trail for the exact official image references sent to a media provider.

No file bytes or public URLs are added to Product models here.  The trace lives
inside ImportMediaCandidate.metadata so no migration is required.
"""
from copy import deepcopy
from django.utils import timezone

TRACE_KEY = "generation_reference_trace"
HISTORY_KEY = "generation_reference_history"
TEXT_GROUNDING_TRACE_KEY = "creative_text_grounding_trace"


def build_reference_trace(*, urls, attempt, view_role, provider_key, recorded_at=None):
    unique = []
    for value in urls or []:
        value = str(value or "").strip()
        if value and value not in unique:
            unique.append(value)
    moment = recorded_at or timezone.now()
    return {
        "reference_urls": unique,
        "attempt": int(attempt or 0),
        "view_role": str(view_role or ""),
        "provider_key": str(provider_key or ""),
        "recorded_at": moment.isoformat(),
    }


def record_reference_trace(candidate, *, urls, provider_key):
    """Persist a trace before the provider request is made.

    The returned URL list is the exact immutable-in-memory list the caller should
    pass to the provider for this generation attempt.
    """
    trace = build_reference_trace(
        urls=urls,
        attempt=candidate.generation_attempts,
        view_role=candidate.view_role,
        provider_key=provider_key,
    )
    metadata = deepcopy(candidate.metadata or {})
    history = list(metadata.get(HISTORY_KEY) or [])
    history.append(trace)
    metadata[HISTORY_KEY] = history[-10:]
    metadata[TRACE_KEY] = trace
    candidate.metadata = metadata
    return list(trace["reference_urls"])


def reference_trace_for_candidate(candidate):
    """Return the immutable provider-request trace for review.

    A valid recorded request may intentionally contain ZERO visual reference
    URLs (Phase 5.2.3 text-grounded creative generation). Presence of the trace
    key — not a non-empty URL list — is therefore what proves that a request
    trace was recorded.

    Older candidates without a trace key still fall back to mutable
    candidate.reference_urls and remain clearly marked as legacy/unlocked.
    """
    metadata = candidate.metadata or {}
    raw_trace = metadata.get(TRACE_KEY)
    if isinstance(raw_trace, dict):
        trace = raw_trace
        return {
            "recorded": True,
            "reference_urls": list(trace.get("reference_urls") or []),
            "attempt": int(trace.get("attempt") or candidate.generation_attempts or 0),
            "view_role": str(trace.get("view_role") or candidate.view_role or ""),
            "provider_key": str(trace.get("provider_key") or candidate.provider_key or ""),
            "recorded_at": str(trace.get("recorded_at") or ""),
        }

    return {
        "recorded": False,
        "reference_urls": list(candidate.reference_urls or []),
        "attempt": int(candidate.generation_attempts or 0),
        "view_role": str(candidate.view_role or ""),
        "provider_key": str(candidate.provider_key or ""),
        "recorded_at": "",
    }


def text_grounding_trace_for_candidate(candidate):
    """Return the verified manufacturer-text grounding snapshot, if present.

    This trace is documentary/audit metadata only.  It never upgrades generated
    appearance into manufacturer-verified visual evidence.
    """
    metadata = candidate.metadata or {}
    raw = metadata.get(TEXT_GROUNDING_TRACE_KEY)
    if not isinstance(raw, dict) or not raw:
        return {
            "recorded": False,
            "mode": "",
            "provider": "",
            "official_product_url": "",
            "name": "",
            "brand": "",
            "model": "",
            "evidence_urls": [],
        }

    return {
        "recorded": True,
        "mode": str(raw.get("mode") or ""),
        "provider": str(raw.get("provider") or ""),
        "official_product_url": str(raw.get("official_product_url") or ""),
        "name": str(raw.get("name") or ""),
        "brand": str(raw.get("brand") or ""),
        "model": str(raw.get("model") or ""),
        "evidence_urls": [
            str(url).strip()
            for url in (raw.get("evidence_urls") or [])
            if str(url).strip()
        ][:20],
    }
