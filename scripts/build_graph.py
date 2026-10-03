"""One-off: pull Delhi NCR roads from Overpass and cache a routing graph.

    python scripts/build_graph.py [--out data/ncr_roads.json]

Includes major and minor OSM highway classes (named and unnamed). Ways that
cannot be driven — restricted access, non-vehicle paths, incomplete geometry —
are dropped and counted by reason so the app can explain gaps.

The app never runs this. It reads the cached JSON, so a cold start works with
no network — which is the whole point at a demo table with bad wifi.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "data" / "ncr_roads.json"

# Delhi + Gurugram + Faridabad + Noida/Greater Noida + Ghaziabad
BBOX = (28.28, 76.80, 28.98, 77.62)

# Driveable carriageway. Unnamed ways are kept; footways/paths/cycleways are not.
HIGHWAY_CLASSES = (
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "living_street",
    "service",
)
HIGHWAY_RE = "^(" + "|".join(HIGHWAY_CLASSES) + ")(_link)?$"

# Tags that mean a vehicle should not be routed here.
RESTRICTED_ACCESS = frozenset(
    {"no", "private", "military", "permit", "delivery", "customers", "destination"}
)
NON_VEHICLE = frozenset(
    {
        "footway",
        "path",
        "cycleway",
        "steps",
        "pedestrian",
        "bridleway",
        "corridor",
        "platform",
        "construction",
        "proposed",
        "abandoned",
        "disused",
        "raceway",
        "bus_guideway",
    }
)

# osm.ch and other regional mirrors answer 200 with an empty result set for
# Indian bboxes, so only query mirrors known to carry the planet.
ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
UA = "JalMarg-SIH-demo/0.1 (one-off offline graph cache build)"
# More tiles: residential coverage is denser than the old major-road extract.
TILES = 4

# Long edges make flood blocking too blunt: one puddle would delete a whole
# corridor. Short edges bloat the cache. 1.2 km is the compromise.
MAX_MERGED_M = 1200.0
COORD_DP = 5
SIMPLIFY_M = 6.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def path_length_m(points: list[tuple[float, float]]) -> float:
    return sum(
        haversine_m(a[0], a[1], b[0], b[1]) for a, b in zip(points, points[1:])
    )


def tile_boxes(n: int = TILES) -> list[tuple[float, float, float, float]]:
    s, w, north, e = BBOX
    dlat = (north - s) / n
    dlon = (e - w) / n
    # Overlap so a way straddling a tile edge is fetched whole by one of them.
    pad = 0.02
    return [
        (s + i * dlat - pad, w + j * dlon - pad, s + (i + 1) * dlat + pad, w + (j + 1) * dlon + pad)
        for i in range(n)
        for j in range(n)
    ]


def tile_query(box: tuple[float, float, float, float]) -> str:
    s, w, n, e = box
    return (
        "[out:json][timeout:300];"
        f'way["highway"~"{HIGHWAY_RE}"]["area"!="yes"]({s:.4f},{w:.4f},{n:.4f},{e:.4f});'
        "out body;>;out skel qt;"
    )


def fetch_one(query: str, attempts: int = 6) -> dict:
    last = "no attempt"
    for attempt in range(attempts):
        for url in ENDPOINTS:
            try:
                r = httpx.post(
                    url, data={"data": query}, timeout=600, headers={"User-Agent": UA}
                )
                if r.status_code == 200:
                    doc = r.json()
                    if doc.get("elements"):
                        return doc
                    last = f"{url} -> 200 but empty (regional mirror?)"
                else:
                    last = f"{url} -> HTTP {r.status_code}"
            except Exception as exc:
                last = f"{url} -> {type(exc).__name__}: {exc}"
            wait = 15 + 20 * attempt
            print(f"    retry in {wait}s ({last})", file=sys.stderr)
            time.sleep(wait)
    raise SystemExit(f"Overpass unreachable: {last}")


def fetch(tile_dir: Path | None = None) -> dict:
    merged: dict[tuple[str, int], dict] = {}
    boxes = tile_boxes()
    if tile_dir:
        tile_dir.mkdir(parents=True, exist_ok=True)
    for i, box in enumerate(boxes, start=1):
        print(f"  tile {i}/{len(boxes)} {box}", file=sys.stderr)
        cache = tile_dir / f"tile_{i:02d}.json" if tile_dir else None
        if cache and cache.exists():
            doc = json.loads(cache.read_text(encoding="utf-8"))
            print(f"    cached {len(doc.get('elements', []))} elements", file=sys.stderr)
        else:
            doc = fetch_one(tile_query(box))
            if cache:
                cache.write_text(json.dumps(doc), encoding="utf-8")
            print(f"    +{len(doc['elements'])} elements", file=sys.stderr)
        for el in doc["elements"]:
            merged[(el["type"], el["id"])] = el
        print(f"    total {len(merged)}", file=sys.stderr)
    return {"elements": list(merged.values())}


def rdp(points: list[tuple[float, float]], eps_m: float) -> list[tuple[float, float]]:
    if len(points) < 3:
        return points
    a, b = points[0], points[-1]
    # Local flat-earth projection is plenty at NCR scale.
    kx = 111320.0 * math.cos(math.radians(a[0]))
    ky = 110540.0
    ax, ay = a[1] * kx, a[0] * ky
    bx, by = b[1] * kx, b[0] * ky
    dx, dy = bx - ax, by - ay
    span = math.hypot(dx, dy)
    worst_i, worst_d = 0, 0.0
    for i, p in enumerate(points[1:-1], start=1):
        px, py = p[1] * kx, p[0] * ky
        if span == 0:
            d = math.hypot(px - ax, py - ay)
        else:
            d = abs(dy * px - dx * py + bx * ay - by * ax) / span
        if d > worst_d:
            worst_i, worst_d = i, d
    if worst_d <= eps_m:
        return [a, b]
    left = rdp(points[: worst_i + 1], eps_m)
    right = rdp(points[worst_i:], eps_m)
    return left[:-1] + right


def exclusion_reason(tags: dict) -> str | None:
    """Return why this way must not enter the driveable graph, or None to keep it."""
    highway = tags.get("highway", "")
    if highway in NON_VEHICLE:
        return "non_vehicle_path"
    if highway.endswith("_link") and highway.replace("_link", "") not in HIGHWAY_CLASSES:
        return "insufficient_road_information"

    for key in ("access", "vehicle", "motor_vehicle", "motorcar"):
        val = (tags.get(key) or "").lower()
        if val in RESTRICTED_ACCESS:
            return "restricted_access"

    # Service roads that are clearly not through-routes (parking aisles etc.).
    if highway == "service":
        service = (tags.get("service") or "").lower()
        if service in {"parking_aisle", "driveway", "emergency_access", "alley"}:
            return "restricted_access"
        if (tags.get("access") or "").lower() == "private":
            return "restricted_access"

    return None


def split_ways(payload: dict) -> tuple[dict[int, tuple[float, float]], list[dict], Counter]:
    coords: dict[int, tuple[float, float]] = {}
    ways: list[dict] = []
    skipped: Counter = Counter()
    for el in payload["elements"]:
        if el["type"] == "node":
            coords[el["id"]] = (el["lat"], el["lon"])
        elif el["type"] == "way" and el.get("nodes"):
            ways.append(el)
    print(f"  {len(ways)} ways, {len(coords)} raw nodes", file=sys.stderr)

    seen = Counter()
    for w in ways:
        for nid in set(w["nodes"]):
            seen[nid] += 1

    segments = []
    for w in ways:
        tags = w.get("tags", {})
        reason = exclusion_reason(tags)
        if reason:
            skipped[reason] += 1
            continue
        name = tags.get("name") or tags.get("ref") or ""
        klass = tags.get("highway", "")
        if not klass:
            skipped["insufficient_road_information"] += 1
            continue
        nodes = [n for n in w["nodes"] if n in coords]
        if len(nodes) < 2:
            skipped["missing_map_data"] += 1
            continue
        if len(nodes) < len(w["nodes"]):
            # Some nodes of the way were outside the tile response — connectivity
            # through that stretch is not verified, so drop rather than invent.
            skipped["unverified_connectivity"] += 1
            continue
        cut = {nodes[0], nodes[-1]} | {n for n in nodes if seen[n] > 1}
        start = 0
        for i in range(1, len(nodes)):
            if nodes[i] in cut:
                chunk = nodes[start : i + 1]
                if len(chunk) >= 2 and chunk[0] != chunk[-1]:
                    segments.append(
                        {"nodes": chunk, "name": name, "class": klass}
                    )
                start = i
    print(f"  {len(segments)} driveable segments; skipped {dict(skipped)}", file=sys.stderr)
    return coords, segments, skipped


def assemble(coords: dict, segments: list[dict]) -> tuple[dict, dict]:
    edges: dict[tuple[int, int], dict] = {}
    for seg in segments:
        u, v = seg["nodes"][0], seg["nodes"][-1]
        key = (u, v) if u < v else (v, u)
        pts = [coords[n] for n in seg["nodes"]]
        if key[0] != u:
            pts = pts[::-1]
        length = path_length_m(pts)
        prev = edges.get(key)
        if prev is None or length < prev["length"]:
            edges[key] = {
                "geom": pts,
                "length": length,
                "name": seg["name"],
                "class": seg["class"],
            }
    used = {n for key in edges for n in key}
    return {n: coords[n] for n in used}, edges


def merge_degree_two(nodes: dict, edges: dict) -> tuple[dict, dict]:
    adj: dict[int, set[tuple[int, int]]] = defaultdict(set)
    for key in edges:
        adj[key[0]].add(key)
        adj[key[1]].add(key)

    changed = True
    while changed:
        changed = False
        for node in list(adj.keys()):
            keys = [k for k in adj[node] if k in edges]
            adj[node] = set(keys)
            if len(keys) != 2:
                continue
            k1, k2 = keys
            e1, e2 = edges[k1], edges[k2]
            if e1["name"] != e2["name"]:
                continue
            if e1["length"] + e2["length"] > MAX_MERGED_M:
                continue
            other1 = k1[0] if k1[1] == node else k1[1]
            other2 = k2[0] if k2[1] == node else k2[1]
            if other1 == other2 or other1 == node or other2 == node:
                continue
            new_key = (other1, other2) if other1 < other2 else (other2, other1)
            if new_key in edges:
                continue
            g1 = _oriented(e1["geom"], nodes[other1])
            g2 = _oriented(e2["geom"], nodes[node])
            geom = g1 + g2[1:]
            edges[new_key] = {
                "geom": geom,
                "length": e1["length"] + e2["length"],
                "name": e1["name"],
                "class": e1["class"] if e1["length"] >= e2["length"] else e2["class"],
            }
            del edges[k1]
            del edges[k2]
            adj[other1].discard(k1)
            adj[other1].discard(k2)
            adj[other2].discard(k1)
            adj[other2].discard(k2)
            adj[other1].add(new_key)
            adj[other2].add(new_key)
            adj[node] = set()
            changed = True

    used = {n for key in edges for n in key}
    return {n: nodes[n] for n in used}, edges


def _oriented(geom: list, start: tuple[float, float]) -> list:
    da = haversine_m(geom[0][0], geom[0][1], start[0], start[1])
    db = haversine_m(geom[-1][0], geom[-1][1], start[0], start[1])
    return geom if da <= db else geom[::-1]


def largest_component(nodes: dict, edges: dict) -> tuple[dict, dict]:
    adj: dict[int, list[int]] = defaultdict(list)
    for a, b in edges:
        adj[a].append(b)
        adj[b].append(a)
    seen: set[int] = set()
    best: set[int] = set()
    for start in nodes:
        if start in seen:
            continue
        stack, comp = [start], set()
        seen.add(start)
        while stack:
            cur = stack.pop()
            comp.add(cur)
            for nxt in adj[cur]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        if len(comp) > len(best):
            best = comp
    return (
        {n: nodes[n] for n in best},
        {k: v for k, v in edges.items() if k[0] in best and k[1] in best},
    )


def clip(nodes: dict, edges: dict, pad: float = 0.06) -> tuple[dict, dict]:
    s, w, n, e = BBOX

    def inside(pt):
        return s - pad <= pt[0] <= n + pad and w - pad <= pt[1] <= e + pad

    keep = {
        k: v for k, v in edges.items() if inside(nodes[k[0]]) or inside(nodes[k[1]])
    }
    used = {x for k in keep for x in k}
    return {x: nodes[x] for x in used}, keep


def serialise(nodes: dict, edges: dict, skipped: Counter | None = None) -> dict:
    order = sorted(nodes)
    index = {nid: i for i, nid in enumerate(order)}
    names: list[str] = []
    name_index: dict[str, int] = {}
    classes: list[str] = []
    class_index: dict[str, int] = {}

    out_edges = []
    for (a, b), data in sorted(edges.items()):
        nm = data["name"]
        if nm not in name_index:
            name_index[nm] = len(names)
            names.append(nm)
        kl = data["class"]
        if kl not in class_index:
            class_index[kl] = len(classes)
            classes.append(kl)
        geom = rdp(_oriented(data["geom"], nodes[a]), SIMPLIFY_M)
        flat = []
        for lat, lon in geom:
            flat.append(round(lat, COORD_DP))
            flat.append(round(lon, COORD_DP))
        out_edges.append(
            [
                index[a],
                index[b],
                name_index[nm],
                round(data["length"], 1),
                class_index[kl],
                flat,
            ]
        )

    return {
        "source": "OpenStreetMap contributors, via the Overpass API",
        "license": "ODbL 1.0",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bbox": list(BBOX),
        "highway_classes": list(HIGHWAY_CLASSES),
        "note": (
            "Intersection-contracted, undirected. Includes major and minor "
            "driveable roads (named and unnamed). Built by scripts/build_graph.py."
        ),
        "excluded": dict(skipped or {}),
        "exclusion_labels": {
            "restricted_access": "restricted access",
            "missing_map_data": "missing map data",
            "unverified_connectivity": "unverified connectivity",
            "insufficient_road_information": "insufficient road information",
            "non_vehicle_path": "not a vehicle road",
            "disconnected_component": "not connected to the main road network",
        },
        "names": names,
        "classes": classes,
        "nodes": [[nid, round(nodes[nid][0], COORD_DP), round(nodes[nid][1], COORD_DP)] for nid in order],
        "edges": out_edges,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--raw", type=Path, help="reuse a saved Overpass json instead of downloading")
    ap.add_argument("--save-raw", type=Path, help="keep the Overpass response here")
    args = ap.parse_args()

    if args.raw:
        print(f"reading {args.raw}", file=sys.stderr)
        payload = json.loads(args.raw.read_text(encoding="utf-8"))
    else:
        print("downloading from Overpass", file=sys.stderr)
        tile_dir = ROOT / "data" / "overpass_tiles"
        payload = fetch(tile_dir)
        if args.save_raw:
            args.save_raw.write_text(json.dumps(payload), encoding="utf-8")

    if not payload.get("elements"):
        raise SystemExit("Overpass returned no elements; refusing to write an empty graph.")

    coords, segments, skipped = split_ways(payload)
    nodes, edges = assemble(coords, segments)
    print(f"  contracted: {len(nodes)} nodes / {len(edges)} edges", file=sys.stderr)
    nodes, edges = clip(nodes, edges)
    nodes, edges = merge_degree_two(nodes, edges)
    print(f"  merged: {len(nodes)} nodes / {len(edges)} edges", file=sys.stderr)
    before = len(edges)
    nodes, edges = largest_component(nodes, edges)
    dropped = before - len(edges)
    if dropped:
        skipped["disconnected_component"] += dropped
    print(f"  largest component: {len(nodes)} nodes / {len(edges)} edges", file=sys.stderr)

    doc = serialise(nodes, edges, skipped)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    size = args.out.stat().st_size / 1e6
    named = sum(1 for e in doc["edges"] if doc["names"][e[2]])
    print(
        f"wrote {args.out} — {len(doc['nodes'])} nodes, {len(doc['edges'])} edges, "
        f"{named} named ({named / max(len(doc['edges']), 1):.0%}), {size:.1f} MB",
        file=sys.stderr,
    )
    print(f"excluded: {doc['excluded']}", file=sys.stderr)


if __name__ == "__main__":
    main()
