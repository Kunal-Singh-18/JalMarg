from app.places import geocode
from app.weather_zones import ZONES, rain_at
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_empty_geocode_query_is_empty():
    assert geocode("") == []
    assert geocode("x") == []


def test_geocode_api_answers():
    data = client.get("/api/geocode", params={"q": ""}).json()
    assert data["ok"] is True
    assert data["results"] == []


def test_rain_at_picks_nearest_zone():
    zones = [{**z, "rain_mm": 10.0 if z["id"] == "noida" else 1.0} for z in ZONES]
    mm, name = rain_at(28.57, 77.32, zones, 50)
    assert name == "Noida"
    assert mm == 10.0
    mm, name = rain_at(28.57, 77.32, None, 50)
    assert mm == 50
    assert name is None


def test_scenario_without_zones_still_works():
    data = client.get("/api/scenario", params={"rain_mm": 0, "use_zones": False}).json()
    assert data["rain_mode"] == "slider"
    assert data["counts"]["blocked"] == 0
