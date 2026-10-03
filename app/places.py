"""Nominatim geocode proxy. Keeps the browser off OSM's public endpoint
and pins results to the Delhi NCR viewbox."""

from __future__ import annotations

import httpx

NOMINATIM = "https://nominatim.openstreetmap.org"
UA = {"User-Agent": "JalMarg-SIH-demo/1.0 (sih-internal)"}
# left, bottom, right, top
NCR_VIEWBOX = "76.84,28.22,77.58,28.88"


def geocode(query: str, limit: int = 6) -> list[dict]:
    q = (query or "").strip()
    if len(q) < 2:
        return []
    params = {
        "q": q,
        "format": "jsonv2",
        "limit": min(max(limit, 1), 8),
        "viewbox": NCR_VIEWBOX,
        "bounded": 0,
        "countrycodes": "in",
        "addressdetails": 1,
    }
    try:
        with httpx.Client(timeout=8.0, headers=UA) as client:
            r = client.get(f"{NOMINATIM}/search", params=params)
            r.raise_for_status()
            rows = r.json()
    except Exception:
        return []
    out = []
    for row in rows:
        try:
            out.append(
                {
                    "name": row.get("display_name", "").split(",")[0].strip() or q,
                    "label": row.get("display_name", q),
                    "lat": float(row["lat"]),
                    "lon": float(row["lon"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


def reverse_geocode(lat: float, lon: float) -> str | None:
    params = {"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 16}
    try:
        with httpx.Client(timeout=8.0, headers=UA) as client:
            r = client.get(f"{NOMINATIM}/reverse", params=params)
            r.raise_for_status()
            place = r.json()
    except Exception:
        return None
    address = place.get("address") or {}
    for key in (
        "road",
        "neighbourhood",
        "suburb",
        "town",
        "village",
        "city_district",
        "city",
    ):
        if address.get(key):
            return str(address[key])
    name = place.get("display_name")
    return name.split(",")[0].strip() if name else None
