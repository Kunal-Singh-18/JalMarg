from __future__ import annotations


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def hotspot_risk(
    spot: dict,
    rain_mm: float,
    news_ids: set[str],
    zone_name: str | None = None,
    uncertain: bool = False,
) -> dict:
    rain_factor = clamp(rain_mm / 80.0)
    severity_factor = spot["severity"] / 5.0
    underpass = 1.28 if spot["is_underpass"] else 1.0
    elev = 1.0 + max(0.0, -spot["relative_elevation_m"]) / 16.0
    news_boost = 0.12 if spot["id"] in news_ids else 0.0
    score = clamp(rain_factor * severity_factor * underpass * elev + news_boost)

    # Underpasses activate earlier; mild rain should still light them up.
    if spot["is_underpass"] and rain_mm >= 12:
        score = max(score, 0.55)
    if rain_mm < 4:
        score = 0.0 if not spot["is_underpass"] else min(score, 0.15)

    reasons = []
    if spot["is_underpass"]:
        reasons.append("Underpass (floods first)")
    reasons.append(f"Historical severity {spot['severity']}/5")
    if spot["relative_elevation_m"] < 0:
        reasons.append(f"Low relative elevation ({spot['relative_elevation_m']:.0f} m)")
    if uncertain:
        score = max(score, 0.28)
        if zone_name:
            reasons.append(f"Uncertain rain in {zone_name} — not treated as dry")
        else:
            reasons.append("Live rain missing or stale — not treated as dry")
    elif zone_name:
        reasons.append(f"{rain_mm:.0f} mm rain in {zone_name}")
    else:
        reasons.append(f"{rain_mm:.0f} mm rain scenario")
    if spot["id"] in news_ids:
        reasons.append("Named in recent monsoon coverage")

    radius_m = 0.0 if score < 0.28 else 80 + score * 500
    return {
        **spot,
        "risk": round(score, 3),
        "radius_m": round(radius_m, 1),
        "level": _level(score),
        "reasons": reasons,
        "news_mentioned": spot["id"] in news_ids,
        "zone_name": zone_name,
        "local_rain_mm": round(rain_mm, 1),
        "rain_uncertain": uncertain,
    }


def _level(score: float) -> str:
    if score >= 0.75:
        return "blocked"
    if score >= 0.55:
        return "likely"
    if score >= 0.28:
        return "watch"
    return "clear"


def edge_risk(
    geom: list,
    scored_spots: list[dict],
    dist_fn,
) -> tuple[float, list[str]]:
    """`scored_spots` is expected to be pre-filtered to spots near this edge;
    the caller owns the spatial lookup, this owns the model."""
    best = 0.0
    names: list[str] = []
    for spot in scored_spots:
        if spot["radius_m"] <= 0:
            continue
        d = dist_fn(spot["lat"], spot["lon"], geom)
        decay = max(0.0, 1.0 - d / spot["radius_m"])
        r = spot["risk"] * decay
        if r > 0.2:
            names.append(spot["name"])
        best = max(best, r)
    return round(best, 3), names
