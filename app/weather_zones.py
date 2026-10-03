"""NCR weather cells for localized rainfall.

Simulation mode (the 0–120 mm slider) still owns a single test value when
zones are off. Live mode never copies that slider into a cell, and a missing
observation is never stored as 0 mm.
"""

from __future__ import annotations

from datetime import datetime, timezone
from time import sleep

import httpx

from app.geo import M_PER_DEG_LAT, M_PER_DEG_LON, haversine_m
from app.rainfall import OPEN_METEO

# Conservative stand-in when live rain is missing/stale. Not dry, not the slider.
UNCERTAIN_MM = 40.0

# Equal-metre squares covering Delhi NCR. 4 km cells keep rain local to
# the roads a path actually uses, without going below the weather model's scale.
SIDE_M = 4000.0
ROWS = 15
COLS = 15
LAT0 = 28.36
LON0 = 76.88
DLAT = SIDE_M / M_PER_DEG_LAT
DLON = SIDE_M / M_PER_DEG_LON

_PLACE_LABELS = [
    ("gurugram", "Gurugram", 28.459, 77.027),
    ("faridabad", "Faridabad", 28.408, 77.318),
    ("south", "South Delhi", 28.535, 77.215),
    ("noida", "Noida", 28.574, 77.325),
    ("west", "West Delhi", 28.651, 77.102),
    ("central", "Central Delhi", 28.632, 77.220),
    ("east", "East Delhi", 28.638, 77.305),
    ("north", "North Delhi", 28.715, 77.185),
    ("ghaziabad", "Ghaziabad", 28.670, 77.420),
]


def _build_zones() -> list[dict]:
    cells: list[dict] = []
    for r in range(ROWS):
        for c in range(COLS):
            south = LAT0 + r * DLAT
            west = LON0 + c * DLON
            north = south + DLAT
            east = west + DLON
            lat = (south + north) / 2
            lon = (west + east) / 2
            nearest = min(
                _PLACE_LABELS,
                key=lambda p: (lat - p[2]) ** 2 + (lon - p[3]) ** 2,
            )
            cells.append(
                {
                    "id": f"r{r}c{c}",
                    "name": nearest[1],
                    "row": r,
                    "col": c,
                    "lat": round(lat, 5),
                    "lon": round(lon, 5),
                    "south": round(south, 5),
                    "west": round(west, 5),
                    "north": round(north, 5),
                    "east": round(east, 5),
                    "bounds": [[round(south, 5), round(west, 5)], [round(north, 5), round(east, 5)]],
                }
            )
    used: set[str] = set()
    for pid, name, plat, plon in _PLACE_LABELS:
        for cell in cells:
            if cell["south"] <= plat < cell["north"] and cell["west"] <= plon < cell["east"]:
                if pid not in used:
                    cell["id"] = pid
                    cell["name"] = name
                    used.add(pid)
                break
    return cells


ZONES = _build_zones()
_ID_BY_RC = {(z["row"], z["col"]): z["id"] for z in ZONES}

_CACHE: dict = {"pack": None}


def reset_cache() -> None:
    _CACHE["pack"] = None


def nearest_zone_id(lat: float, lon: float) -> str:
    r = int((lat - LAT0) / DLAT)
    c = int((lon - LON0) / DLON)
    r = max(0, min(ROWS - 1, r))
    c = max(0, min(COLS - 1, c))
    return _ID_BY_RC[(r, c)]


def nearest_zone(lat: float, lon: float, zones: list[dict] | None = None) -> dict:
    cells = zones if zones else ZONES
    zid = nearest_zone_id(lat, lon)
    hit = next((z for z in cells if z["id"] == zid), None)
    if hit:
        return hit
    return min(cells, key=lambda z: haversine_m(lat, lon, z["lat"], z["lon"]))


def fingerprint(zones: list[dict] | None) -> str:
    if not zones:
        return ""
    return "|".join(f"{z['id']}:{z.get('status')}:{z.get('rain_mm')}" for z in zones)


def _parse_block(data: dict) -> tuple[float, float, float]:
    current = float((data.get("current") or {}).get("precipitation") or 0)
    hourly = data.get("hourly") or {}
    precip = [float(x or 0) for x in (hourly.get("precipitation") or [])]
    past3 = sum(precip[:3]) if precip else current
    suggested = max(past3 * 3, current * 6, 0.0)
    return current, past3, min(suggested, 120.0)


def _sample_points() -> list[tuple[float, float]]:
    """One sample per named place. Open-Meteo rejects a 225-point URL with 429."""
    return [(lat, lon) for _pid, _name, lat, lon in _PLACE_LABELS]


def _download_samples() -> list[dict]:
    out: list[dict] = []
    with httpx.Client(timeout=15.0) as client:
        for lat, lon in _sample_points():
            params = {
                "latitude": lat,
                "longitude": lon,
                "current": "precipitation,rain",
                "hourly": "precipitation",
                "past_hours": 3,
                "forecast_days": 1,
                "timezone": "Asia/Kolkata",
            }
            r = client.get(OPEN_METEO, params=params)
            if r.status_code == 429:
                raise RuntimeError("Open-Meteo hourly limit exceeded")
            r.raise_for_status()
            payload = r.json()
            current, past3, suggested = _parse_block(payload)
            out.append(
                {
                    "lat": lat,
                    "lon": lon,
                    "current": current,
                    "past3": past3,
                    "suggested": suggested,
                }
            )
    if not out:
        raise RuntimeError("Open-Meteo rate-limited")
    return out


def fetch_zones() -> dict:
    try:
        samples = _download_samples()
        if not samples:
            raise RuntimeError("no weather samples")
        zones = []
        for zone in ZONES:
            nearest = min(
                samples,
                key=lambda s: haversine_m(zone["lat"], zone["lon"], s["lat"], s["lon"]),
            )
            current = nearest["current"]
            past3 = nearest["past3"]
            suggested = nearest["suggested"]
            zones.append(
                {
                    **zone,
                    "ok": True,
                    "status": "ok",
                    "current_mm": round(current, 2),
                    "past3h_mm": round(past3, 2),
                    "rain_mm": round(suggested, 1),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        pack = {
            "ok": True,
            "stale": False,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": "Open-Meteo",
            "zones": zones,
        }
        _CACHE["pack"] = pack
        return pack
    except Exception:
        cached = _CACHE.get("pack")
        if cached and cached.get("zones"):
            zones = [{**z, "ok": False, "status": "stale"} for z in cached["zones"]]
            return {
                "ok": False,
                "stale": True,
                "fetched_at": cached.get("fetched_at"),
                "source": "Open-Meteo (stale cache)",
                "zones": zones,
            }
        return {
            "ok": False,
            "stale": False,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": "Open-Meteo (unavailable)",
            "zones": [
                {
                    **z,
                    "ok": False,
                    "status": "unavailable",
                    "current_mm": None,
                    "past3h_mm": None,
                    "rain_mm": None,
                    "updated_at": None,
                }
                for z in ZONES
            ],
        }


def rain_at(lat: float, lon: float, zones: list[dict] | None, default_mm: float) -> tuple[float, str | None]:
    """Slider helper. Live callers should use rain_reading() so missing ≠ 0."""
    if not zones:
        return default_mm, None
    nearest = nearest_zone(lat, lon, zones)
    mm = nearest.get("rain_mm")
    if mm is None:
        return UNCERTAIN_MM, nearest.get("name")
    return float(mm), nearest.get("name")


def rain_reading(lat: float, lon: float, zones: list[dict] | None, default_mm: float) -> dict:
    if not zones:
        return {
            "rain_mm": default_mm,
            "zone_id": None,
            "zone_name": None,
            "status": "slider",
            "uncertain": False,
        }
    nearest = nearest_zone(lat, lon, zones)
    status = nearest.get("status") or ("ok" if nearest.get("ok") else "unavailable")
    mm = nearest.get("rain_mm")
    if mm is None or status == "unavailable":
        return {
            "rain_mm": UNCERTAIN_MM,
            "zone_id": nearest.get("id"),
            "zone_name": nearest.get("name"),
            "status": "unavailable",
            "uncertain": True,
        }
    return {
        "rain_mm": float(mm),
        "zone_id": nearest.get("id"),
        "zone_name": nearest.get("name"),
        "status": status,
        "uncertain": status == "stale",
    }
