from app.weather_zones import ZONES, rain_at
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_ncr_is_tiled_into_square_cells():
    assert len(ZONES) == 225
    names = {z["name"] for z in ZONES}
    assert {"Central Delhi", "Noida", "Gurugram", "Faridabad"} <= names
    for z in ZONES:
        assert z["north"] - z["south"] > 0
        assert z["east"] - z["west"] > 0
        ns = (z["north"] - z["south"]) * 110900
        ew = (z["east"] - z["west"]) * 97600
        assert abs(ns - ew) / ns < 0.02


def test_rain_at_uses_slider_when_zones_off():
    mm, name = rain_at(28.61, 77.21, None, 50)
    assert mm == 50
    assert name is None


def test_named_places_sit_inside_their_squares():
    from app.weather_zones import nearest_zone

    g = nearest_zone(28.459, 77.027)
    assert g["id"] == "gurugram"
    assert g["south"] <= 28.459 < g["north"]
    assert g["west"] <= 77.027 < g["east"]
    n = nearest_zone(28.574, 77.325)
    assert n["id"] == "noida"


def test_rain_at_picks_gurugram_not_noida():
    zones = [{**z, "rain_mm": 80.0 if z["id"] == "gurugram" else 5.0} for z in ZONES]
    mm, name = rain_at(28.459, 77.027, zones, 50)
    assert name == "Gurugram"
    assert mm == 80.0


def test_zones_endpoint_shape():
    data = client.get("/api/rainfall/zones").json()
    assert "ok" in data
    assert "zones" in data
    assert len(data["zones"]) == 225
    assert {"id", "name", "lat", "lon", "rain_mm", "bounds"} <= data["zones"][0].keys()


def test_scenario_zones_flag_does_not_break_counts():
    data = client.get("/api/scenario", params={"rain_mm": 50, "use_zones": False}).json()
    assert data["rain_mode"] == "slider"
    assert data["use_zones"] is False
    assert "blocked" in data["counts"]
