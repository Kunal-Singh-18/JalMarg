from __future__ import annotations

from collections import defaultdict

import networkx as nx

from app.geo import GridIndex, densify, haversine_m, min_dist_to_path_m
from app.graph_data import LANDMARKS, load_osm
from app.risk import _level, clamp, edge_risk
from app.weather_zones import UNCERTAIN_MM, nearest_zone_id

CITY_KMH = 28.0
BLOCK_AT = 0.55

# Edge sample spacing for the flood lookup grid. Also the slack added to a
# hotspot radius when querying it, so an edge that only grazes the circle
# between two samples is still considered.
SAMPLE_M = 200.0

# Placeholder names from graph_data for OSM ways with no name tag; never worth
# reading out as "via".
GENERIC_NAMES = frozenset(
    {
        "Unnamed motorway",
        "Unnamed trunk road",
        "Unnamed primary road",
        "Unnamed secondary road",
        "Unnamed tertiary road",
        "Unnamed local road",
        "Unnamed residential road",
        "Unnamed living street",
        "Unnamed service road",
        "Motorway link",
        "Trunk link",
        "Primary link",
        "Slip road",
        "Tertiary link",
        "Unnamed road",
    }
)


def build_graph() -> nx.Graph:
    doc = load_osm()
    g = nx.Graph(**doc["meta"])
    for nid, lat, lon in doc["nodes"]:
        g.add_node(nid, lat=lat, lon=lon)
    for u, v, name, metres, klass, geom in doc["edges"]:
        g.add_edge(
            u,
            v,
            name=name,
            klass=klass,
            geom=geom,
            metres=metres,
            minutes=metres / 1000 / CITY_KMH * 60,
        )
    return g


GRAPH = build_graph()
EDGE_KEYS: list[tuple[int, int]] = list(GRAPH.edges())
for _nid, _data in GRAPH.nodes(data=True):
    zid = nearest_zone_id(_data["lat"], _data["lon"])
    _data["zone_id"] = zid
    _data["zone_id"] = zid


def _routable(nid: int) -> bool:
    incident = list(GRAPH.edges(nid))
    return len(incident) >= 2 and any(
        not GRAPH.edges[e]["klass"].endswith("_link") for e in incident
    )


def _node_grid() -> GridIndex:
    """Snap targets only. A dead-end ramp stub is never a sensible route
    endpoint — snapping to one sends the router down the expressway and back."""
    grid = GridIndex()
    for nid, d in GRAPH.nodes(data=True):
        if _routable(nid):
            grid.add(d["lat"], d["lon"], (nid, d["lat"], d["lon"]))
    return grid


def _edge_grid() -> GridIndex:
    grid = GridIndex()
    for i, (a, b) in enumerate(EDGE_KEYS):
        for lat, lon in densify(GRAPH.edges[a, b]["geom"], SAMPLE_M):
            grid.add(lat, lon, i)
    return grid


def _landmark_grid() -> GridIndex:
    grid = GridIndex(0.01)
    for _, name, lat, lon in LANDMARKS:
        grid.add(lat, lon, (name, lat, lon))
    return grid


NODE_GRID = _node_grid()
EDGE_GRID = _edge_grid()
LANDMARK_GRID = _landmark_grid()


def _landmark_nodes() -> dict[str, dict]:
    out = {}
    for lid, name, lat, lon in LANDMARKS:
        nid, dist = NODE_GRID.nearest(lat, lon)
        out[lid] = {
            "id": lid,
            "name": name,
            "lat": lat,
            "lon": lon,
            "osm_node": nid,
            "snap_m": round(dist),
        }
    return out


LANDMARK_NODES = _landmark_nodes()


def node_records() -> list[dict]:
    return list(LANDMARK_NODES.values())


def graph_info() -> dict:
    return {
        "nodes": GRAPH.number_of_nodes(),
        "edges": GRAPH.number_of_edges(),
        "km": round(sum(d["metres"] for _, _, d in GRAPH.edges(data=True)) / 1000),
        "landmarks": len(LANDMARK_NODES),
        **GRAPH.graph,
    }


def snap(lat: float, lon: float) -> tuple[int, float]:
    return NODE_GRID.nearest(lat, lon)


def _place_label(lat: float, lon: float) -> str:
    best = min(
        (
            (haversine_m(lat, lon, plat, plon), name)
            for name, plat, plon in LANDMARK_GRID.near(lat, lon, 5000.0)
        ),
        default=None,
    )
    return f"near {best[1]}" if best else "map pick"


def _blocked_pairs(edge_scores: list[dict]) -> set[tuple[int, int]]:
    blocked = {(e["a"], e["b"]) for e in edge_scores if e["blocked"]}
    return blocked | {(b, a) for a, b in blocked}


def _dry_graph(blocked: set[tuple[int, int]]) -> nx.Graph:
    # A view, not a copy: the graph is 15k edges and this runs on every request.
    return nx.restricted_view(GRAPH, [], blocked)


def scored_edges(scored_spots: list[dict]) -> list[dict]:
    """Only edges a hotspot actually reaches. The other 14k are clear by
    construction and would bloat every response."""
    nearby: dict[int, list[dict]] = defaultdict(list)
    for spot in scored_spots:
        if spot["radius_m"] <= 0:
            continue
        for ei in EDGE_GRID.near(spot["lat"], spot["lon"], spot["radius_m"] + SAMPLE_M):
            nearby[ei].append(spot)

    out = []
    for ei, spots in nearby.items():
        a, b = EDGE_KEYS[ei]
        data = GRAPH.edges[a, b]
        risk, near = edge_risk(data["geom"], spots, min_dist_to_path_m)
        level = _level(risk)
        if level == "clear":
            continue
        out.append(
            {
                "a": a,
                "b": b,
                "name": data["name"],
                "coords": [[lat, lon] for lat, lon in data["geom"]],
                "risk": risk,
                "level": level,
                "near_hotspots": near,
                "blocked": risk >= BLOCK_AT,
            }
        )
    return out


def _edge_coords(g: nx.Graph, u: int, v: int) -> list[list[float]]:
    geom = g.edges[u, v]["geom"]
    ulat, ulon = g.nodes[u]["lat"], g.nodes[u]["lon"]
    head = haversine_m(ulat, ulon, geom[0][0], geom[0][1])
    tail = haversine_m(ulat, ulon, geom[-1][0], geom[-1][1])
    ordered = geom if head <= tail else geom[::-1]
    return [[lat, lon] for lat, lon in ordered]


_ROAD_TYPE_BUCKET = {
    "motorway": "highway",
    "motorway_link": "highway",
    "trunk": "highway",
    "trunk_link": "highway",
    "primary": "highway",
    "primary_link": "highway",
    "secondary": "arterial",
    "secondary_link": "arterial",
    "tertiary": "arterial",
    "tertiary_link": "arterial",
    "unclassified": "local",
    "residential": "local",
    "living_street": "local",
    "service": "local",
}


def _risk_index(edge_scores: list[dict]) -> dict[frozenset[int], dict]:
    return {frozenset((e["a"], e["b"])): e for e in edge_scores}


def _path_flood_labels(path: list[int], by_pair: dict[frozenset[int], dict]) -> list[str]:
    names: list[str] = []
    for u, v in zip(path, path[1:]):
        e = by_pair.get(frozenset((u, v)))
        if not e or not e.get("blocked"):
            continue
        label = e["name"]
        if e.get("near_hotspots"):
            label += f" ({', '.join(sorted(set(e['near_hotspots']))[:2])})"
        if label not in names:
            names.append(label)
    return names


def _live_minutes(u: int, v: int, d: dict) -> float:
    from app.traffic import live_minutes

    return live_minutes(u, v, d)


def _path_payload(
    g: nx.Graph,
    path: list[int],
    by_pair: dict[frozenset[int], dict] | None = None,
    flooded_names: list[str] | None = None,
) -> dict:
    by_pair = by_pair or {}
    coords: list[list[float]] = []
    metres = 0.0
    minutes = 0.0
    roads: list[str] = []
    by_road: dict[str, float] = {}
    type_m = {"highway": 0.0, "arterial": 0.0, "local": 0.0, "other": 0.0}
    max_risk = 0.0
    flooded_m = 0.0
    watch_m = 0.0
    risks_along: list[str] = []

    for u, v in zip(path, path[1:]):
        e = g.edges[u, v]
        metres += e["metres"]
        minutes += _live_minutes(u, v, e)
        bucket = _ROAD_TYPE_BUCKET.get(e.get("klass", ""), "other")
        type_m[bucket] = type_m.get(bucket, 0.0) + e["metres"]
        seg = _edge_coords(g, u, v)
        coords.extend(seg if not coords else seg[1:])
        if not roads or roads[-1] != e["name"]:
            roads.append(e["name"])
        by_road[e["name"]] = by_road.get(e["name"], 0.0) + e["metres"]

        scored = by_pair.get(frozenset((u, v)))
        risk = float(scored["risk"]) if scored else 0.0
        max_risk = max(max_risk, risk)
        if scored and scored.get("blocked"):
            flooded_m += e["metres"]
            if scored["name"] not in risks_along:
                risks_along.append(scored["name"])
        elif risk >= 0.28:
            watch_m += e["metres"]

    flooded_names = flooded_names if flooded_names is not None else _path_flood_labels(path, by_pair)
    flood_frac = flooded_m / metres if metres else 0.0
    # 100 = fully dry; blocked metres and peak risk both pull it down.
    safety = clamp(1.0 - 0.55 * max_risk - 0.45 * flood_frac) * 100.0

    real = {r: m for r, m in by_road.items() if r not in GENERIC_NAMES} or by_road
    top = set(sorted(real, key=lambda r: -real[r])[:6])
    via = [r for r in real if r in top]

    type_share = {
        k: round(100.0 * v / metres) if metres else 0
        for k, v in type_m.items()
        if v > 0
    }

    return {
        "nodes": path,
        "coords": coords,
        "km": round(metres / 1000, 2),
        "minutes": round(minutes, 1),
        "roads": roads,
        "via": via,
        "flooded_segments": flooded_names,
        "road_types": type_share,
        "safety_score": round(safety, 1),
        "max_risk": round(max_risk, 3),
        "flooded_km": round(flooded_m / 1000, 2),
        "watch_km": round(watch_m / 1000, 2),
        "uses_flooded_roads": flooded_m > 0,
        "safety_notes": (
            [f"Crosses flooded: {', '.join(flooded_names[:3])}"]
            if flooded_names
            else (
                [f"{round(watch_m / 1000, 2)} km on watch/likely stretches"]
                if watch_m > 0
                else ["No flooded segments on this path"]
            )
        ),
    }


def _stranded(nid: int, blocked: set[tuple[int, int]]) -> bool:
    incident = list(GRAPH.edges(nid))
    return bool(incident) and all((u, v) in blocked for u, v in incident)


def _no_path_reason(
    o_id: int, o_name: str, d_id: int, d_name: str, blocked: set[tuple[int, int]]
) -> str:
    o, d = _stranded(o_id, blocked), _stranded(d_id, blocked)
    if o and d:
        return f"Both {o_name} and {d_name} sit inside flood zones; no dry road leaves either."
    if o:
        return f"Every road out of {o_name} is inside a flood zone."
    if d:
        return f"Every road into {d_name} is inside a flood zone."
    # Flood did not isolate either end — the dry network itself is incomplete.
    excluded = GRAPH.graph.get("excluded") or {}
    labels = GRAPH.graph.get("exclusion_labels") or {}
    if excluded:
        top = sorted(excluded.items(), key=lambda kv: -kv[1])[:2]
        bits = [
            f"{labels.get(code, code.replace('_', ' '))} ({count})"
            for code, count in top
        ]
        return (
            "The two ends sit on separate connected components of the dry road network. "
            "Nearby gaps include: " + "; ".join(bits) + "."
        )
    return (
        "The two ends are left on separate dry road networks — "
        "likely missing map data or unverified connectivity between them."
    )


def _resolve(point: dict) -> tuple[int, float, str]:
    custom_name = point.get("name")
    node = point.get("node")
    if node is not None:
        mark = LANDMARK_NODES.get(node)
        if mark:
            return mark["osm_node"], float(mark["snap_m"]), custom_name or mark["name"]
        if node in GRAPH:
            return node, 0.0, custom_name or _place_label(GRAPH.nodes[node]["lat"], GRAPH.nodes[node]["lon"])
        if isinstance(node, str) and node.isdigit() and int(node) in GRAPH:
            nid = int(node)
            return nid, 0.0, custom_name or _place_label(GRAPH.nodes[nid]["lat"], GRAPH.nodes[nid]["lon"])
        if point.get("lat") is None:
            raise KeyError(f"unknown landmark {node!r}")
    lat, lon = float(point["lat"]), float(point["lon"])
    nid, dist = snap(lat, lon)
    return nid, dist, custom_name or _place_label(lat, lon)


def _rain_multiplier(u: int, v: int, zones_by_id: dict[str, dict] | None) -> float:
    if not zones_by_id:
        return 1.0
    zid = GRAPH.nodes[u].get("zone_id") or GRAPH.nodes[u].get("zone_id")
    z = zones_by_id.get(zid) or {}
    mm = z.get("rain_mm")
    status = z.get("status") or ("ok" if z.get("ok") else "unavailable")
    uncertain = mm is None or status in {"unavailable", "stale"}
    if mm is None:
        mm = UNCERTAIN_MM
    extra = 1.0 + 0.5 * clamp(float(mm) / 80.0)
    if uncertain:
        extra += 0.12
    return extra


def _weather_along(path: list[int], zones: list[dict] | None) -> list[dict]:
    if not zones:
        return []
    by_id = {z["id"]: z for z in zones}
    out: list[dict] = []
    last = None
    for nid in path:
        zid = GRAPH.nodes[nid].get("zone_id") or GRAPH.nodes[nid].get("zone_id")
        if zid == last:
            continue
        last = zid
        z = by_id.get(zid)
        if not z:
            continue
        out.append(
            {
                "id": z["id"],
                "name": z["name"],
                "rain_mm": z.get("rain_mm"),
                "status": z.get("status", "ok"),
                "south": z.get("south"),
                "west": z.get("west"),
                "north": z.get("north"),
                "east": z.get("east"),
                "bounds": z.get("bounds"),
            }
        )
    return out


def route(
    origin: dict,
    dest: dict,
    edge_scores: list[dict],
    prefer: str = "balanced",
    zones: list[dict] | None = None,
) -> dict:
    blocked = _blocked_pairs(edge_scores)
    by_pair = _risk_index(edge_scores)
    zones_by_id = {z["id"]: z for z in zones} if zones else None
    try:
        o_id, o_d, o_name = _resolve(origin)
        d_id, d_d, d_name = _resolve(dest)
    except (KeyError, TypeError, ValueError) as exc:
        return {"error": f"Cannot place that point: {exc}"}

    try:
        naive_path = nx.shortest_path(GRAPH, o_id, d_id, weight="metres")
    except nx.NetworkXNoPath:
        return {
            "error": (
                "No connected path on the available road network between those points. "
                "Likely missing map data or unverified connectivity."
            ),
            "origin_node": o_id,
            "dest_node": d_id,
            "unreachable_reason": "missing map data or unverified connectivity",
        }

    dry = _dry_graph(blocked)

    def w_time(u, v, d):
        return _live_minutes(u, v, d) * _rain_multiplier(u, v, zones_by_id)

    def w_length(u, v, d):
        return d["metres"] * _rain_multiplier(u, v, zones_by_id)

    def w_safety(u, v, d):
        scored = by_pair.get(frozenset((u, v)))
        risk = float(scored["risk"]) if scored else 0.0
        # Soft penalty on watch/likely; blocked edges are already absent from dry.
        return d["metres"] * (1.0 + 6.0 * risk) * _rain_multiplier(u, v, zones_by_id)

    def w_balanced(u, v, d):
        scored = by_pair.get(frozenset((u, v)))
        risk = float(scored["risk"]) if scored else 0.0
        return _live_minutes(u, v, d) * (1.0 + 3.0 * risk) * _rain_multiplier(u, v, zones_by_id)

    candidates: list[tuple[str, str, nx.Graph, object]] = [
        ("fastest", "Shortest travel time", GRAPH, w_time),
        ("shortest_dry", "Shortest dry path", dry, w_length),
        ("safest", "Highest safety", dry, w_safety),
        ("balanced", "Time / safety balance", dry, w_balanced),
    ]

    options: list[dict] = []
    seen_node_sigs: set[tuple[int, ...]] = set()

    def add_option(oid: str, label: str, g: nx.Graph, weight) -> list[int] | None:
        try:
            path = nx.shortest_path(g, o_id, d_id, weight=weight)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None
        sig = tuple(path)
        if sig in seen_node_sigs:
            return path
        seen_node_sigs.add(sig)
        payload = _path_payload(GRAPH, path, by_pair)
        options.append(
            {
                "id": oid,
                "label": label,
                "objective": oid,
                **payload,
                "weather_along": _weather_along(path, zones),
            }
        )
        return path

    path_by_id: dict[str, list[int]] = {}
    for oid, label, g, weight in candidates:
        path = add_option(oid, label, g, weight)
        if path is not None:
            path_by_id[oid] = path

    # One diversion off the balanced/shortest dry path so the list is not just
    # four labels for the same polyline when the network is thin.
    seed = path_by_id.get("balanced") or path_by_id.get("shortest_dry")
    if seed and len(seed) > 2:
        bump = {frozenset((u, v)) for u, v in zip(seed, seed[1:])}

        def w_divert(u, v, d):
            base = w_balanced(u, v, d)
            return base * (8.0 if frozenset((u, v)) in bump else 1.0)

        add_option("alternate", "Alternate dry path", dry, w_divert)

    # Prefer dry options when the user asks for safety/balance.
    prefer = prefer if prefer in {"time", "safety", "balanced"} else "balanced"

    def rank_key(opt: dict) -> tuple:
        dryish = 0 if opt["uses_flooded_roads"] else 1
        if prefer == "time":
            return (opt["minutes"], -opt["safety_score"], opt["km"])
        if prefer == "safety":
            return (-dryish, -opt["safety_score"], opt["minutes"], opt["km"])
        # balanced: prefer dry, then low time/safety tradeoff
        trade = opt["minutes"] / max(opt["safety_score"] / 100.0, 0.05)
        return (-dryish, trade, opt["minutes"])

    if options:
        recommended_id = min(options, key=rank_key)["id"]
    else:
        recommended_id = None

    for opt in options:
        opt["recommended"] = opt["id"] == recommended_id

    naive = _path_payload(GRAPH, naive_path, by_pair)
    safe_opt = next((o for o in options if o["id"] == "shortest_dry"), None)
    if safe_opt is None:
        safe_opt = next((o for o in options if not o["uses_flooded_roads"]), None)

    reason = None
    if safe_opt is None:
        reason = _no_path_reason(o_id, o_name, d_id, d_name, blocked)

    return {
        "origin_node": o_id,
        "dest_node": d_id,
        "origin_name": o_name,
        "dest_name": d_name,
        "snap_m": {"origin": round(o_d), "dest": round(d_d)},
        "prefer": prefer,
        "recommended_id": recommended_id,
        "options": options,
        # Backward-compatible aliases used by older UI / tests.
        "naive": naive,
        "safe": None if safe_opt is None else {k: safe_opt[k] for k in (
            "nodes", "coords", "km", "minutes", "roads", "via", "flooded_segments",
            "road_types", "safety_score", "max_risk", "flooded_km", "watch_km",
            "uses_flooded_roads", "safety_notes",
        )},
        "unreachable": safe_opt is None,
        "unreachable_reason": reason,
        "blocked_edge_count": len({frozenset((e["a"], e["b"])) for e in edge_scores if e["blocked"]}),
    }


ROAD_ACCESS_LABEL = {
    "clear": "road access clear",
    "degraded": "approach roads flooded",
    "cut_off": "unreachable by road",
}

_SNAP_CACHE: dict[tuple[float, float], tuple[int, float]] = {}


def _facility_node(lat: float, lon: float) -> tuple[int, float]:
    key = (lat, lon)
    if key not in _SNAP_CACHE:
        _SNAP_CACHE[key] = snap(lat, lon)
    return _SNAP_CACHE[key]


def _status_label(site_flooded: bool, road_access: str) -> str:
    if road_access == "cut_off":
        return "site flooded and unreachable by road" if site_flooded else "unreachable by road"
    if site_flooded:
        return f"site flooded, {ROAD_ACCESS_LABEL[road_access]}"
    return ROAD_ACCESS_LABEL[road_access] if road_access != "clear" else "open"


def facility_access(
    facilities: list[dict], scored_spots: list[dict], edge_scores: list[dict]
) -> list[dict]:
    """Two separate questions: is the site itself under water, and can a vehicle
    still drive there. They are not the same, and a demo audience reads
    'cut off' as the second one."""
    blocked = _blocked_pairs(edge_scores)
    dry = _dry_graph(blocked)
    components = list(nx.connected_components(dry))
    main = max(components, key=len) if components else set()

    out = []
    for fac in facilities:
        nid, dist = _facility_node(fac["lat"], fac["lon"])
        site_flooded = False
        nearest_spot = None
        nearest_d = float("inf")
        for spot in scored_spots:
            d = haversine_m(fac["lat"], fac["lon"], spot["lat"], spot["lon"])
            if d < nearest_d:
                nearest_d, nearest_spot = d, spot
            if spot["radius_m"] > 0 and d <= spot["radius_m"] * 0.85:
                site_flooded = True

        incident = list(GRAPH.edges(nid))
        flooded_incident = sum(1 for u, v in incident if (u, v) in blocked)
        if nid not in main:
            road_access = "cut_off"
        elif flooded_incident:
            road_access = "degraded"
        else:
            road_access = "clear"

        if road_access == "cut_off":
            status = "cut_off"
        elif site_flooded or road_access == "degraded":
            status = "at_risk"
        else:
            status = "open"

        out.append(
            {
                **fac,
                "status": status,
                "site_flooded": site_flooded,
                "road_access": road_access,
                "status_label": _status_label(site_flooded, road_access),
                "flooded_approaches": flooded_incident,
                "approach_count": len(incident),
                "snap_node": nid,
                "snap_m": round(dist),
                "nearest_hotspot": None
                if not nearest_spot
                else {
                    "name": nearest_spot["name"],
                    "distance_m": round(nearest_d),
                    "risk": nearest_spot["risk"],
                },
            }
        )
    return out
