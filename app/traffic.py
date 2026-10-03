"""Crowd-sourced traffic on the road graph.

Two stores, never mixed:

- **live** — anonymized real GPS. Fixes are snapped to an edge, coords dropped.
- **simulation** — labelled test vehicles (sim-001, …). Dev/test only.

Routing and GET /api/traffic read whichever mode is active. Fake pings cannot
leak into the live store.
"""

from __future__ import annotations

import statistics
import threading
import time
from collections import defaultdict

from app.geo import min_dist_to_path_m

TTL_S = 180.0
MAX_SAMPLES_PER_EDGE = 48
SNAP_M = 75.0
MIN_SPEED_KMH = 0.5
MAX_SPEED_KMH = 90.0

CLEAR_FRAC = 0.70
HEAVY_FRAC = 0.40

LIVE = "live"
SIM = "simulation"

_lock = threading.Lock()
_mode = LIVE

# live: edge -> [(ts, speed)]  (no vehicle id)
_live: dict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)

# sim: edge -> {vid: (ts, speed)}
_sim: dict[tuple[int, int], dict[str, tuple[float, float]]] = defaultdict(dict)
_sim_last_edge: dict[str, tuple[int, int]] = {}
# visualization only (never used for live GPS)
_sim_vehicles: dict[str, dict] = {}


def _key(u: int, v: int) -> tuple[int, int]:
    return (u, v) if u < v else (v, u)


def get_mode() -> str:
    return _mode


def set_mode(mode: str) -> str:
    global _mode
    if mode not in (LIVE, SIM):
        raise ValueError("mode must be 'live' or 'simulation'")
    with _lock:
        _mode = mode
    return _mode


def _graph():
    from app.routing import CITY_KMH, EDGE_GRID, EDGE_KEYS, GRAPH

    return GRAPH, EDGE_GRID, EDGE_KEYS, CITY_KMH


def match_edge(lat: float, lon: float) -> tuple[int, int] | None:
    GRAPH, EDGE_GRID, EDGE_KEYS, _ = _graph()
    idxs = EDGE_GRID.near(lat, lon, SNAP_M)
    best_i = None
    best_d = SNAP_M
    for ei in idxs:
        a, b = EDGE_KEYS[ei]
        geom = GRAPH.edges[a, b]["geom"]
        d = min_dist_to_path_m(lat, lon, geom)
        if d < best_d:
            best_d = d
            best_i = ei
    if best_i is None:
        return None
    a, b = EDGE_KEYS[best_i]
    return _key(a, b)


def _expire_live(now: float) -> None:
    cutoff = now - TTL_S
    dead = []
    for key, rows in _live.items():
        kept = [r for r in rows if r[0] >= cutoff]
        if kept:
            _live[key] = kept[-MAX_SAMPLES_PER_EDGE:]
        else:
            dead.append(key)
    for key in dead:
        del _live[key]


def _expire_sim(now: float) -> None:
    cutoff = now - TTL_S
    gone_vids = []
    for key, bucket in list(_sim.items()):
        for vid, (ts, _spd) in list(bucket.items()):
            if ts < cutoff:
                bucket.pop(vid, None)
                gone_vids.append(vid)
        if not bucket:
            del _sim[key]
    for vid in gone_vids:
        _sim_last_edge.pop(vid, None)
        _sim_vehicles.pop(vid, None)


def ingest_fix(lat: float, lon: float, speed_kmh: float | None, now: float | None = None) -> dict:
    """Production path: anonymous GPS into the live store. Coords are not kept."""
    ts = now or time.time()
    if speed_kmh is None or not (MIN_SPEED_KMH <= float(speed_kmh) <= MAX_SPEED_KMH):
        return {"kept": False, "kept": False, "reason": "speed missing or implausible"}
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return {"kept": False, "kept": False, "reason": "bad coordinates"}
    edge = match_edge(float(lat), float(lon))
    if edge is None:
        return {"kept": False, "kept": False, "reason": "off network"}
    with _lock:
        _expire_live(ts)
        bucket = _live[edge]
        bucket.append((ts, float(speed_kmh)))
        if len(bucket) > MAX_SAMPLES_PER_EDGE:
            del bucket[: len(bucket) - MAX_SAMPLES_PER_EDGE]
        n = len(bucket)
    return {"kept": True, "kept": True, "source": LIVE, "vehicles": n}


def ingest_fixes(fixes: list[dict]) -> dict:
    kept = dropped = 0
    for fix in fixes:
        try:
            lat = float(fix["lat"])
            lon = float(fix["lon"])
            speed = fix.get("speed_kmh")
            speed = float(speed) if speed is not None else None
        except (KeyError, TypeError, ValueError):
            dropped += 1
            continue
        if ingest_fix(lat, lon, speed)["kept"]:
            kept += 1
        else:
            dropped += 1
    return {"kept": kept, "dropped": dropped, "source": LIVE}


def ingest_sim_fix(
    vid: str,
    lat: float,
    lon: float,
    speed_kmh: float,
    heading: float | None = None,
    now: float | None = None,
    dropped_update: bool = False,
) -> dict:
    """Test-only: keep this vehicle on at most one simulated edge."""
    ts = now or time.time()
    if dropped_update:
        return {"kept": False, "kept": False, "reason": "delayed_or_missing_update", "source": SIM}

    if not vid.startswith("sim-"):
        return {"kept": False, "kept": False, "reason": "sim vehicle ids must start with sim-"}
    if speed_kmh is None or speed_kmh < 0 or float(speed_kmh) > MAX_SPEED_KMH:
        return {"kept": False, "kept": False, "reason": "speed missing or implausible"}

    edge = match_edge(float(lat), float(lon))
    GRAPH, _, _, _ = _graph()
    name = ""
    if edge is not None:
        name = GRAPH.edges[edge]["name"]

    with _lock:
        prev = _sim_last_edge.get(vid)
        if prev is not None and prev in _sim:
            _sim[prev].pop(vid, None)
            if not _sim[prev]:
                del _sim[prev]
        if edge is None:
            _sim_last_edge.pop(vid, None)
            _sim_vehicles[vid] = {
                "id": vid,
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "speed_kmh": round(float(speed_kmh), 1),
                "heading": heading,
                "edge": None,
                "name": None,
                "snapped": False,
            }
            return {"kept": False, "kept": False, "reason": "off network", "source": SIM}

        _sim[edge][vid] = (ts, float(speed_kmh))
        _sim_last_edge[vid] = edge
        _sim_vehicles[vid] = {
            "id": vid,
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "speed_kmh": round(float(speed_kmh), 1),
            "heading": None if heading is None else round(heading, 1),
            "edge": {"a": edge[0], "b": edge[1]},
            "name": name,
            "snapped": True,
        }
        n = len(_sim[edge])
    return {"kept": True, "kept": True, "source": SIM, "vehicles": n}


def classify(median_kmh: float, free_kmh: float) -> str:
    if median_kmh >= free_kmh * CLEAR_FRAC:
        return "clear"
    if median_kmh >= free_kmh * HEAVY_FRAC:
        return "moderate"
    return "heavy"


def _speeds_active() -> dict[tuple[int, int], list[float]]:
    now = time.time()
    if _mode == SIM:
        _expire_sim(now)
        return {k: [spd for _ts, spd in bucket.values()] for k, bucket in _sim.items() if bucket}
    _expire_live(now)
    return {k: [spd for _ts, spd in rows] for k, rows in _live.items() if rows}


def live_minutes(u: int, v: int, d: dict) -> float:
    from app.routing import CITY_KMH

    key = _key(u, v)
    with _lock:
        speeds = _speeds_active().get(key) or []
    if not speeds:
        return d["minutes"]
    median = statistics.median(speeds)
    kmh = max(0.5, min(median if median > 0 else 0.5, CITY_KMH * 1.5))
    return d["metres"] / 1000.0 / kmh * 60.0


def snapshot(max_edges: int = 400) -> dict:
    GRAPH, _, _, CITY_KMH = _graph()
    now = time.time()
    with _lock:
        mode = _mode
        speeds_map = _speeds_active()
        vehicle_count = len(_sim_vehicles) if mode == SIM else None
        items = []
        for (a, b), speeds in speeds_map.items():
            if not speeds:
                continue
            median = statistics.median(speeds)
            geom = GRAPH.edges[a, b]["geom"]
            n = len(speeds)
            mean = round(statistics.fmean(speeds), 1)
            coords = [[lat, lon] for lat, lon in geom]
            items.append(
                {
                    "a": a,
                    "b": b,
                    "name": GRAPH.edges[a, b]["name"],
                    "n": n,
                    "median_kmh": round(median, 1),
                    "mean_kmh": mean,
                    "level": classify(median, CITY_KMH),
                    "coords": coords,
                    "n": n,
                    "median_kmh": round(median, 1),
                    "mean_kmh": mean,
                    "coords": coords,
                }
            )

    items.sort(key=lambda e: (-e["n"], e["median_kmh"]))
    items = items[:max_edges]
    n_samples = sum(e["n"] for e in items)
    return {
        "mode": mode,
        "source": mode,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "ttl_s": TTL_S,
        "free_flow_kmh": CITY_KMH,
        "edge_count": len(items),
        "sample_count": n_samples,
        "sample_count": n_samples,
        "vehicle_count": vehicle_count,
        "sample_count": n_samples,
        "edges": items,
        "dev_only": mode == SIM,
        "store": mode,
        "privacy": (
            "simulation: labelled test vehicles, not real users — never mixed with live GPS"
            if mode == SIM
            else "live fixes are snapped to an edge then discarded; only median speed is stored"
        ),
    }


def sim_vehicle_snapshot() -> list[dict]:
    with _lock:
        return list(_sim_vehicles.values())


def reset(source: str | None = None) -> None:
    """Clear stores. source=None clears both (tests)."""
    global _mode
    with _lock:
        if source in (None, LIVE):
            _live.clear()
        if source in (None, SIM):
            _sim.clear()
            _sim_last_edge.clear()
            _sim_vehicles.clear()
        if source is None:
            _mode = LIVE


def simulate(n: int = 280) -> dict:
    """One-shot seed into the *simulation* store (not live). Prefer traffic_sim.start()."""
    import random

    GRAPH, _, EDGE_KEYS, CITY_KMH = _graph()
    rng = random.Random(7)
    if not EDGE_KEYS:
        return {"kept": 0, "dropped": 0, "source": SIM}

    set_mode(SIM)
    ranked = sorted(EDGE_KEYS, key=lambda ab: GRAPH.edges[ab]["metres"], reverse=True)[:800]
    kept = dropped = 0
    for i in range(max(1, min(n, 2000))):
        a, b = rng.choice(ranked)
        geom = GRAPH.edges[a, b]["geom"]
        lat, lon = rng.choice(geom)
        roll = rng.random()
        if roll < 0.45:
            kmh = rng.uniform(CITY_KMH * 0.75, CITY_KMH * 1.05)
        elif roll < 0.8:
            kmh = rng.uniform(CITY_KMH * 0.4, CITY_KMH * 0.7)
        else:
            kmh = rng.uniform(3.0, CITY_KMH * 0.35)
        result = ingest_sim_fix(
            f"sim-seed-{i}",
            lat + rng.uniform(-0.00012, 0.00012),
            lon + rng.uniform(-0.00012, 0.00012),
            round(kmh, 1),
        )
        if result["kept"]:
            kept += 1
        else:
            dropped += 1
    return {"kept": kept, "dropped": dropped, "source": SIM}
