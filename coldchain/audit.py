"""SHA-256 hash-chained immutable audit log.

Every user query, tool call, SQL statement issued, SOP citation and
escalation decision is appended as a hash-linked entry. verify_chain()
recomputes the whole chain; any tampering with history breaks it.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json


def _entry_hash(seq: int, ts: str, event_type: str, payload: str,
                prev_hash: str) -> str:
    material = f"{seq}|{ts}|{event_type}|{payload}|{prev_hash}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class AuditLog:
    GENESIS_HASH = "0" * 64

    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record(self, event_type: str, payload: dict) -> dict:
        seq = len(self.entries)
        ts = _dt.datetime.now(_dt.timezone.utc).isoformat()
        payload_json = json.dumps(payload, sort_keys=True, default=str)
        prev_hash = (self.entries[-1]["hash"] if self.entries
                     else self.GENESIS_HASH)
        entry = {
            "seq": seq,
            "ts": ts,
            "event_type": event_type,
            "payload": json.loads(payload_json),
            "prev_hash": prev_hash,
            "hash": _entry_hash(seq, ts, event_type, payload_json,
                                prev_hash),
        }
        self.entries.append(entry)
        return entry

    def verify_chain(self) -> bool:
        prev_hash = self.GENESIS_HASH
        for entry in self.entries:
            payload_json = json.dumps(entry["payload"], sort_keys=True,
                                      default=str)
            expected = _entry_hash(entry["seq"], entry["ts"],
                                   entry["event_type"], payload_json,
                                   prev_hash)
            if entry["hash"] != expected or entry["prev_hash"] != prev_hash:
                return False
            prev_hash = entry["hash"]
        return True
