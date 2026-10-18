"""Gateway bypasses found in review (2026-10-18); each used to succeed.

Before the SQLite-authorizer backstop the gateway only inspected names that
followed FROM/JOIN plus whitespace, and it trusted any caller-written LIMIT.
"""
import sqlite3

import pytest

from coldchain.telemetry import build_dataset
from coldchain.views import VIEW_DEFS, SecureGateway, SecurityDenial, create_views


@pytest.fixture
def gw(tmp_path):
    path = str(tmp_path / "fleet.db")
    build_dataset(path, seed=99, n_trucks=30, readings_per_truck=10)
    conn = sqlite3.connect(path)
    create_views(conn)
    yield SecureGateway(conn)
    conn.close()


@pytest.mark.parametrize("sql", [
    "SELECT * FROM v_fleet_status, trucks",                 # comma join
    'SELECT name, sql FROM "sqlite_master"',                # quoted schema table
    "SELECT * FROM/**/trucks",                              # comment as whitespace
    "SELECT * FROM v_temp_breaches JOIN/**/telemetry",
])
def test_base_table_and_schema_reads_are_denied(gw, sql):
    with pytest.raises(SecurityDenial) as err:
        gw.execute(sql)
    assert err.value.rule_id == "SEC-VIEW-03"


@pytest.mark.parametrize("limit", ["LIMIT 100000", "LIMIT 100000 OFFSET 0", "LIMIT 0, 100000"])
def test_caller_limit_cannot_exceed_the_cap(gw, limit):
    sql = f"SELECT a.truck_id FROM v_fleet_status a JOIN v_fleet_status b {limit}"
    assert len(gw.execute(sql)) == SecureGateway.MAX_LIMIT


def test_subquery_limit_cannot_exceed_the_cap(gw):
    sql = ("SELECT * FROM (SELECT a.truck_id FROM v_fleet_status a "
           "JOIN v_fleet_status b LIMIT 100000)")
    assert len(gw.execute(sql)) == SecureGateway.MAX_LIMIT


def test_every_view_still_readable(gw):
    for view in VIEW_DEFS:
        gw.execute(f"SELECT * FROM {view}")


def test_authorizer_is_removed_after_the_query(gw):
    gw.execute("SELECT * FROM v_fleet_status")
    assert gw.conn.execute("SELECT count(*) FROM trucks").fetchone()[0] > 0
