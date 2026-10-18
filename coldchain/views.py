"""Least-privilege data access layer.

The agent never touches base tables. It may only issue SELECT statements
against an allowlisted set of clean read-only views. Every denial cites a
stable rule ID so the audit log explains *why* access was refused.

Rule IDs:
  SEC-SELECT-01  Only single SELECT statements are permitted.
  SEC-WRITE-02   Write/DDL keywords are denied at the gateway.
  SEC-VIEW-03    Only allowlisted read-only views may be queried
                 (backed by a SQLite authorizer, see coldchain/authz.py).

At most MAX_LIMIT rows are ever fetched, whatever LIMIT the caller wrote.
"""
from __future__ import annotations

import re
import sqlite3

from . import authz

VIEW_DEFS = {
    "v_fleet_status": (
        "SELECT t.truck_id, tr.depot, t.ts, t.lat, t.lon, t.fuel_pct,"
        " t.eta_variance_min, t.traffic_congestion, t.iot_temp_c,"
        " t.cargo_condition, t.weather_severity, t.port_id, t.port_congestion,"
        " t.supplier_reliability, t.lead_time_days, t.driver_fatigue_score,"
        " t.disruption_likelihood, t.delay_probability, t.risk_class"
        " FROM telemetry t JOIN trucks tr ON tr.truck_id = t.truck_id"
    ),
    "v_temp_breaches": (
        "SELECT truck_id, ts, iot_temp_c, cargo_condition, risk_class,"
        " delay_probability FROM telemetry"
        " WHERE iot_temp_c > 4.0 OR iot_temp_c < 0.0"
    ),
    "v_delay_risk": (
        "SELECT truck_id, ts, delay_probability, risk_class, port_congestion,"
        " eta_variance_min, driver_fatigue_score FROM telemetry"
        " WHERE delay_probability >= 0.4"
    ),
    "v_port_impact": (
        "SELECT truck_id, ts, port_id, port_congestion, delay_probability,"
        " risk_class FROM telemetry"
        " WHERE port_congestion IN ('high', 'severe')"
    ),
}

VIEW_COLUMNS = {
    "v_fleet_status": [
        "truck_id", "depot", "ts", "lat", "lon", "fuel_pct",
        "eta_variance_min", "traffic_congestion", "iot_temp_c",
        "cargo_condition", "weather_severity", "port_id", "port_congestion",
        "supplier_reliability", "lead_time_days", "driver_fatigue_score",
        "disruption_likelihood", "delay_probability", "risk_class",
    ],
    "v_temp_breaches": [
        "truck_id", "ts", "iot_temp_c", "cargo_condition", "risk_class",
        "delay_probability",
    ],
    "v_delay_risk": [
        "truck_id", "ts", "delay_probability", "risk_class", "port_congestion",
        "eta_variance_min", "driver_fatigue_score",
    ],
    "v_port_impact": [
        "truck_id", "ts", "port_id", "port_congestion", "delay_probability",
        "risk_class",
    ],
}

_WRITE_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|"
    r"ATTACH|DETACH|VACUUM|GRANT|REVOKE)\b", re.IGNORECASE)
_FROM_RE = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)",
                      re.IGNORECASE)
_SELECT_RE = re.compile(r"^\s*SELECT\b", re.IGNORECASE | re.DOTALL)
_LIMIT_RE = re.compile(r"\bLIMIT\b", re.IGNORECASE)
_COMMENT_RE = re.compile(r"--[^\n]*|/\*.*?(?:\*/|$)", re.S)
_LITERAL_RE = re.compile(r"'(?:[^']|'')*'")


class SecurityDenial(Exception):
    """Raised when a query violates the least-privilege policy."""

    def __init__(self, rule_id: str, reason: str) -> None:
        super().__init__(f"[{rule_id}] {reason}")
        self.rule_id = rule_id
        self.reason = reason


def create_views(conn: sqlite3.Connection) -> None:
    """Materialize the read-only views inside the client database."""
    for name, select in VIEW_DEFS.items():
        conn.execute(f"CREATE VIEW IF NOT EXISTS {name} AS {select}")
    conn.commit()


class SecureGateway:
    """Single choke point for every SQL statement the agent issues."""

    MAX_LIMIT = 100

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def execute(self, sql: str, params: tuple = ()) -> list[dict]:
        scrubbed = _COMMENT_RE.sub(" ", sql).strip()
        if not _SELECT_RE.match(scrubbed):
            raise SecurityDenial(
                "SEC-SELECT-01",
                "Only single SELECT statements are permitted; "
                "got a non-SELECT or empty statement.")
        if ";" in scrubbed:
            raise SecurityDenial(
                "SEC-SELECT-01",
                "Multiple statements are not permitted; one SELECT only.")
        if _WRITE_RE.search(_LITERAL_RE.sub("", scrubbed)):
            raise SecurityDenial(
                "SEC-WRITE-02",
                "Write/DDL keywords are denied at the gateway; "
                "the agent role is read-only.")
        for table in _FROM_RE.findall(scrubbed):
            if table not in VIEW_DEFS:
                raise SecurityDenial(
                    "SEC-VIEW-03",
                    f"Access to '{table}' denied: only allowlisted "
                    f"read-only views may be queried "
                    f"({', '.join(sorted(VIEW_DEFS))}).")
        statement = scrubbed
        if not _LIMIT_RE.search(statement):
            statement = f"{statement} LIMIT {self.MAX_LIMIT}"
        # Engine-level backstop: the regex above cannot see comma joins or
        # double-quoted names, so SQLite itself refuses any non-view read.
        with authz.views_only(self.conn, VIEW_DEFS) as denied:
            try:
                cursor = self.conn.execute(statement, params)
            except sqlite3.DatabaseError:
                if denied:
                    raise SecurityDenial(
                        "SEC-VIEW-03",
                        f"Access to '{denied[0]}' denied: only allowlisted "
                        f"read-only views may be queried "
                        f"({', '.join(sorted(VIEW_DEFS))}).") from None
                raise
            columns = [d[0] for d in cursor.description]
            # A caller-written LIMIT can be larger than the cap; rows past
            # MAX_LIMIT are never fetched.
            rows = cursor.fetchmany(self.MAX_LIMIT)
        return [dict(zip(columns, row)) for row in rows]
