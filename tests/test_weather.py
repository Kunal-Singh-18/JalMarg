from app.weather_zones import (
    UNCERTAIN_MM,
    ZONES,
    fetch_zones,
    rain_at,
    rain_reading,
    reset_cache,
)
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_slider_reading_is_not_a_live_zone():
    reading = rain_reading(28.61, 77.21, None, 50)
    assert reading["status"] == "slider"
    assert reading["rain_mm"] == 50
    assert reading["uncertain"] is False


def test_missing_live_rain_is_not_zero_and_not_the_slider():
    zones = [{**z, "rain_mm": None, "status": "unavailable", "ok": False} for z in ZONES]
    reading = rain_reading(28.61, 77.21, zones, 80)
    assert reading["uncertain"] is True
    assert reading["status"] == "unavailable"
    assert reading["rain_mm"] != 0
    assert reading["rain_mm"] != 80
    assert reading["rain_mm"] == UNCERTAIN_MM


def test_rain_at_slider_tuple_unchanged():
    mm, name = rain_at(28.61, 77.21, None, 50)
    assert mm == 50
    assert name is None


def test_failed_fetch_does_not_invent_zero_mm(monkeypatch):
    reset_cache()

    def boom():
        raise RuntimeError("network down")

    monkeypatch.setattr("app.weather_zones._download_blocks", boom)
    pack = fetch_zones()
    assert pack["ok"] is False
    assert pack["stale"] is False
    assert all(z["rain_mm"] is None for z in pack["zones"])
    assert all(z["status"] == "unavailable" for z in pack["zones"])


def test_stale_cache_used_when_fetch_fails(monkeypatch):
    reset_cache()
    good = {
        "ok": True,
        "stale": False,
        "source": "Open-Meteo",
        "zones": [{**z, "ok": True, "status": "ok", "rain_mm": 12.0} for z in ZONES],
    }
    monkeypatch.setattr("app.weather_zones._CACHE", {"pack": good})

    def boom():
        raise RuntimeError("network down")

    monkeypatch.setattr("app.weather_zones._download_blocks", boom)
    pack = fetch_zones()
    assert pack["stale"] is True
    assert pack["zones"][0]["rain_mm"] == 12.0
    assert pack["zones"][0]["status"] == "stale"


def test_scenario_slider_still_dry_at_zero():
    data = client.get("/api/scenario", params={"rain_mm": 0, "use_zones": False}).json()
    assert data["rain_mode"] == "slider"
    assert data["use_zones"] is False
    assert data["counts"]["blocked"] == 0


def test_graph_nodes_carry_a_weather_zone():
    from app.routing import GRAPH

    sample = list(GRAPH.nodes(data=True))[::8000]
    assert sample
    assert all("zone_id" in d for _, d in sample)
    ids = {d["zone_id"] for _, d in sample}
    assert len(ids) >= 3


def test_route_weather_along_with_synthetic_zones():
    from app.routing import route
    from app.weather_zones import ZONES as CELLS

    zones = [
        {
            **z,
            "ok": True,
            "status": "ok",
            "rain_mm": 70.0 if z["id"] in {"south", "east", "noida"} else 6.0,
        }
        for z in CELLS
    ]
    result = route(
        {"node": "nizamuddin"},
        {"node": "holy_family"},
        [],
        prefer="balanced",
        zones=zones,
    )
    assert result.get("options")
    along = result["options"][0].get("weather_along") or []
    assert along
    assert all("rain_mm" in z for z in along)
