"""Synthetic fleet telemetry store (SQLite).

Models a Southern California refrigerated fleet, Jan 2021 - Aug 2024 style:
trucks, GPS fixes, fuel, ETA variance, traffic, IoT reefer temperature,
cargo condition, weather severity, port congestion, supplier reliability,
lead times, driver fatigue, disruption likelihood, delay probability and
a derived risk classification.

Everything is generated from a seeded RNG so datasets are deterministic.
All data is synthetic and fictional.
"""
from __future__ import annotations

import datetime as _dt
import random
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS trucks (
    truck_id     TEXT PRIMARY KEY,
    depot        TEXT NOT NULL,
    trailer_type TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS telemetry (
    reading_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    truck_id             TEXT NOT NULL,
    ts                   TEXT NOT NULL,
    lat                  REAL NOT NULL,
    lon                  REAL NOT NULL,
    fuel_pct             REAL NOT NULL,
    eta_variance_min     REAL NOT NULL,
    traffic_congestion   TEXT NOT NULL,
    iot_temp_c           REAL NOT NULL,
    cargo_condition      TEXT NOT NULL,
    weather_severity     TEXT NOT NULL,
    port_id              TEXT NOT NULL,
    port_congestion      TEXT NOT NULL,
    supplier_id          TEXT NOT NULL,
    supplier_reliability REAL NOT NULL,
    lead_time_days       REAL NOT NULL,
    driver_fatigue_score REAL NOT NULL,
    disruption_likelihood REAL NOT NULL,
    delay_probability    REAL NOT NULL,
    risk_class           TEXT NOT NULL,
    FOREIGN KEY (truck_id) REFERENCES trucks (truck_id)
);
CREATE TABLE IF NOT EXISTS warehouses (
    warehouse_id   TEXT PRIMARY KEY,
    location       TEXT NOT NULL,
    product        TEXT NOT NULL,
    quantity       INTEGER NOT NULL,
    storage_temp_c REAL NOT NULL
);
"""

# (truck_id, depot) roster for the synthetic fleet.
FLEET = [
    ("TRK-001", "Los Angeles"), ("TRK-002", "Los Angeles"),
    ("TRK-003", "Long Beach"), ("TRK-004", "Long Beach"),
    ("TRK-005", "San Diego"), ("TRK-006", "San Diego"),
    ("TRK-007", "Ontario"), ("TRK-008", "Ontario"),
    ("TRK-009", "Fresno"), ("TRK-010", "Fresno"),
    ("TRK-011", "Bakersfield"), ("TRK-012", "Bakersfield"),
]

DEPOT_COORDS = {
    "Los Angeles": (34.05, -118.24),
    "Long Beach": (33.77, -118.19),
    "San Diego": (32.72, -117.16),
    "Ontario": (34.06, -117.62),
    "Fresno": (36.74, -119.79),
    "Bakersfield": (35.37, -119.02),
}

PORTS = ["POLA", "POLB", "SAN"]
CONGESTION_LEVELS = ["low", "moderate", "high", "severe"]
CARGO_CONDITIONS = ["good", "good", "good", "fair", "at-risk"]
WEATHER_SEVERITY = ["clear", "clear", "clear", "wind", "heat", "storm"]

WAREHOUSES = [
    ("WH-LA", "Los Angeles", "dairy", 4200, 2.0),
    ("WH-LB", "Long Beach", "produce", 9100, 3.1),
    ("WH-SD", "San Diego", "seafood", 2600, 1.2),
]

RISK_CLASSES = ("low", "medium", "high", "critical")

DATASET_START = _dt.datetime(2021, 1, 1)
DATASET_END = _dt.datetime(2024, 8, 31)


def classify_risk(iot_temp_c: float, delay_probability: float) -> str:
    """Derived risk classification shared by generator and views."""
    breach = iot_temp_c > 4.0 or iot_temp_c < 0.0
    if breach and delay_probability >= 0.7:
        return "critical"
    if breach or delay_probability >= 0.7:
        return "high"
    if delay_probability >= 0.4:
        return "medium"
    return "low"


def _insert_reading(conn: sqlite3.Connection, truck_id: str, ts: str,
                    lat: float, lon: float, fuel_pct: float,
                    eta_variance_min: float, traffic_congestion: str,
                    iot_temp_c: float, cargo_condition: str,
                    weather_severity: str, port_id: str, port_congestion: str,
                    supplier_id: str, supplier_reliability: float,
                    lead_time_days: float, driver_fatigue_score: float,
                    disruption_likelihood: float,
                    delay_probability: float) -> None:
    conn.execute(
        """INSERT INTO telemetry
           (truck_id, ts, lat, lon, fuel_pct, eta_variance_min,
            traffic_congestion, iot_temp_c, cargo_condition, weather_severity,
            port_id, port_congestion, supplier_id, supplier_reliability,
            lead_time_days, driver_fatigue_score, disruption_likelihood,
            delay_probability, risk_class)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (truck_id, ts, lat, lon, fuel_pct, eta_variance_min,
         traffic_congestion, iot_temp_c, cargo_condition, weather_severity,
         port_id, port_congestion, supplier_id, supplier_reliability,
         lead_time_days, driver_fatigue_score, disruption_likelihood,
         delay_probability, classify_risk(iot_temp_c, delay_probability)),
    )


def build_dataset(db_path: str, seed: int = 20260801,
                  n_trucks: int = 12, readings_per_truck: int = 48
                  ) -> sqlite3.Connection:
    """Generate the synthetic fleet dataset. Deterministic for a given seed."""
    rng = random.Random(seed)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)

    span_seconds = int((DATASET_END - DATASET_START).total_seconds())
    for truck_id, depot in FLEET[:n_trucks]:
        conn.execute(
            "INSERT INTO trucks (truck_id, depot, trailer_type) VALUES (?,?,?)",
            (truck_id, depot, "reefer-53ft"),
        )
        lat0, lon0 = DEPOT_COORDS[depot]
        for _ in range(readings_per_truck):
            ts = DATASET_START + _dt.timedelta(
                seconds=rng.randint(0, span_seconds))
            temp = round(rng.gauss(2.5, 1.2), 1)
            delay = round(min(0.99, max(0.01, rng.gauss(0.30, 0.20))), 2)
            _insert_reading(
                conn, truck_id, ts.isoformat(),
                round(lat0 + rng.gauss(0, 0.6), 4),
                round(lon0 + rng.gauss(0, 0.6), 4),
                round(rng.uniform(15.0, 100.0), 1),
                round(rng.gauss(12.0, 25.0), 1),
                rng.choice(CONGESTION_LEVELS),
                temp,
                rng.choice(CARGO_CONDITIONS),
                rng.choice(WEATHER_SEVERITY),
                rng.choice(PORTS),
                rng.choice(CONGESTION_LEVELS),
                f"SUP-{rng.randint(100, 999)}",
                round(rng.uniform(0.55, 0.99), 2),
                round(rng.uniform(1.0, 9.0), 1),
                round(min(0.99, max(0.01, rng.gauss(0.35, 0.2))), 2),
                round(min(0.99, max(0.01, rng.gauss(0.25, 0.2))), 2),
                delay,
            )

    for wid, loc, product, qty, temp in WAREHOUSES:
        conn.execute(
            "INSERT INTO warehouses VALUES (?,?,?,?,?)",
            (wid, loc, product, qty, temp),
        )

    _inject_edge_cases(conn)
    conn.commit()
    return conn


def _inject_edge_cases(conn: sqlite3.Connection) -> None:
    """Deterministic anchor rows so demos and tests have known incidents."""
    # Critical: reefer breach + very likely delay.
    _insert_reading(conn, "TRK-001", "2024-08-15T12:00:00",
                    34.05, -118.24, 62.0, 95.0, "high",
                    7.2, "at-risk", "heat", "POLA", "severe",
                    "SUP-101", 0.61, 6.5, 0.55, 0.80, 0.85)
    # Low fuel.
    _insert_reading(conn, "TRK-003", "2024-08-15T12:05:00",
                    33.77, -118.19, 12.0, 20.0, "moderate",
                    2.8, "good", "clear", "POLB", "moderate",
                    "SUP-102", 0.88, 3.0, 0.30, 0.25, 0.30)
    # Driver fatigue flag.
    _insert_reading(conn, "TRK-005", "2024-08-15T12:10:00",
                    32.72, -117.16, 55.0, 40.0, "moderate",
                    3.1, "fair", "wind", "SAN", "low",
                    "SUP-103", 0.90, 2.5, 0.91, 0.45, 0.52)
    # Severe port congestion with high delay probability.
    _insert_reading(conn, "TRK-007", "2024-08-15T12:15:00",
                    34.06, -117.62, 71.0, 130.0, "severe",
                    1.9, "good", "clear", "POLA", "severe",
                    "SUP-104", 0.58, 8.0, 0.40, 0.70, 0.78)
