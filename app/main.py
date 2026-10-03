from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.loaders import STATIC, load_facilities, load_hotspots, load_news
from app.news import match_news
from app.places import geocode, reverse_geocode
from app.rainfall import fetch_rainfall
from app.risk import hotspot_risk
from app.routing import facility_access, graph_info, route, scored_edges, node_records
from app.weather_zones import fetch_zones, fingerprint, rain_reading

app = FastAPI(title="JalMarg", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

HOTSPOTS = load_hotspots()
FACILITIES = load_facilities()
NEWS = load_news()
NEWS_IDS, NEWS_ANNOTATED = match_news(NEWS, HOTSPOTS)

PRESETS = [
    {
        "id": "nizamuddin_holy_family",
        "label": "Ambulance: Nizamuddin → Holy Family (Okhla)",
        "origin": {"node": "nizamuddin"},
        "dest": {"node": "holy_family"},
        "story": "50 mm rain. Ashram Chowk and Sarai Kale Khan take out the Ring Road together, and the Modi Mill underpass is gone too. The 4.4 km run becomes 12.5 km back up Bhairon Marg and down through Lajpat Nagar.",
    },
    {
        "id": "lajpat_aiims",
        "label": "Ambulance: Lajpat Nagar → AIIMS",
        "origin": {"node": "lajpat"},
        "dest": {"node": "aiims"},
        "story": "The AIIMS Ring Road underpass shuts and takes the AIIMS flyover approach with it. 4.3 km becomes 7.1 km over the Barapullah and in through Aurobindo Marg.",
    },
    {
        "id": "mg_road_fortis",
        "label": "Ambulance: MG Road → Fortis Gurugram",
        "origin": {"node": "mg_road"},
        "dest": {"node": "fortis_ggm"},
        "story": "Gurugram's MG Road service lanes flood before anything else. With Mehrauli-Gurgaon Road cut, 3.4 km becomes a 7.0 km loop out to Golf Course Road and back down.",
    },
    {
        "id": "rajpur_lnjp",
        "label": "Ambulance: Rajpur Road → LNJP (cut off)",
        "origin": {"node": "rajpur"},
        "dest": {"node": "lnjp"},
        "story": "The Civil Lines underpass is the only sane way south from Rajpur Road. At 50 mm every road out of that junction is inside a flood zone, so the desk says so instead of guessing.",
    },
    {
        "id": "raja_garden_rml",
        "label": "Ambulance: Raja Garden → RML (cut off)",
        "origin": {"node": "raja_garden"},
        "dest": {"node": "rml"},
        "story": "Raja Garden sits where the Ring Road meets Najafgarh Road, and both arms plus the flyover go under. No dry path remains — the honest answer for a west Delhi crew.",
    },
    {
        "id": "noida_apollo",
        "label": "Ambulance: Noida Sector 18 → Apollo",
        "origin": {"node": "noida_18"},
        "dest": {"node": "apollo"},
        "story": "Sector 18 and the Mahamaya underpass are both flagged at 50 mm, but Noida's grid has enough parallel roads that the 7.6 km run is unchanged. Push the slider to 80 mm and Sector 18 becomes an island.",
    },
]


class Point(BaseModel):
    lat: float | None = None
    lon: float | None = None
    node: str | None = None
    name: str | None = None


class RouteRequest(BaseModel):
    origin: Point
    dest: Point
    rain_mm: float = Field(50, ge=0, le=200)
    prefer: str = Field("balanced", pattern="^(time|safety|balanced)$")
    use_zones: bool = False


def _scenario(rain_mm: float, use_zones: bool = False) -> dict:
    zone_pack = fetch_zones() if use_zones else None
    zones = (zone_pack or {}).get("zones") if use_zones else None
    scored = []
    for s in HOTSPOTS:
        if use_zones:
            reading = rain_reading(s["lat"], s["lon"], zones, rain_mm)
            scored.append(
                hotspot_risk(
                    s,
                    reading["rain_mm"],
                    NEWS_IDS,
                    zone_name=reading["zone_name"],
                    uncertain=reading["uncertain"],
                )
            )
        else:
            scored.append(hotspot_risk(s, rain_mm, NEWS_IDS))
    edges = scored_edges(scored)
    facilities = facility_access(FACILITIES, scored, edges)
    counts = {
        "watch": sum(1 for s in scored if s["level"] == "watch"),
        "likely": sum(1 for s in scored if s["level"] == "likely"),
        "blocked": sum(1 for s in scored if s["level"] == "blocked"),
        "facilities_cut_off": sum(1 for f in facilities if f["road_access"] == "cut_off"),
        "facilities_at_risk": sum(1 for f in facilities if f["status"] == "at_risk"),
        "facilities_site_flooded": sum(1 for f in facilities if f["site_flooded"]),
        "roads_blocked": sum(1 for e in edges if e["blocked"]),
    }
    return {
        "city": "Delhi NCR",
        "rain_mm": rain_mm,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": (
            "Known spots compiled from public MCD/NDMC and NCR civic lists plus news archives, for a demo. "
            "Risk is a scoring model (rain × severity × underpass/elevation × news), "
            "not a hydrology engine. Roads are the OpenStreetMap driveable network. A human decides."
        ),
        "counts": counts,
        "hotspots": scored,
        "edges": edges,
        "facilities": facilities,
        "news": NEWS_ANNOTATED,
        "use_zones": bool(use_zones),
        "zones": zones or [],
        "rain_mode": "zones" if use_zones else "slider",
        "zones_ok": None if not zone_pack else zone_pack.get("ok"),
        "zones_stale": bool(zone_pack.get("stale")) if zone_pack else False,
        "zones_source": None if not zone_pack else zone_pack.get("source"),
        "zones_fetched_at": None if not zone_pack else zone_pack.get("fetched_at"),
        "zones_fingerprint": fingerprint(zones) if zones else None,
    }


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/meta")
def meta():
    return {
        "name": "JalMarg",
        "tagline": "Urban waterlogging and emergency accessibility",
        "city": {"name": "Delhi NCR", "lat": 28.57, "lon": 77.22, "zoom": 11},
        "presets": PRESETS,
        "nodes": node_records(),
        "graph": graph_info(),
        "news_place_ids": sorted(NEWS_IDS),
    }


@app.get("/api/rainfall")
def rainfall():
    return fetch_rainfall()


@app.get("/api/scenario")
def scenario(
    rain_mm: float = Query(50, ge=0, le=200),
    use_zones: bool = Query(False),
):
    return _scenario(rain_mm, use_zones=use_zones)


@app.post("/api/route")
def route_api(body: RouteRequest):
    scored = _scenario(body.rain_mm, use_zones=body.use_zones)
    result = route(
        body.origin.model_dump(),
        body.dest.model_dump(),
        scored["edges"],
        prefer=body.prefer,
        zones=scored["zones"] if body.use_zones else None,
    )
    result["rain_mm"] = body.rain_mm
    result["use_zones"] = body.use_zones
    result["rain_mode"] = scored["rain_mode"]
    result["zones_fingerprint"] = scored.get("zones_fingerprint")
    return result


@app.get("/api/geocode")
def geocode_api(q: str = Query("", min_length=0), limit: int = Query(6, ge=1, le=8)):
    return {"ok": True, "results": geocode(q, limit)}


@app.get("/api/reverse")
def reverse_api(lat: float = Query(...), lon: float = Query(...)):
    return {"ok": True, "name": reverse_geocode(lat, lon)}


@app.get("/api/rainfall/zones")
def rainfall_zones():
    return fetch_zones()


class TrafficFix(BaseModel):
    lat: float
    lon: float
    speed_kmh: float | None = None


class TrafficPing(BaseModel):
    lat: float | None = None
    lon: float | None = None
    speed_kmh: float | None = None
    fixes: list[TrafficFix] | None = None


class TrafficMode(BaseModel):
    mode: str = Field(pattern="^(live|simulation)$")


class SimStart(BaseModel):
    scenario: str = "moderate"


@app.post("/api/traffic/ping")
def traffic_ping(body: TrafficPing):
    from app.traffic import ingest_fix, ingest_fixes

    if body.fixes:
        return ingest_fixes([f.model_dump() for f in body.fixes])
    if body.lat is None or body.lon is None:
        return {"kept": 0, "dropped": 1}
    result = ingest_fix(body.lat, body.lon, body.speed_kmh)
    return {"kept": int(result["kept"]), "dropped": int(not result["kept"])}


@app.get("/api/traffic")
def traffic_get():
    from app.traffic import snapshot

    return snapshot()


@app.post("/api/traffic/simulate")
def traffic_simulate(n: int = Query(280, ge=1, le=2000)):
    from app.traffic import simulate

    return simulate(n)


@app.get("/api/traffic/mode")
def traffic_mode_get():
    from app.traffic import get_mode

    return {"mode": get_mode()}


@app.post("/api/traffic/mode")
def traffic_mode_set(body: TrafficMode):
    from app.traffic import set_mode
    from app.traffic_sim import stop as sim_stop

    if body.mode == "live":
        sim_stop()
    return {"mode": set_mode(body.mode)}


@app.post("/api/traffic/sim/start")
def traffic_sim_start(scenario: str = Query("moderate")):
    from app.traffic_sim import SCENARIOS, start

    if scenario not in SCENARIOS:
        return {"error": f"unknown scenario {scenario}", "scenarios": list(SCENARIOS)}
    return start(scenario)


@app.post("/api/traffic/sim/stop")
def traffic_sim_stop():
    from app.traffic_sim import stop

    return stop()


@app.get("/api/traffic/sim/status")
def traffic_sim_status():
    from app.traffic_sim import status

    return status()


@app.get("/api/traffic/sim/vehicles")
def traffic_sim_vehicles():
    from app.traffic import get_mode, sim_vehicle_snapshot

    return {"mode": get_mode(), "vehicles": sim_vehicle_snapshot()}
