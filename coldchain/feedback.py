"""Lightweight user-feedback capture wired into the hash-chained audit log.

A thumbs up/down plus a free-text correction is appended as a
``user_feedback`` audit entry via :meth:`AuditLog.record`, so feedback
inherits the chain's tamper evidence and is verifiable with
:meth:`AuditLog.verify_chain` alongside every other event.

Corrections are free text from a user, so before they are written, emails,
phone numbers, SSNs and long digit runs (card or account numbers) become
placeholders, and corrections longer than ``MAX_CORRECTION_CHARS`` are
rejected. The audit chain is append-only, so anything written there stays.
"""
from __future__ import annotations

import re

from .audit import AuditLog

EVENT_TYPE = "user_feedback"
RATINGS = ("up", "down")
MAX_CORRECTION_CHARS = 2000
_PII = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    # Phone numbers in the common written forms, including "(555) 123-4567"
    # and "+1 (555) 123-4567", which the digit-run pattern below misses.
    (re.compile(r"(?<!\w)(?:\+?1[-.\s]?)?(?:\(\d{3}\)\s?|\d{3}[-.\s]?)\d{3}[-.\s]?\d{4}\b"),
     "[NUMBER]"),
    # US SSN shape (9 digits, too short for the digit-run pattern).
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    (re.compile(r"(?:\+?\d[\s().-]?){9,19}\d"), "[NUMBER]"),
]


def redact_correction(text):
    """Replace emails, phone numbers, SSNs and 10+ digit numbers; returns (text, count)."""
    count = 0
    for pattern, placeholder in _PII:
        text, n = pattern.subn(placeholder, text)
        count += n
    return text, count


class FeedbackError(ValueError):
    """Raised when a feedback submission is malformed."""


def _require_nonblank(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FeedbackError(f"{name} must be a non-blank string")
    return value.strip()


def capture_feedback(audit: AuditLog, *, session_id: str, turn_id: str,
                     rating: str, correction: str = "") -> dict:
    """Append one feedback event to the audit chain; returns the entry.

    ``rating`` must be ``"up"`` or ``"down"``. A ``"down"`` rating requires
    a non-blank ``correction`` describing what was wrong; an ``"up"`` rating
    may omit it. ``session_id`` / ``turn_id`` link the feedback to the
    conversation turn it refers to (supplied by the calling UI/orchestrator).
    """
    session_id = _require_nonblank("session_id", session_id)
    turn_id = _require_nonblank("turn_id", turn_id)
    if rating not in RATINGS:
        raise FeedbackError(
            f"rating must be one of {RATINGS}, got {rating!r}")
    correction = correction.strip() if isinstance(correction, str) else ""
    if rating == "down" and not correction:
        raise FeedbackError("a thumbs-down requires a non-blank correction")
    if len(correction) > MAX_CORRECTION_CHARS:
        raise FeedbackError(f"correction is longer than {MAX_CORRECTION_CHARS} characters")
    correction, redactions = redact_correction(correction)
    payload = {
        "session_id": session_id,
        "turn_id": turn_id,
        "rating": rating,
        "correction": correction,
        "pii_redactions": redactions,
    }
    return audit.record(EVENT_TYPE, payload)


def list_feedback(audit: AuditLog) -> list:
    """Return all feedback entries currently in the chain, in order."""
    return [e for e in audit.entries if e["event_type"] == EVENT_TYPE]
