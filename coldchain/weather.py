"""Weather client with an injectable backend.

FakeWeather is deterministic (for tests and offline demos). The
OpenMeteoBackend calls the Open-Meteo forecast API over stdlib urllib for
live runs. On ANY failure the backend returns an explicit data-gap result —
the agent reports the gap and never hallucinates weather.
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from dataclasses import dataclass


@dataclass
class WeatherResult:
    temp_c: float | None
    wind_kmh: float | None
    corridor_risk: str  # low | elevated | severe | unknown
    source: str
    gap: bool
    note: str


def derive_corridor_risk(temp_c: float, wind_kmh: float) -> str:
    """Heat/wind stress on a refrigerated corridor."""
    if temp_c >= 38.0 or wind_kmh >= 75.0:
        return "severe"
    if temp_c >= 32.0 or wind_kmh >= 50.0:
        return "elevated"
    return "low"


class FakeWeather:
    """Deterministic weather for tests: hash(lat, lon) -> conditions."""

    def __init__(self, seed: int = 7) -> None:
        self.seed = seed

    def get(self, lat: float, lon: float) -> WeatherResult:
        digest = hashlib.sha256(
            f"{self.seed}:{round(lat, 2)}:{round(lon, 2)}".encode()
        ).hexdigest()
        temp_c = 18.0 + (int(digest[:4], 16) % 230) / 10.0   # 18.0 - 40.9
        wind_kmh = 5.0 + (int(digest[4:8], 16) % 650) / 10.0  # 5.0 - 69.9
        temp_c = round(temp_c, 1)
        wind_kmh = round(wind_kmh, 1)
        return WeatherResult(
            temp_c=temp_c,
            wind_kmh=wind_kmh,
            corridor_risk=derive_corridor_risk(temp_c, wind_kmh),
            source="fake",
            gap=False,
            note=(f"Deterministic synthetic weather for "
                  f"({lat}, {lon}); not a real observation."),
        )


class OpenMeteoBackend:
    """Live backend: Open-Meteo current temperature + wind (no API key)."""

    URL = "https://api.open-meteo.com/v1/forecast"

    def __init__(self, timeout: int = 10) -> None:
        self.timeout = timeout

    def get(self, lat: float, lon: float) -> WeatherResult:
        query = (f"{self.URL}?latitude={lat}&longitude={lon}"
                 f"&current=temperature_2m,wind_speed_10m")
        try:
            with urllib.request.urlopen(query,
                                        timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            current = payload.get("current", {})
            temp_c = float(current["temperature_2m"])
            wind_kmh = float(current["wind_speed_10m"])
        except Exception as exc:  # network, timeout, schema drift, ...
            return WeatherResult(
                temp_c=None,
                wind_kmh=None,
                corridor_risk="unknown",
                source="open-meteo",
                gap=True,
                note=(f"Weather data unavailable ({type(exc).__name__}: "
                      f"{exc}). The corridor risk cannot be assessed from "
                      f"weather — no values were guessed."),
            )
        return WeatherResult(
            temp_c=temp_c,
            wind_kmh=wind_kmh,
            corridor_risk=derive_corridor_risk(temp_c, wind_kmh),
            source="open-meteo",
            gap=False,
            note=f"Live observation for ({lat}, {lon}).",
        )
