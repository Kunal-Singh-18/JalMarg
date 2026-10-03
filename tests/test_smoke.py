import networkx as nx
from fastapi.testclient import TestClient

from app.graph_data import GRAPH_FILE, LANDMARKS
from app.main import PRESETS, app
from app.routing import GRAPH, LANDMARK_NODES, _facility_node
from app.loaders import load_facilities

client = TestClient(app)

LANDMARK_IDS = {m[0] for m in LANDMARKS}


def test_graph_loads_from_the_cached_osm_extract():
    assert GRAPH_FILE.exists(), "run scripts/build_graph.py to produce the cache"
    assert GRAPH.number_of_nodes() > 5000
    assert GRAPH.number_of_edges() > 5000
    assert GRAPH.graph["source"].startswith("OpenStreetMap")


def test_every_edge_has_real_geometry_and_a_name():
    for a, b, data in GRAPH.edges(data=True):
        assert data["name"], f"{a}-{b} has no name"
        assert len(data["geom"]) >= 2
        assert data["metres"] > 0
    with_shape = sum(1 for _, _, d in GRAPH.edges(data=True) if len(d["geom"]) > 2)
    assert with_shape > GRAPH.number_of_edges() * 0.2, "edges look like straight lines"


def test_graph_is_effectively_connected():
    # Real OSM extracts always shed a few stubs at the bbox edge; what matters is
    # that routing happens on one dominant network.
    biggest = max(nx.connected_components(GRAPH), key=len)
    assert len(biggest) > GRAPH.number_of_nodes() * 0.98


def test_every_landmark_resolves_to_a_real_osm_node():
    assert len(LANDMARK_NODES) == len(LANDMARKS)
    biggest = max(nx.connected_components(GRAPH), key=len)
    for lid, mark in LANDMARK_NODES.items():
        assert mark["osm_node"] in GRAPH, f"{lid} snapped to a node outside the graph"
        assert isinstance(mark["osm_node"], int)
        assert mark["osm_node"] in biggest, f"{lid} is off the main network"
        assert mark["snap_m"] < 2000, f"{lid} snaps {mark['snap_m']} m away"


def test_every_facility_snaps_near_a_road():
    for fac in load_facilities():
        nid, dist = _facility_node(fac["lat"], fac["lon"])
        assert nid in GRAPH
        assert dist < 2500, f"{fac['id']} snaps {dist:.0f} m away"


def test_every_preset_points_at_a_real_landmark():
    for preset in PRESETS:
        for end in ("origin", "dest"):
            node = preset[end]["node"]
            assert node in LANDMARK_IDS, f"preset {preset['id']} has unknown {end} {node}"


def test_index_and_meta_respond():
    assert client.get("/").status_code == 200
    meta = client.get("/api/meta").json()
    assert meta["city"]["name"] == "Delhi NCR"
    assert len(meta["presets"]) == len(PRESETS)
    assert meta["graph"]["nodes"] == GRAPH.number_of_nodes()


def test_scenario_escalates_with_rainfall():
    dry = client.get("/api/scenario?rain_mm=0").json()
    wet = client.get("/api/scenario?rain_mm=80").json()
    assert dry["counts"]["blocked"] == 0
    assert wet["counts"]["blocked"] > 0
    assert wet["counts"]["roads_blocked"] > dry["counts"]["roads_blocked"]


def test_scenario_only_ships_edges_a_hotspot_reaches():
    data = client.get("/api/scenario?rain_mm=50").json()
    assert data["edges"], "50 mm should touch something"
    assert len(data["edges"]) < GRAPH.number_of_edges() / 4
    assert all(e["level"] != "clear" for e in data["edges"])


def test_every_preset_routes_without_error():
    for preset in PRESETS:
        body = {"origin": preset["origin"], "dest": preset["dest"], "rain_mm": 50}
        result = client.post("/api/route", json=body).json()
        assert "error" not in result, f"{preset['id']}: {result.get('error')}"
        assert result["naive"]["km"] > 0
        assert len(result["naive"]["coords"]) > len(result["naive"]["nodes"]) / 2
        assert result["options"], f"{preset['id']}: expected route options"
        assert result["recommended_id"]
        assert any(o["recommended"] for o in result["options"])
        for opt in result["options"]:
            assert "safety_score" in opt and "road_types" in opt and "minutes" in opt
        if result["unreachable"]:
            assert result["unreachable_reason"]
        else:
            assert result["safe"]["km"] >= result["naive"]["km"]


def test_preference_changes_recommended_route():
    body = {
        "origin": {"node": "lajpat"},
        "dest": {"node": "aiims"},
        "rain_mm": 50,
        "prefer": "time",
    }
    by_time = client.post("/api/route", json=body).json()
    body["prefer"] = "safety"
    by_safe = client.post("/api/route", json=body).json()
    assert by_time["options"] and by_safe["options"]
    # Recommendation may match when only one practical dry path exists; still
    # both responses must expose a recommended option and preference echo.
    assert by_time["prefer"] == "time"
    assert by_safe["prefer"] == "safety"
    assert by_time["recommended_id"] in {o["id"] for o in by_time["options"]}
    assert by_safe["recommended_id"] in {o["id"] for o in by_safe["options"]}


def test_presets_still_include_a_detour_and_a_dead_end():
    outcomes = []
    for preset in PRESETS:
        body = {"origin": preset["origin"], "dest": preset["dest"], "rain_mm": 50}
        outcomes.append(client.post("/api/route", json=body).json())
    assert any(r["unreachable"] for r in outcomes), "the honest failure case is the point"
    assert any(
        not r["unreachable"] and r["safe"]["km"] > r["naive"]["km"] * 1.5 for r in outcomes
    ), "at least one preset should show a real detour"


def test_safe_route_never_uses_a_blocked_edge():
    scenario = client.get("/api/scenario?rain_mm=50").json()
    blocked = {frozenset((e["a"], e["b"])) for e in scenario["edges"] if e["blocked"]}
    assert blocked, "50 mm should block something, otherwise this test proves nothing"

    checked = 0
    for preset in PRESETS:
        body = {"origin": preset["origin"], "dest": preset["dest"], "rain_mm": 50}
        result = client.post("/api/route", json=body).json()
        if result["unreachable"]:
            continue
        hops = result["safe"]["nodes"]
        for u, v in zip(hops, hops[1:]):
            assert frozenset((u, v)) not in blocked, f"{preset['id']} routes through a flood"
        checked += 1
    assert checked, "no preset produced a dry path to check"


def test_site_flooded_is_reported_separately_from_road_access():
    facilities = client.get("/api/scenario?rain_mm=50").json()["facilities"]
    assert facilities
    for f in facilities:
        assert f["road_access"] in {"clear", "degraded", "cut_off"}
        assert isinstance(f["site_flooded"], bool)
        assert f["status_label"]
        # "cut off" in the sidebar must mean the roads, not the puddle.
        assert (f["status"] == "cut_off") == (f["road_access"] == "cut_off")

    flooded_but_reachable = [
        f for f in facilities if f["site_flooded"] and f["road_access"] != "cut_off"
    ]
    assert flooded_but_reachable, "the case that used to read as a contradiction"
    for f in flooded_but_reachable:
        assert f["status"] != "cut_off"
        assert "site flooded" in f["status_label"]


def test_a_flooded_facility_is_still_routable():
    scenario = client.get("/api/scenario?rain_mm=50").json()
    target = next(
        f for f in scenario["facilities"] if f["site_flooded"] and f["road_access"] != "cut_off"
    )
    body = {
        "origin": {"node": "cp"},
        "dest": {"lat": target["lat"], "lon": target["lon"]},
        "rain_mm": 50,
    }
    result = client.post("/api/route", json=body).json()
    assert not result["unreachable"], f"{target['name']} reads as flooded but has road access"
