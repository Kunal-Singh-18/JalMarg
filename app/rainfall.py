from __future__ import annotations

from datetime import datetime, timezone

import httpx

DELHI = (28.6139, 77.2090)
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"



def fetch_rainfall() -> dict:
    params = {
        "latitude": DELHI[0],
        "longitude": DELHI[1],
        "current": "precipitation,rain",
        "hourly": "precipitation",
        "past_hours": 3,
        "forecast_days": 1,
        "timezone": "Asia/Kolkata",
    }
    try:
        with httpx.Client(timeout=8.0) as client:
            r = client.get(OPEN_METEO, params=params)
            r.raise_for_status()
            data = r.json()
    except Exception as exc:  # noqa: BLE001 — demo must still load offline
        return {
            "ok": False,
            "error": str(exc),
            "current_mm": 0.0,
            "past3h_mm": 0.0,
            "suggested_slider_mm": 25.0,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": "Open-Meteo (unavailable)",
        }

    current = float((data.get("current") or {}).get("precipitation") or 0)
    hourly = data.get("hourly") or {}
    precip = [float(x or 0) for x in (hourly.get("precipitation") or [])]
    past3 = sum(precip[:3]) if precip else current
    suggested = max(past3 * 3, current * 6, 8.0)
    return {
        "ok": True,
        "current_mm": round(current, 2),
        "past3h_mm": round(past3, 2),
        "suggested_slider_mm": round(min(suggested, 120), 1),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "Open-Meteo",
        "timezone": data.get("timezone"),
    }
