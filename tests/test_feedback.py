"""Feedback capture wired into the hash-chained audit log. Stdlib only."""

import pytest

from coldchain.audit import AuditLog
from coldchain.feedback import (
    EVENT_TYPE,
    FeedbackError,
    capture_feedback,
    list_feedback,
)


def make_log():
    log = AuditLog()
    log.record("user_query", {"q": "show temperature breaches"})
    return log


def test_thumbs_up_without_correction_appends():
    log = make_log()
    entry = capture_feedback(log, session_id="s1", turn_id="t1", rating="up")
    assert entry["event_type"] == EVENT_TYPE
    assert entry["payload"]["session_id"] == "s1"
    assert entry["payload"]["turn_id"] == "t1"
    assert entry["payload"]["rating"] == "up"
    assert log.verify_chain()


def test_thumbs_down_with_correction_appends():
    log = make_log()
    entry = capture_feedback(
        log, session_id="s2", turn_id="t7", rating="down",
        correction="  wrong truck, TRK-009 not TRK-001  ")
    assert entry["payload"]["rating"] == "down"
    assert entry["payload"]["correction"] == "wrong truck, TRK-009 not TRK-001"
    assert log.verify_chain()


def test_thumbs_down_without_correction_rejected():
    log = make_log()
    with pytest.raises(FeedbackError):
        capture_feedback(log, session_id="s1", turn_id="t1", rating="down")


def test_whitespace_correction_rejected():
    log = make_log()
    with pytest.raises(FeedbackError):
        capture_feedback(
            log, session_id="s1", turn_id="t1", rating="down",
            correction="   ")


def test_out_of_range_rating_rejected():
    log = make_log()
    with pytest.raises(FeedbackError):
        capture_feedback(
            log, session_id="s1", turn_id="t1", rating="maybe",
            correction="x")


def test_blank_session_or_turn_rejected():
    log = make_log()
    with pytest.raises(FeedbackError):
        capture_feedback(log, session_id="  ", turn_id="t1", rating="up")
    with pytest.raises(FeedbackError):
        capture_feedback(log, session_id="s1", turn_id="", rating="up")
    assert log.verify_chain()


def test_interleaved_feedback_chain_verifies_and_lists_only_feedback():
    log = make_log()
    capture_feedback(log, session_id="s1", turn_id="t1", rating="up")
    log.record("tool_call", {"tool": "text2sql"})
    capture_feedback(log, session_id="s1", turn_id="t2", rating="down",
                     correction="missed the port delay")
    assert log.verify_chain()
    fb = list_feedback(log)
    assert len(fb) == 2
    assert [e["payload"]["turn_id"] for e in fb] == ["t1", "t2"]


def test_tampered_feedback_breaks_chain():
    log = make_log()
    capture_feedback(log, session_id="s1", turn_id="t1", rating="up")
    assert log.verify_chain()
    log.entries[-1]["payload"]["rating"] = "down"
    assert not log.verify_chain()
