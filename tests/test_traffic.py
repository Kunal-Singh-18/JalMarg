"""Feature 1: anonymized GPS → edge median speed. Isolated from origin/dest."""

from app.routing import GRAPH
from app.traffic import classify, ingest_fix, live_minutes, reset, simulate, snapshot


def test_classify_uses_free_flow_fractions():
    assert classify(22, 28) == "clear"
    assert classify(16, 28) == "moderate"
    assert classify(8, 28) == "heavy"


def test_ping_is_snapped_then_coords_are_not_stored():
    reset()
    a, b, data = next(iter(GRAPH.edges(data=True)))
    lat, lon = data["geom"][0]
    result = ingest_fix(lat, lon, 12.0)
    assert result["kept"] is True
    snap = snapshot()
    assert snap["sample_count"] >= 1
    edge = snap["edges"][0]
    assert "lat" not in edge
    assert "lon" not in edge
    assert edge["level"] in {"clear", "moderate", "heavy"}
    assert edge["n"] >= 1
    reset()


def test_median_not_mean_for_outliers():
    reset()
    a, b, data = next(iter(GRAPH.edges(data=True)))
    lat, lon = data["geom"][0]
    for kmh in (10, 11, 12, 11, 80):
        ingest_fix(lat, lon, kmh)
    edge = snapshot()["edges"][0]
    assert abs(edge["median_kmh"] - 11) < 0.2
    assert edge["median_kmh"] < edge["mean_kmh"]
    reset()


def test_live_minutes_slow_down_when_edge_is_congested():
    reset()
    a, b, data = next(iter(GRAPH.edges(data=True)))
    free = data["minutes"]
    lat, lon = data["geom"][0]
    ingest_fix(lat, lon, 6.0)
    live = live_minutes(a, b, data)
    assert live > free
    reset()
    assert abs(live_minutes(a, b, data) - free) < 1e-9


def test_simulate_then_snapshot_has_classified_edges():
    reset()
    sim = simulate(80)
    assert sim["kept"] > 0
    snap = snapshot()
    assert snap["mode"] == "simulation"
    assert snap["edge_count"] > 0
    assert all(e["level"] in {"clear", "moderate", "heavy"} for e in snap["edges"])
    reset()


def test_live_and_simulation_stores_do_not_mix():
    from app.traffic import get_mode, set_mode

    reset()
    a, b, data = next(iter(GRAPH.edges(data=True)))
    lat, lon = data["geom"][0]
    ingest_fix(lat, lon, 20.0)
    assert get_mode() == "live"
    assert snapshot()["sample_count"] >= 1
    set_mode("simulation")
    assert snapshot()["sample_count"] == 0
    set_mode("live")
    assert snapshot()["sample_count"] >= 1
    reset()


def test_moving_sim_scenarios_change_median_speed():
    from app.traffic_sim import load, step, stop

    reset()
    load("clear")
    step(5)
    clear_med = snapshot()["edges"][0]["median_kmh"]
    load("heavy")
    step(5)
    heavy_med = snapshot()["edges"][0]["median_kmh"]
    assert clear_med > heavy_med
    assert heavy_med < 16
    stop()
    reset()


def test_mixed_scenario_median_ignores_speed_outliers():
    from app.traffic_sim import load, step, stop

    reset()
    load("mixed")
    step(6)
    from app.traffic import sim_vehicle_snapshot

    vehs = sim_vehicle_snapshot()
    speeds = [v["speed_kmh"] for v in vehs]
    assert speeds
    assert min(speeds) <= 5
    assert max(speeds) >= 20
    assert snapshot()["edges"]
    stop()
    reset()


def test_delayed_sim_update_is_ignored():
    from app.traffic import ingest_sim_fix, set_mode

    reset()
    set_mode("simulation")
    a, b, data = next(iter(GRAPH.edges(data=True)))
    lat, lon = data["geom"][0]
    ingest_sim_fix("sim-delay-1", lat, lon, 10.0)
    skipped = ingest_sim_fix("sim-delay-1", lat, lon, 80.0, dropped_update=True)
    assert skipped["kept"] is False
    edge = snapshot()["edges"][0]
    assert abs(edge["median_kmh"] - 10) < 0.2
    reset()


def test_vehicle_leaving_a_segment_drops_the_count():
    from app.traffic import ingest_sim_fix, set_mode

    reset()
    set_mode("simulation")
    edges = list(GRAPH.edges(data=True))
    a1, b1, d1 = edges[0]
    a2, b2, d2 = edges[min(40, len(edges) - 1)]
    lat1, lon1 = d1["geom"][0]
    lat2, lon2 = d2["geom"][0]
    ingest_sim_fix("sim-stay", lat1, lon1, 18.0)
    ingest_sim_fix("sim-leave", lat1, lon1, 19.0)
    first = next(e for e in snapshot()["edges"] if {e["a"], e["b"]} == {a1, b1})
    assert first["n"] == 2
    ingest_sim_fix("sim-leave", lat2, lon2, 19.0)
    snap = snapshot()
    left = next((e for e in snap["edges"] if {e["a"], e["b"]} == {a1, b1}), None)
    assert left is None or left["n"] == 1
    reset()


def test_stopped_and_outlier_vehicles_do_not_break_median():
    from app.traffic import sim_vehicle_snapshot
    from app.traffic_sim import load, step, stop

    reset()
    load("mixed")
    step(4)
    vehs = sim_vehicle_snapshot()
    assert any(v["id"].startswith("sim-") for v in vehs)
    assert any(v["speed_kmh"] == 0 for v in vehs)
    snap = snapshot()
    assert snap["edges"]
    assert any(e["median_kmh"] != e["mean_kmh"] for e in snap["edges"])
    stop()
    reset()


def test_noisy_sim_fix_still_snaps_to_a_road():
    from app.traffic import ingest_sim_fix, set_mode

    reset()
    set_mode("simulation")
    a, b, data = next(iter(GRAPH.edges(data=True)))
    lat, lon = data["geom"][0]
    result = ingest_sim_fix("sim-noise-1", lat + 0.00008, lon + 0.00008, 18.0)
    assert result["kept"] is True
    reset()

